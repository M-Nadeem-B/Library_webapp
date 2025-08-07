from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import timedelta
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']


# Session configuration
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Clears on browser close
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Adjust as needed

# Database configuration
DATABASE_CONFIG = {
    'host': os.environ['DB_HOST'],
    'port': os.environ['DB_PORT'],
    'database': os.environ['DB_NAME'],
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASSWORD']
}

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(**DATABASE_CONFIG)
        return conn
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

# Initialize database tables
def init_db():
    conn = get_db_connection()
    if not conn:
        print("Could not connect to database!")
        return
    
    cursor = conn.cursor()
    
    try:
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50),
                enrollment_no VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # Create pdfs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pdfs (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                filename VARCHAR(255) NOT NULL,
                file_path VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Create user_pdf_access table (many-to-many relationship)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_pdf_access (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                pdf_id INTEGER REFERENCES pdfs(id) ON DELETE CASCADE,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                granted_by VARCHAR(50),
                UNIQUE(user_id, pdf_id)
            )
        ''')
        
        # Create login_logs table for security tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_logs (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50),
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address INET,
                user_agent TEXT,
                success BOOLEAN
            )
        ''')
        
        conn.commit()
        print("Database tables created successfully!")
        
        # Insert demo data if tables are empty
        insert_demo_data(cursor, conn)
        
    except psycopg2.Error as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

# Insert demo data
def insert_demo_data(cursor, conn):
    try:
        # Check if users exist
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            print("Inserting demo data...")
            
            # Insert demo users
            demo_users = [
                ('Nadeem', 'JSMU/DPHM/056/IPS/2021'),
                ('admin', 'JSMU/DPHM/XXX/IPS/XXXX')
            ]
            
            for username, enrollment_no in demo_users:
                password_hash = generate_password_hash(enrollment_no)
                cursor.execute(
                    "INSERT INTO users (username, enrollment_no, password_hash) VALUES (%s, %s, %s)",
                    (username, enrollment_no, password_hash)
                )
            
            # Insert demo PDFs
            demo_pdfs = [
                ('HEC recommendation', 'HEC provided Books for each department of Pharmacy as a reference', 'List-of-Recommended-Books-Pharm-D.pdf'),
            ]
            
            for title, description, filename in demo_pdfs:
                cursor.execute(
                    "INSERT INTO pdfs (title, description, filename, file_path) VALUES (%s, %s, %s, %s)",
                    (title, description, filename, f'pdfs/{filename}')
                )
            
            # Set up user-PDF access permissions
            cursor.execute("SELECT id FROM users WHERE username = 'Nadeem'")
            user_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM pdfs")
            user_pdfs = cursor.fetchall()
            
            for pdf in user_pdfs:
                cursor.execute(
                    "INSERT INTO user_pdf_access (user_id, pdf_id, granted_by) VALUES (%s, %s, %s)",
                    (user_id, pdf[0], 'system')
                    )
            
            # Admin - All documents
            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            admin_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM pdfs")
            all_pdfs = cursor.fetchall()
            
            for pdf in all_pdfs:
                cursor.execute(
                    "INSERT INTO user_pdf_access (user_id, pdf_id, granted_by) VALUES (%s, %s, %s)",
                    (admin_id, pdf[0], 'system')
                )
            
            conn.commit()
            print("Demo data inserted successfully!")
            
    except psycopg2.Error as e:
        print(f"Error inserting demo data: {e}")
        conn.rollback()

