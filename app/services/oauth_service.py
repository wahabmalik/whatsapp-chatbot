"""OAuth2 authentication service for Google, Facebook, and LinkedIn."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from authlib.integrations.flask_client import OAuth, OAuthError

from app.models import BotConfig, ConnectionState, OAuthProvider, Tenant, UsageCounter, User
from app.models.base import new_uuid, utcnow

logger = logging.getLogger(__name__)

# OAuth provider configurations
OAUTH_CONFIGS = {
    "google": {
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
        "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "access_token_url": "https://www.googleapis.com/oauth2/v4/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": ["profile", "email"],
    },
    "facebook": {
        "client_id_env": "FACEBOOK_OAUTH_APP_ID",
        "client_secret_env": "FACEBOOK_OAUTH_APP_SECRET",
        "authorize_url": "https://www.facebook.com/v18.0/dialog/oauth",
        "access_token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "userinfo_url": "https://graph.facebook.com/me",
        "scope": ["public_profile", "email"],
    },
    "linkedin": {
        "client_id_env": "LINKEDIN_OAUTH_CLIENT_ID",
        "client_secret_env": "LINKEDIN_OAUTH_CLIENT_SECRET",
        "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
        "access_token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "userinfo_url": "https://api.linkedin.com/v2/me",
        "scope": ["profile", "email"],
    },
}


class OAuthService:
    """Service for OAuth2 authentication flows."""

    def __init__(self, app=None):
        self.oauth = OAuth()
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize OAuth with Flask app."""
        self.oauth.init_app(app)
        
        # Register remote applications for each provider
        for provider, config in OAUTH_CONFIGS.items():
            client_id = app.config.get(config["client_id_env"])
            client_secret = app.config.get(config["client_secret_env"])
            
            if not client_id or not client_secret:
                logger.warning(f"OAuth provider '{provider}' not configured (missing credentials)")
                continue
            
            self.oauth.register(
                name=provider,
                client_id=client_id,
                client_secret=client_secret,
                server_metadata_url=f"https://accounts.google.com/.well-known/openid-configuration"
                if provider == "google" else None,
                authorize_url=config["authorize_url"],
                access_token_url=config["access_token_url"],
                userinfo_endpoint=config["userinfo_url"],
                client_kwargs={"scope": " ".join(config["scope"])},
            )

    def get_authorization_url(self, provider: str, redirect_uri: str) -> str:
        """Generate authorization URL for OAuth provider."""
        config = OAUTH_CONFIGS.get(provider)
        if not config:
            raise ValueError(f"Unknown OAuth provider: {provider}")
        
        params = {
            "client_id": f"{{{config['client_id_env']}}}",
            "redirect_uri": redirect_uri,
            "scope": "+".join(config["scope"]),
            "response_type": "code",
        }
        
        # Provider-specific parameters
        if provider == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"
        elif provider == "facebook":
            params["auth_type"] = "rerequest"
        elif provider == "linkedin":
            params["state"] = "linkedin"
        
        return f"{config['authorize_url']}?{urlencode(params)}"

    def get_user_info(self, provider: str, access_token: str) -> dict:
        """Fetch user info from OAuth provider using access token."""
        config = OAUTH_CONFIGS.get(provider)
        if not config:
            raise ValueError(f"Unknown OAuth provider: {provider}")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Provider-specific requests
        if provider == "facebook":
            params = {"fields": "id,name,email,picture.type(large)"}
            response = requests.get(
                config["userinfo_url"],
                params=params,
                headers=headers,
                timeout=10
            )
            if response.ok:
                data = response.json()
                return {
                    "id": data.get("id"),
                    "email": data.get("email"),
                    "name": data.get("name"),
                    "picture_url": data.get("picture", {}).get("data", {}).get("url"),
                }
        elif provider == "linkedin":
            # For LinkedIn, need separate requests for profile and email
            profile_response = requests.get(
                config["userinfo_url"],
                headers=headers,
                timeout=10
            )
            email_response = requests.get(
                "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
                headers=headers,
                timeout=10
            )
            if profile_response.ok and email_response.ok:
                profile = profile_response.json()
                email_data = email_response.json()
                
                name = None
                if "localizedFirstName" in profile and "localizedLastName" in profile:
                    name = f"{profile['localizedFirstName']} {profile['localizedLastName']}"
                
                email = None
                if "elements" in email_data and len(email_data["elements"]) > 0:
                    email = email_data["elements"][0].get("handle~", {}).get("emailAddress")
                
                return {
                    "id": profile.get("id"),
                    "email": email,
                    "name": name,
                    "picture_url": profile.get("profilePicture", {}).get("displayImage"),
                }
        else:  # google
            response = requests.get(config["userinfo_url"], headers=headers, timeout=10)
            if response.ok:
                data = response.json()
                return {
                    "id": data.get("id"),
                    "email": data.get("email"),
                    "name": data.get("name"),
                    "picture_url": data.get("picture"),
                }
        
        return {}

    def find_or_create_user(
        self,
        db,
        provider: str,
        provider_user_info: dict,
        tenant_id: str | None = None,
    ) -> tuple[User, bool]:
        """
        Find existing user by OAuth provider or create new user.
        
        Returns: (user, created) tuple
        """
        provider_id = provider_user_info.get("id")
        email = provider_user_info.get("email")
        name = provider_user_info.get("name", "")
        picture_url = provider_user_info.get("picture_url")
        
        if not provider_id:
            raise ValueError(f"Provider {provider} did not return user ID")
        
        # Try to find existing OAuth link
        session = db.session()
        try:
            oauth_provider = session.query(OAuthProvider).filter(
                OAuthProvider.provider == provider,
                OAuthProvider.provider_user_id == provider_id,
            ).one_or_none()

            if oauth_provider is not None:
                oauth_provider.email = email
                oauth_provider.name = name
                oauth_provider.picture_url = picture_url
                oauth_provider.updated_at = datetime.now(timezone.utc)
                session.commit()
                return oauth_provider.user, False

            user = None
            if email:
                user = session.query(User).filter(User.email == email).one_or_none()

            if user is None:
                if not tenant_id:
                    tenant = Tenant(name=email or name or "New User", is_active=True)
                    session.add(tenant)
                    session.flush()
                    tenant_id = tenant.id
                    session.add(BotConfig(tenant_id=tenant.id))
                    session.add(
                        UsageCounter(
                            tenant_id=tenant.id,
                            period_start=utcnow(),
                            conversations_used=0,
                            is_blocked=False,
                        )
                    )
                    session.add(ConnectionState(tenant_id=tenant.id, status="disconnected"))

                user = User(
                    id=new_uuid(),
                    tenant_id=tenant_id,
                    email=email or f"{provider}_{provider_id}@oauth.local",
                    password_hash="",
                    is_admin=True,
                )
                session.add(user)
                session.flush()

            oauth_provider = OAuthProvider(
                id=new_uuid(),
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_id,
                email=email,
                name=name,
                picture_url=picture_url,
            )
            session.add(oauth_provider)
            session.commit()
            return user, True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Global OAuth service instance
oauth_service = OAuthService()
