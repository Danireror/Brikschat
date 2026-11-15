import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Ключ берём из переменной окружения, а локально — запасной вариант
app.secret_key = os.environ.get("SECRET_KEY", "лбьенre34nmk231")

DB_NAME = "shop.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
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
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_NAME)


init_db()


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
    return redirect(url_for('chat'))


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

    if text and recipient:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (sender, recipient, text, created_at) VALUES (?, ?, ?, ?)",
            (session['username'], recipient, text, datetime.now().strftime('%H:%M'))
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
        SELECT sender, text, created_at FROM messages
        WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
        ORDER BY id
    """, (session['username'], username, username, session['username']))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([{'sender': r[0], 'text': r[1], 'time': r[2]} for r in rows])


@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('show_login'))
    return render_template('profile.html', username=session['username'])


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('show_login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
