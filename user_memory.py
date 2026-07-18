"""User Memory (PRD V2 Module 6) — standalone service.

Honesty note: the PRD asks this module to remember "Previous Purchases" and
"Languages". Neither is implemented here, and neither is faked:
  - Previous Purchases: this app has no checkout/order flow. Users only ever
    click through to an external "Purchase Link" on a third-party site — we
    have zero visibility into whether a purchase actually happened. Tracking
    "purchases" would mean fabricating data. What IS real and IS tracked is
    search history, which is a genuinely different (weaker) signal and is
    never presented as purchase history.
  - Languages: this app has no language switcher — everything is English
    only. A "preferred language" field would just be a hardcoded "en" for
    every user, which isn't a learned preference, so it isn't stored.

What this module DOES remember, derived from real SearchHistory rows:
  - budget: typical (median) budget_max across past searches
  - brands: brands mentioned across past searches, most frequent first
  - favorite_categories: categories searched, most frequent first
  - favorite_stores: stores that showed up most often in past search RESULTS
    (a real behavioral signal — which sellers keep appearing for this user
    — not a fabricated "favorite" based on stated intent we don't have)
  - search_history: the raw list of past queries with timestamps

Contract:
    record_search(user_id: int, query: str, intent: dict, top_stores: list[str]) -> None
    get_memory_summary(user_id: int, limit: int = 20) -> {
        "search_count": int,
        "top_categories": [(category, count), ...],
        "top_brands": [(brand, count), ...],
        "typical_budget_max": float | None,
        "top_stores": [(store, count), ...],
        "recent_searches": [{"query": str, "category": str | None, "created_at": str}, ...],
    }
    welcome_back_message(user_id: int) -> str | None
"""

from collections import Counter
from statistics import median

from extensions import db
from models import SearchHistory


def record_search(user_id, query, intent, top_stores=None):
    """Save a completed search. Called only after a real product search
    finishes — never for intermediate AI Buying Advisor question turns,
    since those aren't a completed search yet."""
    entry = SearchHistory(
        user_id=user_id,
        search_query=query[:500],
        category=(intent or {}).get("category"),
        brand=(intent or {}).get("brand"),
        budget_max=(intent or {}).get("budget_max"),
        top_stores=",".join((top_stores or [])[:5]) or None,
    )
    db.session.add(entry)
    db.session.commit()


def get_memory_summary(user_id, limit=20):
    rows = (
        SearchHistory.query
        .filter_by(user_id=user_id)
        .order_by(SearchHistory.created_at.desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return {
            "search_count": 0,
            "top_categories": [],
            "top_brands": [],
            "typical_budget_max": None,
            "top_stores": [],
            "recent_searches": [],
        }

    categories = Counter(r.category for r in rows if r.category)
    brands = Counter(r.brand for r in rows if r.brand)
    budgets = [r.budget_max for r in rows if r.budget_max]

    stores = Counter()
    for r in rows:
        if r.top_stores:
            stores.update(s for s in r.top_stores.split(",") if s)

    return {
        "search_count": len(rows),
        "top_categories": categories.most_common(5),
        "top_brands": brands.most_common(5),
        "typical_budget_max": round(median(budgets), 2) if budgets else None,
        "top_stores": stores.most_common(5),
        "recent_searches": [
            {
                "query": r.search_query,
                "category": r.category,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows[:5]
        ],
    }


def welcome_back_message(user_id):
    """A short personalized greeting for a returning user with search
    history, or None for a new user with nothing to reference yet."""
    summary = get_memory_summary(user_id, limit=5)
    if summary["search_count"] == 0:
        return None

    most_recent_category = summary["recent_searches"][0]["category"]
    if most_recent_category:
        return f"Welcome back! Still looking for {most_recent_category}, or searching for something new today?"

    most_recent_query = summary["recent_searches"][0]["query"]
    return f"Welcome back! Still interested in \"{most_recent_query}\", or searching for something new today?"
