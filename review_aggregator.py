import os
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search"

PLATFORM_QUERIES = {
    "YouTube": "site:youtube.com",
    "Reddit": "site:reddit.com",
    "Twitter/X": "(site:twitter.com OR site:x.com)",
    "Instagram": "site:instagram.com",
    "Facebook": "site:facebook.com",
}


def _search_web(query, num=5):
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": num,
        "gl": "in",
        "hl": "en",
    }
    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=12)
        response.raise_for_status()
        return response.json().get("organic_results", []) or []
    except requests.RequestException:
        return []


def gather_review_signals(product_title):
    """Search YouTube, Reddit, Twitter/X, Instagram, and Facebook for review mentions of a product."""
    def search_platform(platform_filter):
        query = f'"{product_title}" review {platform_filter}'
        return _search_web(query)

    with ThreadPoolExecutor(max_workers=len(PLATFORM_QUERIES)) as executor:
        futures = {
            platform: executor.submit(search_platform, platform_filter)
            for platform, platform_filter in PLATFORM_QUERIES.items()
        }
        results = {platform: future.result() for platform, future in futures.items()}

    platform_counts = {}
    total_sources = 0
    snippets = []

    for platform, organic_results in results.items():
        count = len(organic_results)
        platform_counts[platform] = count
        total_sources += count
        for result in organic_results[:3]:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if title or snippet:
                snippets.append(f"[{platform}] {title}: {snippet}")

    return {
        "platform_counts": platform_counts,
        "total_sources": total_sources,
        "snippets": snippets[:12],
    }


def _fallback_reason(product, signals=None):
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")
    total_sources = (signals or {}).get("total_sources")
    if total_sources:
        return (
            f"Recommended based on a {rating} rating from {reviews} shopping reviews. "
            f"{total_sources} external mentions were found across YouTube, Reddit, "
            "Twitter/X, Instagram, and Facebook, but a detailed summary couldn't be "
            "generated this time."
        )
    return (
        f"Recommended based on a {rating} rating from {reviews} shopping reviews. "
        "Cross-platform review lookup was unavailable for this product right now."
    )


def enrich_products_with_reviews(products):
    """Attach cross-platform (YouTube/Reddit/Twitter) review reasons to each product."""
    from query_understanding import synthesize_review_reason

    def enrich_one(product):
        signals = {"platform_counts": {}, "total_sources": 0, "snippets": []}
        try:
            signals = gather_review_signals(product.get("title", ""))
            product["review_sources_count"] = signals["total_sources"]
            product["review_platform_counts"] = signals["platform_counts"]
            product["why_recommend"] = synthesize_review_reason(product, signals)
        except Exception:
            product["review_sources_count"] = signals["total_sources"]
            product["review_platform_counts"] = signals["platform_counts"]
            product["why_recommend"] = _fallback_reason(product, signals)
        return product

    with ThreadPoolExecutor(max_workers=5) as executor:
        return list(executor.map(enrich_one, products))
