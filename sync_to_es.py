import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any
import requests
import urllib3
from dotenv import load_dotenv
from lib.db import ArticleDB

# Suppress SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_es_config() -> tuple[str, int, bool, bool, tuple[str, str] | None]:
    """Get Elasticsearch configuration from environment variables"""
    load_dotenv()

    host = os.getenv("ES_HOST", "localhost")
    port = int(os.getenv("ES_PORT", "9200"))
    use_ssl = True  # Always use SSL
    verify_certs = os.getenv("ES_VERIFY_CERTS", "false").lower() == "true"

    # Get authentication credentials if provided
    username = os.getenv("ES_USERNAME")
    password = os.getenv("ES_PASSWORD")
    auth = (username, password) if username and password else None

    return host, port, use_ssl, verify_certs, auth


def prepare_article_for_es(article: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare article data for Elasticsearch indexing"""
    # Convert Unix timestamps to ISO format for better ES compatibility
    es_doc = article.copy()

    for ts_field in ["published_at", "timestamp"]:
        if es_doc.get(ts_field):
            es_doc[ts_field] = datetime.fromtimestamp(es_doc[ts_field]).isoformat()

    return es_doc


def sync_to_elasticsearch():
    host, port, use_ssl, verify_certs, auth = get_es_config()
    protocol = "https" if use_ssl else "http"
    base_url = f"{protocol}://{host}:{port}"

    # Test ES connection
    try:
        resp = requests.get(
            f"{base_url}/_cluster/health", verify=verify_certs, auth=auth
        )
        resp.raise_for_status()
        logger.info("Successfully connected to Elasticsearch")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to connect to Elasticsearch: {e}")
        sys.exit(1)

    # Initialize DB connection
    db = ArticleDB()

    # Ensure index exists with proper mappings
    index_name = "articles"
    mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "username": {"type": "keyword"},
                "title": {"type": "text"},
                "published_at": {"type": "date"},
                "timestamp": {"type": "date"},
                "url": {"type": "keyword"},
                "display_name": {"type": "keyword"},
                "repost": {"type": "boolean"},
                "op_display_name": {"type": "keyword"},
                "op_username": {"type": "keyword"},
            }
        }
    }

    # Create index if it doesn't exist
    index_url = f"{base_url}/{index_name}"
    if requests.head(index_url, verify=verify_certs, auth=auth).status_code == 404:
        resp = requests.put(index_url, json=mapping, verify=verify_certs, auth=auth)
        if resp.status_code != 200:
            logger.error(f"Failed to create index: {resp.text}")
            sys.exit(1)
        logger.info("Created Elasticsearch index with mappings")

    # Fetch and index articles
    articles_dict = db.get_all_articles()
    success_count = 0
    error_count = 0

    for article_key, article_data in articles_dict.items():
        # Add the key as id for ES
        doc_id = article_key.replace(":", "_")  # ES doesn't like colons in IDs

        es_doc = prepare_article_for_es(article_data)

        try:
            resp = requests.put(
                f"{index_url}/_doc/{doc_id}",
                json=es_doc,
                verify=verify_certs,
                auth=auth,
            )
            if resp.status_code in (200, 201):
                success_count += 1
            else:
                error_count += 1
                logger.error(f"Failed to index article {doc_id}: {resp.text}")
        except requests.exceptions.RequestException as e:
            error_count += 1
            logger.error(f"Request failed for article {doc_id}: {e}")

    logger.info(f"Sync complete. Successfully indexed {success_count} articles.")
    if error_count > 0:
        logger.warning(f"Failed to index {error_count} articles.")


if __name__ == "__main__":
    sync_to_elasticsearch()
