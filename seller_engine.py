"""Seller Trust Engine (PRD V2 Module 4) — standalone service.

Honesty note: the PRD calls for seller rating, years selling, GST
verification status, return/replacement/warranty policy text, delivery
reliability history, and a customer complaint count. NONE of that is
available from SerpAPI's Google Shopping response — it returns only a
seller/store name, an optional delivery blurb, and whether multiple sellers
list the same product. This v1 does not invent the missing fields; every one
of them comes back as None so the UI can render "not available" instead of a
fabricated number.

What it DOES compute honestly:
  - seller_category: classifies the seller name against a curated list of
    recognized major Indian/global marketplaces and official brand stores.
    This is a real, defensible signal — established platforms carry actual
    buyer-protection infrastructure (return windows, dispute resolution,
    payment protection) that an unrecognized small reseller may not.
  - seller_trust_percent: derived from that classification plus the delivery
    text and multi-seller flag SerpAPI does provide.

This module makes no external API calls — pure lookup + arithmetic.

Contract:
    analyze_seller(product: dict) -> {
        "seller_name": str,
        "seller_category": "Major Platform" | "Official Brand Store" | "Marketplace Seller" | "Unknown Seller",
        "seller_trust_percent": int (0-100),
        "delivery_info": str | None,
        "listed_by_multiple_sellers": bool | None,
        "years_selling": None,        # not available from current data sources
        "gst_verified": None,         # not available
        "return_policy": None,        # not available
        "replacement_policy": None,   # not available
        "warranty_info": None,        # not available
        "customer_complaints": None,  # not available
        "reason": str,
    }
"""

MAJOR_PLATFORMS = [
    "amazon", "flipkart", "myntra", "ajio", "nykaa", "reliance digital",
    "croma", "tata cliq", "tatacliq", "vijay sales", "firstcry", "shopsy",
    "meesho", "snapdeal",
]

OFFICIAL_BRAND_STORES = [
    "boat", "noise", "oneplus", "apple", "samsung", "lenovo", "dell", "hp",
    "asus", "acer", "sony", "xiaomi", "mi.com", "realme", "oppo", "vivo",
    "nothing", "google store", "motorola", "nokia",
]

_CATEGORY_BASE_SCORE = {
    "Major Platform": 85,
    "Official Brand Store": 80,
    "Marketplace Seller": 45,
    "Unknown Seller": 25,
}


def _normalize(name):
    return (name or "").strip().lower()


def _classify_seller(seller_name):
    normalized = _normalize(seller_name)
    if not normalized:
        return "Unknown Seller"
    if any(platform in normalized for platform in MAJOR_PLATFORMS):
        return "Major Platform"
    if any(brand in normalized for brand in OFFICIAL_BRAND_STORES):
        return "Official Brand Store"
    return "Marketplace Seller"


def analyze_seller(product):
    raw_seller_name = product.get("source")
    category = _classify_seller(raw_seller_name)
    seller_name = raw_seller_name or "Unknown Seller"
    delivery_info = product.get("delivery")
    multiple_sellers = product.get("multiple_sources")

    score = _CATEGORY_BASE_SCORE[category]
    reason_parts = [f"'{seller_name}' recognized as a {category.lower()}."]

    if delivery_info:
        lowered = delivery_info.lower()
        if "free" in lowered:
            score += 5
            reason_parts.append("Free delivery offered.")
        if "next-day" in lowered or "next day" in lowered:
            score += 3
            reason_parts.append("Fast (next-day) delivery available.")

    if multiple_sellers:
        score += 5
        reason_parts.append(
            "This exact listing is available through multiple sellers, "
            "consistent with an established, actively-stocked product."
        )

    score = max(0, min(100, score))

    reason_parts.append(
        "Years selling, GST verification, return/replacement/warranty policy "
        "text, delivery reliability history, and complaint counts aren't "
        "available from the current data source, so they're not scored or "
        "shown here rather than guessed."
    )

    return {
        "seller_name": seller_name,
        "seller_category": category,
        "seller_trust_percent": score,
        "delivery_info": delivery_info,
        "listed_by_multiple_sellers": bool(multiple_sellers) if multiple_sellers is not None else None,
        "years_selling": None,
        "gst_verified": None,
        "return_policy": None,
        "replacement_policy": None,
        "warranty_info": None,
        "customer_complaints": None,
        "reason": " ".join(reason_parts),
    }
