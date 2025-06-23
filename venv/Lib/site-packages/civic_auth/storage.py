"""Storage implementations for Civic Auth."""

from abc import ABC, abstractmethod
from typing import Optional

from .types import CookieSettings


class AuthStorage(ABC):
    """Abstract base class for authentication storage."""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Get a value from storage."""
        pass

    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        """Set a value in storage."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a value from storage."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all values from storage."""
        pass


class CookieStorage(AuthStorage):
    """Abstract cookie storage implementation."""

    def __init__(self, settings: Optional[CookieSettings] = None):
        """Initialize cookie storage with settings."""
        self.settings: CookieSettings = {
            "secure": True,
            "http_only": True,
            "same_site": "lax",
            "path": "/",
            "max_age": 60 * 15,  # 15 minutes
            **(settings or {}),
        }
