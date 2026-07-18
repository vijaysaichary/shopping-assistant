"""Decision Report (PRD V2 Module 9) — standalone service.

Generates a structured "Why this product?" checklist for a single product,
built ENTIRELY from evidence already computed by the other engines earlier
in this pipeline (trust_engine, review_intelligence, price_engine,
seller_engine) — no new LLM call, no new data source, zero added cost.

"No generic text. Everything evidence based" is enforced structurally, not
just by instruction: every checklist item is a deterministic rule over a
specific field those modules already produced. An item only appears if the
data it claims is actually present and clears its threshold — there is no
step where an LLM is asked to free-associate reasons.

Honesty note: some PRD example items (Best Gaming, Best Battery, Strong
Resale Value, Good After-Sales) assume structured spec data this app
doesn't have per-category. Where the PRD's example items map to something
we DO have — a keyword genuinely present in review_intelligence's
what_people_love list — that's used. Nothing is inferred from category
alone (e.g. never assume "good camera" just because it's a phone).

Contract:
    generate_decision_report(product: dict) -> {
        "reasons": [str, ...],    # confirmed, evidence-backed positives
        "cautions": [str, ...],   # confirmed, evidence-backed concerns
    }
"""

KEYWORD_REASONS = {
    "battery": "Great battery life (per real reviews)",
    "camera": "Strong camera performance (per real reviews)",
    "gaming": "Well suited for gaming (per real reviews)",
    "fps": "Well suited for gaming (per real reviews)",
    "sound": "Strong sound quality (per real reviews)",
    "audio": "Strong sound quality (per real reviews)",
    "display": "Strong display quality (per real reviews)",
    "screen": "Strong display quality (per real reviews)",
    "comfort": "Comfortable to use (per real reviews)",
    "comfortable": "Comfortable to use (per real reviews)",
    "build": "Solid build quality (per real reviews)",
    "durable": "Solid build quality (per real reviews)",
    "lightweight": "Lightweight and portable (per real reviews)",
    "fast charg": "Fast charging (per real reviews)",
}


def _keyword_reasons(what_people_love):
    found = []
    seen_labels = set()
    for item in what_people_love or []:
        lowered = item.lower()
        for keyword, label in KEYWORD_REASONS.items():
            if keyword in lowered and label not in seen_labels:
                found.append(label)
                seen_labels.add(label)
    return found


def generate_decision_report(product):
    reasons = []
    cautions = []

    trust_score = product.get("trust_score")
    trust_confidence = product.get("trust_confidence")
    fake_probability = product.get("trust_fake_review_probability")
    rating = product.get("rating")
    reviews = product.get("reviews")

    intel = product.get("review_intelligence") or {}
    love = intel.get("what_people_love") or []
    complaints = intel.get("common_complaints") or []
    reliability = intel.get("long_term_reliability")
    warranty = intel.get("warranty_experience")
    source_summaries = intel.get("source_summaries") or {}
    disagreement = intel.get("disagreement_note")

    price_intel = product.get("price_intelligence") or {}
    price_recommendation = price_intel.get("recommendation")

    seller_intel = product.get("seller_intelligence") or {}
    seller_category = seller_intel.get("seller_category")
    seller_trust_pct = seller_intel.get("seller_trust_percent")

    # --- Trust ---
    if trust_score is not None and trust_score >= 80:
        reasons.append(f"Highest AI Trust Score ({trust_score}/100, {trust_confidence} confidence)")
    elif trust_score is not None and trust_score >= 65:
        reasons.append(f"Solid AI Trust Score ({trust_score}/100, {trust_confidence} confidence)")

    if fake_probability is not None and fake_probability >= 0.5:
        cautions.append(f"{round(fake_probability * 100)}% estimated chance this listing's rating/reviews are inflated")

    # --- Shopping rating volume ---
    if isinstance(rating, (int, float)) and isinstance(reviews, (int, float)):
        if rating >= 4.5 and reviews >= 100:
            reasons.append(f"High rating ({rating}★) backed by a large review volume ({reviews} reviews)")

    # --- Review evidence ---
    if love and len(complaints) <= 1:
        reasons.append("Low complaint rate across independently gathered reviews")
    for item in complaints[:2]:
        cautions.append(f"Reported issue: {item}")

    if reliability in ("Excellent", "Good"):
        reasons.append(f"{reliability} long-term reliability reported")
    elif reliability == "Poor":
        cautions.append("Poor long-term reliability reported")

    if warranty == "Good":
        reasons.append("Positive warranty experience reported")
    elif warranty == "Poor":
        cautions.append("Poor warranty experience reported")

    if len(source_summaries) >= 2 and not disagreement:
        reasons.append(f"Consistently recommended across {len(source_summaries)} independent platforms")
    if disagreement:
        cautions.append(f"Mixed opinions across sources: {disagreement}")

    reasons.extend(_keyword_reasons(love))

    # --- Price ---
    if price_recommendation in ("Excellent Deal", "Buy Now"):
        reasons.append(f"Good value right now ({price_recommendation})")
    elif price_recommendation == "Poor Deal":
        cautions.append("Priced above today's comparable listings")

    # --- Seller ---
    if seller_category in ("Major Platform", "Official Brand Store"):
        reasons.append(f"Sold by a {seller_category.lower()} ({seller_trust_pct}% seller trust)")
    elif seller_category in ("Marketplace Seller", "Unknown Seller") and (seller_trust_pct or 0) < 50:
        cautions.append(f"Sold by a less-established seller ({seller_category.lower()})")

    return {"reasons": reasons, "cautions": cautions}
