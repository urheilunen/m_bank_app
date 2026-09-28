from datetime import datetime

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, abort
from flask_qrcode import QRcode
import socket
import time
import sqlite3
from contextlib import closing
from waitress import serve

app = Flask(__name__)
QRcode(app)
app.secret_key = 'mUYkyAdCYtQ5a2z4w7hYH1Ibq7R8ksZlHsEhvcoU7tbVTpxpEVKfClbAGFkR846l'
DATABASE = 'monopoly_cashier.db'


def init_db():
    conn = sqlite3.connect(DATABASE, timeout=5)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            pk INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            secret_word TEXT NOT NULL,
            balance INTEGER,
            bank_holder INTEGER,
            last_transaction TEXT DEFAULT "+0"
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            pk INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            amount INTEGER,
            comment TEXT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            pk INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_pk INTEGER,
            target_user TEXT NOT NULL,
            type TEXT NOT NULL
        )
    ''')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lap_requests (
            pk INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            transaction_pk INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_pending_lap ON lap_requests(username) WHERE status='pending'")
    conn.commit()
    conn.close()


def query_get_from_db(query, args=(), one=False):
    with closing(sqlite3.connect(DATABASE, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        rv = conn.execute(query, args).fetchall()
    return (rv[0] if rv else None) if one else [dict(row) for row in rv]


def query_update_db(query, args=(), one=False):
    with closing(sqlite3.connect(DATABASE, timeout=5)) as conn:
        with conn:
            cursor = conn.execute(query, args)
            return cursor.lastrowid


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Подключаемся к несуществующему адресу, чтобы получить локальный IP
        s.connect(('10.254.254.254', 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'username' in session:
        return redirect(url_for('index'))
    else:
        base_url = 'http://' + get_local_ip()
        if request.method == 'POST':
            username = request.form['username']
            if username.lower() in ['bank', 'банк']:
                return render_template('signup.html', error="Нельзя называться банком", base_url=base_url)
            secret_word = request.form['secret_word']
            user = query_get_from_db("SELECT * FROM users WHERE name=?", (username,))
            if user:
                # юзер найден, сверить секретное слово
                user = user[0]
                if user['secret_word'] == secret_word:
                    # секретное слово сходится, начать сессию и перейти на индекс
                    session['username'] = username
                    return redirect(url_for('index'))
                else:
                    # секретное слово не сошлось, спросить снова
                    return render_template('signup.html', error="Пользователь найден, но неправильное секретное слово", base_url=base_url)
            else:
                # юзер не найден, создать и перенаправить на индекс
                users_amount = len(query_get_from_db('SELECT * FROM users'))
                bank_holder = 1 if users_amount == 0 else 0
                query_update_db('INSERT INTO users (name, secret_word, balance, bank_holder) VALUES (?, ?, ?, ?)',
                                (username, secret_word, 1500, bank_holder))
                session['username'] = username
                return redirect(url_for('index'))
        return render_template('signup.html', base_url=base_url)


# функция удаления сессии
@app.route('/signout')
def signout():
    session.pop('username', None)
    return redirect(url_for('signup'))


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' in session:
        username = session['username']
        users = query_get_from_db('SELECT name FROM users WHERE 1')
        try:
            user = query_get_from_db('SELECT * FROM users WHERE name=?', (username,))[0]
        except IndexError:
            return redirect(url_for('signout'))
        user_transactions = query_get_from_db('SELECT * FROM transactions WHERE receiver=? OR sender=? ORDER BY pk DESC',
                                              (username, username))
        bank_transactions = query_get_from_db('SELECT * FROM transactions WHERE receiver=? OR sender=? ORDER BY pk DESC',
                                              ('bank', 'bank'))
        all_transactions = query_get_from_db('SELECT * FROM transactions ORDER BY pk DESC')
        query_update_db('DELETE FROM notifications WHERE target_user=?', (username,))
        return render_template(
            'index.html',
            user=user,
            users=users,
            user_transactions=user_transactions,
            bank_transactions=bank_transactions,
            all_transactions=all_transactions)
    else:
        return redirect(url_for('signup'))


@app.route('/info', methods=['GET'])
def info():
    return render_template('info.html')


@app.route('/create_transaction', methods=['POST'])
def create_transaction():
    if 'username' in session:
        actor = query_get_from_db('SELECT bank_holder FROM users WHERE name=?', (session['username'],), one=True)
        if actor is None:
            abort(401)
        sender = request.form.get('sender')
        if sender != session['username'] and not (sender == 'bank' and actor['bank_holder']):
            abort(403)
        receiver = request.form.get('receiver')
        amount = request.form.get('amount')
        comment = request.form.get('comment')
        timestamp = time.time()

        # создать транзакцию
        transaction_pk = query_update_db(
            'INSERT INTO transactions (sender, receiver, amount, timestamp, comment) VALUES (?, ?, ?, ?, ?)',
            (sender, receiver, amount, datetime.fromtimestamp(timestamp).strftime('%H:%M:%S'), comment)
        )

        # записать последнюю транзакцию каждому юзеру
        query_update_db('UPDATE users SET last_transaction=? WHERE name=?', ('-' + amount, sender))
        query_update_db('UPDATE users SET last_transaction=? WHERE name=?', ('+' + amount, receiver))

        # подсчитать баланс, но сначала проверить хватает ли денег у отправителя (если это не банк конечно)
        if sender != 'bank':
            sender_balance = query_get_from_db('SELECT balance FROM users WHERE name=?', (sender,))[0]['balance']
            if int(sender_balance) < int(amount):
                return jsonify({'result': 'fail', 'error': 'Недостаточно средств!'})
        query_update_db('UPDATE users SET balance=balance - ? WHERE name=?', (amount, sender))
        query_update_db('UPDATE users SET balance=balance + ? WHERE name=?', (amount, receiver))

        # создать необходимые уведомления сначала для получателя и отправителя (если не являются банком)
        if receiver != 'bank':
            query_update_db(
                'INSERT INTO notifications (transaction_pk, target_user, type) VALUES (?, ?, ?)',
                (transaction_pk, receiver, 'personal')
            )
        if receiver != 'bank':
            query_update_db(
                'INSERT INTO notifications (transaction_pk, target_user, type) VALUES (?, ?, ?)',
                (transaction_pk, sender, 'personal')
            )

        # создать общие уведомления для каждого юзера
        all_users = query_get_from_db('SELECT name FROM users')
        for i_user in all_users:
            query_update_db(
                'INSERT INTO notifications (transaction_pk, target_user, type) VALUES (?, ?, ?)',
                (transaction_pk, i_user['name'], 'all')
            )
            # если транзакция банковская, создать банковское уведомление
            if receiver == 'bank' or sender == 'bank':
                query_update_db(
                    'INSERT INTO notifications (transaction_pk, target_user, type) VALUES (?, ?, ?)',
                    (transaction_pk, i_user['name'], 'bank')
                )
        return jsonify(
            {'result': 'success', 'transaction_pk': transaction_pk}
        )
    else:
        return abort(401)


def lap_state(username):
    own = query_get_from_db('SELECT * FROM lap_requests WHERE username=? ORDER BY pk DESC LIMIT 1', (username,))
    banker = query_get_from_db('SELECT bank_holder FROM users WHERE name=?', (username,), one=True)
    pending = query_get_from_db("SELECT * FROM lap_requests WHERE status='pending' ORDER BY pk") if banker and banker['bank_holder'] else []
    return {'own': own[0] if own else None, 'pending': pending}


@app.post('/lap_requests')
def request_lap():
    username = session.get('username')
    if not username:
        abort(401)
    payload = request.get_json(silent=True)
    previous = payload.get('previous_id') if isinstance(payload, dict) else None
    if type(previous) is not int or previous < 0:
        abort(400)
    with closing(sqlite3.connect(DATABASE, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM users WHERE name=?', (username,)).fetchone():
                abort(401)
            latest = conn.execute('SELECT * FROM lap_requests WHERE username=? ORDER BY pk DESC LIMIT 1', (username,)).fetchone()
            # Compare the last observed request: retries cannot create another lap,
            # even if the banker already processed the original request.
            if (latest and latest['status'] == 'pending') or previous != (latest['pk'] if latest else 0):
                return jsonify(request=dict(latest) if latest else None)
            pk = conn.execute('INSERT INTO lap_requests (username) VALUES (?)', (username,)).lastrowid
            row = conn.execute('SELECT * FROM lap_requests WHERE pk=?', (pk,)).fetchone()
    return jsonify(request=dict(row))


@app.post('/lap_requests/<int:pk>/decision')
def decide_lap(pk):
    username = session.get('username')
    if not username:
        abort(401)
    payload = request.get_json(silent=True)
    decision = payload.get('decision') if isinstance(payload, dict) else None
    if decision not in ('approved', 'rejected'):
        abort(400)
    with closing(sqlite3.connect(DATABASE, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            banker = conn.execute('SELECT bank_holder FROM users WHERE name=?', (username,)).fetchone()
            if not banker or not banker['bank_holder']:
                abort(403)
            lap = conn.execute('SELECT * FROM lap_requests WHERE pk=?', (pk,)).fetchone()
            if lap is None:
                abort(404)
            if lap['status'] != 'pending':
                return jsonify(request=dict(lap))
            transaction_pk = None
            if decision == 'approved':
                recipient = lap['username']
                if not conn.execute('SELECT 1 FROM users WHERE name=?', (recipient,)).fetchone():
                    abort(409)
                transaction_pk = conn.execute(
                    'INSERT INTO transactions (sender, receiver, amount, timestamp, comment) VALUES (?, ?, ?, ?, ?)',
                    ('bank', recipient, 200, datetime.now().strftime('%H:%M:%S'), 'Пройден круг')).lastrowid
                conn.execute('UPDATE users SET balance=balance+200, last_transaction=? WHERE name=?', ('+200', recipient))
                notifications = [(transaction_pk, recipient, 'personal')]
                for user in conn.execute('SELECT name FROM users').fetchall():
                    notifications.extend([(transaction_pk, user['name'], 'all'), (transaction_pk, user['name'], 'bank')])
                conn.executemany('INSERT INTO notifications (transaction_pk, target_user, type) VALUES (?, ?, ?)', notifications)
            conn.execute('UPDATE lap_requests SET status=?, transaction_pk=? WHERE pk=?', (decision, transaction_pk, pk))
            row = conn.execute('SELECT * FROM lap_requests WHERE pk=?', (pk,)).fetchone()
    return jsonify(request=dict(row))


@app.route('/get_updates', methods=['GET'])
def get_updates():
    if 'username' in session:
        username = session['username']

        # получить уведомления с разделением по типу
        new_transactions = query_get_from_db(
            'SELECT '
            'transactions.pk AS transaction_pk, transactions.sender AS transaction_sender, transactions.receiver AS transaction_receiver, '
            'transactions.amount AS transaction_amount, transactions.timestamp AS transaction_timestamp, transactions.comment AS transaction_comment,'
            'notifications.type AS notification_type, notifications.pk AS notification_pk '
            'FROM notifications JOIN transactions ON transactions.pk=notifications.transaction_pk WHERE target_user=? ORDER BY transactions.pk ASC',
            (username,)
        )
        # получить инфу об игроках
        players_amount = query_get_from_db("SELECT COUNT(*) as players_amount FROM users")[0]['players_amount']
        players = query_get_from_db("SELECT name, balance, last_transaction FROM users")

        # получить текущий баланс юзера
        balance = query_get_from_db('SELECT balance FROM users WHERE name=?', (username,))[0]['balance']
        return jsonify(
            {
                'status': 'success',
                'new_transactions': new_transactions,
                'balance': balance,
                'players_amount': players_amount,
                'players': players,
                'laps': lap_state(username),
            }
        )
    else:
        return abort(401)


@app.route('/delete_notifications', methods=['POST'])
def delete_notifications():
    if 'username' not in session:
        abort(401)
    payload = request.get_json(silent=True)
    ids = payload.get('notification_pks') if isinstance(payload, dict) else None
    if not isinstance(ids, list) or any(type(pk) is not int or pk <= 0 for pk in ids):
        abort(400)
    # Bound SQLite parameter counts even after a long disconnection.
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        placeholders = ','.join('?' for _ in batch)
        query_update_db(
            f'DELETE FROM notifications WHERE target_user=? AND pk IN ({placeholders})',
            (session['username'], *batch))
    return jsonify(status='success')


@app.route('/delete_notification', methods=['POST'])
def delete_notification():
    if 'username' in session:
        notification_pk = request.form.get('notification_pk')
        query_update_db('DELETE FROM notifications WHERE pk=? AND target_user=?', (notification_pk, session['username']))
        return jsonify(
            {
                'status': 'success'
            }
        )
    else:
        return abort(401)


if __name__ == '__main__':
    init_db()
    serve(app, host='0.0.0.0', port=80, threads=8)
