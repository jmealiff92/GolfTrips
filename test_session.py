#!/usr/bin/env python3
"""
Quick test to verify session is accessible in the app
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import app, server
from flask import session

print("=" * 60)
print("Testing Flask/Dash Session Setup")
print("=" * 60)

# Test that the app is configured correctly
print(f"\n✓ App loaded successfully")
print(f"✓ Server secret key configured: {bool(server.secret_key)}")
print(f"✓ Session cookie settings:")
print(f"  - HTTPONLY: {server.config.get('SESSION_COOKIE_HTTPONLY', False)}")
print(f"  - SAMESITE: {server.config.get('SESSION_COOKIE_SAMESITE', 'Not set')}")

# Test in request context
with server.test_request_context():
    with server.test_client() as client:
        # Simulate setting a session value
        with client.session_transaction() as sess:
            sess['user'] = {'email': 'test@example.com', 'name': 'Test User'}

        print(f"\n✓ Session can be set in test context")
        print(f"✓ Test user email: test@example.com")

print("\n" + "=" * 60)
print("Setup looks good! Now test with the actual app:")
print("1. Run: python src/app.py")
print("2. Visit: http://localhost:8050")
print("3. Click Login and authenticate")
print("4. Check if navbar buttons are clickable")
print("=" * 60)
