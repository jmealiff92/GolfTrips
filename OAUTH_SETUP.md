# Google OAuth Setup Guide

This guide will help you set up Google OAuth authentication for the Golf Trips application.

## Prerequisites

- A Google account
- Access to Google Cloud Console

## Step-by-Step Setup

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click on the project dropdown at the top of the page
3. Click "New Project"
4. Enter a project name (e.g., "Golf Trips App")
5. Click "Create"

### 2. Enable Google+ API

1. In your Google Cloud project, go to **APIs & Services** > **Library**
2. Search for "Google+ API"
3. Click on it and then click **Enable**

### 3. Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Select **External** user type (unless you have a Google Workspace)
3. Click **Create**
4. Fill in the required fields:
   - **App name**: Golf Trips
   - **User support email**: Your email
   - **Developer contact information**: Your email
5. Click **Save and Continue**
6. On the "Scopes" page, click **Save and Continue** (no additional scopes needed)
7. On the "Test users" page, add test user emails if you're in testing mode
8. Click **Save and Continue**
9. Review and click **Back to Dashboard**

### 4. Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth client ID**
3. Select **Web application**
4. Enter a name (e.g., "Golf Trips Web Client")
5. Under **Authorized redirect URIs**, add:
   - For local development: `http://localhost:8050/authorize`
   - For production: `https://yourdomain.com/authorize`
6. Click **Create**
7. A dialog will appear with your **Client ID** and **Client Secret**
8. Copy these values - you'll need them for the `.env` file

### 5. Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your OAuth credentials:
   ```bash
   # Google OAuth Configuration
   GOOGLE_CLIENT_ID=your-client-id-here.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret-here

   # Generate a secret key
   SECRET_KEY=$(python -c "import os; print(os.urandom(24).hex())")

   # Add admin emails (comma-separated)
   ADMIN_EMAILS=admin1@gmail.com,admin2@gmail.com
   ```

### 6. Install Required Packages

```bash
pip install -r requirements.txt
```

The important new packages are:
- `authlib` - OAuth client library
- `flask` - Web framework (Dash is built on Flask)

### 7. Run the Application

```bash
python src/app.py
```

Visit `http://localhost:8050` and you should see a "Login" button in the top right.

## How It Works

### Authentication Flow

1. **User clicks "Login"** → Redirected to Google OAuth consent screen
2. **User approves** → Google redirects back to `/authorize` with auth token
3. **App verifies token** → User session is created
4. **User is logged in** → Email and profile info stored in session

### Authorization Levels

The app has two levels of access:

1. **Viewer** (default for all authenticated users):
   - Can view all pages and statistics
   - Cannot add, edit, or delete data
   - Admin-only pages are disabled in navigation

2. **Admin** (users listed in `ADMIN_EMAILS`):
   - Full access to all features
   - Can add matches, players, courses
   - Can edit and delete data

### Admin Configuration

To grant admin access to specific users:

1. Edit `.env` file
2. Add emails to `ADMIN_EMAILS` (comma-separated):
   ```bash
   ADMIN_EMAILS=user1@gmail.com,user2@gmail.com,user3@gmail.com
   ```
3. Restart the application

**Note**: If `ADMIN_EMAILS` is empty, all authenticated users will have admin access.

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive credentials
2. **Use HTTPS in production** - OAuth requires HTTPS for security
3. **Rotate secrets regularly** - Update `SECRET_KEY` periodically
4. **Limit admin access** - Only add trusted users to `ADMIN_EMAILS`
5. **Review OAuth scopes** - Only request necessary permissions

## Troubleshooting

### "Redirect URI mismatch" error

Make sure the redirect URI in Google Cloud Console exactly matches your app URL:
- Local: `http://localhost:8050/authorize`
- Production: `https://yourdomain.com/authorize`

### "Access blocked: Authorization Error"

Your OAuth app may be in testing mode. Either:
1. Add your email as a test user in OAuth consent screen
2. Publish your app (if ready for production)

### Session not persisting

Make sure `SECRET_KEY` is set in `.env` and is consistent across restarts.

### Admin access not working

1. Check that email in `ADMIN_EMAILS` exactly matches the Google account email
2. Verify `.env` is loaded correctly
3. Restart the application after changing `.env`

## Production Deployment

When deploying to production:

1. Update authorized redirect URIs in Google Cloud Console
2. Set `SECRET_KEY` to a strong, random value
3. Use HTTPS (required for OAuth)
4. Set appropriate `ADMIN_EMAILS`
5. Consider publishing your OAuth app for unrestricted use

## Support

For issues or questions:
- Check the [Authlib documentation](https://docs.authlib.org/)
- Review [Google OAuth documentation](https://developers.google.com/identity/protocols/oauth2)
