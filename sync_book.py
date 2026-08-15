import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': os.environ.get('DB_PORT', '5432'),
    'database': os.environ.get('DB_NAME', 'pdf_library'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', '')
}

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        try:
            return psycopg2.connect(database_url, sslmode='require')
        except Exception as e:
            print(f"Render DATABASE_URL connection error during sync: {e}")

    try:
        return psycopg2.connect(**DATABASE_CONFIG)
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

def sync_repo_books():
    owner = "M-Nadeem-B"
    repo = "Pharma-book-repo"
    base_api = f"https://api.github.com/repos/{owner}/{repo}/contents"

    conn = get_db_connection()
    if not conn:
        print("Could not connect to database for repo sync.")
        return

    cursor = conn.cursor()

    try:
        root_resp = requests.get(base_api, timeout=30)
        root_resp.raise_for_status()
        root_items = root_resp.json()

        for item in root_items:
            if item.get("type") != "dir":
                continue

            subject_name = item["name"].strip().upper()
            subject_api_url = item["url"]

            cursor.execute(
                """
                INSERT INTO subjects (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                """,
                (subject_name,)
            )

            cursor.execute(
                "SELECT id FROM subjects WHERE name = %s",
                (subject_name,)
            )
            subject_row = cursor.fetchone()
            if not subject_row:
                print(f"Could not resolve subject id for: {subject_name}")
                continue

            subject_id = subject_row[0]

            folder_resp = requests.get(subject_api_url, timeout=30)
            folder_resp.raise_for_status()
            folder_items = folder_resp.json()

            for file_item in folder_items:
                if file_item.get("type") != "file":
                    continue

                filename = file_item["name"]

                if not filename.lower().endswith(".pdf"):
                    continue

                title = os.path.splitext(filename)[0]
                storage_url = file_item.get("download_url")

                cursor.execute(
                    "SELECT id FROM pdfs WHERE storage_url = %s",
                    (storage_url,)
                )
                existing_pdf = cursor.fetchone()

                if existing_pdf:
                    cursor.execute(
                        """
                        UPDATE pdfs
                        SET title = %s,
                            description = %s,
                            filename = %s,
                            subject_id = %s,
                            is_active = TRUE
                        WHERE id = %s
                        """,
                        (
                            title,
                            f"{subject_name} book imported from GitHub repo",
                            filename,
                            subject_id,
                            existing_pdf[0]
                        )
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO pdfs (
                            title,
                            description,
                            filename,
                            file_path,
                            author,
                            edition,
                            year,
                            cover_url,
                            storage_url,
                            subject_id,
                            is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        """,
                        (
                            title,
                            f"{subject_name} book imported from GitHub repo",
                            filename,
                            None,
                            None,
                            None,
                            None,
                            None,
                            storage_url,
                            subject_id
                        )
                    )

        conn.commit()
        print("Repo sync completed successfully.")

    except requests.RequestException as e:
        conn.rollback()
        print(f"GitHub API error during repo sync: {e}")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"Database error during repo sync: {e}")
    except Exception as e:
        conn.rollback()
        print(f"Unexpected error during repo sync: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    sync_repo_books()
    