"""Type definitions for Civic Auth Python SDK."""

from datetime import datetime
from typing import List, Optional, TypedDict


class BaseUser(TypedDict, total=False):
    """Base user type containing common user properties."""

    id: str
    email: Optional[str]
    username: Optional[str]
    name: Optional[str]
    given_name: Optional[str]
    family_name: Optional[str]
    picture: Optional[str]
    updated_at: Optional[datetime]


class Tokens(TypedDict, total=False):
    """OAuth tokens."""

    access_token: str
    id_token: str
    refresh_token: Optional[str]
    token_type: str
    expires_in: Optional[int]
    scope: Optional[str]


class AuthConfig(TypedDict, total=False):
    """Configuration for Civic Auth."""

    client_id: str
    redirect_url: str
    oauth_server: Optional[str]
    challenge_url: Optional[str]
    refresh_url: Optional[str]
    post_logout_redirect_url: Optional[str]
    scopes: Optional[List[str]]


class PKCEChallenge(TypedDict):
    """PKCE challenge data."""

    code_verifier: str
    code_challenge: str
    code_challenge_method: str


class CookieSettings(TypedDict, total=False):
    """Cookie configuration settings."""

    secure: bool
    http_only: bool
    same_site: str
    max_age: Optional[int]
    path: str
    domain: Optional[str]
