"""Combined evidence analysis — standalone service.

trust_engine.py (Module 1), review_intelligence.py (Module 2), and the
why-recommend synthesizer in query_understanding.py were each making their
own separate Groq call per product, all analyzing the exact same underlying
evidence (the same review snippets, the same shopping rating/review count)
just asking for a different slice of structured output. That's 3 Groq calls
per product — with 5 products enriched per search, ~16 Groq calls per search
total, easily enough to trip Groq's per-minute rate limit on the free tier
even though the daily quota is generous.

This module makes ONE Groq call per product covering the union of all three
schemas, and the pipeline (review_aggregator.py) distributes the result into
trust_engine's and review_intelligence's own scoring/validation functions —
so those modules keep their public contracts, their own tests, and their own
"never hallucinate" validation logic; they just stop each making their own
network call in the normal pipeline path. Each module's original standalone
function (calculate_trust_score, generate_review_intelligence) still exists
and still works on its own — useful for direct testing — it's simply not
what the hot path calls anymore.

Contract:
    analyze_evidence(product: dict, review_signals: dict) -> {
        "why_recommend": str,
        "positive_ratio": float (0-1),
        "negative_ratio": float (0-1),
        "fake_review_probability": float (0-1),
        "sentiment_score": int (0-100),
        "sentiment_reason": str,
        "what_people_love": [str, ...],
        "common_complaints": [str, ...],
        "best_for": [str, ...],
        "not_recommended_for": [str, ...],
        "long_term_reliability": "Excellent" | "Good" | "Average" | "Poor" | "Unknown",
        "warranty_experience": "Good" | "Average" | "Poor" | "Unknown",
        "ai_confidence": int (0-100),
        "source_summaries": {platform: str, ...},
        "disagreement_note": str | None,
    }
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

ALLOWED_BEST_FOR_TAGS = [
    "Students", "Gamers", "Office", "Travel", "Photography", "Parents",
    "Professionals", "Fitness", "Content Creators", "Casual Users", "Home Use",
]

SYSTEM_PROMPT = f"""You are a review-evidence analysis engine for an Indian shopping assistant. You are given a product's shopping rating/review count and review evidence gathered separately from up to three sources: YouTube, Reddit, Twitter/X.

STRICT RULES:
1. Ground everything ONLY in the evidence given. Never invent specs, complaints, praise, or use-cases not actually present in the snippets or shopping metadata.
2. Mentally summarize each source's evidence SEPARATELY first, then combine — source_summaries must reflect what that specific source said, not a blended average.
3. If sources disagree with each other, you MUST say so in disagreement_note rather than silently averaging the conflict away.
4. If there is no evidence at all for a field, return an empty list / "Unknown" / null — do not guess.
5. best_for must ONLY use tags from this exact list, and only if evidence actually supports it: {ALLOWED_BEST_FOR_TAGS}
6. fake_review_probability: raise it when the shopping rating is very high (4.8+) with very few shopping reviews, or when external sources are completely silent despite a large shopping review count. Lower it when independent sources corroborate the shopping rating.

Respond with ONLY a single JSON object with these exact keys:
- why_recommend: 2-3 plain-text sentences recommending (or not) this product, citing the evidence. State it was cross-checked across YouTube, Reddit, and Twitter/X.
- positive_ratio: float 0-1, fraction of evidence reading positive.
- negative_ratio: float 0-1, fraction reading negative (positive_ratio + negative_ratio should not exceed 1).
- fake_review_probability: float 0-1.
- sentiment_score: integer 0-100 (50 = neutral/no signal, 100 = overwhelmingly positive, 0 = overwhelmingly negative).
- sentiment_reason: one sentence justifying the above four numbers.
- what_people_love: array of short specific strings, [] if no evidence.
- common_complaints: array of short specific strings, [] if no evidence.
- best_for: array of tags from the allowed list, [] if not clearly supported.
- not_recommended_for: array of short strings, [] if no evidence.
- long_term_reliability: one of "Excellent", "Good", "Average", "Poor", "Unknown".
- warranty_experience: one of "Good", "Average", "Poor", "Unknown".
- ai_confidence: integer 0-100 — how much real evidence backs this whole analysis.
- source_summaries: object mapping each source with evidence to a one-sentence summary of what THAT source said. Omit sources with no evidence.
- disagreement_note: one-sentence conflict description if sources disagree, otherwise null.

No prose, no markdown code fences — JSON only."""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _format_evidence_by_source(snippets_by_platform):
    if not snippets_by_platform:
        return "No external review evidence was found on any platform."
    blocks = []
    for platform, entries in snippets_by_platform.items():
        entries_text = "\n".join(f"  - {entry}" for entry in entries)
        blocks.append(f"{platform}:\n{entries_text}")
    return "\n\n".join(blocks)


def _fallback_result(reason):
    return {
        "why_recommend": reason,
        "positive_ratio": 0.5,
        "negative_ratio": 0.2,
        "fake_review_probability": 0.3,
        "sentiment_score": 50,
        "sentiment_reason": reason,
        "what_people_love": [],
        "common_complaints": [],
        "best_for": [],
        "not_recommended_for": [],
        "long_term_reliability": "Unknown",
        "warranty_experience": "Unknown",
        "ai_confidence": 0,
        "source_summaries": {},
        "disagreement_note": None,
    }


def analyze_evidence(product, review_signals):
    """One Groq call producing everything trust_engine and review_intelligence need."""
    review_signals = review_signals or {}
    title = product.get("title", "this product")
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")
    snippets_by_platform = review_signals.get("snippets_by_platform") or {}
    total_sources = review_signals.get("total_sources", 0)
    platform_counts = review_signals.get("platform_counts", {})

    evidence_block = _format_evidence_by_source(snippets_by_platform)

    user_prompt = f"""Product: {title}
Shopping rating: {rating} ({reviews} shopping reviews)
External sources checked: {total_sources} across {platform_counts}

Evidence grouped by source:
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
        return _fallback_result(
            f"Recommended based on a {rating} rating from {reviews} shopping reviews. "
            "Detailed evidence analysis was unavailable this time."
        )

    allowed_set = set(ALLOWED_BEST_FOR_TAGS)
    best_for = [tag for tag in (data.get("best_for") or []) if tag in allowed_set]

    return {
        "why_recommend": data.get("why_recommend") or "Strong match based on rating, review volume, and price.",
        "positive_ratio": float(data.get("positive_ratio", 0.5) or 0.5),
        "negative_ratio": float(data.get("negative_ratio", 0.2) or 0.2),
        "fake_review_probability": float(data.get("fake_review_probability", 0.3) or 0.3),
        "sentiment_score": max(0, min(100, int(data.get("sentiment_score", 50) or 50))),
        "sentiment_reason": data.get("sentiment_reason") or "No strong signal found in the available evidence.",
        "what_people_love": list(data.get("what_people_love") or [])[:6],
        "common_complaints": list(data.get("common_complaints") or [])[:6],
        "best_for": best_for,
        "not_recommended_for": list(data.get("not_recommended_for") or [])[:4],
        "long_term_reliability": data.get("long_term_reliability") or "Unknown",
        "warranty_experience": data.get("warranty_experience") or "Unknown",
        "ai_confidence": max(0, min(100, int(data.get("ai_confidence", 0) or 0))),
        "source_summaries": dict(data.get("source_summaries") or {}),
        "disagreement_note": data.get("disagreement_note") or None,
    }
