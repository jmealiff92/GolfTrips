"""Google OAuth (Authlib's Starlette client) + session-based auth/admin helpers.

Port of src/auth.py's logic. The one structural difference: Flask lets
is_authenticated()/is_admin() read flask.session implicitly via a thread-local
request context (has_request_context()). Starlette has no equivalent, so every
helper here takes the session dict explicitly instead.
"""
import os
from typing import Optional

from authlib.integrations.starlette_client import OAuth
from fasthtml.common import Div, P

ADMIN_EMAILS = [e.strip() for e in os.getenv('ADMIN_EMAILS', '').split(',') if e.strip()]

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


def build_redirect_uri(req) -> str:
    """Build the /authorize redirect URI.

    Defaults to deriving it from the incoming request's host, so the same code
    works locally and on a Render preview URL without a hardcoded hostname.
    OAUTH_REDIRECT_BASE_URL can override this (e.g. if a proxy reports the
    wrong scheme/host).
    """
    override = os.getenv('OAUTH_REDIRECT_BASE_URL')
    base = override.rstrip('/') if override else str(req.base_url).rstrip('/')
    return f"{base}/authorize"


def is_authenticated(session: dict) -> bool:
    return bool(session.get('user'))


def get_current_user(session: dict) -> Optional[dict]:
    return session.get('user')


def get_current_user_email(session: dict) -> Optional[str]:
    user = get_current_user(session)
    return user.get('email') if user else None


def is_admin(session: dict) -> bool:
    """Same rule as src/auth.py: empty ADMIN_EMAILS means every authenticated user is admin."""
    email = get_current_user_email(session)
    if not email:
        return False
    if not ADMIN_EMAILS:
        return is_authenticated(session)
    return email in ADMIN_EMAILS


def check_admin_access(session: dict):
    """Port of app.py's check_admin_access() (app.py:3055-3063). Returns (bool, FT|None)."""
    if not is_authenticated(session):
        return False, Div(P("Please login to perform this action"), cls='alert alert-warning')
    if not is_admin(session):
        return False, Div(
            P("You do not have permission to perform this action. Admin access required."),
            cls='alert alert-danger',
        )
    return True, None
