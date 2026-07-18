"""AI Trust Score engine (PRD V2 Module 1) — standalone service.

Replaces a raw shopping star rating with a single 0-100 trust score that
combines structured signals (rating, review volume, cross-platform social
proof, platform diversity) with an AI sentiment/authenticity read of real
review evidence gathered from YouTube, Reddit, and Twitter/X.

Honesty note: several inputs listed in the V2 PRD — verified-purchase status,
seller reputation, warranty quality, return rate, price stability, brand
reliability — aren't available from the current data sources (SerpAPI Google
Shopping + web search) and are NOT fabricated here. This module only scores
on evidence it actually has; those become inputs once Modules 3/4 (Price
Intelligence, Seller Trust) exist. Extend `calculate_trust_score`'s inputs
when those signals become available rather than guessing at them now.

Contract:
    calculate_trust_score(product: dict, review_signals: dict) -> { ...same shape... }
        Standalone path — makes its own Groq sentiment call. Good for direct
        use/testing; NOT what the live pipeline calls (see below).

    score_from_sentiment(product: dict, review_signals: dict, sentiment: dict) -> {
        "trust_score": int (0-100),
        "confidence": "High" | "Medium" | "Low",
        "positive_ratio": float (0-1),
        "negative_ratio": float (0-1),
        "fake_review_probability": float (0-1),
        "reason": str,
    }
        Pipeline path — pure math, no network call. `sentiment` is expected to
        already exist (produced once per product by evidence_engine.py, which
        also feeds review_intelligence.py — this avoids 3 separate Groq calls
        per product collapsing into 1).

`review_signals` is the dict already produced by
review_aggregator.gather_review_signals — this module takes it as input
rather than fetching its own data, so it stays a pure scoring service and
never duplicates the SerpAPI calls that gathered it.
"""

import os
import json
import re
import math
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = Groq(api_key=GROQ_API_KEY)

SENTIMENT_SYSTEM_PROMPT = """You are a trust and authenticity analysis engine for an Indian shopping assistant. You are given a product's shopping rating/review count and raw review snippets scraped from YouTube, Reddit, and Twitter/X.

Analyze ONLY the evidence given — never invent facts not present in it. Respond with a single JSON object with these exact keys:

- positive_ratio: float 0-1, fraction of the evidence that reads positive/satisfied.
- negative_ratio: float 0-1, fraction that reads negative/dissatisfied (positive_ratio + negative_ratio should not exceed 1; the remainder is neutral/mixed/no signal).
- fake_review_probability: float 0-1, your estimate of how likely the shopping rating/review count looks manipulated or fake. Raise this when the shopping rating is very high (4.8+) with very few shopping reviews, when external sources are completely silent despite a large shopping review count, or when snippets themselves mention fakes/bots/paid reviews. Lower it when independent sources across multiple distinct platforms corroborate the shopping rating and review volume.
- sentiment_score: integer 0-100 summarizing overall sentiment strength in the evidence (50 = neutral or no clear signal, 100 = overwhelmingly positive, 0 = overwhelmingly negative).
- reason: one or two plain-text sentences justifying these numbers, citing what the evidence actually shows. If evidence is thin or absent, say so plainly rather than guessing.

Respond with ONLY the JSON object. No prose, no markdown code fences."""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _default_sentiment(reason):
    return {
        "positive_ratio": 0.5,
        "negative_ratio": 0.2,
        "fake_review_probability": 0.3,
        "sentiment_score": 50.0,
        "reason": reason,
    }


