"""Exception classes for Civic Auth."""


class CivicAuthError(Exception):
    """Base exception for Civic Auth errors."""

    pass


class ConfigurationError(CivicAuthError):
    """Raised when configuration is invalid."""

    pass


class AuthenticationError(CivicAuthError):
    """Raised when authentication fails."""

    pass


class TokenValidationError(CivicAuthError):
    """Raised when token validation fails."""

    pass


class StorageError(CivicAuthError):
    """Raised when storage operations fail."""

    pass
