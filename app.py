"""
个人状态养护追踪 - Wellness Tracker
Flask + PostgreSQL，Render 部署版
DATABASE_URL 环境变量由 Render PostgreSQL 自动注入
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, g
from datetime import date, timedelta

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id SERIAL PRIMARY KEY,
            check_date DATE UNIQUE NOT NULL,
            sleep INTEGER NOT NULL CHECK(sleep BETWEEN 1 AND 3),
            exercise INTEGER NOT NULL CHECK(exercise BETWEEN 1 AND 3),
            care INTEGER NOT NULL CHECK(care BETWEEN 1 AND 3),
            diet INTEGER NOT NULL CHECK(diet BETWEEN 1 AND 3),
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.commit()
    cur.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/today')
def get_today():
    db = get_db()
    cur = db.cursor()
    today = date.today()
    cur.execute('SELECT * FROM checkins WHERE check_date = %s', (today,))
    row = cur.fetchone()
    cur.close()
    return jsonify(dict(row) if row else None)

@app.route('/api/week')
def get_week():
    db = get_db()
    cur = db.cursor()
    seven_days_ago = date.today() - timedelta(days=6)
    cur.execute(
        'SELECT * FROM checkins WHERE check_date >= %s ORDER BY check_date ASC',
        (seven_days_ago,)
    )
    rows = cur.fetchall()
    cur.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/submit', methods=['POST'])
def submit():
    data = request.get_json()
    today = date.today()
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO checkins (check_date, sleep, exercise, care, diet, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (check_date) DO UPDATE SET
            sleep = excluded.sleep,
            exercise = excluded.exercise,
            care = excluded.care,
            diet = excluded.diet,
            note = excluded.note
    ''', (today, data['sleep'], data['exercise'], data['care'], data['diet'], data.get('note', '')))
    db.commit()
    cur.close()
    return jsonify({'ok': True})

@app.route('/api/all')
def get_all():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM checkins ORDER BY check_date DESC LIMIT 90')
    rows = cur.fetchall()
    cur.close()
    return jsonify([dict(r) for r in rows])

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
