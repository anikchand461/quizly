"""Core CivicAuth implementation."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .exceptions import AuthenticationError, ConfigurationError
from .storage import AuthStorage
from .types import AuthConfig, BaseUser, Tokens
from .utils import (
    build_url,
    generate_pkce_challenge,
    generate_random_string,
    is_token_expired,
    parse_jwt_without_validation,
)


class CivicAuth:
    """Main CivicAuth class for server-side authentication."""

    # Storage keys
    PKCE_VERIFIER_KEY = "civic_auth_pkce_verifier"
    STATE_KEY = "civic_auth_state"
    NONCE_KEY = "civic_auth_nonce"
    ID_TOKEN_KEY = "civic_auth_id_token"
    ACCESS_TOKEN_KEY = "civic_auth_access_token"
    REFRESH_TOKEN_KEY = "civic_auth_refresh_token"
    TOKEN_EXPIRY_KEY = "civic_auth_token_expiry"

    # Default OAuth server
    DEFAULT_OAUTH_SERVER = "https://auth.civic.com/oauth"

    def __init__(self, storage: AuthStorage, config: AuthConfig):
        """Initialize CivicAuth with storage and configuration."""
        self.storage = storage
        self.config = self._validate_config(config)
        self.oauth_server = config.get("oauth_server") or self.DEFAULT_OAUTH_SERVER
        self.client = httpx.AsyncClient()
        self._endpoints: Optional[Dict[str, str]] = None  # Will be populated by OIDC discovery
        self._discovery_url = f"{self.oauth_server}/.well-known/openid-configuration"

    def _validate_config(self, config: AuthConfig) -> AuthConfig:
        """Validate required configuration."""
        if not config.get("client_id"):
            raise ConfigurationError("client_id is required")
        if not config.get("redirect_url"):
            raise ConfigurationError("redirect_url is required")
        return config

    async def _discover_endpoints(self) -> Dict[str, str]:
        """Discover OAuth endpoints using OIDC discovery."""
        if self._endpoints:
            return self._endpoints

        try:
            response = await self.client.get(self._discovery_url)
            if response.status_code == 200:
                discovery = response.json()
                self._endpoints = {
                    "authorization_endpoint": discovery.get("authorization_endpoint"),
                    "token_endpoint": discovery.get("token_endpoint"),
                    "end_session_endpoint": discovery.get("end_session_endpoint"),
                    "issuer": discovery.get("issuer"),
                }
                return self._endpoints
        except Exception:
            pass

        # Fallback to default endpoints if discovery fails
        self._endpoints = {
            "authorization_endpoint": f"{self.oauth_server}/authorize",
            "token_endpoint": f"{self.oauth_server}/token",
            "end_session_endpoint": f"{self.oauth_server}/logout",
            "issuer": self.oauth_server,
        }
        return self._endpoints

    async def get_user(self) -> Optional[BaseUser]:
        """Get the authenticated user from stored tokens."""
        id_token = await self.storage.get(self.ID_TOKEN_KEY)
        if not id_token:
            return None

        # Check if token is expired
        if is_token_expired(id_token):
            # Try to refresh tokens
            refresh_token = await self.storage.get(self.REFRESH_TOKEN_KEY)
            if refresh_token:
                try:
                    await self.refresh_tokens()
                    id_token = await self.storage.get(self.ID_TOKEN_KEY)
                except Exception:
                    return None
            else:
                return None

        # Parse user info from ID token
        assert id_token is not None  # We've already checked this above
        claims = parse_jwt_without_validation(id_token)
        if not claims:
            return None

        # Map JWT claims to BaseUser
        user: BaseUser = {
            "id": claims.get("sub", ""),
            "email": claims.get("email"),
            "username": claims.get("username"),
            "name": claims.get("name"),
            "given_name": claims.get("given_name"),
            "family_name": claims.get("family_name"),
            "picture": claims.get("picture"),
        }

        # Convert updated_at if present
        if "updated_at" in claims:
            try:
                user["updated_at"] = datetime.fromtimestamp(claims["updated_at"], tz=timezone.utc)
            except (ValueError, TypeError):
                pass

        return user

    async def get_tokens(self) -> Optional[Tokens]:
        """Get stored OAuth tokens if valid."""
        access_token = await self.storage.get(self.ACCESS_TOKEN_KEY)
        id_token = await self.storage.get(self.ID_TOKEN_KEY)

        if not access_token or not id_token:
            return None

        # Check if tokens are expired
        if is_token_expired(id_token):
            refresh_token = await self.storage.get(self.REFRESH_TOKEN_KEY)
            if refresh_token:
                try:
                    return await self.refresh_tokens()
                except Exception:
                    return None
            else:
                return None

        tokens: Tokens = {
            "access_token": access_token,
            "id_token": id_token,
            "token_type": "Bearer",
        }

        refresh_token = await self.storage.get(self.REFRESH_TOKEN_KEY)
        if refresh_token:
            tokens["refresh_token"] = refresh_token

        return tokens

    async def is_logged_in(self) -> bool:
        """Check if user is currently logged in."""
        user = await self.get_user()
        return user is not None

    async def build_login_url(self, scopes: Optional[List[str]] = None) -> str:
        """Build the OAuth authorization URL."""
        # Generate and store PKCE challenge
        pkce = generate_pkce_challenge()
        await self.storage.set(self.PKCE_VERIFIER_KEY, pkce["code_verifier"])

        # Generate and store state
        state = generate_random_string(32)
        await self.storage.set(self.STATE_KEY, state)

        # Generate and store nonce
        nonce = generate_random_string(32)
        await self.storage.set(self.NONCE_KEY, nonce)

        # Get authorization endpoint
        endpoints = await self._discover_endpoints()

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": self.config["client_id"],
            "redirect_uri": self.config["redirect_url"],
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce["code_challenge"],
            "code_challenge_method": pkce["code_challenge_method"],
            "scope": " ".join(scopes or ["openid", "email", "profile"]),
        }

        return build_url(endpoints["authorization_endpoint"], "", params)

    async def resolve_oauth_access_code(self, code: str, state: str) -> Tokens:
        """Exchange authorization code for tokens."""
        # Verify state
        stored_state = await self.storage.get(self.STATE_KEY)
        if not stored_state or stored_state != state:
            raise AuthenticationError("Invalid state parameter")

        # Get PKCE verifier
        code_verifier = await self.storage.get(self.PKCE_VERIFIER_KEY)
        if not code_verifier:
            raise AuthenticationError("PKCE verifier not found")

        # Get token endpoint
        endpoints = await self._discover_endpoints()

        # Exchange code for tokens
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config["redirect_url"],
            "client_id": self.config["client_id"],
            "code_verifier": code_verifier,
        }

        response = await self.client.post(endpoints["token_endpoint"], data=data)
        if response.status_code != 200:
            raise AuthenticationError(f"Token exchange failed: {response.text}")

        tokens = response.json()

        # Store tokens
        await self._store_tokens(tokens)

        # Clean up temporary storage
        await self.storage.delete(self.STATE_KEY)
        await self.storage.delete(self.NONCE_KEY)
        await self.storage.delete(self.PKCE_VERIFIER_KEY)

        return Tokens(**tokens)

    async def refresh_tokens(self) -> Tokens:
        """Refresh access tokens using refresh token."""
        refresh_token = await self.storage.get(self.REFRESH_TOKEN_KEY)
        if not refresh_token:
            raise AuthenticationError("No refresh token available")

        # Get token endpoint
        endpoints = await self._discover_endpoints()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config["client_id"],
        }

        response = await self.client.post(endpoints["token_endpoint"], data=data)
        if response.status_code != 200:
            raise AuthenticationError(f"Token refresh failed: {response.text}")

        tokens = response.json()
        await self._store_tokens(tokens)

        return Tokens(**tokens)

    async def build_logout_redirect_url(self) -> str:
        """Build the logout URL."""
        id_token = await self.storage.get(self.ID_TOKEN_KEY)

        # Get logout endpoint
        endpoints = await self._discover_endpoints()

        params = {
            "post_logout_redirect_uri": self.config.get("post_logout_redirect_url"),
            "id_token_hint": id_token,
        }

        # Clear tokens
        await self.clear_tokens()

        return build_url(endpoints["end_session_endpoint"], "", params)

    async def clear_tokens(self) -> None:
        """Clear all stored tokens."""
        await self.storage.delete(self.ID_TOKEN_KEY)
        await self.storage.delete(self.ACCESS_TOKEN_KEY)
        await self.storage.delete(self.REFRESH_TOKEN_KEY)
        await self.storage.delete(self.TOKEN_EXPIRY_KEY)

    async def _store_tokens(self, tokens: Dict[str, Any]) -> None:
        """Store tokens in storage."""
        if "id_token" in tokens:
            await self.storage.set(self.ID_TOKEN_KEY, tokens["id_token"])

        if "access_token" in tokens:
            await self.storage.set(self.ACCESS_TOKEN_KEY, tokens["access_token"])

        if "refresh_token" in tokens:
            await self.storage.set(self.REFRESH_TOKEN_KEY, tokens["refresh_token"])

        # Store expiry time
        if "expires_in" in tokens:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
            await self.storage.set(self.TOKEN_EXPIRY_KEY, expiry.isoformat())

    async def __aenter__(self) -> "CivicAuth":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - close HTTP client."""
        await self.client.aclose()
