# OAuth2 Sign-In Integration

## Summary

Successfully implemented OAuth2 sign-in capabilities for **Google**, **Facebook**, and **LinkedIn** in the application.

## Components Implemented

### 1. **Database Model** – [app/models/__init__.py](app/models/__init__.py#L318)
- Added `OAuthProvider` model to store OAuth provider links with users
- Tracks provider ID, email, name, picture URL, and token information
- Supports multiple OAuth providers linked to a single user account

### 2. **OAuth Service** – [app/services/oauth_service.py](app/services/oauth_service.py)
- Core OAuth2 service using `authlib` library
- Handles authorization, token exchange, and user info retrieval
- Methods:
  - `init_app()` – Initialize with Flask app
  - `get_authorization_url()` – Generate provider-specific auth URLs
  - `get_user_info()` – Fetch user profile from each provider
  - `find_or_create_user()` – Handle OAuth user creation/linking

### 3. **OAuth Routes** – [app/views_auth.py](app/views_auth.py#L461)
- `/auth/oauth/authorize/<provider>` – Initiate OAuth flow
- `/auth/oauth/callback/<provider>` – Handle OAuth callback
- `/auth/oauth/link/<provider>` – Link OAuth to existing account
- `/auth/oauth/link/callback/<provider>` – Handle account linking

### 4. **UI Updates** – [app/templates/auth_login.html](app/templates/auth_login.html)
- Added OAuth sign-in buttons for Google, Facebook, and LinkedIn
- Responsive button styling with provider brand colors
- Divider line separating email/password from OAuth options

### 5. **Configuration** – [.env](.env#L51)
```
# OAuth2 Credentials
GOOGLE_OAUTH_CLIENT_ID=""
GOOGLE_OAUTH_CLIENT_SECRET=""

FACEBOOK_OAUTH_APP_ID=""
FACEBOOK_OAUTH_APP_SECRET=""

LINKEDIN_OAUTH_CLIENT_ID=""
LINKEDIN_OAUTH_CLIENT_SECRET=""
```

### 6. **Dependencies** – [requirements.txt](requirements.txt)
- Added `authlib` – OAuth2 framework
- Added `requests` – HTTP library for provider API calls

## How It Works

### Sign-In Flow
1. User clicks "Sign in with [Provider]"
2. App redirects to provider's authorization endpoint
3. User authenticates with provider
4. Provider redirects back to app with authorization code
5. App exchanges code for access token
6. App retrieves user profile from provider
7. App creates or finds user account
8. User is logged in

### Account Linking Flow
1. Authenticated user clicks link OAuth provider
2. Similar OAuth flow as above
3. New OAuthProvider record is created
4. User can later sign in with either password or OAuth

## Setup Instructions

### 1. Create OAuth Applications

**Google OAuth:**
- Go to https://console.cloud.google.com/
- Create OAuth 2.0 Client ID (Web application)
- Add redirect URI: `http://localhost:8000/auth/oauth/callback/google`
- Copy Client ID and Client Secret

**Facebook OAuth:**
- Go to https://developers.facebook.com/
- Create Facebook App
- Add "Facebook Login" product
- Configure OAuth Redirect URIs: `http://localhost:8000/auth/oauth/callback/facebook`
- Copy App ID and App Secret

**LinkedIn OAuth:**
- Go to https://www.linkedin.com/developers/
- Create app
- Configure redirect URLs: `http://localhost:8000/auth/oauth/callback/linkedin`
- Copy Client ID and Client Secret

### 2. Configure Credentials

Update `.env` file with your OAuth credentials:
```bash
GOOGLE_OAUTH_CLIENT_ID="your-google-client-id"
GOOGLE_OAUTH_CLIENT_SECRET="your-google-client-secret"

FACEBOOK_OAUTH_APP_ID="your-facebook-app-id"
FACEBOOK_OAUTH_APP_SECRET="your-facebook-app-secret"

LINKEDIN_OAUTH_CLIENT_ID="your-linkedin-client-id"
LINKEDIN_OAUTH_CLIENT_SECRET="your-linkedin-client-secret"
```

### 3. Test the Feature

1. Navigate to `/auth/login`
2. You should see three OAuth sign-in buttons
3. Click any provider to test the flow
4. After authorization, you'll be logged in automatically

## Provider-Specific Notes

### Google
- Uses OAuth 2.0 with OpenID Connect
- Returns: id, email, name, picture
- Supports offline access for refresh tokens

### Facebook
- Returns: id, email, name, picture (large)
- Graph API v18.0
- Picture data nested in response

### LinkedIn
- Uses OAuth 2.0
- Requires separate requests for profile and email
- Returns: id, email, localizedFirstName, localizedLastName, profilePicture

## Database Migration

The `OAuthProvider` table will be created automatically when:
1. App starts with `create_tables()` call
2. Or manually via Alembic migration:
```bash
alembic revision --autogenerate -m "Add OAuth providers table"
alembic upgrade head
```

## Error Handling

- Missing credentials: Providers don't appear in UI
- Invalid state: Prevents CSRF attacks
- Token errors: User redirected to login with error message
- Provider errors: Logged and user-friendly error shown

## Security

- CSRF protection via state parameter
- Tokens stored securely in database
- Session-based authentication after OAuth
- Email deduplication prevents account confusion

## Testing

Test accounts from each provider:
- Use test credentials from provider dashboards
- In development mode, use localhost URLs
- For production, update redirect URIs and app settings

## Next Steps

1. Add OAuth provider credentials to `.env`
2. Test login flow with each provider
3. Configure account linking UI in dashboard
4. Add profile picture display from OAuth
5. Consider social profile enrichment

