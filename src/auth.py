"""
Authentication module for Google OAuth
"""
import os
from flask import session, redirect, url_for, has_request_context
from authlib.integrations.flask_client import OAuth
from functools import wraps
from typing import List, Optional

# Admin emails that can make changes (add/edit/delete)
ADMIN_EMAILS = os.getenv('ADMIN_EMAILS', '').split(',')
ADMIN_EMAILS = [email.strip() for email in ADMIN_EMAILS if email.strip()]

# Initialize OAuth
oauth = OAuth()


def init_oauth(app):
    """Initialize OAuth with the Flask app"""
    oauth.init_app(app)

    # Configure Google OAuth
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

    return oauth


def is_authenticated() -> bool:
    """Check if user is authenticated"""
    if not has_request_context():
        return False
    try:
        return 'user' in session and session.get('user') is not None
    except RuntimeError:
        return False


def get_current_user() -> Optional[dict]:
    """Get current logged in user"""
    if not has_request_context():
        return None
    try:
        return session.get('user')
    except RuntimeError:
        return None


def get_current_user_email() -> Optional[str]:
    """Get current logged in user's email"""
    user = get_current_user()
    return user.get('email') if user else None


def is_admin(email: Optional[str] = None) -> bool:
    """Check if user is an admin (can make changes)"""
    if email is None:
        email = get_current_user_email()

    if not email:
        return False

    # If no admin emails configured, allow all authenticated users
    if not ADMIN_EMAILS:
        return is_authenticated()

    return email in ADMIN_EMAILS


def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def require_admin(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for('login'))
        if not is_admin():
            return {'error': 'Unauthorized - Admin access required'}, 403
        return f(*args, **kwargs)
    return decorated_function


def get_admin_status() -> dict:
    """Get current user's admin status for display"""
    return {
        'authenticated': is_authenticated(),
        'email': get_current_user_email(),
        'is_admin': is_admin(),
        'user': get_current_user()
    }
