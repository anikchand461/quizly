"""Django integration for Civic Auth."""

import asyncio
from functools import wraps
from typing import Any, Dict, Optional

from civic_auth import AuthConfig, BaseUser, CivicAuth, CookieSettings, CookieStorage

try:
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured
    from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
    from django.urls import path
except ImportError as e:
    raise ImportError(
        "Django is not installed. Install it with: pip install civic-auth[django]"
    ) from e


class DjangoCookieStorage(CookieStorage):
    """Django-specific cookie storage implementation."""

    def __init__(self, request: HttpRequest, settings: Optional[CookieSettings] = None):
        # Default to secure=False for local development
        default_settings = {"secure": False}
        if settings:
            default_settings.update(settings)
        super().__init__(default_settings)
        self._request = request
        self._cookies_to_set: Dict[str, tuple[str, Dict[str, Any]]] = {}
        self._cookies_to_delete: set[str] = set()

    async def get(self, key: str) -> Optional[str]:
        """Get a value from Django cookies."""
        return self._request.COOKIES.get(key)

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
        for key in self._request.COOKIES:
            await self.delete(key)

    def apply_to_response(self, response: HttpResponse) -> HttpResponse:
        """Apply queued cookie operations to Django response."""
        # Set cookies
        for key, (value, settings) in self._cookies_to_set.items():
            response.set_cookie(
                key=key,
                value=value,
                max_age=settings.get("max_age"),
                secure=settings.get("secure", True),
                httponly=settings.get("http_only", True),
                samesite=settings.get("same_site", "lax"),
                path=settings.get("path", "/"),
                domain=settings.get("domain"),
            )

        # Delete cookies
        for key in self._cookies_to_delete:
            response.delete_cookie(key, path=self.settings.get("path", "/"))

        return response


class CivicAuthMiddleware:
    """Django middleware for Civic Auth."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.config = self._get_config()

    def _get_config(self) -> AuthConfig:
        """Get Civic Auth config from Django settings."""
        if not hasattr(settings, "CIVIC_AUTH"):
            raise ImproperlyConfigured(
                "CIVIC_AUTH configuration not found in settings. "
                "Please add CIVIC_AUTH dictionary to your Django settings."
            )

        config = settings.CIVIC_AUTH
        required_fields = ["client_id", "redirect_url"]

        for field in required_fields:
            if field not in config:
                raise ImproperlyConfigured(f"CIVIC_AUTH['{field}'] is required in Django settings.")

        return config

    def __call__(self, request):
        # Create storage and auth instances
        request.civic_storage = DjangoCookieStorage(request)
        request.civic_auth = CivicAuth(request.civic_storage, self.config)

        # Get response
        response = self.get_response(request)

        # Apply cookies to response
        if hasattr(request, "civic_storage"):
            request.civic_storage.apply_to_response(response)

        # Clean up
        if hasattr(request, "civic_auth"):
            # Run async cleanup in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(request.civic_auth.client.aclose())
            except RuntimeError:
                # Event loop might be closed, ignore
                pass
            finally:
                loop.close()

        return response


def civic_auth_required(view_func):
    """Decorator to require authentication for Django views."""

    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not hasattr(request, "civic_auth"):
            raise ImproperlyConfigured(
                "CivicAuthMiddleware not installed. "
                "Add 'civic_auth.integrations.django.CivicAuthMiddleware' to MIDDLEWARE."
            )

        # Check authentication in async context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            is_logged_in = loop.run_until_complete(request.civic_auth.is_logged_in())
            if not is_logged_in:
                return HttpResponse("Unauthorized", status=401)

            # Get user info
            request.civic_user = loop.run_until_complete(request.civic_auth.get_user())
        finally:
            loop.close()

        return view_func(request, *args, **kwargs)

    return wrapped_view


def civic_auth_required_async(view_func):
    """Decorator to require authentication for async Django views."""

    @wraps(view_func)
    async def wrapped_view(request, *args, **kwargs):
        if not hasattr(request, "civic_auth"):
            raise ImproperlyConfigured(
                "CivicAuthMiddleware not installed. "
                "Add 'civic_auth.integrations.django.CivicAuthMiddleware' to MIDDLEWARE."
            )

        if not await request.civic_auth.is_logged_in():
            return HttpResponse("Unauthorized", status=401)

        request.civic_user = await request.civic_auth.get_user()
        return await view_func(request, *args, **kwargs)

    return wrapped_view


# Helper functions for views
def run_async(coro):
    """Run async coroutine in sync Django view."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def get_civic_auth(request) -> CivicAuth:
    """Get CivicAuth instance from request."""
    if not hasattr(request, "civic_auth"):
        raise ImproperlyConfigured(
            "CivicAuthMiddleware not installed. "
            "Add 'civic_auth.integrations.django.CivicAuthMiddleware' to MIDDLEWARE."
        )
    return request.civic_auth


def get_civic_user_sync(request) -> Optional[BaseUser]:
    """Get current user synchronously."""
    auth = get_civic_auth(request)
    return run_async(auth.get_user())


async def get_civic_user_async(request) -> Optional[BaseUser]:
    """Get current user asynchronously."""
    auth = get_civic_auth(request)
    return await auth.get_user()


# Auth views for Django
def login(request):
    """Redirect to Civic Auth login."""
    auth = get_civic_auth(request)
    url = run_async(auth.build_login_url())

    # Create redirect response and apply cookies
    response = HttpResponseRedirect(url)
    if hasattr(request, "civic_storage"):
        request.civic_storage.apply_to_response(response)

    return response


def callback(request):
    """Handle OAuth callback."""
    code = request.GET.get("code")
    state = request.GET.get("state")

    if not code or not state:
        return HttpResponse("Missing code or state parameter", status=400)

    auth = get_civic_auth(request)
    try:
        run_async(auth.resolve_oauth_access_code(code, state))

        # Create redirect response and apply cookies
        response = HttpResponseRedirect("/admin/hello")
        if hasattr(request, "civic_storage"):
            request.civic_storage.apply_to_response(response)

        return response
    except Exception as e:
        return HttpResponse(f"Auth failed: {str(e)}", status=400)


def logout(request):
    """Logout and redirect."""
    auth = get_civic_auth(request)
    url = run_async(auth.build_logout_redirect_url())

    # Create redirect response and apply cookies
    response = HttpResponseRedirect(url)
    if hasattr(request, "civic_storage"):
        request.civic_storage.apply_to_response(response)

    return response


def logout_callback(request):
    """Handle logout callback from Civic Auth."""
    # Simply redirect to home after logout is complete
    return HttpResponseRedirect("/")


@civic_auth_required
def get_user(request):
    """Get current user info."""
    user = request.civic_user
    return JsonResponse(
        {"id": user.id, "email": user.email, "name": user.name, "picture": user.picture}
    )


# URL patterns for auth endpoints
def get_auth_urls():
    """Get Django URL patterns for auth endpoints."""
    return [
        path("auth/login/", login, name="civic_auth_login"),
        path("auth/callback/", callback, name="civic_auth_callback"),
        path("auth/logout/", logout, name="civic_auth_logout"),
        path("auth/logoutcallback/", logout_callback, name="civic_auth_logout_callback"),
        path("auth/user/", get_user, name="civic_auth_user"),
    ]
