import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_SHOPPING_URL = "https://google.serper.dev/shopping"

_PRICE_PATTERN = re.compile(r"[\d,]+(?:\.\d+)?")


def _extract_price(price_value):
    """Serper returns price as a string (e.g. '₹599') rather than a
    pre-parsed number the way SerpAPI's extracted_price did — pull the
    numeric value out ourselves so the rest of the app (ranking, price
    intelligence, deal optimizer) keeps working unchanged."""
    if price_value is None:
        return None
    if isinstance(price_value, (int, float)):
        return float(price_value)
    match = _PRICE_PATTERN.search(str(price_value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def search_products(query, num_results=20):
    """Query Google Shopping via Serper.dev and return listings normalized to
    the same field names the rest of this app already expects (title,
    source, price, extracted_price, rating, reviews, thumbnail, ...) — so
    switching providers required no changes anywhere else in the pipeline.

    Known gap vs. the previous SerpAPI-based version: Serper's shopping
    results don't include an original/"was" price the way SerpAPI
    sometimes did, so per-listing discount_percent detection in
    price_engine.py will not fire for Serper-sourced results — old_price and
    extracted_old_price are left as None (never guessed) rather than faked.
    Cross-listing comparisons (average/lowest/highest/percentile among
    today's results) are unaffected since those only need extracted_price.
    """
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "gl": "in", "hl": "en", "num": num_results}

    response = requests.post(SERPER_SHOPPING_URL, json=payload, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()

    results = []
    for item in (data.get("shopping") or [])[:num_results]:
        results.append({
            "title": item.get("title"),
            "source": item.get("source"),
            "product_link": item.get("link"),
            "link": item.get("link"),
            "price": item.get("price"),
            "extracted_price": _extract_price(item.get("price")),
            "rating": item.get("rating"),
            "reviews": item.get("ratingCount"),
            "delivery": item.get("delivery"),
            "thumbnail": item.get("imageUrl"),
            "product_id": item.get("productId") or item.get("position"),
            "position": item.get("position"),
            "old_price": None,
            "extracted_old_price": None,
            "multiple_sources": None,
        })

    return results
