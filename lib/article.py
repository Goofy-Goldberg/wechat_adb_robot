from dataclasses import dataclass
from time import time
from typing import Optional, List


@dataclass
class Article:
    username: str
    title: Optional[str] = None
    published_at: Optional[float] = None
    url: Optional[str] = None
    timestamp: float = None
    display_name: Optional[str] = None
    id: Optional[int] = None
    repost: bool = False
    op_display_name: Optional[str] = None
    op_username: Optional[str] = None
    content: Optional[str] = None
    content_raw: Optional[str] = None
    content_translated: Optional[str] = None
    content_translated_raw: Optional[str] = None
    title_translated: Optional[str] = None
    author: Optional[str] = None
    scraped_at: Optional[float] = None
    metadata: Optional[str] = None
    keywords: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time()

    @property
    def key(self) -> str:
        """Unique identifier for the article"""
        return f"{self.username}:{self.title}"

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage"""
        return {
            "username": self.username,
            "title": self.title,
            "published_at": self.published_at,
            "url": self.url,
            "timestamp": self.timestamp,
            "display_name": self.display_name,
            "id": self.id,
            "repost": self.repost,
            "op_display_name": self.op_display_name,
            "op_username": self.op_username,
            "content": self.content,
            "content_raw": self.content_raw,
            "content_translated": self.content_translated,
            "content_translated_raw": self.content_translated_raw,
            "title_translated": self.title_translated,
            "author": self.author,
            "scraped_at": self.scraped_at,
            "metadata": self.metadata,
            "keywords": self.keywords,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Create an Article instance from a dictionary"""
        return cls(**data)
