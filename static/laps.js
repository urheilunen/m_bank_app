let ownLap = null;
let lapReady = false;
let requestingLap = false;
let decidingLap = false;
let lapQueue = [];
let lapError = '';
const announcedLaps = new Set();
const decidedLaps = new Set();

function mergeOwnLap(next) {
    if (!next) return;
    if (!ownLap || next.pk > ownLap.pk ||
        (next.pk === ownLap.pk && ownLap.status === 'pending')) ownLap = next;
}

function renderLapState(state) {
    lapReady = true;
    mergeOwnLap(state.own);
    lapQueue = state.pending.filter(item => !decidedLaps.has(item.pk));
    const requestButton = document.getElementById('requestLap');
    const waiting = Boolean(ownLap && ownLap.status === 'pending');
    requestButton.disabled = requestingLap || waiting;
    requestButton.textContent = requestingLap ? 'Отправляем заявку…' : waiting ? 'Ожидаем банкира…' : 'Пройден круг · +200';
    document.getElementById('lapStatus').textContent = lapError || (waiting
        ? 'Заявка отправлена. 200 будут начислены после подтверждения банкиром.'
        : ownLap && ownLap.status === 'approved' ? 'Круг подтверждён: начислено 200. Следующее нажатие — заявка на новый круг.'
        : ownLap && ownLap.status === 'rejected' ? 'Банкир отклонил заявку. Если это ошибка, обсудите её и отправьте новую.'
        : 'Нажмите после прохождения круга. Выплату подтверждает банкир.');

    const dialog = document.getElementById('lapDialog');
    if (!dialog || decidingLap) return;
    const show = document.getElementById('showLapRequests');
    show.hidden = !lapQueue.length;
    show.textContent = 'Заявки на круг: ' + lapQueue.length;
    const queue = document.getElementById('lapQueue');
    // Preserve focused buttons while regular polling returns the same queue.
    const signature = lapQueue.map(item => item.pk).join(',');
    if (queue.dataset.signature !== signature) {
        queue.dataset.signature = signature;
        queue.replaceChildren();
        for (const item of lapQueue) {
            const card = document.createElement('div');
            card.className = 'lap-request';
            const text = document.createElement('p');
            text.textContent = 'Подтвердите: игрок ' + item.username + ' прошёл круг.';
            card.append(text);
            for (const [decision, label] of [['approved', 'Подтвердить · +200'], ['rejected', 'Отклонить']]) {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = label;
                button.className = decision;
                button.addEventListener('click', () => decideLap(item.pk, decision));
                card.append(button);
            }
            queue.append(card);
        }
    }
    const fresh = lapQueue.some(item => !announcedLaps.has(item.pk));
    lapQueue.forEach(item => announcedLaps.add(item.pk));
    if (fresh && !dialog.open) dialog.showModal();
    if (!lapQueue.length && dialog.open) dialog.close();
}

async function lapPost(url, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
        const response = await fetch(url, {
            method: 'POST', signal: controller.signal,
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
        });
        if (response.status === 401) location.assign('/signup');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return await response.json();
    } finally {
        clearTimeout(timer);
    }
}

async function decideLap(pk, decision) {
    if (decidingLap) return;
    decidingLap = true;
    document.querySelectorAll('#lapQueue button').forEach(button => button.disabled = true);
    const status = document.getElementById('lapDecisionStatus');
    status.textContent = 'Сохраняем решение…';
    try {
        const result = await lapPost('/lap_requests/' + pk + '/decision', {decision});
        decidedLaps.add(pk);
        lapQueue = lapQueue.filter(item => item.pk !== pk);
        if (result.request.username === currentUser) mergeOwnLap(result.request);
        status.textContent = result.request.status === 'approved' ? 'Начислено 200.' : 'Заявка отклонена.';
    } catch (error) {
        status.textContent = 'Нет ответа. Можно повторить решение: повторного начисления не будет.';
    } finally {
        decidingLap = false;
        document.querySelectorAll('#lapQueue button').forEach(button => button.disabled = false);
        renderLapState({own: ownLap, pending: lapQueue});
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('requestLap').addEventListener('click', async () => {
        if (!lapReady || requestingLap || (ownLap && ownLap.status === 'pending')) return;
        const previous = ownLap ? ownLap.pk : 0;
        requestingLap = true;
        lapError = '';
        renderLapState({own: ownLap, pending: lapQueue});
        try {
            const result = await lapPost('/lap_requests', {previous_id: previous});
            mergeOwnLap(result.request);
        } catch (error) {
            lapError = 'Не удалось получить ответ. Статус обновится при восстановлении связи.';
        } finally {
            requestingLap = false;
            renderLapState({own: ownLap, pending: lapQueue});
            lapError = '';
        }
    });
    const dialog = document.getElementById('lapDialog');
    if (dialog) {
        document.getElementById('showLapRequests').addEventListener('click', () => dialog.showModal());
        document.getElementById('closeLapDialog').addEventListener('click', () => dialog.close());
    }
});
