import os
import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search"


def search_products(query, num_results=10):
    """Query Google Shopping via SerpAPI and return raw product listings."""
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": num_results,
        "google_domain": "google.co.in",
        "gl": "in",
        "hl": "en",
        "location": "India",
        "currency": "INR",
    }

    response = requests.get(SERPAPI_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    return data.get("shopping_results", [])
