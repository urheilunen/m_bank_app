import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import app


class TransferOutcomes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.previous_db = app.DATABASE
        app.DATABASE = str(Path(self.folder.name) / 'test.db')
        app.init_db()
        for name, banker in [('Banker', 1), ('Alice', 0), ('Bob', 0)]:
            app.query_update_db('INSERT INTO users (name, secret_word, balance, bank_holder) VALUES (?, ?, 1500, ?)', (name, 'test', banker))

    def tearDown(self):
        app.DATABASE = self.previous_db
        self.folder.cleanup()

    def send(self, amount, sender='Alice', receiver='Bob', actor='Alice'):
        client = app.app.test_client()
        with client.session_transaction() as session:
            session['username'] = actor
        return client.post('/create_transaction', data={'sender': sender, 'receiver': receiver, 'amount': amount})

    def balances(self):
        return {row['name']: row['balance'] for row in app.query_get_from_db('SELECT name, balance FROM users')}

    def test_rejections_leave_no_changes(self):
        for amount in ('0', '-5', '2.5', 'bad', '1501'):
            self.assertEqual(self.send(amount).json['outcome'], 'not_applied')
        self.assertEqual(self.send('200', sender='bank').json['outcome'], 'not_applied')
        self.assertEqual(self.send('200', receiver='Nobody').json['outcome'], 'not_applied')
        self.assertEqual(set(self.balances().values()), {1500})
        self.assertEqual(app.query_get_from_db('SELECT * FROM transactions'), [])
        self.assertEqual(app.query_get_from_db('SELECT * FROM notifications'), [])
        self.assertEqual({r['last_transaction'] for r in app.query_get_from_db('SELECT last_transaction FROM users')}, {'+0'})

    def test_success_and_bank_transfers(self):
        self.assertEqual(self.send('150').json['result'], 'success')
        self.assertEqual(self.balances()['Alice'], 1350)
        self.assertEqual(self.balances()['Bob'], 1650)
        self.assertEqual(self.send('200', sender='bank', actor='Banker').json['result'], 'success')
        self.assertEqual(self.balances()['Bob'], 1850)
        self.assertEqual(self.send('50', receiver='bank').json['result'], 'success')
        self.assertTrue(app.query_get_from_db("SELECT * FROM notifications WHERE target_user='Alice' AND type='personal' AND transaction_pk=3"))

    def test_failure_rolls_back_whole_transfer(self):
        app.query_update_db("CREATE TRIGGER fail_notifications BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'test'); END")
        previous = app.app.config['TESTING']
        app.app.config['TESTING'] = True
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.send('200')
        finally:
            app.app.config['TESTING'] = previous
        self.assertEqual(set(self.balances().values()), {1500})
        self.assertEqual(app.query_get_from_db('SELECT * FROM transactions'), [])

    def test_concurrent_spending_cannot_overdraw(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.send('1000').json['result'], range(2)))
        self.assertEqual(sorted(results), ['fail', 'success'])
        self.assertEqual(self.balances()['Alice'], 500)

    def test_lap_rejection_contract(self):
        client = app.app.test_client()
        self.assertEqual(client.post('/lap_requests', json={'previous_id': 0}).json['outcome'], 'not_applied')
        with client.session_transaction() as session:
            session['username'] = 'Alice'
        lap = client.post('/lap_requests', json={'previous_id': 0}).json['request']
        response = client.post(f"/lap_requests/{lap['pk']}/decision", json={'decision': 'approved'})
        self.assertEqual(response.json['outcome'], 'not_applied')
        self.assertEqual(set(self.balances().values()), {1500})


if __name__ == '__main__':
    unittest.main()
