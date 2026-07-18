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

SYSTEM_PROMPT = """You are a shopping query understanding engine for an Indian e-commerce assistant. All prices are in Indian Rupees (INR).

Given a user's natural language shopping request, extract structured intent as JSON with these exact keys:

- category: the precise product type. Maintain strict category matching (e.g. "wireless earbuds" not "earphones" if the user said earbuds or TWS; "gaming laptop" not "laptop" if gaming was mentioned; "running shoes" not "shoes" if running was specified; "iPhone" only if iPhone/Apple was requested, never Android, and vice versa).
- brand: brand/company name if mentioned, else null. Never invent or substitute a brand.
- budget_min: number in INR or null.
- budget_max: number in INR or null.
  Rules: "under X" / "below X" -> budget_max=X, budget_min=null. "between X and Y" -> budget_min=X, budget_max=Y. "around 1 lakh" -> budget_min=90000, budget_max=110000. "cheap"/"budget" -> set a reasonable low budget_max for that category. "premium" -> set a reasonable high budget_min for that category. No mention -> both null.
- purpose: why the user wants it (e.g. "gaming", "photography", "coding", "video editing", "calls"), else null.
- specs: array of specific requested specs/features (e.g. ["8GB RAM", "5G", "ANC", "AMOLED display"]). Empty array if none mentioned.
- search_query: a concise, optimized Google Shopping search string combining category, brand (if any), and the most important specs. Do not include currency symbols or budget numbers in this string.
- needs_clarification: true ONLY if the request is too broad to search meaningfully (no category signal, no budget, no brand, no purpose at all — e.g. just "suggest me a laptop"). If there is enough signal to search, even partially, set this to false.
- clarification_question: a short, friendly question asking for budget, usage/purpose, and brand preference — only when needs_clarification is true, else null.

Respond with ONLY a single valid JSON object. No prose, no markdown code fences."""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_query(user_query):
    """Convert a natural language shopping request into structured intent."""
    response = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    text = _strip_code_fences(response.choices[0].message.content)
    intent = json.loads(text)

    intent.setdefault("category", None)
    intent.setdefault("brand", None)
    intent.setdefault("budget_min", None)
    intent.setdefault("budget_max", None)
    intent.setdefault("purpose", None)
    intent.setdefault("specs", [])
    intent.setdefault("search_query", user_query)
    intent.setdefault("needs_clarification", False)
    intent.setdefault("clarification_question", None)

    return intent


def synthesize_review_reason(product, review_signals):
    """Use Groq to explain why a product is recommended based on cross-platform review signals."""
    title = product.get("title", "this product")
    price = product.get("price", "N/A")
    rating = product.get("rating", "N/A")
    reviews = product.get("reviews", "N/A")

    snippets = review_signals.get("snippets") or []
    snippets_text = "\n".join(snippets) if snippets else "No external review snippets were found."
    platform_counts = review_signals.get("platform_counts", {})
    total_sources = review_signals.get("total_sources", 0)

    prompt = f"""Product: {title}
Shopping price: {price}
Shopping rating: {rating} ({reviews} reviews)

External review mentions found across the web:
{snippets_text}

Platform coverage (number of mentions found): {platform_counts}
Total external sources checked: {total_sources}

Write a concise 2-3 sentence recommendation reason for this product. State that it was cross-checked across YouTube, Reddit, and Twitter/X ({total_sources} sources total), and briefly summarize what those sources commonly say about it (praise or complaints). If no external snippets were found, say so plainly and base the reason on the shopping rating and review count instead. Plain text only, no markdown."""

    response = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()