# Database helper functions
def get_user_by_enrollment_no(enrollment_no):
    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM users WHERE enrollment_no = %s AND is_active = TRUE", (enrollment_no,))
        user = cursor.fetchone()
        return dict(user) if user else None
    except psycopg2.Error as e:
        print(f"Error fetching user: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

# def get_user_by_username(username):
#     conn = get_db_connection()
#     if not conn:
#         return None
    
#     cursor = conn.cursor(cursor_factory=RealDictCursor)
#     try:
#         cursor.execute("SELECT * FROM users WHERE username = %s AND is_active = TRUE", (username,))
#         user = cursor.fetchone()
#         return dict(user) if user else None
#     except psycopg2.Error as e:
#         print(f"Error fetching user: {e}")
#         return None
#     finally:
#         cursor.close()
#         conn.close()

def get_user_pdfs(user_id):
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute('''
            SELECT p.* FROM pdfs p
            JOIN user_pdf_access upa ON p.id = upa.pdf_id
            WHERE upa.user_id = %s AND p.is_active = TRUE
            ORDER BY p.title
        ''', (user_id,))
        pdfs = cursor.fetchall()
        return [dict(pdf) for pdf in pdfs]
    except psycopg2.Error as e:
        print(f"Error fetching user PDFs: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def has_pdf_access(user_id, filename):
    conn = get_db_connection()
    if not conn:
        return False
    
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT COUNT(*) FROM pdfs p
            JOIN user_pdf_access upa ON p.id = upa.pdf_id
            WHERE upa.user_id = %s AND p.filename = %s AND p.is_active = TRUE
        ''', (user_id, filename))
        count = cursor.fetchone()[0]
        return count > 0
    except psycopg2.Error as e:
        print(f"Error checking PDF access: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def log_login_attempt(username, enrollment_no, success, ip_address, user_agent):
    conn = get_db_connection()
    if not conn:
        return
    
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO login_logs (username, enrollment_no, success, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s)
        ''', (username, enrollment_no, success, ip_address, user_agent))
        conn.commit()
    except psycopg2.Error as e:
        print(f"Error logging login attempt: {e}")
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
    except psycopg2.Error as e:
        print(f"Error updating last login: {e}")
    finally:
        cursor.close()
        conn.close()

# Decorator to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('library'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        enrollment_no = request.form.get('enrollment_no')

        user = get_user_by_enrollment_no(enrollment_no)
        # user = get_user_by_username(username)
        # is_valid = user and check_password_hash(user['password_hash'], enrollment_no)
        is_valid = False

        if user:
            db_enrollment = user['enrollment_no']
            if db_enrollment.startswith('^') and db_enrollment.endswith('$'):
                # Regex pattern
                if re.match(db_enrollment, enrollment_no):
                    is_valid = True
            else:
                is_valid = check_password_hash(user['password_hash'], enrollment_no)

        # Log the login attempt
        log_login_attempt(
            username,
            enrollment_no,
            is_valid,
            request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
            request.headers.get('User-Agent')
        )

        if is_valid:
            session['user_id'] = user['id']
            session['username'] = username
            session['enrollment_no'] = user['enrollment_no']
            session.permanent = False

            # Update last login time
            update_last_login(user['id'])

            flash(f'Welcome back, {username}!', 'success')

            # Redirect admin to dashboard, others to library
            if user['username'] == 'admin':
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('library'))
        else:
            flash('Invalid username or enrollment number.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/library')
@login_required
def library():
    user_id = session['user_id']
    username = session.get('username', '')
    # enrollment_no = session['enrollment_no']
    pdfs = get_user_pdfs(user_id)
    
    return render_template('library.html', username=username, pdfs=pdfs)

# Add this route for admin dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    # Check if user is admin
    if session.get('username') != 'admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('library'))
    
    # Get some stats for dashboard
    conn = get_db_connection()
    stats = {}
    if conn:
        cursor = conn.cursor()
        try:
            # Count total users
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            stats['total_users'] = cursor.fetchone()[0]
            
            # Count total PDFs
            cursor.execute("SELECT COUNT(*) FROM pdfs WHERE is_active = TRUE")
            stats['total_pdfs'] = cursor.fetchone()[0]
            
            # Count recent logins (last 7 days)
            cursor.execute("SELECT COUNT(*) FROM login_logs WHERE login_time >= NOW() - INTERVAL '7 days' AND success = TRUE")
            stats['recent_logins'] = cursor.fetchone()[0]
            
        except psycopg2.Error as e:
            print(f"Error fetching dashboard stats: {e}")
            flash("Error loading dashboard data.", "error")
        finally:
            cursor.close()
            conn.close()
    
    return render_template('dashboard.html', stats=stats)

