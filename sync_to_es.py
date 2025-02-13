from lib.db import ArticleDB
import requests
from lib.utils import new_stream_logger
from os import getenv
from dotenv import load_dotenv

logger = new_stream_logger(__name__)
load_dotenv()  # Load environment variables from .env file


def sync_to_elasticsearch():
    # Initialize DB connection
    db = ArticleDB()

    # Fetch articles
    articles_dict = db.get_all_articles()

    # Get API configuration from environment variables
    api_host = getenv("API_HOST", "localhost")
    api_port = getenv("API_PORT", "8000")
    api_url = f"http://{api_host}:{api_port}/articles/bulk"

    # Prepare articles list
    articles = []
    for article_key, article_data in articles_dict.items():
        article_data.pop("id", None)  # Remove id field
        articles.append(article_data)

    # Send to API in batches
    batch_size = 100
    for i in range(0, len(articles), batch_size):
        batch = articles[i : i + batch_size]
        response = requests.post(
            api_url,
            json=batch,
            verify=False,  # Only if using self-signed certs
        )
        response.raise_for_status()
        result = response.json()
        logger.info(
            f"Batch {i // batch_size + 1}: "
            f"Succeeded: {result['success_count']}, "
            f"Failed: {result['error_count']}"
        )
