function clampAmount(value, maximum) {
    const amount = Number(value);
    return Math.min(Math.max(0, Math.floor(Number.isFinite(amount) ? amount : 0)),
        Math.max(0, Math.floor(maximum)));
}

function syncPlayers(players) {
    const list = document.querySelector('.players-list');
    const bankSelect = document.getElementById('receiverFromBankInput');
    for (const player of players) {
        let button = [...list.querySelectorAll('.player-transfer')]
            .find(item => item.dataset.receiver === player.name);
        if (!button) {
            const card = document.createElement('li');
            card.className = 'player-in-list';
            button = document.createElement('button');
            button.type = 'button';
            button.className = 'player-transfer';
            button.dataset.receiver = player.name;
            button.disabled = player.name === currentUser;
            for (const name of ['player-list-name', 'player-balance', 'player-last-transaction']) {
                const span = document.createElement('span');
                span.className = name;
                button.append(span);
            }
            card.append(button);
            list.append(card);
        }
        button.title = player.name;
        button.querySelector('.player-list-name').textContent = player.name;
        button.querySelector('.player-balance').textContent = '$' + player.balance;
        const last = button.querySelector('.player-last-transaction');
        last.textContent = '$' + player.last_transaction;
        last.style.color = player.last_transaction.startsWith('-') ? '#c30' : '#0c9';
        if (![...bankSelect.options].some(option => option.value === player.name)) {
            bankSelect.add(new Option(player.name, player.name));
        }
    }
}

function refreshAmounts() {
    for (const input of document.querySelectorAll('.popup-amount')) {
        const maximum = input.id === 'amountInput' ? currentBalance : Number.MAX_SAFE_INTEGER;
        input.value = clampAmount(input.value, maximum);
        input.max = Math.max(0, maximum);
        const form = input.closest('form');
        const receiver = form.querySelector('[name="receiver"]').value;
        const busy = form.dataset.busy === 'true';
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = busy || !receiver || Number(input.value) <= 0;
        submit.value = busy ? 'Отправляем…' : Number(input.value) > 0 ? 'Перевести ' + input.value : 'Перевести';
        form.querySelectorAll('.amount-step').forEach(button => {
            const next = clampAmount(Number(input.value) + Number(button.dataset.step), maximum);
            button.disabled = busy || next === Number(input.value);
        });
    }
    document.getElementById('availableBalance').textContent = Math.max(0, currentBalance);
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('.players-list').addEventListener('click', event => {
        const button = event.target.closest('.player-transfer');
        if (!button || button.disabled) return;
        const form = document.getElementById('regularTransactionForm');
        if (form.dataset.busy === 'true') return;
        document.getElementById('receiverInput').value = button.dataset.receiver;
        document.getElementById('receiverName').textContent = button.dataset.receiver === 'bank' ? 'Банк' : button.dataset.receiver;
        document.getElementById('amountInput').value = 0;
        document.getElementById('commentInput').value = '';
        refreshAmounts();
        location.hash = 'popup';
    });

    document.querySelectorAll('.amount-controls').forEach(controls => {
        controls.addEventListener('click', event => {
            const button = event.target.closest('.amount-step');
            if (!button || button.disabled) return;
            const input = document.getElementById(controls.dataset.amountInput);
            const maximum = input.id === 'amountInput' ? currentBalance : Number.MAX_SAFE_INTEGER;
            input.value = clampAmount(Number(input.value) + Number(button.dataset.step), maximum);
            refreshAmounts();
        });
    });
    document.getElementById('receiverFromBankInput').addEventListener('change', refreshAmounts);

    for (const form of document.querySelectorAll('#regularTransactionForm, #bankTransactionForm')) {
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (form.dataset.busy === 'true') return;
            const bank = form.id === 'bankTransactionForm';
            const amount = Number(form.querySelector('[name="amount"]').value);
            const receiver = form.querySelector('[name="receiver"]').value;
            if (!receiver || !Number.isSafeInteger(amount) || amount <= 0 || (!bank && amount > currentBalance)) {
                refreshAmounts();
                return;
            }
            const payload = new URLSearchParams(new FormData(form));
            payload.set('sender', bank ? 'bank' : currentUser);
            form.dataset.busy = 'true';
            refreshAmounts();
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 10000);
            try {
                const response = await fetch('/create_transaction', {
                    method: 'POST', body: payload, signal: controller.signal
                });
                const result = await readActionResponse(response);
                if (result.result !== 'success') throw new Error('Unknown outcome');
                notifications.dismiss('action');
                form.reset();
                location.hash = '';
            } catch (error) {
                notifyActionError(error, 'Перевод не выполнен', 'Не удалось узнать результат перевода. Проверьте баланс и историю перед повтором: деньги могли уже уйти.');
            } finally {
                clearTimeout(timeout);
                form.dataset.busy = 'false';
                refreshAmounts();
            }
        });
    }
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && ['#popup', '#popup1'].includes(location.hash)) location.hash = '';
    });
    refreshAmounts();
});
