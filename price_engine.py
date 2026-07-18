"""Price Intelligence Engine (PRD V2 Module 3) — standalone service.

Honesty note: the PRD describes this module backed by a price-history
database updated by a daily cron job, tracking each product's price over
time so "average/lowest/highest" means "across weeks/months." That
infrastructure doesn't exist yet in this codebase. This v1 works entirely
from the current search's snapshot instead:
  - the live price the shopping API returned right now
  - any listed/original price the source itself is advertising a discount
    against (SerpAPI's extracted_old_price, when present)
  - how this listing's price compares to the OTHER real listings found for
    the same search right now (not historical data — a same-moment market
    comparison across sellers)

"Average/Lowest/Highest Price" here means "across today's comparable
listings," not "across time." Nothing here is fabricated as if it were
historical. The output vocabulary (Buy Now / Wait / Excellent Deal / Poor
Deal) matches the PRD's UI contract so the frontend and chat copy don't need
to change later — only this module's internals would, once a real price
history table + cron job (the PRD's own stated "Future" work) exists to feed
genuine trend data in.

This module makes no external API calls — it's pure arithmetic on data
already fetched elsewhere in the pipeline, so it adds no SerpAPI/Groq cost.

Known data quirk this module works around: SerpAPI's own `extracted_old_price`
field is unreliable when the source text is formatted like "16% off₹2,990" —
SerpAPI parses out "16" (the discount percentage) instead of 2990 (the actual
old price). This module re-parses the ₹ amount out of the raw `old_price`
string itself rather than trusting `extracted_old_price` directly.

Contract:
    build_market_snapshot(comparable_products: list[dict]) -> {
        "average_price": float | None,
        "lowest_price": float | None,
        "highest_price": float | None,
        "sample_size": int,
    }

    analyze_price(product: dict, market_snapshot: dict, comparable_prices: list[float]) -> {
        "current_price": float | None,
        "listed_price": float | None,
        "discount_percent": float | None,
        "average_price": float | None,
        "lowest_price": float | None,
        "highest_price": float | None,
        "price_percentile": float | None,   # 0 (priciest here) - 100 (cheapest here)
        "recommendation": "Buy Now" | "Wait" | "Excellent Deal" | "Poor Deal" | "Unknown",
        "reason": str,
        "trend_available": False,
    }
"""


import re

_PRICE_PATTERN = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)")


def _parse_price_from_text(text):
    """Extract the ₹ amount from a raw price string. SerpAPI's own
    extracted_old_price field can't be trusted for "X% off₹Y"-style text (see
    module docstring), so this re-parses the actual amount directly."""
    if not text or not isinstance(text, str):
        return None
    match = _PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def build_market_snapshot(comparable_products):
    """Average/lowest/highest price across the OTHER listings found in this
    same search — a today-only market comparison, not price history."""
    prices = [
        p.get("extracted_price")
        for p in (comparable_products or [])
        if isinstance(p.get("extracted_price"), (int, float)) and p.get("extracted_price") > 0
    ]
    if not prices:
        return {"average_price": None, "lowest_price": None, "highest_price": None, "sample_size": 0}
    return {
        "average_price": round(sum(prices) / len(prices), 2),
        "lowest_price": min(prices),
        "highest_price": max(prices),
        "sample_size": len(prices),
    }


def _price_percentile(current_price, comparable_prices):
    """0 = priciest listing found, 100 = cheapest listing found."""
    if current_price is None or not comparable_prices:
        return None
    if len(comparable_prices) <= 1:
        return 50.0
    more_expensive = sum(1 for p in comparable_prices if p > current_price)
    return round((more_expensive / (len(comparable_prices) - 1)) * 100, 1)


def analyze_price(product, market_snapshot, comparable_prices=None):
    current_price = product.get("extracted_price")
    listed_price = _parse_price_from_text(product.get("old_price"))
    if listed_price is None and isinstance(product.get("extracted_old_price"), (int, float)):
        # Fall back to SerpAPI's own field only when there's no raw text to
        # re-parse — it's fine in the plain "₹Y" case, just not "X% off₹Y".
        candidate = product["extracted_old_price"]
        if isinstance(current_price, (int, float)) and candidate > current_price:
            listed_price = candidate
    market_snapshot = market_snapshot or {}
    comparable_prices = comparable_prices or []

    discount_percent = None
    if (
        isinstance(listed_price, (int, float))
        and isinstance(current_price, (int, float))
        and listed_price > current_price > 0
    ):
        discount_percent = round((listed_price - current_price) / listed_price * 100, 1)

    if not isinstance(current_price, (int, float)):
        return {
            "current_price": None,
            "listed_price": listed_price,
            "discount_percent": discount_percent,
            "average_price": market_snapshot.get("average_price"),
            "lowest_price": market_snapshot.get("lowest_price"),
            "highest_price": market_snapshot.get("highest_price"),
            "price_percentile": None,
            "recommendation": "Unknown",
            "reason": "Price data unavailable for this listing.",
            "trend_available": False,
        }

    percentile = _price_percentile(current_price, comparable_prices)

    if discount_percent is not None and discount_percent >= 20:
        recommendation = "Excellent Deal"
    elif discount_percent is not None and discount_percent >= 8:
        recommendation = "Buy Now"
    elif percentile is not None and percentile >= 75:
        recommendation = "Buy Now"
    elif percentile is not None and percentile <= 15:
        recommendation = "Poor Deal"
    else:
        recommendation = "Wait"

    reason_parts = []
    if discount_percent:
        reason_parts.append(f"{discount_percent}% off the listed price of ₹{listed_price:,.0f}")
    if percentile is not None and market_snapshot.get("sample_size", 0) > 1:
        if percentile >= 50:
            reason_parts.append(f"cheaper than {round(percentile)}% of the {market_snapshot['sample_size']} comparable listings found today")
        else:
            reason_parts.append(f"pricier than {round(100 - percentile)}% of the {market_snapshot['sample_size']} comparable listings found today")

    reason = (
        "Based on today's listings: " + "; ".join(reason_parts) + "."
        if reason_parts
        else "No active discount or enough comparable listings found today to judge this price against."
    )

    return {
        "current_price": current_price,
        "listed_price": listed_price,
        "discount_percent": discount_percent,
        "average_price": market_snapshot.get("average_price"),
        "lowest_price": market_snapshot.get("lowest_price"),
        "highest_price": market_snapshot.get("highest_price"),
        "price_percentile": percentile,
        "recommendation": recommendation,
        "reason": reason,
        "trend_available": False,
    }
