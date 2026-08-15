import os
from datetime import timedelta

from flask import Flask
from dotenv import load_dotenv

from db import get_db_connection, init_db
from routes import register_routes
from sync_book import sync_repo_books

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# Session configuration
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('RENDER') == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

register_routes(app)

# Initialize DB once for both local runs and Render/Gunicorn workers.
init_db()

conn = get_db_connection()
if conn:
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM pdfs WHERE is_active = TRUE')
            book_count = cursor.fetchone()[0]
        if book_count == 0:
            print('No books found in database. Syncing GitHub book metadata...')
            sync_repo_books()
    finally:
        conn.close()
else:
    print('Database unavailable during startup book sync check.')

if __name__ == '__main__':
    print("Server starting at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)