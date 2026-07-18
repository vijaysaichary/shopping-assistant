"""Product Comparison Engine (PRD V2 Module 7) — standalone service.

Honesty note: the PRD's example comparison axes (Camera, Gaming, Charging,
Repairability, Resale Value, Display, Build) assume access to structured
spec sheets this app doesn't have — SerpAPI's Google Shopping response has
no camera megapixels, no repairability index, no resale-value data, etc.
Fabricating scores on those axes would be making numbers up. Instead this
module:
  1. Always compares on axes we have REAL data for: Price, AI Trust Score,
     Shopping Rating, Seller Trust.
  2. Asks the AI to identify a FEW additional qualitative axes (battery,
     camera, build, whatever's actually relevant) — but ONLY grounded in the
     specific evidence already gathered for these products (each product's
     review_intelligence pros/cons/source_summaries, why_recommend text).
     If the evidence doesn't support comparing on an axis for a given
     product, that cell says "Not enough evidence" rather than a guess.

Cost note: comparison is user-INITIATED (they pick 2-5 products from a
completed search and ask to compare them), not run automatically on every
search — so it's one extra Groq call only when actually used, not a
per-search cost multiplier like the other modules.

Contract:
    compare_products(products: list[dict]) -> {
        "winner": str,                 # a product title
        "verdict": str,                # 2-4 sentence AI explanation
        "axes": [
            {
                "axis": str,
                "values": {product_title: str, ...},
            }, ...
        ],
        "per_product_pros_cons": {
            product_title: {"pros": [str, ...], "cons": [str, ...]}
        },
    }
Raises ValueError if fewer than 2 or more than 5 products are given.
"""

import os
import json
import re
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are a product comparison engine for an Indian shopping assistant. You are given 2-5 products with their real shopping data (price, rating) and AI-gathered evidence (trust score, review pros/cons, source summaries).

STRICT RULES:
1. Ground everything ONLY in the data given. Never invent specs (camera megapixels, battery mAh, repairability scores, resale value, etc.) that aren't present in the evidence.
2. For any comparison axis where the evidence doesn't clearly support a judgment for a given product, its value must be "Not enough evidence" — never guess or default to a plausible-sounding number.
3. Beyond the fixed axes (Price, AI Trust Score, Shopping Rating, Seller Trust — provided to you, don't recompute), identify 2-4 ADDITIONAL qualitative axes that the evidence actually discusses (e.g. "Battery Life", "Camera Quality", "Build Quality", "Comfort") — only include an axis if at least one product has real evidence about it.
4. The winner must be justified by the axes and verdict, not chosen arbitrarily.

Respond with ONLY a single JSON object with these exact keys:
- winner: the exact title string of the recommended product.
- verdict: 2-4 plain-text sentences explaining the winner and key tradeoffs between the products.
- additional_axes: array of objects, each {"axis": str, "values": {product_title: str}} — values keyed by the EXACT product titles given, "Not enough evidence" where evidence is thin.
- per_product_pros_cons: object keyed by exact product title, each {"pros": [str,...], "cons": [str,...]} summarizing 2-3 points each from the evidence given.

No prose, no markdown code fences — JSON only."""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _fixed_axes(products):
    """The axes we have REAL data for — computed directly, no LLM guessing."""
    def row(name, formatter):
        values = {}
        for p in products:
            values[p.get("title", "Unknown")] = formatter(p)
        return {"axis": name, "values": values}

    def fmt_price(p):
        return p.get("price") or "N/A"

    def fmt_trust(p):
        score = p.get("trust_score")
        return f"{score}/100" if score is not None else "N/A"

    def fmt_rating(p):
        rating = p.get("rating")
        reviews = p.get("reviews", "N/A")
        return f"{rating}★ ({reviews} reviews)" if rating is not None else "N/A"

    def fmt_seller(p):
        pct = (p.get("seller_intelligence") or {}).get("seller_trust_percent")
        return f"{pct}%" if pct is not None else "N/A"

    return [
        row("Price", fmt_price),
        row("AI Trust Score", fmt_trust),
        row("Shopping Rating", fmt_rating),
        row("Seller Trust", fmt_seller),
    ]


def _format_product_evidence(product):
    title = product.get("title", "Unknown product")
    price = product.get("price", "N/A")
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")
    trust = product.get("trust_score")
    intel = product.get("review_intelligence") or {}
    love = intel.get("what_people_love") or []
    complaints = intel.get("common_complaints") or []
    sources = intel.get("source_summaries") or {}
    why = product.get("why_recommend") or ""

    lines = [
        f"### {title}",
        f"Price: {price} | Rating: {rating} ({reviews} reviews) | AI Trust Score: {trust if trust is not None else 'N/A'}",
    ]
    if love:
        lines.append(f"What people love: {'; '.join(love)}")
    if complaints:
        lines.append(f"Common complaints: {'; '.join(complaints)}")
    for platform, summary in sources.items():
        lines.append(f"{platform} says: {summary}")
    if why:
        lines.append(f"Overall assessment: {why}")

    return "\n".join(lines)


def compare_products(products):
    if not products or len(products) < 2:
        raise ValueError("compare_products needs at least 2 products.")
    if len(products) > 5:
        raise ValueError("compare_products supports at most 5 products.")

    fixed_axes = _fixed_axes(products)
    evidence_block = "\n\n".join(_format_product_evidence(p) for p in products)
    titles = [p.get("title", "Unknown") for p in products]

    user_prompt = f"""Products to compare: {titles}

{evidence_block}"""

    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(_strip_code_fences(response.choices[0].message.content))
    except Exception:
        # Fallback: no AI verdict available, but the fixed real-data axes and
        # a neutral note still let the user compare something meaningful.
        best_by_trust = max(
            products, key=lambda p: p.get("trust_score") if p.get("trust_score") is not None else -1
        )
        return {
            "winner": best_by_trust.get("title", "Unknown"),
            "verdict": "AI comparison analysis was unavailable this time; winner shown is based on AI Trust Score alone.",
            "axes": fixed_axes,
            "per_product_pros_cons": {},
        }

    additional_axes = []
    valid_titles = set(titles)
    for axis in (data.get("additional_axes") or []):
        values = axis.get("values") or {}
        filtered_values = {t: values.get(t, "Not enough evidence") for t in titles}
        additional_axes.append({"axis": axis.get("axis", "Unknown"), "values": filtered_values})

    pros_cons = {}
    raw_pros_cons = data.get("per_product_pros_cons") or {}
    for title in titles:
        entry = raw_pros_cons.get(title) or {}
        pros_cons[title] = {
            "pros": list(entry.get("pros") or [])[:3],
            "cons": list(entry.get("cons") or [])[:3],
        }

    winner = data.get("winner")
    if winner not in valid_titles:
        winner = titles[0]

    return {
        "winner": winner,
        "verdict": data.get("verdict") or "Comparison generated from the available evidence.",
        "axes": fixed_axes + additional_axes,
        "per_product_pros_cons": pros_cons,
    }
