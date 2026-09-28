// A single request chain, including notification acknowledgements, per page.
function startPolling(update, env = window) {
    let timer;
    let active = null;
    let failures = 0;
    let stopped = false;
    let cancelled = false;
    const available = () => !stopped && !env.document.hidden && env.navigator.onLine !== false;

    async function run() {
        env.clearTimeout(timer);
        if (active || !available()) return;
        const controller = new AbortController();
        active = controller;
        cancelled = false;
        const deadline = env.setTimeout(() => controller.abort(), 10000);
        try {
            await update(controller.signal);
            failures = 0;
            if (!cancelled) env.connectionStatus?.recovered();
        } catch (error) {
            if (cancelled) return;
            if (error.status === 401) {
                stopped = true;
                env.location.assign('/signup');
            } else {
                failures = Math.min(failures + 1, 5);
                if (error.connectionFailure || error.name === 'AbortError') env.connectionStatus?.lost();
            }
        } finally {
            env.clearTimeout(deadline);
            active = null;
            if (available()) timer = env.setTimeout(run, Math.min(1000 * 2 ** failures, 30000));
        }
    }

    function resume() {
        env.clearTimeout(timer);
        if (!available() && active) { cancelled = true; active.abort(); }
        else if (!active && available()) run();
    }
    env.document.addEventListener('visibilitychange', resume);
    env.addEventListener('online', resume);
    env.addEventListener('offline', () => { env.connectionStatus?.lost(); resume(); });
    env.addEventListener('pagehide', () => {
        stopped = true;
        env.clearTimeout(timer);
        if (active) { cancelled = true; active.abort(); }
    });
    env.addEventListener('pageshow', () => {
        stopped = false;
        resume();
    });
    if (env.navigator.onLine === false) env.connectionStatus?.lost();
    run();
}
