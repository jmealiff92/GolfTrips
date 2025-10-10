# Session Availability Fix for Dash Callbacks

## Problem
After authentication worked, navbar buttons were not clickable because the session data wasn't being properly accessed in Dash callbacks, preventing the `update_nav_access` callback from determining if the user was an admin.

## Root Cause
The `update_auth_store` callback was trying to check authentication status but wasn't properly accessing the Flask session that exists in the request context. The callback needs to run within Flask's request context to access the session cookie sent by the browser.

## Solution Applied

### 1. Added Session Configuration (lines 43-47)
```python
server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
```
This ensures cookies are properly handled and sent with requests.

### 2. Simplified Auth Store Callback (lines 1844-1874)
Changed from making HTTP requests to directly calling auth functions:
```python
@app.callback(
    Output('auth-store', 'data'),
    [Input('auth-check-interval', 'n_intervals'),
     Input('url', 'pathname')]
)
def update_auth_store(n, pathname):
    authenticated = is_authenticated()
    email = get_current_user_email()
    admin = is_admin()
    ...
```

Key improvements:
- Direct function calls work because Dash callbacks execute in Flask request context
- Added URL pathname as trigger for immediate updates on navigation
- Added logging for debugging
- Proper error handling

## How It Works

1. **User authenticates** → OAuth stores user info in `session['user']`
2. **Browser makes request** → Sends session cookie with the request
3. **Dash callback executes** → Runs in Flask request context with session access
4. **Auth functions work** → `is_authenticated()` can read from `session`
5. **Auth store updates** → Stores auth status in client-side storage
6. **Nav buttons update** → `update_nav_access` callback enables/disables buttons based on auth status

## Testing Steps

1. **Start the application:**
   ```bash
   python src/app.py
   ```

2. **Before login:**
   - Visit http://localhost:8050
   - Navbar admin buttons should be disabled/greyed out
   - See "🔐 Login" button in top-right

3. **After login:**
   - Click "🔐 Login"
   - Complete Google OAuth
   - Return to app
   - Should see your email and "(Admin)" or "(Viewer)" badge
   - **Admin buttons should now be clickable**
   - Check browser console and server logs for "Auth check" messages

4. **Verify navigation:**
   - Click on admin-only pages: "Manage Players", "Manage Courses", "Add Match", "Edit Matches"
   - Should navigate successfully
   - Each navigation triggers auth check (via URL pathname trigger)

## Debugging

If buttons are still not clickable, check:

1. **Server logs** - Look for:
   ```
   Auth check - Authenticated: True, Email: your@email.com, Admin: True
   ```

2. **Browser console** - Check for JavaScript errors

3. **Session cookie** - In browser DevTools → Application → Cookies, verify session cookie exists for localhost:8050

4. **Admin emails** - Verify your email is in the `ADMIN_EMAILS` environment variable (or that it's empty to allow all authenticated users)

## Environment Variables Required

```bash
# .env file
SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
ADMIN_EMAILS=admin1@example.com,admin2@example.com  # Optional: comma-separated list
```

If `ADMIN_EMAILS` is empty or not set, all authenticated users are treated as admins.
