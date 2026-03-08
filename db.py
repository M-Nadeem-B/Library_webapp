import os
import psycopg2
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DATABASE_CONFIG = {
    'host': os.environ['DB_HOST'],
    'port': os.environ['DB_PORT'],
    'database': os.environ['DB_NAME'],
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASSWORD']
}

def get_db_connection():
    try:
        return psycopg2.connect(**DATABASE_CONFIG)
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        print("Could not connect to database!")
        return

    cursor = conn.cursor()

    try:
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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subjects (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) UNIQUE NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pdfs (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                filename VARCHAR(255),
                file_path VARCHAR(500),
                author VARCHAR(255),
                edition VARCHAR(100),
                year VARCHAR(10),
                cover_url TEXT,
                storage_url TEXT,
                subject_id INTEGER REFERENCES subjects(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reading_progress (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                pdf_id INTEGER REFERENCES pdfs(id) ON DELETE CASCADE,
                last_page INTEGER DEFAULT 1,
                last_position JSONB DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, pdf_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS highlights (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                pdf_id INTEGER REFERENCES pdfs(id) ON DELETE CASCADE,
                page INTEGER,
                text TEXT,
                meta JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_logs (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50),
                enrollment_no VARCHAR(255),
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address INET,
                user_agent TEXT,
                success BOOLEAN
            )
        ''')

        conn.commit()

        # Insert demo users only if users table is empty
        insert_demo_users()

        print("Database tables created successfully!")

    except psycopg2.Error as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def insert_demo_users():
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        if user_count == 0:
            print("Inserting demo users...")

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

            conn.commit()
            print("Demo users inserted successfully!")

    except psycopg2.Error as e:
        print(f"Error inserting demo users: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()