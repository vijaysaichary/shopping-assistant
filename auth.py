import os
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

from extensions import db
from models import User

load_dotenv(Path(__file__).resolve().parent / ".env")

auth_bp = Blueprint("auth", __name__)

oauth = OAuth()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")


def init_oauth(app):
    oauth.init_app(app)
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", google_enabled=bool(GOOGLE_CLIENT_ID)), 401

        login_user(user, remember=remember)
        return redirect(url_for("index"))

    return render_template("login.html", google_enabled=bool(GOOGLE_CLIENT_ID))


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("signup.html", google_enabled=bool(GOOGLE_CLIENT_ID)), 400

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("signup.html", google_enabled=bool(GOOGLE_CLIENT_ID)), 400

        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("signup.html", google_enabled=bool(GOOGLE_CLIENT_ID)), 400

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
            return render_template("signup.html", google_enabled=bool(GOOGLE_CLIENT_ID)), 400

        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("index"))

    return render_template("signup.html", google_enabled=bool(GOOGLE_CLIENT_ID))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/auth/google")
def google_login():
    if "google" not in oauth._clients:
        flash("Google sign-in is not configured.", "error")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    if "google" not in oauth._clients:
        return redirect(url_for("auth.login"))

    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.userinfo()

    google_id = userinfo["sub"]
    email = userinfo["email"].lower()
    name = userinfo.get("name") or email.split("@")[0]
    avatar_url = userinfo.get("picture")

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    if not user:
        user = User(name=name, email=email, google_id=google_id, avatar_url=avatar_url)
        db.session.add(user)
    else:
        user.google_id = user.google_id or google_id
        user.avatar_url = avatar_url or user.avatar_url

    db.session.commit()
    login_user(user)
    return redirect(url_for("index"))
