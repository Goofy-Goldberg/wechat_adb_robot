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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT NOT NULL,
                    title TEXT,
                    published_at REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    UNIQUE(account, url)
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
        account: str,
        title: str,
        published_at: float,
        url: str,
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
                    INSERT INTO articles (account, title, published_at, timestamp, url)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (account, title, published_at, time.time(), url),
                )
                conn.commit()
                return True, ""
        except sqlite3.IntegrityError as e:
            # Article already exists (either duplicate URL or account+url combination)
            return False, f"Duplicate article: {str(e)}"
        except sqlite3.Error as e:
            # Other SQLite errors (connection issues, table problems, etc)
            return False, f"Database error: {str(e)}"
        except Exception as e:
            # Unexpected errors
            return False, f"Unexpected error: {str(e)}"

    def article_exists(self, account, title):
        """Check if an article exists in the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM articles 
                WHERE account = ? AND title = ?
            """,
                (account, title),
            )
            return cursor.fetchone()[0] > 0

    def get_article(self, account: str, title: str) -> Optional[Article]:
        """Get article details from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT account, title, published_at, timestamp, url 
                FROM articles 
                WHERE account = ? AND title = ?
                """,
                (account, title),
            )
            row = cursor.fetchone()
            if row:
                return Article(
                    account=row[0],
                    title=row[1],
                    published_at=row[2],
                    timestamp=row[3],
                    url=row[4],
                )
            return None

    def get_all_articles(self):
        """Get all articles from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT account, title, published_at, timestamp, url FROM articles"
            )
            articles = {}
            for row in cursor.fetchall():
                key = f"{row[0]}:{row[1]}"
                articles[key] = {
                    "account": row[0],
                    "title": row[1],
                    "published_at": row[2],
                    "timestamp": row[3],
                    "url": row[4],
                }
            return articles

    def get_articles_paginated(self, account=None, limit=100, offset=0):
        """Get articles with pagination and optional account filter"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if account:
                cursor.execute(
                    """
                    SELECT account, title, published_at, timestamp, url 
                    FROM articles 
                    WHERE account = ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (account, limit, offset),
                )
            else:
                cursor.execute(
                    """
                    SELECT account, title, published_at, timestamp, url 
                    FROM articles 
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """,
                    (limit, offset),
                )

            return [
                {
                    "account": row[0],
                    "title": row[1],
                    "published_at": row[2],
                    "timestamp": row[3],
                    "url": row[4],
                }
                for row in cursor.fetchall()
            ]

    def get_unique_accounts(self):
        """Get list of all unique accounts"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT account FROM articles ORDER BY account")
            return [row[0] for row in cursor.fetchall()]
