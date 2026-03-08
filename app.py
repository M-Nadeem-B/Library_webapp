import os
from datetime import timedelta

from flask import Flask
from dotenv import load_dotenv

from db import init_db
from routes import register_routes

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']

# Session configuration
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

register_routes(app)

if __name__ == '__main__':
    print("Initializing database...")
    init_db()

    print("Server starting at http://127.0.0.1:5000")
    app.run(debug=True)