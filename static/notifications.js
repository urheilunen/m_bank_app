// notify('Message', {type: 'error'|'warning'|'success', id, duration});
// duration: 0 keeps a notification visible until dismissed or updated.
class Notifier {
    constructor() {
        this.items = new Map();
        this.host = null;
    }
    show(message, {type = 'warning', id = 'message', duration = 5000} = {}) {
        if (!this.host) {
            this.host = document.createElement('div');
            this.host.className = 'toast-host';
            this.host.setAttribute('popover', 'manual');
            document.body.append(this.host);
        }
        let item = this.items.get(id);
        if (!item) {
            const element = document.createElement('div');
            element.className = 'toast';
            element.setAttribute('role', 'status');
            element.setAttribute('aria-live', 'polite');
            element.setAttribute('aria-atomic', 'true');
            const dot = document.createElement('span');
            dot.className = 'toast-dot';
            dot.setAttribute('aria-hidden', 'true');
            const text = document.createElement('span');
            const close = document.createElement('button');
            close.type = 'button';
            close.textContent = '×';
            close.setAttribute('aria-label', 'Скрыть уведомление');
            close.addEventListener('click', () => this.dismiss(id));
            element.append(dot, text, close);
            this.host.append(element);
            item = {element, text, timer: null};
            this.items.set(id, item);
        }
        clearTimeout(item.timer);
        item.element.dataset.type = type;
        item.text.textContent = message;
        // Popover puts notifications above native banker dialogs without stealing focus.
        if (this.host.showPopover) {
            if (this.host.matches(':popover-open')) this.host.hidePopover();
            this.host.showPopover();
        }
        if (duration > 0) item.timer = setTimeout(() => this.dismiss(id), duration);
        return id;
    }
    dismiss(id) {
        const item = this.items.get(id);
        if (!item) return;
        clearTimeout(item.timer);
        item.element.remove();
        this.items.delete(id);
        if (!this.items.size && this.host.hidePopover) this.host.hidePopover();
    }
}
const notifications = new Notifier();
function notify(message, options) { return notifications.show(message, options); }

class ConnectionStatus {
    constructor(show) { this.show = show; this.disconnected = false; }
    lost() {
        if (this.disconnected) return;
        this.disconnected = true;
        this.show('Восстанавливаем соединение…', {id: 'connection', type: 'warning', duration: 0});
    }
    recovered() {
        if (!this.disconnected) return;
        this.disconnected = false;
        this.show('Соединение восстановлено', {id: 'connection', type: 'success', duration: 2500});
    }
}
window.connectionStatus = new ConnectionStatus(notify);

// Only the server's explicit not_applied outcome proves a failed action.
async function readActionResponse(response) {
    let result;
    try { result = await response.json(); } catch { throw new Error('Unknown outcome'); }
    if (result.outcome === 'not_applied') {
        const error = new Error(result.error || 'Действие не выполнено. Попробуйте ещё раз.');
        error.notApplied = true;
        throw error;
    }
    if (!response.ok) throw new Error('Unknown outcome');
    return result;
}
function notifyActionError(error, action, unknownMessage) {
    notify(error.notApplied ? `${action}: ${error.message}` : unknownMessage, {
        id: 'action', type: error.notApplied ? 'error' : 'warning', duration: error.notApplied ? 7000 : 0
    });
}
