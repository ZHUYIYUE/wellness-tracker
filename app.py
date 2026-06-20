"""
个人状态养护追踪 - Wellness Tracker
Flask + SQLite，Render 部署版
首次访问会初始化数据库，请等待几秒
"""
import os
import sqlite3
from flask import Flask, request, jsonify, render_template, g
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), 'wellness.db')
app = Flask(__name__)

# ── 数据库 ──────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_date TEXT UNIQUE NOT NULL,
            sleep INTEGER NOT NULL CHECK(sleep BETWEEN 1 AND 3),
            exercise INTEGER NOT NULL CHECK(exercise BETWEEN 1 AND 3),
            care INTEGER NOT NULL CHECK(care BETWEEN 1 AND 3),
            diet INTEGER NOT NULL CHECK(diet BETWEEN 1 AND 3),
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    db.commit()

# ── 页面 ──────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ── API ──────────────────────────────────────
@app.route('/api/today')
def get_today():
    db = get_db()
    today = date.today().isoformat()
    row = db.execute('SELECT * FROM checkins WHERE check_date = ?', (today,)).fetchone()
    return jsonify(dict(row) if row else None)

@app.route('/api/week')
def get_week():
    db = get_db()
    seven_days_ago = (date.today() - timedelta(days=6)).isoformat()
    rows = db.execute(
        'SELECT * FROM checkins WHERE check_date >= ? ORDER BY check_date ASC',
        (seven_days_ago,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/submit', methods=['POST'])
def submit():
    data = request.get_json()
    today = date.today().isoformat()
    db = get_db()
    db.execute('''
        INSERT INTO checkins (check_date, sleep, exercise, care, diet, note)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(check_date) DO UPDATE SET
            sleep = excluded.sleep,
            exercise = excluded.exercise,
            care = excluded.care,
            diet = excluded.diet,
            note = excluded.note
    ''', (today, data['sleep'], data['exercise'], data['care'], data['diet'], data.get('note', '')))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/all')
def get_all():
    db = get_db()
    rows = db.execute('SELECT * FROM checkins ORDER BY check_date DESC LIMIT 90').fetchall()
    return jsonify([dict(r) for r in rows])

# ── 启动 ──────────────────────────────────────
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
