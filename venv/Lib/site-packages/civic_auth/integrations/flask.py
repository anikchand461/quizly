"""Flask integration for Civic Auth."""

from functools import wraps
from typing import Any, Dict, Optional

from civic_auth import AuthConfig, BaseUser, CivicAuth, CookieSettings, CookieStorage

try:
    from flask import Blueprint, Request, g, make_response, redirect, request
    from flask.wrappers import Response as FlaskResponse
except ImportError as e:
    raise ImportError(
        "Flask is not installed. Install it with: pip install civic-auth[flask]"
    ) from e


class FlaskCookieStorage(CookieStorage):
    """Flask-specific cookie storage implementation."""

    def __init__(self, request: Request, settings: Optional[CookieSettings] = None):
        # Default to secure=False for local development
        default_settings = {"secure": False}
        if settings:
            default_settings.update(settings)
        super().__init__(default_settings)
        self._request = request
        self._cookies_to_set: Dict[str, tuple[str, Dict[str, Any]]] = {}
        self._cookies_to_delete: set[str] = set()

    async def get(self, key: str) -> Optional[str]:
        """Get a value from Flask cookies."""
        return self._request.cookies.get(key)

    async def set(self, key: str, value: str) -> None:
        """Set a cookie value (queued until response)."""
        self._cookies_to_set[key] = (value, self.settings.copy())
        self._cookies_to_delete.discard(key)

    async def delete(self, key: str) -> None:
        """Delete a cookie (queued until response)."""
        self._cookies_to_delete.add(key)
        self._cookies_to_set.pop(key, None)

    async def clear(self) -> None:
        """Clear all cookies."""
        for key in self._request.cookies:
            await self.delete(key)

    def apply_to_response(self, response: FlaskResponse) -> FlaskResponse:
        """Apply queued cookie operations to Flask response."""
        # Set cookies
        for key, (value, settings) in self._cookies_to_set.items():
            response.set_cookie(
                key,
                value,
                max_age=settings.get("max_age"),
                secure=settings.get("secure", True),
                httponly=settings.get("http_only", True),
                samesite=settings.get("same_site", "lax"),
                path=settings.get("path", "/"),
                domain=settings.get("domain"),
            )

        # Delete cookies
        for key in self._cookies_to_delete:
            response.delete_cookie(key)

        return response


def civic_auth_required(f):
    """Decorator to require authentication for Flask routes."""

    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if not hasattr(g, "civic_auth"):
            return make_response("CivicAuth not initialized", 500)

        if not await g.civic_auth.is_logged_in():
            return make_response("Unauthorized", 401)

        g.civic_user = await g.civic_auth.get_user()
        return await f(*args, **kwargs)

    return decorated_function


def init_civic_auth(app, config: AuthConfig):
    """Initialize Civic Auth for Flask app."""

    @app.before_request
    async def before_request():
        """Create CivicAuth instance for each request."""
        storage = FlaskCookieStorage(request)
        g.civic_auth = CivicAuth(storage, config)
        g.civic_storage = storage

    @app.after_request
    async def after_request(response):
        """Apply cookie changes to response."""
        if hasattr(g, "civic_storage"):
            g.civic_storage.apply_to_response(response)

        # Close the CivicAuth client
        if hasattr(g, "civic_auth"):
            try:
                await g.civic_auth.client.aclose()
            except RuntimeError:
                # Event loop might be closed, ignore
                pass

        return response

    return app


def create_auth_blueprint(config: AuthConfig) -> Blueprint:
    """Create a Flask blueprint with auth endpoints."""
    auth_bp = Blueprint("civic_auth", __name__)

    @auth_bp.route("/auth/login")
    async def login():
        """Redirect to Civic Auth login."""
        auth = g.civic_auth
        url = await auth.build_login_url()

        response = redirect(url)
        g.civic_storage.apply_to_response(response)
        return response

    @auth_bp.route("/auth/callback")
    async def callback():
        """Handle OAuth callback."""
        code = request.args.get("code")
        state = request.args.get("state")

        if not code or not state:
            return make_response("Missing code or state parameter", 400)

        auth = g.civic_auth
        try:
            await auth.resolve_oauth_access_code(code, state)
            response = redirect("/")
            g.civic_storage.apply_to_response(response)
            return response
        except Exception as e:
            return make_response(f"Auth failed: {str(e)}", 400)

    @auth_bp.route("/auth/logout")
    async def logout():
        """Logout and redirect."""
        auth = g.civic_auth
        url = await auth.build_logout_redirect_url()

        response = redirect(url)
        g.civic_storage.apply_to_response(response)
        return response

    @auth_bp.route("/auth/user")
    @civic_auth_required
    async def get_user():
        """Get current user info."""
        return g.civic_user

    @auth_bp.route("/auth/logoutcallback")
    async def logout_callback():
        """Handle logout callback from Civic Auth."""
        # Simply redirect to home after logout is complete
        return redirect("/")

    return auth_bp


# Convenience functions for Flask routes
async def get_civic_auth() -> CivicAuth:
    """Get the current CivicAuth instance."""
    if not hasattr(g, "civic_auth"):
        raise RuntimeError("CivicAuth not initialized. Call init_civic_auth first.")
    return g.civic_auth


async def get_civic_user() -> Optional[BaseUser]:
    """Get the current authenticated user."""
    auth = await get_civic_auth()
    return await auth.get_user()
