"""Smart Recommendation Labels (PRD V2 Module 10) — standalone service.

Generates category-winner badges (Best Overall, Best Budget, Best Premium,
Best Value, Best Camera, Best Battery, Best Gaming, Best Student Choice,
Best Office Choice, Best Travel Choice) across the CURRENT ranked result
set — purely comparative logic over data the earlier engines already
computed (trust_score, price, review_intelligence.what_people_love/best_for).
Zero new API calls; this is presentation/comparison over existing data, like
Module 9.

This module is also now the single source of truth for "best X" logic —
chatbot.py's end-of-reply summary lines (Best overall/budget/performance/deal)
call into this instead of maintaining separate duplicate logic, so the text
summary and the per-product badges shown in the UI can never drift apart.

Honesty note: attribute-specific labels (Best Camera, Best Battery, Best
Gaming) are only awarded when a product's review_intelligence evidence
ACTUALLY mentions that attribute — never assumed from category alone (a
phone doesn't automatically get "Best Camera" just for being a phone; it
only gets it if a real review said so). If no product in the batch has
evidence for a given label, that label is simply not awarded to anyone
rather than forced onto an arbitrary pick.

Contract:
    generate_labels(ranked_products: list[dict]) -> {
        product_title: [str, ...],   # labels this product earned, [] if none
    }
"""

KEYWORD_LABELS = {
    "Best Camera": ["camera", "photo", "photograph"],
    "Best Battery": ["battery"],
    "Best Gaming": ["gaming", "fps", "game"],
}

BEST_FOR_LABELS = {
    "Best Student Choice": ["Students"],
    "Best Office Choice": ["Office", "Professionals"],
    "Best Travel Choice": ["Travel"],
}

PREMIUM_TRUST_THRESHOLD = 60


def _has_keyword(product, keywords):
    love = ((product.get("review_intelligence") or {}).get("what_people_love")) or []
    text = " ".join(love).lower()
    return any(kw in text for kw in keywords)


def _has_best_for_tag(product, tags):
    best_for = ((product.get("review_intelligence") or {}).get("best_for")) or []
    return any(tag in best_for for tag in tags)


def _priced_products(products):
    return [p for p in products if isinstance(p.get("extracted_price"), (int, float)) and p["extracted_price"] > 0]


def _trusted_products(products):
    return [p for p in products if p.get("trust_score") is not None]


def generate_labels(ranked_products):
    if not ranked_products:
        return {}

    labels = {p.get("title", "Unknown"): [] for p in ranked_products}

    def award(label, product):
        if product:
            labels[product.get("title", "Unknown")].append(label)

    trusted = _trusted_products(ranked_products)
    priced = _priced_products(ranked_products)

    # Best Overall — highest trust score (or rating, if no trust scores exist yet)
    if trusted:
        award("Best Overall", max(trusted, key=lambda p: p["trust_score"]))
    else:
        rated = [p for p in ranked_products if p.get("rating") is not None]
        if rated:
            award("Best Overall", max(rated, key=lambda p: p["rating"]))

    # Best Budget — cheapest in the batch
    if priced:
        award("Best Budget", min(priced, key=lambda p: p["extracted_price"]))

    # Best Premium — highest price, but only among products with a real trust
    # score clearing a reasonable bar, so "premium" means justified quality,
    # not just "the most expensive listing regardless of how bad it is"
    premium_candidates = [p for p in priced if (p.get("trust_score") or 0) >= PREMIUM_TRUST_THRESHOLD]
    if premium_candidates:
        award("Best Premium", max(premium_candidates, key=lambda p: p["extracted_price"]))

    # Best Value — highest trust-per-rupee ratio
    value_candidates = [p for p in priced if p.get("trust_score") is not None]
    if value_candidates:
        award("Best Value", max(value_candidates, key=lambda p: p["trust_score"] / p["extracted_price"]))

    # Attribute labels — only awarded if at least one product has real evidence
    for label, keywords in KEYWORD_LABELS.items():
        candidates = [p for p in ranked_products if _has_keyword(p, keywords)]
        if candidates:
            winner = max(candidates, key=lambda p: p.get("trust_score") if p.get("trust_score") is not None else -1)
            award(label, winner)

    # Use-case labels — from review_intelligence's own best_for tags
    for label, tags in BEST_FOR_LABELS.items():
        candidates = [p for p in ranked_products if _has_best_for_tag(p, tags)]
        if candidates:
            winner = max(candidates, key=lambda p: p.get("trust_score") if p.get("trust_score") is not None else -1)
            award(label, winner)

    return labels