# Fix the insert_demo_data function
def insert_demo_data(cursor, conn):
    try:
        # Check if users exist
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            print("Inserting demo data...")
            
            # Insert demo users
            demo_users = [
                ('Nadeem', 'JSMU/DPHM/056/IPS/2021'),
                ('admin', 'JSMU/DPHM/XXX/IPS/XXXX')

            ]
            
            for username, enrollment_no in demo_users:
                password_hash = generate_password_hash(enrollment_no)
                cursor.execute(
                    "INSERT INTO users (username, enrollment_no, password_hash) VALUES (%s, %s, %s)",
                    (username, enrollment_no, password_hash)
                )
            
            # Insert demo PDFs
            demo_pdfs = [
                ('HEC recommendation', 'HEC provided Books for each department of Pharmacy as a reference', 'List-of-Recommended-Books-Pharm-D.pdf'),
            ]
            
            for title, description, filename in demo_pdfs:
                cursor.execute(
                    "INSERT INTO pdfs (title, description, filename, file_path) VALUES (%s, %s, %s, %s)",
                    (title, description, filename, f'pdfs/{filename}')
                )
            
            # Set up user-PDF access permissions for Nadeem
            cursor.execute("SELECT id FROM users WHERE username = 'Nadeem'")
            nadeem_result = cursor.fetchone()
            if nadeem_result:
                nadeem_id = nadeem_result[0]
                cursor.execute("SELECT id FROM pdfs")
                user_pdfs = cursor.fetchall()
                
                for pdf in user_pdfs:
                    cursor.execute(
                        "INSERT INTO user_pdf_access (user_id, pdf_id, granted_by) VALUES (%s, %s, %s)",
                        (nadeem_id, pdf[0], 'system')
                    )
            
            # Admin - All documents
            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            admin_result = cursor.fetchone()
            if admin_result:
                admin_id = admin_result[0]
                cursor.execute("SELECT id FROM pdfs")
                all_pdfs = cursor.fetchall()
                
                for pdf in all_pdfs:
                    cursor.execute(
                        "INSERT INTO user_pdf_access (user_id, pdf_id, granted_by) VALUES (%s, %s, %s)",
                        (admin_id, pdf[0], 'system')
                    )
            
            conn.commit()
            print("Demo data inserted successfully!")
            
    except psycopg2.Error as e:
        print(f"Error inserting demo data: {e}")
        conn.rollback()

@app.route('/pdf/<filename>')
@login_required
def serve_pdf(filename):
    user_id = session.get('user_id')
    print("User ID:", user_id)
    print("Filename requested:", filename)

    if not has_pdf_access(user_id, filename):
        print("Access denied")
        abort(403)

    pdf_path = os.path.join(current_app.root_path, 'static', 'pdfs', filename)
    print("Full PDF path:", pdf_path)

    if not os.path.exists(pdf_path):
        print("File not found!")
        abort(404)

    return send_file(pdf_path, as_attachment=False)

@app.route('/download/<filename>')
@login_required
def download_pdf(filename):
    print("Session at download:", dict(session))
    user_id = session['user_id']
    
    # Check if user has access to this PDF
    if not has_pdf_access(user_id, filename):
        abort(403)
    
    # Check if file exists
    pdf_path = os.path.join(current_app.root_path, 'static', 'pdfs', filename)
    if not os.path.exists(pdf_path):
        abort(404)
    
    return send_file(pdf_path, as_attachment=True)


@app.errorhandler(403)
def forbidden(error):
    return render_template('error.html', 
                         error_code=403, 
                         error_message="You don't have permission to access this resource"), 403

@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', 
                         error_code=404, 
                         error_message="The requested resource was not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', 
                         error_code=500, 
                         error_message="Internal server error occurred"), 500

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

if __name__ == '__main__':
    # Initialize database
    print("Initializing database...")
    init_db()
    
    # Create pdfs directory if it doesn't exist
    if not os.path.exists('pdfs'):
        os.makedirs('pdfs')
    
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("\nDemo Credentials:")
    print(f"Username: Nadeem, enrollment_no: JSMU/DPHM/056/IPS/2021")
    print("Username: admin, enrollment_no: JSMU/DPHM/XXX/IPS/XXXX")
    print(f"\nDatabase: {DATABASE_CONFIG['database']}@{DATABASE_CONFIG['host']}:{DATABASE_CONFIG['port']}")
    print("Server starting at http://127.0.0.1:5000")
    
    app.run(debug=True)
