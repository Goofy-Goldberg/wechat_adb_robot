from dataclasses import dataclass
from time import time
from typing import Optional


@dataclass
class Article:
    account: str
    title: str
    timestamp: Optional[str] = None
    url: Optional[str] = None
    first_seen: float = None

    def __post_init__(self):
        if self.first_seen is None:
            self.first_seen = time()

    @property
    def key(self) -> str:
        """Unique identifier for the article"""
        return f"{self.account}:{self.title}"

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage"""
        return {
            "account": self.account,
            "title": self.title,
            "timestamp": self.timestamp,
            "url": self.url,
            "first_seen": self.first_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Create an Article instance from a dictionary"""
        return cls(**data)
