import os
import re
import json
import psycopg2

from flask import render_template, request, redirect, url_for, session, flash, send_file, abort, current_app, jsonify
from werkzeug.security import check_password_hash
from psycopg2.extras import RealDictCursor

from db import get_db_connection
from auth import (
    login_required,
    get_user_by_username,
    get_user_by_enrollment_no,
    log_login_attempt,
    update_last_login
)


def register_routes(app):
    @app.route('/')
    def index():
        if 'user_id' in session:
            if session.get('username') == 'admin':
                return redirect(url_for('dashboard'))
            return redirect(url_for('user_dashboard'))
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            enrollment_no = request.form.get('enrollment_no')

            print(f"Login attempt - form username={username!r}, enrollment_no={enrollment_no!r}")

            user = get_user_by_username(username) or get_user_by_enrollment_no(enrollment_no)
            is_valid = False

            if user:
                db_enrollment = user.get('enrollment_no', '')
                if isinstance(db_enrollment, str) and db_enrollment.startswith('^') and db_enrollment.endswith('$'):
                    if re.match(db_enrollment, enrollment_no):
                        is_valid = True
                else:
                    try:
                        is_valid = check_password_hash(user.get('password_hash', ''), enrollment_no)
                    except Exception:
                        is_valid = False

            log_login_attempt(
                user['username'] if user and 'username' in user else username,
                enrollment_no,
                is_valid,
                request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
                request.headers.get('User-Agent')
            )

            if is_valid:
                session['user_id'] = user['id']
                session['username'] = user.get('username', username)
                session['enrollment_no'] = user.get('enrollment_no')
                session.permanent = False

                update_last_login(user['id'])
                flash(f'Welcome back, {username}!', 'success')

                if user['username'] == 'admin':
                    return redirect(url_for('dashboard'))
                return redirect(url_for('user_dashboard'))

            flash('Invalid username or enrollment number.', 'error')
            return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/library')
    @login_required
    def library():
        return redirect(url_for('user_dashboard'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        if session.get('username') != 'admin':
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('user_dashboard'))

        conn = get_db_connection()
        stats = {}

        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
                stats['total_users'] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM pdfs WHERE is_active = TRUE")
                stats['total_pdfs'] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM login_logs WHERE login_time >= NOW() - INTERVAL '7 days' AND success = TRUE")
                stats['recent_logins'] = cursor.fetchone()[0]

            except psycopg2.Error as e:
                print(f"Error fetching dashboard stats: {e}")
                flash("Error loading dashboard data.", "error")
            finally:
                cursor.close()
                conn.close()

        return render_template('dashboard.html', stats=stats)

    @app.route('/user/dashboard')
    @login_required
    def user_dashboard():
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                s.id,
                s.name,
                COUNT(p.id) AS book_count
            FROM subjects s
            LEFT JOIN pdfs p
                ON p.subject_id = s.id
            AND p.is_active = TRUE
            GROUP BY s.id, s.name
            ORDER BY s.name
        """)
        subjects = cursor.fetchall() or []

        cursor.execute('''
            SELECT p.id, p.title, p.description, p.filename, p.author, p.edition,
                p.year, p.cover_url, p.storage_url, p.subject_id
            FROM pdfs p
            WHERE p.is_active = TRUE
            ORDER BY p.title
            LIMIT 50
        ''')
        pdfs = cursor.fetchall() or []

        cursor.execute("SELECT pdf_id, last_page FROM reading_progress WHERE user_id = %s", (user_id,))
        progress_rows = cursor.fetchall() or []
        progress_map = {r['pdf_id']: r['last_page'] for r in progress_rows}

        cursor.close()
        conn.close()

        return render_template('user_dashboard.html', subjects=subjects, pdfs=pdfs, progress_map=progress_map)
    @app.route('/api/subjects')
    @login_required
    def api_subjects():
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name FROM subjects ORDER BY name")
        subs = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(subs)

    @app.route('/api/books')
    @login_required
    def api_books():
        subject_id = request.args.get('subject_id')
        query = (request.args.get('q') or '').strip()

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            sql = """
                SELECT
                    p.id,
                    p.title,
                    p.description,
                    p.filename,
                    p.author,
                    p.edition,
                    p.year,
                    p.cover_url,
                    p.storage_url,
                    p.subject_id
                FROM pdfs p
                WHERE p.is_active = TRUE
            """
            params = []

            if subject_id:
                sql += " AND p.subject_id = %s"
                params.append(subject_id)

            if query:
                sql += """
                    AND (
                        p.title ILIKE %s
                        OR COALESCE(p.author, '') ILIKE %s
                    )
                """
                like_query = f"%{query}%"
                params.extend([like_query, like_query])

            sql += " ORDER BY p.title"

            cursor.execute(sql, params)
            rows = cursor.fetchall() or []
            return jsonify(rows)

        except Exception as e:
            print(f"Error in api_books: {e}")
            return jsonify([])
        finally:
            cursor.close()
            conn.close()

    @app.route('/api/last-read', methods=['POST'])
    @login_required
    def api_last_read():
        payload = request.json or {}
        pdf_id = payload.get('pdf_id')
        last_page = payload.get('last_page')
        last_position = payload.get('last_position', {})

        if not pdf_id or last_page is None:
            return jsonify({'error': 'pdf_id and last_page required'}), 400

        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO reading_progress (user_id, pdf_id, last_page, last_position, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, pdf_id)
                DO UPDATE SET last_page = EXCLUDED.last_page, last_position = EXCLUDED.last_position, updated_at = CURRENT_TIMESTAMP
            ''', (user_id, pdf_id, last_page, json.dumps(last_position)))
            conn.commit()
            return jsonify({'ok': True})
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route('/api/highlight', methods=['POST'])
    @login_required
    def api_highlight():
        payload = request.json or {}
        pdf_id = payload.get('pdf_id')
        page = payload.get('page')
        text = payload.get('text')
        meta = payload.get('meta', {})

        if not pdf_id or page is None or not text:
            return jsonify({'error': 'pdf_id, page, and text required'}), 400

        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO highlights (user_id, pdf_id, page, text, meta)
                VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at
            ''', (user_id, pdf_id, page, text, json.dumps(meta)))
            row = cursor.fetchone()
            conn.commit()
            return jsonify({'ok': True, 'id': row[0], 'created_at': str(row[1])})
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route('/api/highlights')
    @login_required
    def api_get_highlights():
        pdf_id = request.args.get('pdf_id')
        if not pdf_id:
            return jsonify([])

        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT id, page, text, meta, created_at FROM highlights WHERE user_id = %s AND pdf_id = %s ORDER BY created_at DESC",
            (user_id, pdf_id)
        )
        rows = cursor.fetchall() or []
        cursor.close()
        conn.close()
        return jsonify(rows)

    @app.route('/download/<int:pdf_id>')
    @login_required
    def download_pdf(pdf_id):
        conn = get_db_connection()
        if not conn:
            abort(500)

        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("""
                SELECT *
                FROM pdfs
                WHERE id = %s AND is_active = TRUE
            """, (pdf_id,))
            pdf = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if not pdf:
            abort(404)

        pdf = dict(pdf)

        if pdf.get('storage_url'):
            return redirect(pdf['storage_url'])

        if pdf.get('filename'):
            pdf_path = os.path.join(current_app.root_path, 'static', 'pdfs', pdf['filename'])
            if not os.path.exists(pdf_path):
                abort(404)

            return send_file(
                pdf_path,
                as_attachment=True,
                download_name=pdf['filename']
            )

        abort(404)

    @app.errorhandler(403)
    def forbidden(error):
        return render_template('error.html', error_code=403, error_message="You don't have permission to access this resource"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template('error.html', error_code=404, error_message="The requested resource was not found"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('error.html', error_code=500, error_message="Internal server error occurred"), 500

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route('/clear-session', methods=['POST'])
    def clear_session():
        session.clear()
        return '', 204

    @app.route('/logout')
    def logout():
        session.clear()
        flash('You have been logged out successfully', 'info')
        return redirect(url_for('login'))