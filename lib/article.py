from dataclasses import dataclass
from time import time
from typing import Optional


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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Create an Article instance from a dictionary"""
        return cls(**data)
