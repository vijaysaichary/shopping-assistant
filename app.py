import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from flask import Flask, request, jsonify, render_template, session
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from extensions import db, login_manager
from models import User
from auth import auth_bp, init_oauth
from serp_service import search_products
from product_ranker import dedupe_products, filter_products, rank_products
from chatbot import build_response
from query_understanding import parse_query
from review_aggregator import enrich_products_with_reviews
from price_engine import build_market_snapshot, analyze_price
from seller_engine import analyze_seller
from buying_advisor import start_advisor, continue_advisor
from user_memory import record_search, welcome_back_message
from comparison_engine import compare_products
from deal_optimizer import calculate_deal, calculate_emi
from decision_report import generate_decision_report
from smart_labels import generate_labels

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_proto=1,
    x_host=1
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

# Flask's automatic instance-folder detection can end up anchored to the
# process's working directory rather than this file's location, silently
# creating/reading a different (empty) database depending on how the app is
# launched. Anchor a relative sqlite:/// URI to this file's own instance/
# folder explicitly. An absolute path (e.g. sqlite:////tmp/users.db, set via
# Vercel's env vars) is left untouched.
BASE_DIR = Path(__file__).resolve().parent
raw_db_url = os.getenv("DATABASE_URL", "sqlite:///users.db")
if raw_db_url.startswith("sqlite:///") and not raw_db_url.startswith("sqlite:////"):
    db_filename = raw_db_url[len("sqlite:///"):]
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{(instance_dir / db_filename).resolve()}"
else:
    db_url = raw_db_url

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
login_manager.init_app(app)
init_oauth(app)
app.register_blueprint(auth_bp)

@app.before_request
def create_tables():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
@login_required
def index():
    return render_template(
        "index.html", user=current_user,
        welcome_message=welcome_back_message(current_user.id),
    )


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Missing 'query' in request body"}), 400

    # If there's an AI Buying Advisor conversation already in progress for
    # this session, this message is an ANSWER to the last question asked —
    # not an independent new query. continue_advisor returns None when
    # there's no active conversation, so a normal fresh search falls through
    # to the parse_query() path below as before.
    advisor_result = continue_advisor(session, query)

    if advisor_result is not None:
        if advisor_result["status"] == "asking":
            return jsonify({
                "reply": advisor_result["question"], "products": [],
                "intent": {}, "needs_input": True,
            })
        intent = advisor_result["final_intent"]
        query = advisor_result.get("original_query") or query
    else:
        try:
            intent = parse_query(query)
        except Exception as exc:
            message = "The AI is temporarily rate-limited or unavailable. Please try again in a minute."
            if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc) or "rate_limit" in str(exc).lower():
                message = "AI request rate limit reached. Please try again in a minute."
            return jsonify({"error": message}), 503

        override_budget_max = data.get("budget_max")
        if isinstance(override_budget_max, (int, float)) and override_budget_max > 0:
            intent["budget_max"] = override_budget_max
            intent["needs_clarification"] = False

        # The AI Buying Advisor is the primary conversational path whenever we
        # at least know WHAT category the user wants — including when Groq
        # itself set needs_clarification=True (its own system prompt treats a
        # bare "I need a laptop" as needing clarification even though a
        # category was extracted). Only fall back to Groq's single generic
        # clarification_question when category itself is unknown, since a
        # rule-based question bank can't be built without one.
        if intent.get("category"):
            advisor_start = start_advisor(session, query, intent)
            if advisor_start["status"] == "asking":
                return jsonify({
                    "reply": advisor_start["question"], "products": [],
                    "intent": intent, "needs_input": True,
                })
            intent = advisor_start["final_intent"]
        elif intent.get("needs_clarification"):
            reply = build_response(query, intent, [])
            return jsonify({"reply": reply, "products": [], "intent": intent, "needs_input": True})

    try:
        products = search_products(intent.get("search_query") or query, num_results=20)
        products = dedupe_products(products)
        products = filter_products(products, intent)

        # Market snapshot uses the FULL filtered listing set (not just the
        # top 5 that make the final shortlist) so "average/lowest/highest
        # price" reflects real comparable listings found today, not just the
        # already-cherry-picked shortlist.
        market_snapshot = build_market_snapshot(products)
        comparable_prices = [
            p.get("extracted_price") for p in products
            if isinstance(p.get("extracted_price"), (int, float)) and p.get("extracted_price") > 0
        ]

        ranked = rank_products(products)
        ranked = enrich_products_with_reviews(ranked)
        for product in ranked:
            product["price_intelligence"] = analyze_price(product, market_snapshot, comparable_prices)
            product["seller_intelligence"] = analyze_seller(product)
            # Decision Report reads price/seller intelligence, so it must run
            # after both are set above — it's a zero-cost presentation layer
            # over data the earlier engines already computed, not a new call.
            product["decision_report"] = generate_decision_report(product)
        # The Bayesian rank_products() pass only has shopping-site rating/review
        # data to work with; once the AI Trust Score exists (rating + review
        # volume + cross-platform corroboration + fake-review adjustment), it's
        # the better final ordering signal for the shortlist actually shown.
        ranked.sort(key=lambda p: p.get("trust_score") if p.get("trust_score") is not None else -1, reverse=True)

        # Smart Labels compares ACROSS the final shortlist (Best Budget/Best
        # Value/etc need every product's price+trust together), so it must
        # run after the per-product enrichment loop above, not inside it.
        labels_by_title = generate_labels(ranked)
        for product in ranked:
            product["smart_labels"] = labels_by_title.get(product.get("title", "Unknown"), [])

        reply = build_response(query, intent, ranked)
    except Exception:
        app.logger.exception("Search pipeline failed for query=%r", query)
        return jsonify({"error": "Unable to fetch products right now. Please try again."}), 503

    try:
        top_stores = [p.get("source") for p in ranked if p.get("source")]
        record_search(current_user.id, query, intent, top_stores=top_stores)
    except Exception:
        app.logger.exception("Failed to record search history for user_id=%r", current_user.id)

    return jsonify({"reply": reply, "products": ranked, "intent": intent, "needs_input": False})


