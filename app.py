"""
MyBase - 个人生活管理系统
Flask + PostgreSQL，Render 部署版
模块：状态养护（打卡） + 记账管理
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, g
from datetime import date, datetime, timezone, timedelta
import json

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def cn_today():
    """返回东八区今天的日期"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def cn_month():
    """返回东八区当前月份 YYYY-MM"""
    return cn_today().strftime('%Y-%m')


def cn_time():
    """返回东八区当前时间 HH:MM"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%H:%M')


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
    # 添加 imported 字段（兼容已有表）
    try:
        cur.execute('ALTER TABLE expenses ADD COLUMN imported BOOLEAN DEFAULT FALSE')
        db.commit()
    except Exception:
        db.rollback()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            category VARCHAR(40) PRIMARY KEY,
            amount DECIMAL(10,2) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.commit()
    cur.close()


def import_legacy_data(force=False):
    """导入历史记账数据（幂等：除非 force=True）"""
    db = get_db()
    cur = db.cursor()

    if not force:
        cur.execute('SELECT COUNT(*) as cnt FROM expenses WHERE imported = TRUE')
        if cur.fetchone()['cnt'] > 0:
            print('Legacy data already imported, skipping.')
            cur.close()
            return
    else:
        cur.execute('DELETE FROM expenses WHERE imported = TRUE')
        print('Deleted old imported records for reimport.')

    expenses_path = os.path.join(BASE_DIR, 'expenses.json')
    if os.path.exists(expenses_path):
        with open(expenses_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data.get('records', [])
        inserted = 0
        skipped = 0
        for r in records:
            try:
                expense_date = r.get('date') or str(cn_today())
                expense_time = r.get('time') or '00:00'
                category = r.get('category') or '未分类'
                description = r.get('description') or r.get('note') or r.get('project') or ''
                amount = r.get('amount') or 0
                cur.execute('''
                    INSERT INTO expenses (expense_date, expense_time, category, description, amount, imported)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                ''', (expense_date, expense_time, category, description, amount))
                inserted += 1
            except Exception as e:
                print('import error:', e, r)
                skipped += 1
                db.rollback()
                cur = db.cursor()
        print(f'imported={inserted}, skipped={skipped}')
    else:
        print(f'expenses.json not found at {expenses_path}')

    budgets_path = os.path.join(BASE_DIR, 'fixed_expenses.json')
    if os.path.exists(budgets_path):
        with open(budgets_path, 'r', encoding='utf-8') as f:
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
        print('budgets imported')

    db.commit()
    cur.close()


def _serialize_rows(rows):
    """将含 time/date 对象的行转为 JSON 可序列化的 dict"""
    result = []
    for r in rows:
        d = dict(r)
        for key in ('expense_time', 'expense_date', 'check_date', 'created_at', 'updated_at'):
            if key in d and hasattr(d[key], 'isoformat'):
                d[key] = d[key].isoformat()
        result.append(d)
    return result


@app.route('/')
def index():
    return render_template('index.html')


# ==================== 状态养护 API ====================

@app.route('/api/today')
def get_today():
    db = get_db()
    cur = db.cursor()
    today = cn_today()
    cur.execute('SELECT * FROM checkins WHERE check_date = %s', (today,))
    row = cur.fetchone()
    cur.close()
    return jsonify(dict(row) if row else None)


@app.route('/api/week')
def get_week():
    db = get_db()
    cur = db.cursor()
    seven_days_ago = cn_today() - timedelta(days=6)
    cur.execute(
        'SELECT * FROM checkins WHERE check_date >= %s ORDER BY check_date ASC',
        (seven_days_ago,)
    )
    rows = cur.fetchall()
    cur.close()
    return jsonify(_serialize_rows(rows))


@app.route('/api/submit', methods=['POST'])
def submit():
    data = request.get_json()
    today = cn_today()
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
    return jsonify(_serialize_rows(rows))


# ==================== 记账 API ====================

@app.route('/api/expenses', methods=['GET'])
def list_expenses():
    month = request.args.get('month', '')
    try:
        db = get_db()
        cur = db.cursor()

        # 懒加载：如果 expenses 表为空，自动触发历史数据导入
        cur.execute('SELECT COUNT(*) as cnt FROM expenses')
        if cur.fetchone()['cnt'] == 0:
            cur.close()
            try:
                import_legacy_data()
            except Exception as e:
                print('WARNING: auto-import failed:', e)
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
        return jsonify(_serialize_rows(rows))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/expenses', methods=['POST'])
def create_expense():
    data = request.get_json()
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO expenses (expense_date, expense_time, category, description, amount, imported)
        VALUES (%s, %s, %s, %s, %s, FALSE)
        RETURNING id
    ''', (
        data.get('date', str(cn_today())),
        data.get('time', cn_time()),
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
    month = request.args.get('month', cn_month())
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM expenses
        WHERE to_char(expense_date, 'YYYY-MM') = %s
        GROUP BY category
        ORDER BY total DESC
    ''', (month,))
    by_category = [dict(r) for r in cur.fetchall()]

    cur.execute('''
        SELECT SUM(amount) as total, COUNT(*) as count
        FROM expenses
        WHERE to_char(expense_date, 'YYYY-MM') = %s
    ''', (month,))
    month_total = cur.fetchone()

    today = cn_today()
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
    force = request.get_json(silent=True) or {}
    import_legacy_data(force=force.get('force', False))
    return jsonify({'ok': True})


with app.app_context():
    init_db()
    # 延迟导入：不在启动时执行，避免数据库问题导致整个应用无法启动

if __name__ == '__main__':
    app.run(debug=True, port=5001)
