"""AI Buying Advisor (PRD V2 Module 5) — standalone, rule-based service.

Instead of jumping straight to search on an underspecified request, this
asks a short, category-specific sequence of clarifying questions (budget,
purpose, brand — capped at 3, not the PRD's full 8, as a deliberate UX
scoping choice: a chat flow that interrogates the user for 8 turns before
showing anything is worse than showing decent results after 2-3 quick
questions) and folds each answer back into the search intent before
searching.

This also fixes a real gap in the previous single-question clarification
flow: a user's answer to "what's your budget?" was being re-parsed by
parse_query() from scratch, with zero memory that it was an answer to
anything — the LLM had no idea "under 50k" was a reply about a laptop asked
about two turns ago. This module tracks that state explicitly instead.

Cost note: this is intentionally 100% rule-based — CATEGORY_QUESTION_BANKS is
a static lookup and answers are parsed with plain regex/string matching, not
an LLM call. Zero additional Groq tokens, which matters given this project's
tight daily token budget.

Scope note: state here lives only in the Flask session for the duration of
ONE clarifying conversation (a few turns, until the search runs). Remembering
a user's preferences across DIFFERENT search sessions (e.g. "you usually
prefer Samsung") is Module 6 (User Memory)'s job, not this module's.

Contract:
    start_advisor(session: dict, original_query: str, intent: dict) -> {
        "status": "asking", "question": str
    } | {
        "status": "ready", "final_intent": dict
    }
        Call whenever intent.get("category") is truthy — it internally
        figures out whether anything is actually missing and immediately
        returns "ready" (a no-op) if the user already gave enough detail.

    continue_advisor(session: dict, answer_text: str) -> same "asking"/"ready"
        shape as start_advisor (plus "original_query" on "ready"), or None if
        there is no in-progress advisor conversation in session — callers
        should treat None as "this is a fresh, independent query."
    reset(session: dict) -> None
"""

import re

SESSION_KEY = "buying_advisor"
MAX_QUESTIONS = 3

SKIP_PHRASES = {
    "skip", "any", "no preference", "doesn't matter", "does not matter",
    "na", "n/a", "none", "no", "nothing specific", "not sure", "anything",
}


def _budget_question(label="it"):
    return f"What's your budget for {label} (in ₹)? You can say things like '50000', '50k', or '1 lakh'."


CATEGORY_QUESTION_BANKS = {
    "laptop": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the laptop")},
        {"field": "purpose", "type": "text", "question": "What will you mainly use it for — programming, gaming, office work, or general use?"},
        {"field": "brand", "type": "text", "question": "Any brand preference (Dell, HP, Lenovo, ASUS, Apple, etc.), or open to any?"},
    ],
    "smartphone": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the phone")},
        {"field": "purpose", "type": "text", "question": "What matters most to you — camera quality, gaming performance, or battery life?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "earbuds": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the earbuds")},
        {"field": "purpose", "type": "text", "question": "Mainly for calls, gym/workouts, or general music listening?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "headphone": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the headphones")},
        {"field": "purpose", "type": "text", "question": "Mainly for calls, travel/noise cancellation, or general listening?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "smartwatch": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the smartwatch")},
        {"field": "purpose", "type": "text", "question": "Mainly for fitness tracking, notifications, or as a fashion accessory?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "tv": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the TV")},
        {"field": "specs", "type": "spec", "question": "What screen size are you looking for (in inches)?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "shoes": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the shoes")},
        {"field": "purpose", "type": "text", "question": "Mainly for running, casual wear, or sports/training?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
    "camera": [
        {"field": "budget_max", "type": "budget", "question": _budget_question("the camera")},
        {"field": "purpose", "type": "text", "question": "Mainly for photography, vlogging/video, or travel?"},
        {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
    ],
}

DEFAULT_QUESTIONS = [
    {"field": "budget_max", "type": "budget", "question": _budget_question("it")},
    {"field": "purpose", "type": "text", "question": "What will you mainly use it for?"},
    {"field": "brand", "type": "text", "question": "Any brand preference, or open to any?"},
]


def _match_question_bank(category):
    if not category:
        return DEFAULT_QUESTIONS
    normalized = category.lower()
    for key, bank in CATEGORY_QUESTION_BANKS.items():
        if key in normalized:
            return bank
    return DEFAULT_QUESTIONS


def _missing_questions(intent, bank):
    pending = []
    for q in bank:
        field = q["field"]
        has_value = bool(intent.get("specs")) if field == "specs" else bool(intent.get(field))
        if not has_value:
            pending.append(q)
    return pending[:MAX_QUESTIONS]


def _is_skip(text):
    return (text or "").strip().lower() in SKIP_PHRASES


_LAKH_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)\b")
_K_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*k\b")
_NUMBER_PATTERN = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def _parse_budget_answer(text):
    if not text:
        return None
    normalized = text.lower().replace(",", "").strip()

    lakh_match = _LAKH_PATTERN.search(normalized)
    if lakh_match:
        return float(lakh_match.group(1)) * 100000

    k_match = _K_PATTERN.search(normalized)
    if k_match:
        return float(k_match.group(1)) * 1000

    num_match = _NUMBER_PATTERN.search(text.replace(",", ""))
    if num_match:
        try:
            return float(num_match.group(1))
        except ValueError:
            return None
    return None


def _apply_answer(intent, question, answer_text):
    if _is_skip(answer_text):
        return intent

    field = question["field"]
    qtype = question["type"]

    if qtype == "budget":
        value = _parse_budget_answer(answer_text)
        if value:
            intent["budget_max"] = value
    elif qtype == "spec":
        specs = list(intent.get("specs") or [])
        specs.append(answer_text.strip())
        intent["specs"] = specs
    else:
        intent[field] = answer_text.strip()

    return intent


def start_advisor(session, original_query, intent):
    bank = _match_question_bank(intent.get("category"))
    pending = _missing_questions(intent, bank)

    if not pending:
        return {"status": "ready", "final_intent": intent}

    session[SESSION_KEY] = {
        "original_query": original_query,
        "intent": intent,
        "pending_questions": pending,
        "asked_index": 0,
    }
    session.modified = True
    return {"status": "asking", "question": pending[0]["question"]}


def continue_advisor(session, answer_text):
    """Returns None if there's no in-progress advisor conversation — the
    caller should treat the message as a fresh, independent query instead."""
    state = session.get(SESSION_KEY)
    if not state:
        return None

    pending = state["pending_questions"]
    idx = state["asked_index"]
    current_question = pending[idx]

    intent = _apply_answer(state["intent"], current_question, answer_text)
    next_idx = idx + 1

    if next_idx >= len(pending):
        original_query = state.get("original_query")
        session.pop(SESSION_KEY, None)
        session.modified = True
        intent["needs_clarification"] = False
        return {"status": "ready", "final_intent": intent, "original_query": original_query}

    state["intent"] = intent
    state["asked_index"] = next_idx
    session[SESSION_KEY] = state
    session.modified = True
    return {"status": "asking", "question": pending[next_idx]["question"]}


def reset(session):
    session.pop(SESSION_KEY, None)
    session.modified = True
