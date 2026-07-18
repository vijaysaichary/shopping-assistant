"""Deal Optimizer (PRD V2 Module 8) — standalone service.

Honesty note: this app has no real access to live coupon codes, bank card
offer terms, cashback program rates, festival sale terms, or UPI offers —
none of that is available from SerpAPI or any other data source wired into
this app. Presenting fabricated offers as if they were real, applicable
discounts would be actively misleading in a financial context — worse than
the "Unknown"/empty-field honesty pattern used elsewhere, since a wrong
number here could cost the user real money.

So this is NOT an offer-discovery engine. It's a SAVINGS CALCULATOR: the
user enters whatever real offers they've actually found (a coupon they have,
their bank's card discount, an exchange value they were quoted, a cashback
percentage, etc.) and this module does the arithmetic — stacking them and
computing the final price — plus an EMI breakdown if they want one. Zero
fabricated data; only calculation on numbers the user supplies. Pure math,
no external API calls, no cost.

Contract:
    calculate_deal(base_price: float, offers: list[dict]) -> {
        "base_price": float,
        "offers_applied": [{"label": str, "type": str, "amount": float}, ...],
        "total_savings": float,
        "final_price": float,
        "savings_percent": float,
    }
        Each offer dict: {"label": str, "type": str, "value": float, "is_percent": bool}.
        Offer "type" is just a display category (coupon / card_offer /
        exchange / cashback / student_discount / festival_offer / upi_offer /
        other) — all are calculated identically as either a flat ₹ amount or
        a percentage of base_price. Offers are computed against the ORIGINAL
        base_price (not compounded sequentially), matching how multiple
        simultaneous checkout offers are typically applied in practice.

    calculate_emi(principal: float, tenure_months: int, annual_interest_rate: float = 0.0) -> {
        "monthly_installment": float,
        "total_payment": float,
        "total_interest": float,
    }
"""

OFFER_TYPES = [
    "coupon", "card_offer", "exchange", "cashback",
    "student_discount", "festival_offer", "upi_offer", "other",
]


def calculate_deal(base_price, offers=None):
    if not isinstance(base_price, (int, float)) or base_price <= 0:
        raise ValueError("base_price must be a positive number.")

    offers_applied = []
    total_savings = 0.0

    for offer in (offers or []):
        value = offer.get("value")
        if not isinstance(value, (int, float)) or value <= 0:
            continue

        is_percent = bool(offer.get("is_percent"))
        offer_type = offer.get("type") if offer.get("type") in OFFER_TYPES else "other"
        label = offer.get("label") or offer_type.replace("_", " ").title()

        amount = (base_price * value / 100.0) if is_percent else float(value)
        amount = max(0.0, min(amount, base_price))

        offers_applied.append({"label": label, "type": offer_type, "amount": round(amount, 2)})
        total_savings += amount

    total_savings = min(total_savings, base_price)
    final_price = round(base_price - total_savings, 2)
    savings_percent = round((total_savings / base_price) * 100, 1) if base_price else 0.0

    return {
        "base_price": round(base_price, 2),
        "offers_applied": offers_applied,
        "total_savings": round(total_savings, 2),
        "final_price": final_price,
        "savings_percent": savings_percent,
    }


def calculate_emi(principal, tenure_months, annual_interest_rate=0.0):
    if not isinstance(principal, (int, float)) or principal <= 0:
        raise ValueError("principal must be a positive number.")
    if not isinstance(tenure_months, int) or tenure_months <= 0:
        raise ValueError("tenure_months must be a positive integer.")

    if not annual_interest_rate or annual_interest_rate <= 0:
        monthly_installment = principal / tenure_months
        total_payment = principal
        total_interest = 0.0
    else:
        r = (annual_interest_rate / 12) / 100
        factor = (1 + r) ** tenure_months
        monthly_installment = principal * r * factor / (factor - 1)
        total_payment = monthly_installment * tenure_months
        total_interest = total_payment - principal

    return {
        "monthly_installment": round(monthly_installment, 2),
        "total_payment": round(total_payment, 2),
        "total_interest": round(total_interest, 2),
    }
