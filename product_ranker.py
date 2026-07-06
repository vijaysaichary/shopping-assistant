def _parse_price(product):
    price = product.get("extracted_price")
    return price if price is not None else float("inf")


def dedupe_products(products):
    """Drop duplicate listings for the same product."""
    seen = set()
    unique = []
    for product in products:
        key = product.get("product_id") or (product.get("title"), product.get("source"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique


# Pairs of (trigger keywords in the requested category, keywords to exclude
# from product titles) so a strict category ask doesn't leak in the sibling
# category (e.g. "headphones" shouldn't return earbuds, and vice versa).
CATEGORY_KEYWORD_RULES = [
    (
        ["headphone", "headphones", "over-ear", "over ear", "on-ear", "on ear"],
        ["earbud", "earbuds", "tws", "in-ear", "in ear"],
    ),
    (
        ["earbud", "earbuds", "tws", "in-ear", "in ear"],
        ["headphone", "headphones", "over-ear", "over ear", "on-ear", "on ear"],
    ),
    (
        ["iphone"],
        ["samsung", "android", "oneplus", "xiaomi", "redmi", "vivo", "oppo",
         "realme", "poco", "motorola", "nokia", "pixel"],
    ),
    (
        ["android phone", "android smartphone"],
        ["iphone", "apple"],
    ),
]


def _category_exclusions(category):
    if not category:
        return []
    category_lower = category.lower()
    for triggers, excludes in CATEGORY_KEYWORD_RULES:
        if any(trigger in category_lower for trigger in triggers):
            return excludes
    return []


def filter_products(products, intent):
    """Filter out products that don't match the requested brand, budget, or category."""
    brand = (intent.get("brand") or "").strip().lower()
    budget_min = intent.get("budget_min")
    budget_max = intent.get("budget_max")
    category_exclusions = _category_exclusions(intent.get("category"))

    filtered = []
    for product in products:
        title = (product.get("title") or "").lower()

        if brand and brand not in title:
            continue

        if category_exclusions and any(bad in title for bad in category_exclusions):
            continue

        price = product.get("extracted_price")
        if price is not None:
            if budget_min is not None and price < budget_min:
                continue
            if budget_max is not None and price > budget_max:
                continue

        filtered.append(product)

    # If strict filtering wipes out every result, relax only the budget/brand
    # constraints — never let sibling-category products (e.g. earbuds when
    # headphones were asked for) leak back in through the fallback.
    if filtered:
        return filtered

    if category_exclusions:
        return [
            p for p in products
            if not any(bad in (p.get("title") or "").lower() for bad in category_exclusions)
        ] or products

    return products


def _score(product):
    """Bayesian-weighted rating so high-review products outrank high-rating/low-review ones."""
    rating = product.get("rating") or 0
    reviews = product.get("reviews") or 0
    confidence = 50
    baseline_rating = 4.0
    return (reviews * rating + confidence * baseline_rating) / (reviews + confidence)


def rank_products(products, top_n=5):
    """Rank by weighted rating/review score first, then price."""
    def sort_key(product):
        return (-_score(product), _parse_price(product))

    ranked = sorted(products, key=sort_key)
    return ranked[:top_n]
