from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from lib.db import ArticleDB

app = FastAPI(
    title="WeChat Article Monitor API",
    description="API for accessing collected WeChat articles",
)


class Article(BaseModel):
    id: int
    username: str
    title: str
    published_at: str
    timestamp: float
    url: str
    display_name: Optional[str] = None


@app.get("/articles/", response_model=List[Article])
async def get_articles(
    username: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    after: Optional[int] = None,
):
    """Get all articles with optional filtering by username and ID

    Args:
        username: Optional username to filter by
        limit: Maximum number of articles to return
        offset: Number of articles to skip
        after: Only return articles with ID greater than this value
    """
    db = ArticleDB()
    articles = db.get_articles_paginated(
        username=username,
        limit=limit,
        offset=offset,
        after_id=after,
    )
    return articles


@app.get("/articles/{username}/{title}", response_model=Article)
async def get_article(username: str, title: str):
    """Get a specific article by username and title"""
    db = ArticleDB()
    article = db.get_article(username, title)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get("/usernames/", response_model=List[str])
async def get_usernames():
    """Get list of all unique usernames"""
    db = ArticleDB()
    articles = db.get_all_articles()
    usernames = set(article["username"] for article in articles.values())
    return sorted(list(usernames))
