"""Utility functions for Civic Auth."""

import base64
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import jwt


def generate_random_string(length: int = 32) -> str:
    """Generate a cryptographically secure random string."""
    return secrets.token_urlsafe(length)[:length]


def generate_pkce_challenge() -> Dict[str, str]:
    """Generate PKCE challenge and verifier."""
    code_verifier = generate_random_string(128)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    return {
        "code_verifier": code_verifier,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }


def build_url(base_url: str, path: str = "", params: Optional[Dict[str, Any]] = None) -> str:
    """Build a URL with optional path and query parameters."""
    url = base_url.rstrip("/")
    if path:
        url += "/" + path.lstrip("/")
    if params:
        # Filter out None values
        filtered_params = {k: v for k, v in params.items() if v is not None}
        if filtered_params:
            url += "?" + urlencode(filtered_params)
    return url


def parse_jwt_without_validation(token: str) -> Dict[str, Any]:
    """Parse JWT without validation to extract claims."""
    try:
        # Decode without verification to get claims
        decoded: Dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
        return decoded
    except Exception:
        return {}


def get_token_expiry(token: str) -> Optional[datetime]:
    """Extract expiry time from JWT token."""
    claims = parse_jwt_without_validation(token)
    exp = claims.get("exp")
    if exp:
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    return None


def is_token_expired(token: str) -> bool:
    """Check if a JWT token is expired."""
    expiry = get_token_expiry(token)
    if not expiry:
        return True
    return datetime.now(timezone.utc) > expiry
