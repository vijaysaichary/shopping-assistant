import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify, render_template
from flask_login import login_required, current_user

from extensions import db, login_manager
from models import User
from auth import auth_bp, init_oauth
from serp_service import search_products
from product_ranker import dedupe_products, filter_products, rank_products
from chatbot import build_response
from query_understanding import parse_query
from review_aggregator import enrich_products_with_reviews

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///users.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
login_manager.init_app(app)
init_oauth(app)
app.register_blueprint(auth_bp)

with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user)


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Missing 'query' in request body"}), 400

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

    if intent.get("needs_clarification"):
        reply = build_response(query, intent, [])
        return jsonify({"reply": reply, "products": [], "intent": intent})

    try:
        products = search_products(intent.get("search_query") or query, num_results=20)
        products = dedupe_products(products)
        products = filter_products(products, intent)
        ranked = rank_products(products)
        ranked = enrich_products_with_reviews(ranked)
        reply = build_response(query, intent, ranked)
    except Exception:
        return jsonify({"error": "Unable to fetch products right now. Please try again."}), 503

    return jsonify({"reply": reply, "products": ranked, "intent": intent})


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
