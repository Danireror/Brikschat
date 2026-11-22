import os
import sqlite3
import smtplib
import random
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from email.mime.text import MIMEText
import requests


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "лбьенre34nmk231")

# --- База данных: храним в постоянной папке /data, если она доступна ---
if os.path.isdir("/data") and os.access("/data", os.W_OK):
    DB_PATH = "/data/shop.db"
else:
    DB_PATH = "shop.db"  # локальный запасной вариант (на твоём компьютере)

UPLOAD_FOLDER = "static/uploads"
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            contact TEXT NOT NULL,
            UNIQUE(owner, contact)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_codes (
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            UNIQUE(email)
        )
    """)
    conn.commit()

    # Добавляем колонки, если база существовала раньше
    cursor.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'photo_path' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN photo_path TEXT")
        conn.commit()

    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'email' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.commit()

    conn.close()
    print(f"=== БАЗА ГОТОВА: {DB_PATH} ===")


def get_db():
    return sqlite3.connect(DB_PATH)


import os
import requests

def send_code_email(to_email, code):
    import requests

    api_key = os.environ.get('UNISENDER_API_KEY')
    sender = os.environ.get('SMTP_USER', '')

    print(f"=== ПОЧТА: начата отправка на {to_email} ===")

    if not api_key:
        print("=== ОШИБКА: UNISENDER_API_KEY не задан ===")
        return False

    try:
        resp = requests.post(
            "https://api.unisender.com/ru/api/sendEmail",
            data={
                "api_key": api_key,
                "email": to_email,
                "sender_name": "BricksChat",
                "sender_email": sender,
                "subject": "Код подтверждения BricksChat",
                "body": f"Твой код: {code}\n\nКод действует 10 минут.",
            },
            timeout=10,
        )
        # Разбираем JSON — статус 200 обманчив
        try:
            data = resp.json()
        except Exception:
            print(f"=== ОШИБКА UNISENDER (не JSON): {resp.status_code} {resp.text} ===")
            return False

        if "result" in data:
            print(f"=== УСПЕХ: письмо принято, email_id = {data['result'].get('email_id')} ===")
            return True
        print(f"=== ОТКАЗ UNISENDER: {data} ===")
        return False

    except Exception as e:
        print(f"=== КРИТИЧЕСКАЯ ОШИБКА СЕТИ: {e} ===")
        return False


init_db()

@app.route('/test_email')
def test_email():
    print("=== ДИАГНОСТИКА: маршрут /test_email РАБОТАЕТ ===")
    ok = send_code_email("danireror@yourmail.com", "111111")  # подставь свою почту
    return f"Код отправки: {'OK' if ok else 'FAIL'} — смотри логи Amvera"

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('show_login'))


@app.route('/login')
def show_login():
    error = request.args.get('error')
    return render_template('login.html', error=error)


@app.route('/submit-login', methods=['POST'])
def handle_login():
    username = request.form.get('username')
    password = request.form.get('password')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    # user — строка таблицы: (id, username, password), пароль под номером 2
    if user and check_password_hash(user[2], password):
        session['username'] = username
        return redirect(url_for('chat'))
    else:
        return redirect(url_for('show_login', error='1'))


@app.route('/register')
def show_register():
    error = request.args.get('error')
    return render_template('register.html', error=error)


@app.route('/submit-register', methods=['POST'])
def handle_register():
    username = request.form.get('username')
    password = request.form.get('password')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return redirect(url_for('show_register', error='1'))

    hashed_password = generate_password_hash(password)
    cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
    conn.commit()
    conn.close()

    session['username'] = username
    print(f"=== ЗАРЕГИСТРИРОВАН И ЗАЛОГИНЕН: {username} ===")
    return redirect(url_for('verify_page'))


@app.route('/verify')
def verify_page():
    if 'username' not in session:
        return redirect(url_for('show_login'))
    return render_template('verify.html', sent=False, error=None, email='')


@app.route('/chat')
@app.route('/chat/<username>')
def chat(username=None):
    if 'username' not in session:
        return redirect(url_for('show_login'))

    conn = get_db()
    cursor = conn.cursor()

    if username is None:
        cursor.execute("SELECT contact FROM contacts WHERE owner = ?", (session['username'],))
        all_users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return render_template('chat.html', other=None, me=session['username'], all_users=all_users)

    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    if not cursor.fetchone():
        conn.close()
        return redirect(url_for('chat'))

    conn.close()
    return render_template('chat.html', other=username, me=session['username'], all_users=[])


@app.route('/api/search')
def api_search():
    if 'username' not in session:
        return jsonify([])

    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username FROM users WHERE username LIKE ? AND username != ? LIMIT 10",
        ('%' + query + '%', session['username'])
    )
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(users)


@app.route('/add/<username>')
def add_contact(username):
    if 'username' not in session:
        return redirect(url_for('show_login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        cursor.execute(
            "INSERT OR IGNORE INTO contacts (owner, contact) VALUES (?, ?)",
            (session['username'], username)
        )
        conn.commit()
    conn.close()
    return redirect(url_for('chat'))


@app.route('/send', methods=['POST'])
def send():
    if 'username' not in session:
        return redirect(url_for('show_login'))

    recipient = request.form.get('recipient')
    text = request.form.get('text', '').strip()
    photo = request.files.get('photo')

    photo_path = None
    if photo and photo.filename and allowed_file(photo.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ext = photo.filename.rsplit('.', 1)[1].lower()
        filename = f"{session['username']}_{os.urandom(4).hex()}.{ext}"
        photo.save(os.path.join(UPLOAD_FOLDER, filename))
        photo_path = f"uploads/{filename}"

    if (text or photo_path) and recipient:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (sender, recipient, text, created_at, photo_path) VALUES (?, ?, ?, ?, ?)",
            (session['username'], recipient, text, datetime.now().strftime('%H:%M'), photo_path)
        )
        conn.commit()
        conn.close()

    return redirect(url_for('chat', username=recipient))


@app.route('/api/messages/<username>')
def api_messages(username):
    if 'username' not in session:
        return jsonify([])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender, text, created_at, photo_path FROM messages
        WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
        ORDER BY id
    """, (session['username'], username, username, session['username']))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([
        {'sender': r[0], 'text': r[1], 'time': r[2], 'photo': r[3]} for r in rows
    ])


