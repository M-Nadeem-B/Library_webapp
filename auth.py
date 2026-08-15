from functools import wraps

from flask import session, redirect, url_for
from psycopg2.extras import RealDictCursor

from db import get_db_connection

def get_user_by_enrollment_no(enrollment_no):
    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT * FROM users WHERE enrollment_no = %s AND is_active = TRUE",
            (enrollment_no,)
        )
        user = cursor.fetchone()
        return dict(user) if user else None
    finally:
        cursor.close()
        conn.close()

def get_user_by_username(username):
    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT * FROM users WHERE username = %s AND is_active = TRUE",
            (username,)
        )
        user = cursor.fetchone()
        return dict(user) if user else None
    finally:
        cursor.close()
        conn.close()

def log_login_attempt(username, enrollment_no, success, ip_address, user_agent):
    conn = get_db_connection()
    if not conn:
        return

    clean_ip = None
    if ip_address:
        clean_ip = str(ip_address).split(',')[0].strip() or None

    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO login_logs (username, enrollment_no, success, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s)
        ''', (username, enrollment_no, success, clean_ip, user_agent))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def update_last_login(user_id):
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s",
            (user_id,)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function