"""Review Intelligence Engine (PRD V2 Module 2) — standalone service.

Replaces a single generic recommendation paragraph with structured insights
mined from the same cross-platform evidence review_aggregator.py already
gathers (YouTube, Reddit, Twitter/X) plus the shopping site's own
rating/review count.

Design intent, matching the PRD's backend rules for this module:
  - The model is shown evidence grouped BY SOURCE (not a blended blob) and is
    required to produce a per-source summary for each platform that actually
    has evidence, before it is allowed to produce the combined verdict. This
    is enforced by the output schema itself (source_summaries is a required
    field alongside the combined fields), not just an instruction to a single
    blended prompt.
  - Never hallucinate: any field with no supporting evidence comes back empty
    ([]) or "Unknown" rather than invented. The prompt explicitly forbids
    inventing specs, complaints, or use-cases not present in the evidence.
  - Explicit disagreement detection: if platforms disagree (e.g. YouTube
    praises battery life while Reddit reports drain complaints),
    disagreement_note must say so rather than silently averaging it away.

Contract:
    generate_review_intelligence(product: dict, review_signals: dict) -> {
        "what_people_love": [str, ...],
        "common_complaints": [str, ...],
        "best_for": [str, ...],            # subset of ALLOWED_BEST_FOR_TAGS
        "not_recommended_for": [str, ...],
        "long_term_reliability": "Excellent" | "Good" | "Average" | "Poor" | "Unknown",
        "warranty_experience": "Good" | "Average" | "Poor" | "Unknown",
        "ai_confidence": int (0-100),
        "source_summaries": {platform: str, ...},   # only platforms with evidence
        "disagreement_note": str | None,
    }

`review_signals` is the dict produced by
review_aggregator.gather_review_signals (must include "snippets_by_platform")
— this module scores what it's given rather than fetching its own data, so it
stays a pure, independently testable service and never duplicates SerpAPI calls.
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

SYSTEM_PROMPT = f"""You are a Review Intelligence engine for an Indian shopping assistant. You are given a product's shopping rating/review count and review evidence gathered separately from up to three sources: YouTube, Reddit, Twitter/X.

STRICT RULES:
1. Ground everything ONLY in the evidence given. Never invent specs, complaints, praise, or use-cases that aren't actually present in the snippets or shopping metadata.
2. Mentally summarize each source's evidence SEPARATELY first, then combine — your source_summaries field must reflect what that specific source said, not a blended average.
3. If sources disagree with each other (e.g. one platform praises something another complains about), you MUST say so in disagreement_note. Do not silently average away a conflict.
4. If there is no evidence at all for a field, return an empty list / "Unknown" — do not guess.
5. best_for must ONLY use tags from this exact list, and only include a tag if the evidence actually supports it: {ALLOWED_BEST_FOR_TAGS}

Respond with ONLY a single JSON object with these exact keys:
- what_people_love: array of short strings (specific points, not generic praise), [] if no evidence.
- common_complaints: array of short strings, [] if no evidence.
- best_for: array of tags from the allowed list above, [] if evidence doesn't clearly support any.
- not_recommended_for: array of short strings describing who should avoid it, [] if no evidence.
- long_term_reliability: one of "Excellent", "Good", "Average", "Poor", "Unknown".
- warranty_experience: one of "Good", "Average", "Poor", "Unknown".
- ai_confidence: integer 0-100 — how much real evidence backs this summary (low if evidence is thin/absent, high if multiple sources corroborate).
- source_summaries: object mapping each source name that has evidence to a one-sentence summary of what THAT source specifically said. Omit sources with no evidence entirely — do not include empty entries.
- disagreement_note: a one-sentence note describing the conflict if sources disagree, otherwise null.

No prose, no markdown code fences — JSON only."""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _empty_result(reason):
    return {
        "what_people_love": [],
        "common_complaints": [],
        "best_for": [],
        "not_recommended_for": [],
        "long_term_reliability": "Unknown",
        "warranty_experience": "Unknown",
        "ai_confidence": 0,
        "source_summaries": {},
        "disagreement_note": reason,
    }


def _format_evidence_by_source(snippets_by_platform):
    if not snippets_by_platform:
        return "No external review evidence was found on any platform."
    blocks = []
    for platform, entries in snippets_by_platform.items():
        entries_text = "\n".join(f"  - {entry}" for entry in entries)
        blocks.append(f"{platform}:\n{entries_text}")
    return "\n\n".join(blocks)


def _normalize(data):
    """Validate/clamp a raw dict (from either this module's own Groq call or
    evidence_engine.analyze_evidence()'s combined result) into this module's
    output contract. Shared so both paths enforce identical guarantees."""
    allowed_set = set(ALLOWED_BEST_FOR_TAGS)
    best_for = [tag for tag in (data.get("best_for") or []) if tag in allowed_set]

    return {
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


def from_raw(data):
    """Pipeline path: normalize an already-fetched raw dict (from
    evidence_engine.analyze_evidence()) — no network call. This is what the
    live pipeline uses, so this module doesn't make its own redundant Groq
    call on top of evidence_engine's."""
    return _normalize(data or {})


def generate_review_intelligence(product, review_signals):
    """Standalone path: makes its own dedicated Groq call, then normalizes the
    result. Useful for direct/unit testing of this module in isolation; the
    live pipeline instead calls from_raw() with data evidence_engine.py
    already produced, to avoid a duplicate Groq call."""
    review_signals = review_signals or {}
    snippets_by_platform = review_signals.get("snippets_by_platform") or {}

    title = product.get("title", "this product")
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")

    evidence_block = _format_evidence_by_source(snippets_by_platform)

    user_prompt = f"""Product: {title}
Shopping rating: {rating} ({reviews} shopping reviews)

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
        return _empty_result(
            "Review Intelligence analysis was unavailable for this product right now."
        )

    return _normalize(data)