@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('show_login'))
    return render_template('profile.html', username=session['username'])


@app.route('/verify/email', methods=['POST'])
def request_code():
    print("=== ЗАПРОС ПРИШЁЛ НА /verify/email ===")

    if 'username' not in session:
        print("=== СЕССИИ НЕТ — ПЕРЕБРАСЫВАЕТ НА ЛОГИН ===")
        return redirect(url_for('show_login'))

    email = request.form.get('email', '').strip().lower()
    if not email or '@' not in email:
        return redirect(url_for('verify_page'))

    code = str(random.randint(100000, 999999))
    print(f"СГЕНЕРИРОВАН КОД: {code} ДЛЯ {email}")

    expires = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO email_codes (email, code, expires_at) VALUES (?, ?, ?)",
        (email, code, expires)
    )
    conn.commit()
    conn.close()

    if not SMTP_USER or not SMTP_PASS:
        print("=== ОШИБКА: SMTP_USER ИЛИ SMTP_PASS НЕ ЗАДАНЫ В ПЕРЕМЕННЫХ ===")
    else:
        send_code_email(email, code)

    return render_template('verify.html', email=email, sent=True)


@app.route('/verify/check', methods=['POST'])
def check_code():
    if 'username' not in session:
        return redirect(url_for('show_login'))

    email = request.form.get('email', '').strip().lower()
    code = request.form.get('code', '').strip()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT code, expires_at FROM email_codes WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == code and datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S') > datetime.now():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET email = ? WHERE username = ?",
                       (email, session['username']))
        conn.commit()
        conn.close()
        return redirect(url_for('profile'))

    return render_template('verify.html', email=email, error='Неверный или устаревший код')


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('show_login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

