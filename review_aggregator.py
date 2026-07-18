import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_SEARCH_URL = "https://google.serper.dev/search"

# Limited to 3 platforms (not 5) to control SerpAPI cost: each product does
# one search per platform here, and this runs for every product in the
# shortlist, so platform count directly multiplies API usage. Instagram and
# Facebook were dropped rather than YouTube/Reddit/Twitter — both aggressively
# block search-engine crawlers, so they contributed little real evidence per
# call spent versus these three.
PLATFORM_QUERIES = {
    "YouTube": "site:youtube.com",
    "Reddit": "site:reddit.com",
    "Twitter/X": "(site:twitter.com OR site:x.com)",
}


def _search_web(query, num=5):
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "gl": "in", "hl": "en", "num": num}
    try:
        response = requests.post(SERPER_SEARCH_URL, json=payload, headers=headers, timeout=12)
        response.raise_for_status()
        organic = response.json().get("organic") or []
        # Normalized to the same {"title", "snippet"} shape SerpAPI's
        # organic_results used, so gather_review_signals() below (and
        # everything downstream of it) needed no further changes.
        return [{"title": r.get("title", ""), "snippet": r.get("snippet", "")} for r in organic]
    except requests.RequestException:
        return []


def gather_review_signals(product_title):
    """Search YouTube, Reddit, and Twitter/X for review mentions of a product."""
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
    snippets_by_platform = {}

    for platform, organic_results in results.items():
        count = len(organic_results)
        platform_counts[platform] = count
        total_sources += count
        platform_snippets = []
        for result in organic_results[:5]:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if title or snippet:
                entry = f"{title}: {snippet}"
                platform_snippets.append(entry)
                if len(platform_snippets) <= 3:
                    snippets.append(f"[{platform}] {entry}")
        if platform_snippets:
            snippets_by_platform[platform] = platform_snippets

    return {
        "platform_counts": platform_counts,
        "total_sources": total_sources,
        "snippets": snippets[:12],
        "snippets_by_platform": snippets_by_platform,
    }


def _fallback_reason(product, signals=None):
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")
    total_sources = (signals or {}).get("total_sources")
    if total_sources:
        return (
            f"Recommended based on a {rating} rating from {reviews} shopping reviews. "
            f"{total_sources} external mentions were found across YouTube, Reddit, "
            "and Twitter/X, but a detailed summary couldn't be generated this time."
        )
    return (
        f"Recommended based on a {rating} rating from {reviews} shopping reviews. "
        "Cross-platform review lookup was unavailable for this product right now."
    )


def enrich_products_with_reviews(products):
    """Attach cross-platform (YouTube/Reddit/Twitter) review reasons, an AI
    Trust Score, and structured Review Intelligence to each product.

    Fetches review evidence once per product, then makes exactly ONE Groq
    call per product (evidence_engine.analyze_evidence) covering everything
    trust_engine and review_intelligence need, instead of each of those
    modules making its own separate call — cuts ~3 Groq calls/product down
    to 1, which matters a lot with 5 products enriched per search (was
    tripping Groq's per-minute rate limit on the free tier)."""
    from evidence_engine import analyze_evidence
    from trust_engine import score_from_sentiment
    from review_intelligence import from_raw

    def enrich_one(product):
        signals = {"platform_counts": {}, "total_sources": 0, "snippets": [], "snippets_by_platform": {}}
        try:
            signals = gather_review_signals(product.get("title", ""))
        except Exception:
            pass
        product["review_sources_count"] = signals["total_sources"]
        product["review_platform_counts"] = signals["platform_counts"]

        try:
            evidence = analyze_evidence(product, signals)
        except Exception:
            evidence = None

        if evidence is None:
            product["why_recommend"] = _fallback_reason(product, signals)
            trust = {
                "trust_score": None,
                "confidence": "Low",
                "positive_ratio": None,
                "negative_ratio": None,
                "fake_review_probability": None,
                "reason": "AI Trust Score was unavailable for this product right now.",
            }
            product["review_intelligence"] = None
        else:
            product["why_recommend"] = evidence["why_recommend"]
            sentiment = {
                "positive_ratio": evidence["positive_ratio"],
                "negative_ratio": evidence["negative_ratio"],
                "fake_review_probability": evidence["fake_review_probability"],
                "sentiment_score": evidence["sentiment_score"],
                "reason": evidence["sentiment_reason"],
            }
            try:
                trust = score_from_sentiment(product, signals, sentiment)
            except Exception:
                trust = {
                    "trust_score": None,
                    "confidence": "Low",
                    "positive_ratio": None,
                    "negative_ratio": None,
                    "fake_review_probability": None,
                    "reason": "AI Trust Score was unavailable for this product right now.",
                }
            product["review_intelligence"] = from_raw(evidence)

        product["trust_score"] = trust["trust_score"]
        product["trust_confidence"] = trust["confidence"]
        product["trust_positive_ratio"] = trust["positive_ratio"]
        product["trust_negative_ratio"] = trust["negative_ratio"]
        product["trust_fake_review_probability"] = trust["fake_review_probability"]
        product["trust_reason"] = trust["reason"]

        return product

    with ThreadPoolExecutor(max_workers=5) as executor:
        return list(executor.map(enrich_one, products))