def _analyze_sentiment(product, review_signals):
    """AI read of the gathered evidence — sentiment split + fake-review estimate."""
    title = product.get("title", "this product")
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")
    snippets = review_signals.get("snippets") or []
    snippets_text = "\n".join(snippets) if snippets else "No external review snippets were found."
    total_sources = review_signals.get("total_sources", 0)
    platform_counts = review_signals.get("platform_counts", {})

    user_prompt = f"""Product: {title}
Shopping rating: {rating} ({reviews} shopping reviews)
External sources checked: {total_sources} across {platform_counts}

Evidence snippets:
{snippets_text}"""

    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(_strip_code_fences(response.choices[0].message.content))
        return {
            "positive_ratio": float(data.get("positive_ratio", 0.5) or 0.5),
            "negative_ratio": float(data.get("negative_ratio", 0.2) or 0.2),
            "fake_review_probability": float(data.get("fake_review_probability", 0.3) or 0.3),
            "sentiment_score": float(data.get("sentiment_score", 50) or 50),
            "reason": data.get("reason") or "No strong signal found in the available evidence.",
        }
    except Exception:
        return _default_sentiment(
            "Trust analysis was unavailable this time; score falls back to shopping metadata only."
        )


def _rating_score(product):
    rating = product.get("rating")
    if not rating:
        return 50.0
    return max(0.0, min(100.0, (rating / 5.0) * 100))


def _review_volume_score(product):
    reviews = product.get("reviews")
    if not isinstance(reviews, (int, float)) or reviews <= 0:
        return 30.0
    return max(0.0, min(100.0, (math.log10(reviews + 1) / math.log10(10000)) * 100))


def _social_proof_score(review_signals):
    total_sources = review_signals.get("total_sources", 0)
    return max(0.0, min(100.0, (total_sources / 25) * 100))


def _platform_diversity_score(review_signals):
    platform_counts = review_signals.get("platform_counts") or {}
    if not platform_counts:
        return 0.0
    covered = sum(1 for count in platform_counts.values() if count > 0)
    return (covered / len(platform_counts)) * 100


def _confidence_level(product, review_signals):
    reviews = product.get("reviews")
    total_sources = review_signals.get("total_sources", 0)
    has_meaningful_reviews = isinstance(reviews, (int, float)) and reviews >= 50

    if total_sources >= 15 and has_meaningful_reviews:
        return "High"
    if total_sources >= 5 or has_meaningful_reviews:
        return "Medium"
    return "Low"


def score_from_sentiment(product, review_signals, sentiment):
    """Combine structured metadata + an ALREADY-COMPUTED sentiment read into an
    AI Trust Score. Pure math, no network call — used by the pipeline when
    evidence_engine.analyze_evidence() has already produced the sentiment
    fields for this product, so this module doesn't make its own redundant
    Groq call. `sentiment` must have positive_ratio, negative_ratio,
    fake_review_probability, sentiment_score, and reason keys (same shape
    _analyze_sentiment returns)."""
    review_signals = review_signals or {"platform_counts": {}, "total_sources": 0, "snippets": []}

    structured_score = (
        _rating_score(product) * 0.35
        + _review_volume_score(product) * 0.25
        + _social_proof_score(review_signals) * 0.20
        + _platform_diversity_score(review_signals) * 0.20
    )

    combined = structured_score * 0.6 + sentiment["sentiment_score"] * 0.4
    fake_penalty = sentiment["fake_review_probability"] * 25
    trust_score = round(max(0, min(100, combined - fake_penalty)))

    return {
        "trust_score": trust_score,
        "confidence": _confidence_level(product, review_signals),
        "positive_ratio": round(sentiment["positive_ratio"], 2),
        "negative_ratio": round(sentiment["negative_ratio"], 2),
        "fake_review_probability": round(sentiment["fake_review_probability"], 2),
        "reason": sentiment["reason"],
    }


def calculate_trust_score(product, review_signals):
    """Standalone path: fetches its own sentiment analysis via a dedicated Groq
    call, then delegates to score_from_sentiment(). Useful for direct/unit
    testing of this module in isolation; the live pipeline instead calls
    score_from_sentiment() directly with sentiment already produced by
    evidence_engine.analyze_evidence(), to avoid a duplicate Groq call."""
    review_signals = review_signals or {"platform_counts": {}, "total_sources": 0, "snippets": []}
    sentiment = _analyze_sentiment(product, review_signals)
    return score_from_sentiment(product, review_signals, sentiment)
