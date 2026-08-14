import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATABASE_CONFIG = {
    'host': os.environ['DB_HOST'],
    'port': os.environ['DB_PORT'],
    'database': os.environ['DB_NAME'],
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASSWORD']
}

def get_db_connection():
    return psycopg2.connect(**DATABASE_CONFIG)

def import_subjects_from_excel(excel_path):
    df = pd.read_excel(excel_path)

    # Keep only unique subject_id + subject name combinations
    df = df[['subject_id', 'Subjects']].dropna().drop_duplicates()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for _, row in df.iterrows():
            subject_id = int(row['subject_id'])
            name = str(row['Subjects']).strip()

            # Insert with explicit id, ignore if already present
            cur.execute("""
                INSERT INTO subjects (id, name)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name;
            """, (subject_id, name))

        conn.commit()
        print("Subjects imported successfully.")
    except Exception as e:
        conn.rollback()
        print("Error:", e)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    import_subjects_from_excel("Books_detail.xlsx")
