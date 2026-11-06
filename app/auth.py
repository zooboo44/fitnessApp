import json
import time

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from joserfc import jwt
from joserfc.jwk import ECKey

from authlib.integrations.flask_client import OAuth

from .extensions import csrf, db
from .models import OAuthIdentity, User

bp = Blueprint("auth", __name__, url_prefix="/auth")

APPLE_ISSUER = "https://appleid.apple.com"


# --------------------------------------------------------------------------- setup


def init_oauth(app):
    # One registry per app instance, so providers configured for one app never leak into another.
    oauth = OAuth(app)
    app.extensions["fitness_oauth"] = oauth
    cfg = app.config
    if cfg["GOOGLE_CLIENT_ID"] and cfg["GOOGLE_CLIENT_SECRET"]:
        oauth.register(
            "google",
            client_id=cfg["GOOGLE_CLIENT_ID"],
            client_secret=cfg["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    if apple_enabled(app):
        oauth.register(
            "apple",
            client_id=cfg["APPLE_CLIENT_ID"],
            client_secret=None,  # generated per request, see _apple_client_secret()
            server_metadata_url=f"{APPLE_ISSUER}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email name", "token_endpoint_auth_method": "client_secret_post"},
            authorize_params={"response_mode": "form_post"},
        )


def _apple_private_key(app):
    cfg = app.config
    if cfg["APPLE_PRIVATE_KEY"]:
        return cfg["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    if cfg["APPLE_PRIVATE_KEY_PATH"]:
        with open(cfg["APPLE_PRIVATE_KEY_PATH"]) as fh:
            return fh.read()
    return ""


def apple_enabled(app):
    cfg = app.config
    return bool(cfg["APPLE_CLIENT_ID"] and cfg["APPLE_TEAM_ID"] and cfg["APPLE_KEY_ID"]) and bool(
        cfg["APPLE_PRIVATE_KEY"] or cfg["APPLE_PRIVATE_KEY_PATH"]
    )


def _apple_client_secret():
    """Apple requires the client secret to be an ES256 JWT signed with your .p8 key."""
    cfg = current_app.config
    now = int(time.time())
    claims = {
        "iss": cfg["APPLE_TEAM_ID"],
        "iat": now,
        "exp": now + 300,
        "aud": APPLE_ISSUER,
        "sub": cfg["APPLE_CLIENT_ID"],
    }
    key = ECKey.import_key(_apple_private_key(current_app))
    return jwt.encode({"alg": "ES256", "kid": cfg["APPLE_KEY_ID"]}, claims, key)


def _client(name):
    return current_app.extensions["fitness_oauth"].create_client(name)


def _redirect_uri(endpoint):
    base = current_app.config["BASE_URL"]
    if base:
        return base + url_for(endpoint)
    return url_for(endpoint, _external=True)


def providers():
    """Names of SSO providers that are configured."""
    return [name for name in ("google", "apple") if _client(name) is not None]


# --------------------------------------------------------------------------- user linking


def _truthy(v):
    return v is True or (isinstance(v, str) and v.lower() == "true")


def _login_from_claims(provider, claims, name=None):
    subject = claims.get("sub")
    if not subject:
        abort(400, "Identity provider did not return a subject")
    email = (claims.get("email") or "").lower() or None
    email_verified = _truthy(claims.get("email_verified"))

    identity = OAuthIdentity.query.filter_by(provider=provider, subject=subject).first()
    if identity:
        user = identity.user
    else:
        user = None
        # Link to an existing account with the same verified email (e.g. Google then Apple,
        # or an email/password account).
        if email and email_verified:
            user = User.query.filter_by(email=email).first()
            if user is not None and user.password_hash and not user.email_verified:
                # Nobody proved they owned this address when the password was set, so it
                # might belong to someone else who registered it first. Drop the password
                # so only the verified owner keeps access.
                user.set_password(None)
                flash("Your password was reset because your email was verified with "
                      f"{provider.capitalize()}. You can set a new one in Settings.", "success")
        if user is None:
            # An unverified email that already belongs to someone else is not stored.
            if email and User.query.filter_by(email=email).first():
                email = None
            user = User(email=email, name=name or claims.get("name"))
            db.session.add(user)
            db.session.flush()
        db.session.add(OAuthIdentity(provider=provider, subject=subject, user_id=user.id))

    if not user.name and (name or claims.get("name")):
        user.name = name or claims.get("name")
    if not user.email and email:
        user.email = email
    if email_verified and user.email == email:
        user.email_verified = True
    db.session.commit()

    return _finish_login(user)


def _finish_login(user):
    login_user(user, remember=True)
    next_url = session.pop("next_url", None)
    return redirect(next_url or url_for("main.dashboard"))


MIN_PASSWORD_LENGTH = 8


def _normalise_email(value):
    email = (value or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 255:
        return None
    return email


# --------------------------------------------------------------------------- routes


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    nxt = request.args.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        session["next_url"] = nxt

    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user and user.check_password(request.form.get("password") or ""):
            return _finish_login(user)
        if user and not user.password_hash and user.identities:
            flash("This account signs in with "
                  + " or ".join(sorted({i.provider.capitalize() for i in user.identities}))
                  + ". Use that button below, then set a password in Settings if you want one.", "error")
        else:
            flash("Incorrect email or password.", "error")
    return render_template("auth/login.html", providers=providers(), email=email)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = {"email": "", "name": ""}
    if request.method == "POST":
        form = {"email": request.form.get("email", ""), "name": request.form.get("name", "").strip()}
        email = _normalise_email(form["email"])
        password = request.form.get("password") or ""
        error = None
        if email is None:
            error = "Enter a valid email address."
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif password != request.form.get("confirm"):
            error = "Passwords don't match."
        elif User.query.filter_by(email=email).first():
            error = "An account with this email already exists — sign in instead."
        if error:
            flash(error, "error")
        else:
            user = User(email=email, name=form["name"][:255] or None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            return _finish_login(user)
    return render_template("auth/register.html", providers=providers(), form=form)


@bp.route("/login/<provider>")
def login_provider(provider):
    client = _client(provider)
    if client is None:
        abort(404)
    return client.authorize_redirect(_redirect_uri(f"auth.callback_{provider}"))


@bp.route("/callback/google")
def callback_google():
    client = _client("google")
    if client is None:
        abort(404)
    if request.args.get("error"):
        flash("Google sign-in was cancelled.", "error")
        return redirect(url_for("auth.login"))
    token = client.authorize_access_token()
    claims = token.get("userinfo") or client.userinfo()
    return _login_from_claims("google", claims)


@bp.route("/callback/apple", methods=["POST"])
@csrf.exempt
def callback_apple():
    """Apple POSTs here cross-site (response_mode=form_post), so the SameSite=Lax session
    cookie holding the OAuth state is NOT sent. Bounce the form to a same-site endpoint
    so the browser includes the session cookie."""
    if _client("apple") is None:
        abort(404)
    fields = {k: request.form.get(k, "") for k in ("code", "state", "user", "error")}
    return render_template("auth/apple_bounce.html", fields=fields)


@bp.route("/callback/apple/complete", methods=["POST"])
@csrf.exempt  # protected by the OAuth state parameter instead
def callback_apple_complete():
    client = _client("apple")
    if client is None:
        abort(404)
    if request.form.get("error"):
        flash("Apple sign-in was cancelled.", "error")
        return redirect(url_for("auth.login"))
    client.client_secret = _apple_client_secret()
    token = client.authorize_access_token()
    claims = token.get("userinfo") or {}

    # Apple only sends the user's name on the very first authorization.
    name = None
    raw_user = request.form.get("user")
    if raw_user:
        try:
            n = json.loads(raw_user).get("name") or {}
            name = " ".join(p for p in (n.get("firstName"), n.get("lastName")) if p) or None
        except (ValueError, AttributeError):
            pass
    return _login_from_claims("apple", claims, name=name)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # Clear first: logout_user() leaves a flag in the session that tells Flask-Login to
    # delete the "remember me" cookie, and clearing afterwards would wipe that flag.
    session.clear()
    logout_user()
    return redirect(url_for("auth.login"))
