"""FastAPI integration for Civic Auth."""

from typing import Optional

from civic_auth import AuthConfig, BaseUser, CivicAuth, CookieSettings, CookieStorage

try:
    from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
    from fastapi.responses import RedirectResponse
except ImportError as e:
    raise ImportError(
        "FastAPI is not installed. Install it with: pip install civic-auth[fastapi]"
    ) from e


class FastAPICookieStorage(CookieStorage):
    """FastAPI-specific cookie storage implementation."""

    def __init__(
        self, request: Request, response: Response, settings: Optional[CookieSettings] = None
    ):
        # Default to secure=False for local development
        default_settings = {"secure": False}
        if settings:
            default_settings.update(settings)
        super().__init__(default_settings)
        self._request = request
        self._response = response

    async def get(self, key: str) -> Optional[str]:
        """Get a value from FastAPI cookies."""
        return self._request.cookies.get(key)

    async def set(self, key: str, value: str) -> None:
        """Set a cookie value in FastAPI response."""
        self._response.set_cookie(
            key=key,
            value=value,
            max_age=self.settings.get("max_age"),
            secure=self.settings.get("secure", True),
            httponly=self.settings.get("http_only", True),
            samesite=self.settings.get("same_site", "lax"),
            path=self.settings.get("path", "/"),
            domain=self.settings.get("domain"),
        )

    async def delete(self, key: str) -> None:
        """Delete a cookie from FastAPI response."""
        self._response.delete_cookie(key=key, path=self.settings.get("path", "/"))

    async def clear(self) -> None:
        """Clear all cookies."""
        for key in self._request.cookies:
            await self.delete(key)


class CivicAuthDependency:
    """FastAPI dependency for Civic Auth."""

    def __init__(self, config: AuthConfig):
        self.config = config

    async def __call__(self, request: Request, response: Response) -> CivicAuth:
        """Create CivicAuth instance for each request."""
        storage = FastAPICookieStorage(request, response)
        return CivicAuth(storage, self.config)


def create_civic_auth_dependency(config: AuthConfig) -> CivicAuthDependency:
    """Create a FastAPI dependency for Civic Auth."""
    return CivicAuthDependency(config)


def create_auth_dependencies(config: AuthConfig):
    """Create auth dependencies with the given config."""
    civic_auth_dep = CivicAuthDependency(config)

    async def get_current_user(civic_auth: CivicAuth = Depends(civic_auth_dep)) -> BaseUser:
        """FastAPI dependency to get current authenticated user."""
        user = await civic_auth.get_user()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        return user

    async def require_auth(civic_auth: CivicAuth = Depends(civic_auth_dep)) -> None:
        """FastAPI dependency to require authentication."""
        if not await civic_auth.is_logged_in():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
            )

    return civic_auth_dep, get_current_user, require_auth


def create_auth_router(config: AuthConfig) -> APIRouter:
    """Create a FastAPI router with auth endpoints."""
    router = APIRouter()
    civic_auth_dep, get_current_user, require_auth = create_auth_dependencies(config)

    @router.get("/auth/login")
    async def login(request: Request):
        """Redirect to Civic Auth login."""
        # Create redirect response with a placeholder URL
        redirect_response = RedirectResponse(url="/", status_code=302)

        # Create storage with the redirect response
        storage = FastAPICookieStorage(request, redirect_response)
        civic_auth = CivicAuth(storage, config)

        # Build login URL - this will set cookies on redirect_response
        url = await civic_auth.build_login_url()

        # Update the redirect URL
        redirect_response.headers["location"] = url

        return redirect_response

    @router.get("/auth/callback")
    async def callback(code: str, state: str, request: Request):
        """Handle OAuth callback."""
        try:
            # Create a redirect response first
            redirect_response = RedirectResponse(url="/", status_code=302)

            # Create storage with the redirect response
            storage = FastAPICookieStorage(request, redirect_response)
            civic_auth = CivicAuth(storage, config)

            # This will set cookies on the redirect_response
            await civic_auth.resolve_oauth_access_code(code, state)

            return redirect_response
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @router.get("/auth/logout")
    async def logout(request: Request):
        """Logout and redirect."""
        # Create redirect response with a placeholder URL
        redirect_response = RedirectResponse(url="/", status_code=302)

        # Create storage with the redirect response
        storage = FastAPICookieStorage(request, redirect_response)
        civic_auth = CivicAuth(storage, config)

        # Build logout URL - this will clear cookies
        url = await civic_auth.build_logout_redirect_url()

        # Update the redirect URL
        redirect_response.headers["location"] = url

        return redirect_response

    @router.get("/auth/user")
    async def get_user(user: BaseUser = Depends(get_current_user)):
        """Get current user info."""
        return user

    @router.get("/auth/logoutcallback")
    async def logout_callback(state: Optional[str] = None):
        """Handle logout callback from Civic Auth."""
        # Simply redirect to home after logout is complete
        return RedirectResponse(url="/", status_code=302)

    return router
