from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from lib.db import ArticleDB

app = FastAPI(
    title="WeChat Article Monitor API",
    description="API for accessing collected WeChat articles",
)


class Article(BaseModel):
    account: str
    title: str
    published_at: str
    timestamp: float
    url: str


@app.get("/articles/", response_model=List[Article])
async def get_articles(
    account: Optional[str] = None, limit: int = 100, offset: int = 0
):
    """Get all articles with optional filtering by account"""
    db = ArticleDB()
    articles = []

    # Convert the dictionary from get_all_articles() to a list
    all_articles = [v for v in db.get_all_articles().values()]

    # Filter by account if specified
    if account:
        all_articles = [a for a in all_articles if a["account"] == account]

    # Apply pagination
    articles = all_articles[offset : offset + limit]

    return articles


@app.get("/articles/{account}/{title}", response_model=Article)
async def get_article(account: str, title: str):
    """Get a specific article by account and title"""
    db = ArticleDB()
    article = db.get_article(account, title)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get("/accounts/", response_model=List[str])
async def get_accounts():
    """Get list of all unique accounts"""
    db = ArticleDB()
    articles = db.get_all_articles()
    accounts = set(article["account"] for article in articles.values())
    return sorted(list(accounts))
