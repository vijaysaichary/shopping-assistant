def _find_by_label(ranked, label):
    """smart_labels.generate_labels() is the single source of truth for
    "Best X" comparisons — reading its output here instead of recomputing
    means the text summary below and the badges shown on product cards in
    the UI can never disagree with each other."""
    for p in ranked:
        if label in (p.get("smart_labels") or []):
            return p
    return None


def _best_deal(ranked):
    candidates = [
        p for p in ranked
        if (p.get("price_intelligence") or {}).get("recommendation") in ("Excellent Deal", "Buy Now")
    ]
    if not candidates:
        return None

    tier_rank = {"Excellent Deal": 1, "Buy Now": 0}

    def deal_strength(p):
        intel = p["price_intelligence"]
        # Rank by recommendation tier first, then by actual cheapness
        # (price_percentile) within a tier — a real "cheapest of the batch"
        # result should win over a smaller discount tagged on a pricier item.
        tier = tier_rank.get(intel.get("recommendation"), -1)
        percentile = intel.get("price_percentile") or 0
        return (tier, percentile)

    return max(candidates, key=deal_strength)


PRODUCT_EVIDENCE_PHRASINGS = ["Backed by", "Supported by", "Validated by", "Confirmed by", "Reinforced by"]


def _evidence_note(product, phrasing):
    shopping_reviews = product.get("reviews")
    sources = product.get("review_sources_count")
    has_reviews = shopping_reviews not in (None, "N/A")
    if not has_reviews and not sources:
        return ""

    review_part = f"{shopping_reviews} shopping reviews" if has_reviews else "the available shopping reviews"
    source_part = (
        f"{sources} independent mentions across YouTube, Reddit, and Twitter/X"
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

        trust_score = product.get("trust_score")
        trust_confidence = product.get("trust_confidence")
        fake_probability = product.get("trust_fake_review_probability")

        lines.append(f"{i}. {title}")
        lines.append(f"   Price: {price}")
        if trust_score is not None:
            lines.append(f"   AI Trust Score: {trust_score}/100 ({trust_confidence} Confidence)")
            if fake_probability is not None and fake_probability >= 0.5:
                lines.append(
                    f"   Caution: {round(fake_probability * 100)}% estimated chance this "
                    "listing's rating/reviews are inflated or unreliable."
                )
        price_intel = product.get("price_intelligence")
        if price_intel and price_intel.get("recommendation") not in (None, "Unknown"):
            avg = price_intel.get("average_price")
            low = price_intel.get("lowest_price")
            high = price_intel.get("highest_price")
            price_line = f"   Price Intelligence: {price_intel['recommendation']}"
            if avg is not None:
                price_line += f" (today's avg ₹{avg:,.0f}, low ₹{low:,.0f}, high ₹{high:,.0f})"
            lines.append(price_line)
            if price_intel.get("reason"):
                lines.append(f"   {price_intel['reason']}")

        lines.append(f"   Shopping Rating: {rating} ({reviews} reviews)")
        seller_intel = product.get("seller_intelligence")
        if seller_intel:
            lines.append(
                f"   Store: {store} — Seller Trust: {seller_intel['seller_trust_percent']}% "
                f"({seller_intel['seller_category']})"
            )
        else:
            lines.append(f"   Store: {store}")
        lines.append(f"   Best For: {purpose}")
        lines.append(f"   Important Features: {features}")
        if sources_count is not None:
            evidence_suffix = f" (platforms: {platforms_checked})" if platforms_checked else ""
            lines.append(f"   {evidence_line}{evidence_suffix}.")

        intel = product.get("review_intelligence")
        if intel:
            if intel.get("what_people_love"):
                lines.append(f"   What People Love: {'; '.join(intel['what_people_love'])}")
            if intel.get("common_complaints"):
                lines.append(f"   Common Complaints: {'; '.join(intel['common_complaints'])}")
            if intel.get("best_for"):
                lines.append(f"   Recommended For: {', '.join(intel['best_for'])}")
            if intel.get("not_recommended_for"):
                lines.append(f"   Not Ideal For: {'; '.join(intel['not_recommended_for'])}")
            reliability = intel.get("long_term_reliability")
            warranty = intel.get("warranty_experience")
            if reliability and reliability != "Unknown" or warranty and warranty != "Unknown":
                lines.append(
                    f"   Long-Term Reliability: {reliability or 'Unknown'} | "
                    f"Warranty Experience: {warranty or 'Unknown'}"
                )
            if intel.get("disagreement_note"):
                lines.append(f"   Note: {intel['disagreement_note']}")
            if intel.get("ai_confidence") is not None:
                lines.append(f"   Review Intelligence Confidence: {intel['ai_confidence']}%")

        report = product.get("decision_report")
        if report and (report.get("reasons") or report.get("cautions")):
            lines.append("   Why This Product?")
            for reason in report.get("reasons") or []:
                lines.append(f"     ✓ {reason}")
            for caution in report.get("cautions") or []:
                lines.append(f"     ⚠ {caution}")

        lines.append(f"   Why I recommend this: {why_recommend}")
        lines.append(f"   Purchase Link: {link}\n")

    overall = _find_by_label(ranked_products, "Best Overall")
    budget = _find_by_label(ranked_products, "Best Budget")
    value = _find_by_label(ranked_products, "Best Value")
    deal = _best_deal(ranked_products)

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
    if value and value is not overall:
        lines.append(
            f"Best value choice: {value.get('title')}"
            f"{_evidence_note(value, 'the strongest trust-per-rupee among the shortlisted picks, backed by')}"
        )
    if deal:
        deal_intel = deal["price_intelligence"]
        lines.append(
            f"Best deal right now: {deal.get('title')} — {deal_intel['recommendation']}. {deal_intel.get('reason', '')}"
        )

    return "\n".join(lines)