@app.route("/compare", methods=["POST"])
@login_required
def compare():
    """Compares 2-5 already-fetched products (the frontend sends back the
    exact product objects it already received from /chat — this stays
    stateless, no need to look anything up server-side)."""
    data = request.get_json(silent=True) or {}
    products = data.get("products") or []

    if len(products) < 2:
        return jsonify({"error": "Select at least 2 products to compare."}), 400
    if len(products) > 5:
        return jsonify({"error": "You can compare at most 5 products at once."}), 400

    try:
        result = compare_products(products)
    except Exception:
        app.logger.exception("Product comparison failed")
        return jsonify({"error": "Unable to compare these products right now. Please try again."}), 503

    return jsonify(result)


@app.route("/calculate-deal", methods=["POST"])
@login_required
def calculate_deal_route():
    """Pure-math savings calculator (Module 8) — the user supplies real
    offers they've found (a coupon, a card discount, an exchange value); this
    never fabricates offers on its own. No Groq/SerpAPI cost."""
    data = request.get_json(silent=True) or {}
    base_price = data.get("base_price")
    offers = data.get("offers") or []

    try:
        result = calculate_deal(base_price, offers)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    emi = data.get("emi")
    if emi:
        try:
            result["emi"] = calculate_emi(
                result["final_price"],
                int(emi.get("tenure_months")),
                float(emi.get("annual_interest_rate", 0) or 0),
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": f"Invalid EMI input: {exc}"}), 400

    return jsonify(result)


if __name__ == "__main__":
    # host="localhost" makes Werkzeug's dev server bind both IPv4 (127.0.0.1)
    # and IPv6 (::1) loopback — but on Windows that dual-stack dev server
    # setup is flaky and intermittently resets connections on ::1
    # (ERR_EMPTY_RESPONSE). Binding only 127.0.0.1 is reliable; access the
    # app at that address. If Google sign-in needs "localhost" specifically
    # (matching its registered redirect URI), add 127.0.0.1's callback URI
    # to Google Cloud Console instead of relying on this dual-stack bind.
    app.run(host="127.0.0.1", port=5000, debug=False)