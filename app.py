"""
MyBase - 个人生活管理系统
Flask + PostgreSQL，Render 部署版
模块：状态养护（打卡） + 记账管理
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, g
from datetime import date, timedelta, datetime
import json

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

EXPENSES_JSON_PATH = '/Users/yiyuezhu/.qclaw/workspace/expense-tracker/expenses.json'
BUDGETS_JSON_PATH = '/Users/yiyuezhu/.qclaw/workspace/expense-tracker/fixed_expenses.json'


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

    cur.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            expense_date DATE NOT NULL,
            expense_time TIME NOT NULL,
            category VARCHAR(40) NOT NULL,
            description VARCHAR(200) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            category VARCHAR(40) PRIMARY KEY,
            amount DECIMAL(10,2) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.commit()
    cur.close()


def import_legacy_data():
    """一次性导入历史记账数据（幂等：按日期+时间+描述去重）"""
    db = get_db()
    cur = db.cursor()

    # 导入支出记录
    if os.path.exists(EXPENSES_JSON_PATH):
        with open(EXPENSES_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data.get('records', [])
        inserted = 0
        skipped = 0
        for r in records:
            try:
                cur.execute('''
                    INSERT INTO expenses (expense_date, expense_time, category, description, amount)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                ''', (r['date'], r['time'], r['category'], r['description'], r['amount']))
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print('import expense error:', e)
                skipped += 1
        print(f'expenses import: inserted={inserted}, skipped={skipped}')

    # 导入预算设置
    if os.path.exists(BUDGETS_JSON_PATH):
        with open(BUDGETS_JSON_PATH, 'r', encoding='utf-8') as f:
            budgets = json.load(f)
        for cat, amount in budgets.items():
            if cat == '固定合计':
                continue
            cur.execute('''
                INSERT INTO budgets (category, amount)
                VALUES (%s, %s)
                ON CONFLICT (category) DO UPDATE SET
                    amount = EXCLUDED.amount,
                    updated_at = CURRENT_TIMESTAMP
            ''', (cat, amount))

    db.commit()
    cur.close()


@app.route('/')
def index():
    return render_template('index.html')


# ==================== 状态养护 API ====================

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


# ==================== 记账 API ====================

@app.route('/api/expenses', methods=['GET'])
def list_expenses():
    month = request.args.get('month', '')  # 格式 YYYY-MM
    db = get_db()
    cur = db.cursor()
    if month:
        cur.execute('''
            SELECT * FROM expenses
            WHERE to_char(expense_date, 'YYYY-MM') = %s
            ORDER BY expense_date DESC, expense_time DESC
        ''', (month,))
    else:
        cur.execute('''
            SELECT * FROM expenses
            ORDER BY expense_date DESC, expense_time DESC
            LIMIT 100
        ''')
    rows = cur.fetchall()
    cur.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/expenses', methods=['POST'])
def create_expense():
    data = request.get_json()
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO expenses (expense_date, expense_time, category, description, amount)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    ''', (
        data.get('date', str(date.today())),
        data.get('time', datetime.now().strftime('%H:%M')),
        data['category'],
        data['description'],
        data['amount']
    ))
    new_id = cur.fetchone()['id']
    db.commit()
    cur.close()
    return jsonify({'ok': True, 'id': new_id})


@app.route('/api/expenses/<int:eid>', methods=['DELETE'])
def delete_expense(eid):
    db = get_db()
    cur = db.cursor()
    cur.execute('DELETE FROM expenses WHERE id = %s', (eid,))
    db.commit()
    cur.close()
    return jsonify({'ok': True})


@app.route('/api/expenses/summary')
def expenses_summary():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    db = get_db()
    cur = db.cursor()

    # 月度汇总
    cur.execute('''
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM expenses
        WHERE to_char(expense_date, 'YYYY-MM') = %s
        GROUP BY category
        ORDER BY total DESC
    ''', (month,))
    by_category = [dict(r) for r in cur.fetchall()]

    # 月度总额
    cur.execute('''
        SELECT SUM(amount) as total, COUNT(*) as count
        FROM expenses
        WHERE to_char(expense_date, 'YYYY-MM') = %s
    ''', (month,))
    month_total = cur.fetchone()

    # 今日总额
    today = date.today()
    cur.execute('''
        SELECT SUM(amount) as total, COUNT(*) as count
        FROM expenses
        WHERE expense_date = %s
    ''', (today,))
    today_total = cur.fetchone()

    cur.close()
    return jsonify({
        'month': month,
        'month_total': float(month_total['total'] or 0),
        'month_count': month_total['count'] or 0,
        'today_total': float(today_total['total'] or 0),
        'today_count': today_total['count'] or 0,
        'by_category': by_category
    })


@app.route('/api/budgets', methods=['GET'])
def get_budgets():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM budgets ORDER BY category')
    rows = cur.fetchall()
    cur.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/budgets/<category>', methods=['PUT'])
def set_budget(category):
    data = request.get_json()
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO budgets (category, amount)
        VALUES (%s, %s)
        ON CONFLICT (category) DO UPDATE SET
            amount = EXCLUDED.amount,
            updated_at = CURRENT_TIMESTAMP
    ''', (category, data['amount']))
    db.commit()
    cur.close()
    return jsonify({'ok': True})


@app.route('/api/import', methods=['POST'])
def trigger_import():
    import_legacy_data()
    return jsonify({'ok': True})


with app.app_context():
    init_db()
    import_legacy_data()


if __name__ == '__main__':
    app.run(debug=True, port=5001)
