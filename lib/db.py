import sqlite3
import time
from contextlib import contextmanager


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
                    title TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    url TEXT NOT NULL,
                    UNIQUE(account, title)
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

    def add_article(self, account, title, timestamp, url):
        """Add a new article to the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO articles (account, title, timestamp, first_seen, url)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (account, title, timestamp, time.time(), url),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Article already exists
                return False

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

    def get_article(self, account, title):
        """Get article details from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT account, title, timestamp, first_seen, url 
                FROM articles 
                WHERE account = ? AND title = ?
            """,
                (account, title),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "account": row[0],
                    "title": row[1],
                    "timestamp": row[2],
                    "first_seen": row[3],
                    "url": row[4],
                }
            return None

    def get_all_articles(self):
        """Get all articles from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT account, title, timestamp, first_seen, url FROM articles"
            )
            articles = {}
            for row in cursor.fetchall():
                key = f"{row[0]}:{row[1]}"
                articles[key] = {
                    "account": row[0],
                    "title": row[1],
                    "timestamp": row[2],
                    "first_seen": row[3],
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
                    SELECT account, title, timestamp, first_seen, url 
                    FROM articles 
                    WHERE account = ?
                    ORDER BY first_seen DESC
                    LIMIT ? OFFSET ?
                """,
                    (account, limit, offset),
                )
            else:
                cursor.execute(
                    """
                    SELECT account, title, timestamp, first_seen, url 
                    FROM articles 
                    ORDER BY first_seen DESC
                    LIMIT ? OFFSET ?
                """,
                    (limit, offset),
                )

            return [
                {
                    "account": row[0],
                    "title": row[1],
                    "timestamp": row[2],
                    "first_seen": row[3],
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
