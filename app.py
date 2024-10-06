from datetime import datetime

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, abort
from flask_qrcode import QRcode
import socket
import time
import sqlite3

app = Flask(__name__)
QRcode(app)
app.secret_key = 'mUYkyAdCYtQ5a2z4w7hYH1Ibq7R8ksZlHsEhvcoU7tbVTpxpEVKfClbAGFkR846l'
DATABASE = 'monopoly_cashier.db'
DB_LOCKED = False


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
    conn.commit()
    conn.close()


def query_get_from_db(query, args=(), one=False):
    global DB_LOCKED
    while DB_LOCKED:
        time.sleep(0.2)
    DB_LOCKED = True
    conn = sqlite3.connect(DATABASE, timeout=5)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.close()
    DB_LOCKED = False
    return (rv[0] if rv else None) if one else [dict(row) for row in rv]


def query_update_db(query, args=(), one=False):
    global DB_LOCKED
    while DB_LOCKED:
        time.sleep(0.2)
    DB_LOCKED = True
    conn = sqlite3.connect(DATABASE, timeout=5)
    cursor = conn.cursor()
    cursor.execute(query, args)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    DB_LOCKED = False
    return last_id


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
        username = session['username']
        return render_template('index.html', username=username)
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
        sender = request.form.get('sender')
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
        players = query_get_from_db("SELECT * FROM users")

        # получить текущий баланс юзера
        balance = query_get_from_db('SELECT balance FROM users WHERE name=?', (username,))[0]['balance']
        return jsonify(
            {
                'status': 'success',
                'new_transactions': new_transactions,
                'balance': balance,
                'players_amount': players_amount,
                'players': players,
            }
        )
    else:
        return abort(401)


@app.route('/delete_notification', methods=['POST'])
def delete_notification():
    if 'username' in session:
        notification_pk = request.form.get('notification_pk')
        query_update_db('DELETE FROM notifications WHERE pk=?', (notification_pk,))
        return jsonify(
            {
                'status': 'success'
            }
        )
    else:
        return abort(401)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=80, debug=True)
    # app.run(debug=True)
