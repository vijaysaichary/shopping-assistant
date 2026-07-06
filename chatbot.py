def _best_overall(ranked):
    return ranked[0] if ranked else None


def _best_budget(ranked):
    priced = [p for p in ranked if p.get("extracted_price") is not None]
    return min(priced, key=lambda p: p["extracted_price"]) if priced else None


def _best_performance(ranked):
    return max(ranked, key=lambda p: p.get("rating") or 0) if ranked else None


PRODUCT_EVIDENCE_PHRASINGS = ["Backed by", "Supported by", "Validated by", "Confirmed by", "Reinforced by"]


def _evidence_note(product, phrasing):
    shopping_reviews = product.get("reviews")
    sources = product.get("review_sources_count")
    has_reviews = shopping_reviews not in (None, "N/A")
    if not has_reviews and not sources:
        return ""

    review_part = f"{shopping_reviews} shopping reviews" if has_reviews else "the available shopping reviews"
    source_part = (
        f"{sources} independent mentions across YouTube, Reddit, Twitter/X, Instagram, and Facebook"
        if sources else None
    )
    evidence = review_part if not source_part else f"{review_part} plus {source_part}"
    return f" — {phrasing} {evidence}."


def build_response(query, intent, ranked_products):
    """Turn parsed intent + ranked products into a structured chatbot reply."""
    if intent.get("needs_clarification"):
        return intent.get("clarification_question") or (
            "Could you tell me your budget, what you'll use it for, and any brand "
            "preference so I can recommend the right product?"
        )

    if not ranked_products:
        return (
            f"Sorry, I couldn't find any products matching \"{query}\". "
            "Try relaxing the budget or brand constraint."
        )

    purpose = intent.get("purpose") or intent.get("category") or "general use"
    features = ", ".join(intent.get("specs") or []) or "See listing for full specs"

    lines = ["Recommended Products:\n"]
    for i, product in enumerate(ranked_products, start=1):
        title = product.get("title", "Unknown product")
        price = product.get("price", "N/A")
        rating = product.get("rating", "N/A")
        reviews = product.get("reviews", "N/A")
        store = product.get("source", "N/A")
        link = product.get("product_link") or product.get("link", "")

        why_recommend = product.get("why_recommend") or (
            f"Strong match for \"{query}\" based on rating, review volume, and price."
        )
        sources_count = product.get("review_sources_count")
        platform_counts = product.get("review_platform_counts") or {}
        platforms_checked = ", ".join(
            f"{platform} ({count})" for platform, count in platform_counts.items()
        )
        phrasing = PRODUCT_EVIDENCE_PHRASINGS[(i - 1) % len(PRODUCT_EVIDENCE_PHRASINGS)]
        evidence_line = _evidence_note(product, phrasing).strip(" —.")

        lines.append(f"{i}. {title}")
        lines.append(f"   Price: {price}")
        lines.append(f"   Rating: {rating}")
        lines.append(f"   Reviews: {reviews}")
        lines.append(f"   Store: {store}")
        lines.append(f"   Best For: {purpose}")
        lines.append(f"   Important Features: {features}")
        if sources_count is not None:
            evidence_suffix = f" (platforms: {platforms_checked})" if platforms_checked else ""
            lines.append(f"   {evidence_line}{evidence_suffix}.")
        lines.append(f"   Why I recommend this: {why_recommend}")
        lines.append(f"   Purchase Link: {link}\n")

    overall = _best_overall(ranked_products)
    budget = _best_budget(ranked_products)
    performance = _best_performance(ranked_products)

    if overall:
        lines.append(
            f"Best overall choice: {overall.get('title')}"
            f"{_evidence_note(overall, 'after comparing all available listings, this topped the shortlist, backed by')}"
        )
    if budget:
        lines.append(
            f"Best budget choice: {budget.get('title')}"
            f"{_evidence_note(budget, 'the most wallet-friendly of the shortlisted picks, backed by')}"
        )
    if performance:
        lines.append(
            f"Best performance choice: {performance.get('title')}"
            f"{_evidence_note(performance, 'the highest-rated of the shortlisted picks, backed by')}"
        )

    return "\n".join(lines)
