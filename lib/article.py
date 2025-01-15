from dataclasses import dataclass
from time import time
from typing import Optional


@dataclass
class Article:
    account: str
    title: str
    published_at: Optional[float] = None
    url: Optional[str] = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time()

    @property
    def key(self) -> str:
        """Unique identifier for the article"""
        return f"{self.account}:{self.title}"

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage"""
        return {
            "account": self.account,
            "title": self.title,
            "published_at": self.published_at,
            "url": self.url,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Create an Article instance from a dictionary"""
        return cls(**data)
