import sqlite3
import time
from contextlib import contextmanager
from typing import Optional
from .article import Article


class ArticleDB:
    def __init__(self, db_path="articles.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # First check if we need to migrate from old schema
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='articles'"
            )
            table_exists = cursor.fetchone() is not None

            if table_exists:
                # Check if we need to migrate from old schema
                cursor.execute("PRAGMA table_info(articles)")
                columns = [col[1] for col in cursor.fetchall()]

                if "account" in columns:  # Need to migrate
                    # Rename account to username
                    cursor.execute(
                        "ALTER TABLE articles RENAME COLUMN account TO username"
                    )
                    conn.commit()

                if "display_name" not in columns:  # Need to add display_name
                    cursor.execute("ALTER TABLE articles ADD COLUMN display_name TEXT")
                    conn.commit()
            else:
                # Create new table with updated schema
                cursor.execute("""
                    CREATE TABLE articles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL,
                        title TEXT,
                        published_at REAL NOT NULL,
                        timestamp REAL NOT NULL,
                        url TEXT NOT NULL UNIQUE,
                        display_name TEXT,
                        UNIQUE(username, url)
                    )
                """)
                conn.commit()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def add_article(
        self,
        username: str,
        title: str,
        published_at: float,
        url: str,
        display_name: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Add an article to the database if it doesn't exist

        Returns:
            tuple[bool, str]: (success, error_message)
            - If successful: (True, "")
            - If failed: (False, error_message)
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO articles (username, title, published_at, timestamp, url, display_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username, title, published_at, time.time(), url, display_name),
                )
                conn.commit()
                return True, ""
        except sqlite3.IntegrityError as e:
            # Article already exists (either duplicate URL or username+url combination)
            return False, f"Duplicate article: {str(e)}"
        except sqlite3.Error as e:
            # Other SQLite errors (connection issues, table problems, etc)
            return False, f"Database error: {str(e)}"
        except Exception as e:
            # Unexpected errors
            return False, f"Unexpected error: {str(e)}"

    def article_exists(self, username, title):
        """Check if an article exists in the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM articles 
                WHERE username = ? AND title = ?
            """,
                (username, title),
            )
            return cursor.fetchone()[0] > 0

    def get_article(self, username: str, title: str) -> Optional[Article]:
        """Get article details from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, username, title, published_at, timestamp, url, display_name
                FROM articles 
                WHERE username = ? AND title = ?
                """,
                (username, title),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "username": row[1],
                    "title": row[2],
                    "published_at": row[3],
                    "timestamp": row[4],
                    "url": row[5],
                    "display_name": row[6],
                }
            return None

    def get_all_articles(self):
        """Get all articles from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, title, published_at, timestamp, url, display_name FROM articles"
            )
            articles = {}
            for row in cursor.fetchall():
                key = f"{row[0]}:{row[1]}"
                articles[key] = {
                    "username": row[0],
                    "title": row[1],
                    "published_at": row[2],
                    "timestamp": row[3],
                    "url": row[4],
                    "display_name": row[5],
                }
            return articles

    def get_articles_paginated(self, username=None, limit=100, offset=0, after_id=None):
        """Get articles with pagination and optional username filter

        Args:
            username: Optional username to filter by
            limit: Maximum number of articles to return
            offset: Number of articles to skip
            after_id: Only return articles with ID greater than this value
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if username and after_id:
                cursor.execute(
                    """
                    SELECT id, username, title, published_at, timestamp, url, display_name
                    FROM articles 
                    WHERE username = ? AND id > ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (username, after_id, limit, offset),
                )
            elif username:
                cursor.execute(
                    """
                    SELECT id, username, title, published_at, timestamp, url, display_name
                    FROM articles 
                    WHERE username = ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (username, limit, offset),
                )
            elif after_id:
                cursor.execute(
                    """
                    SELECT id, username, title, published_at, timestamp, url, display_name
                    FROM articles 
                    WHERE id > ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (after_id, limit, offset),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, username, title, published_at, timestamp, url, display_name
                    FROM articles 
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (limit, offset),
                )

            return [
                {
                    "id": row[0],
                    "username": row[1],
                    "title": row[2],
                    "published_at": row[3],
                    "timestamp": row[4],
                    "url": row[5],
                    "display_name": row[6],
                }
                for row in cursor.fetchall()
            ]

    def get_unique_usernames(self):
        """Get list of all unique usernames"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT username FROM articles ORDER BY username")
            return [row[0] for row in cursor.fetchall()]
