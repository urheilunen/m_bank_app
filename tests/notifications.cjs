const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
(async () => {
    const messages = [], timers = new Map(), events = {};
    let next = 0, calls = 0, finish;
    const context = vm.createContext({window: {}, AbortController, setTimeout, clearTimeout, record: (text, options) => messages.push({text, ...options})});
    vm.runInContext(fs.readFileSync('static/notifications.js', 'utf8'), context);
    vm.runInContext(fs.readFileSync('static/polling.js', 'utf8'), context);
    const connection = vm.runInContext('new ConnectionStatus(record)', context);
    const env = {
        document: {hidden: false, addEventListener: (name, fn) => events[name] = fn},
        navigator: {onLine: true}, connectionStatus: connection, location: {assign() {}},
        addEventListener: (name, fn) => events[name] = fn,
        setTimeout: (fn, ms) => {timers.set(++next, {fn, ms}); return next;},
        clearTimeout: id => timers.delete(id)
    };
    const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
    const fire = ms => {
        const entry = [...timers].find(([, task]) => task.ms === ms);
        assert.ok(entry, 'missing timer ' + ms);
        timers.delete(entry[0]); entry[1].fn();
    };
    context.startPolling(signal => {
        calls++;
        return new Promise((resolve, reject) => {
            finish = resolve;
            signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'})));
        });
    }, env);
    finish(); await flush();
    assert.equal(messages.length, 0, 'no green notification on startup');
    fire(1000);
    env.document.hidden = true; events.visibilitychange(); await flush();
    assert.equal(messages.length, 0, 'backgrounding is not a connection failure');
    env.document.hidden = false; events.visibilitychange();
    fire(10000); await flush();
    assert.equal(messages.at(-1).type, 'warning');
    assert.equal(messages.at(-1).duration, 0);
    fire(2000); fire(10000); await flush();
    assert.equal(messages.length, 1, 'outage notifications do not accumulate');
    env.navigator.onLine = false; events.offline();
    env.navigator.onLine = true; events.online();
    assert.equal(messages.length, 1, 'online event alone does not prove server recovery');
    finish(); await flush();
    assert.equal(messages.at(-1).type, 'success');
    assert.equal(messages.at(-1).duration, 2500);
    fire(1000); finish(); await flush();
    assert.equal(messages.length, 2, 'healthy polling stays silent');
    env.navigator.onLine = false; events.offline();
    assert.equal(messages.at(-1).type, 'warning');
    events.pagehide();
    for (const response of [
        {ok: false, json: async () => ({})},
        {ok: false, json: async () => { throw new Error('html response'); }}
    ]) {
        await assert.rejects(context.readActionResponse(response), error => !error.notApplied);
    }
    await assert.rejects(context.readActionResponse({ok: false, json: async () => ({outcome: 'not_applied', error: 'Insufficient funds'})}), error => error.notApplied === true);
    assert.equal((await context.readActionResponse({ok: true, json: async () => ({result: 'success'})})).result, 'success');
    console.log('PASS: silent startup, intentional aborts, timeout, deduplication, verified recovery, action outcome classification');
})().catch(error => {console.error(error); process.exitCode = 1;});
