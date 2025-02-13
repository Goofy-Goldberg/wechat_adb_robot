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
                    username TEXT NOT NULL,
                    title TEXT,
                    published_at REAL,
                    timestamp REAL NOT NULL,
                    url TEXT UNIQUE,
                    display_name TEXT,
                    repost BOOLEAN DEFAULT FALSE,
                    op_display_name TEXT,
                    op_username TEXT,
                    content TEXT,
                    content_raw TEXT,
                    content_translated TEXT,
                    content_translated_raw TEXT,
                    title_translated TEXT,
                    scraped_at REAL,
                    metadata TEXT,  -- JSON string for additional metadata (description, ogImage, biz, sn, mid, idx, etc.)
                    keywords TEXT,  -- JSON array of extracted keywords from content_translated
                    UNIQUE(username, title)
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
        repost: bool = False,
        op_display_name: Optional[str] = None,
        op_username: Optional[str] = None,
        content: Optional[str] = None,
        content_raw: Optional[str] = None,
        content_translated: Optional[str] = None,
        content_translated_raw: Optional[str] = None,
        title_translated: Optional[str] = None,
        metadata: Optional[str] = None,
        keywords: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Add or update an article in the database

        Args:
            username: The account username
            title: Article title
            published_at: UTC timestamp of publication
            url: Article URL
            display_name: Display name of the account
            repost: Whether this is a repost
            op_display_name: Original poster's display name (for reposts)
            op_username: Original poster's username (for reposts)
            content: Processed article content
            content_raw: Raw article content
            content_translated: Translated article content
            content_translated_raw: Raw translated article content
            title_translated: Translated article title
            metadata: JSON string containing additional metadata
            keywords: JSON array of extracted keywords from content_translated

        Returns:
            tuple[bool, str]: (success, error_message)
            - If successful: (True, "")
            - If duplicate: (False, "Duplicate article: {url}")
            - If database error: (False, "Database error: {error}")
            - If other error: (False, "Unexpected error: {error}")
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # First check if article exists
                cursor.execute(
                    """
                    SELECT url FROM articles 
                    WHERE (username = ? AND title = ?) OR url = ?
                    """,
                    (username, title, url),
                )
                existing = cursor.fetchone()
                if existing:
                    return False, f"Duplicate article: {existing[0]}"

                # If we get here, article doesn't exist, so insert it
                cursor.execute(
                    """
                    INSERT INTO articles (
                        username, title, published_at, timestamp, url, 
                        display_name, repost, op_display_name, op_username,
                        content, content_raw, content_translated, content_translated_raw,
                        title_translated, metadata, keywords
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        title,
                        published_at,
                        time.time(),
                        url,
                        display_name,
                        repost,
                        op_display_name,
                        op_username,
                        content,
                        content_raw,
                        content_translated,
                        content_translated_raw,
                        title_translated,
                        metadata,
                        keywords,
                    ),
                )
                conn.commit()
                return True, ""
        except sqlite3.Error as e:
            return False, f"Database error: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def update_article(
        self, username: str, title: str, url: str, **kwargs
    ) -> tuple[bool, str]:
        """Update an existing article in the database

        Args:
            username: The account username
            title: Article title
            url: Article URL
            **kwargs: Any article fields to update

        Returns:
            tuple[bool, str]: (success, error_message)
            - If successful: (True, "")
            - If article not found: (False, "Article not found")
            - If database error: (False, "Database error: {error}")
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # First check if article exists
                cursor.execute(
                    """
                    SELECT id FROM articles 
                    WHERE (username = ? AND title = ?) OR url = ?
                    """,
                    (username, title, url),
                )
                existing = cursor.fetchone()
                if not existing:
                    return False, "Article not found"

                # Build update query dynamically based on provided kwargs
                if not kwargs:
                    return True, ""  # Nothing to update

                set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
                values = list(kwargs.values())
                values.extend([username, title, url])  # For WHERE clause

                cursor.execute(
                    f"""
                    UPDATE articles 
                    SET {set_clause}
                    WHERE (username = ? AND title = ?) OR url = ?
                    """,
                    values,
                )
                conn.commit()
                return True, ""
        except sqlite3.Error as e:
            return False, f"Database error: {str(e)}"
        except Exception as e:
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
                "SELECT * FROM articles WHERE username = ? AND title = ?",
                (username, title),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row, cursor)
            return None

    def get_all_articles(self):
        """Get all articles from the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM articles")
            return {
                f"{row[1]}:{row[2]}": self._row_to_dict(row, cursor)
                for row in cursor.fetchall()
            }

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
            base_query = "SELECT * FROM articles"

            if username and after_id:
                where_clause = "WHERE username = ? AND id > ?"
                params = (username, after_id, limit, offset)
            elif username:
                where_clause = "WHERE username = ?"
                params = (username, limit, offset)
            elif after_id:
                where_clause = "WHERE id > ?"
                params = (after_id, limit, offset)
            else:
                where_clause = ""
                params = (limit, offset)

            query = f"""
                {base_query}
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params)
            return [self._row_to_dict(row, cursor) for row in cursor.fetchall()]

    def get_unique_usernames(self):
        """Get list of all unique usernames"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT username FROM articles ORDER BY username")
            return [row[0] for row in cursor.fetchall()]

    def _row_to_dict(self, row: tuple, cursor) -> dict:
        """Convert a database row to a dictionary"""
        columns = [desc[0] for desc in cursor.description]  # Get column names
        result = dict(zip(columns, row))

        # Handle any type conversions
        if "repost" in result:
            result["repost"] = bool(result["repost"])

        return result
