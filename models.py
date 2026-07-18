from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    avatar_url = db.Column(db.String(500), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class SearchHistory(db.Model):
    """One row per completed product search (PRD V2 Module 6 — User Memory).

    Deliberately does NOT track "purchases" — this app has no checkout flow,
    users only ever click through to an external purchase link, so there is
    no real signal of whether anything was bought. Only what's genuinely
    knowable is stored: the search itself and which stores appeared in its
    results.
    """
    __tablename__ = "search_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Named search_query, not query — Model.query is Flask-SQLAlchemy's own
    # built-in query-building class attribute; a column literally named
    # "query" shadows it and breaks SearchHistory.query.filter_by(...).
    search_query = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(120), nullable=True)
    brand = db.Column(db.String(120), nullable=True)
    budget_max = db.Column(db.Float, nullable=True)
    top_stores = db.Column(db.String(300), nullable=True)  # comma-separated
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
