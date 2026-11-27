"""Exceptions raised by django-admin-remote."""
from __future__ import annotations


class AdminError(RuntimeError):
    """Base class for every error this package raises on purpose."""


class NotLoggedIn(AdminError):
    """The site asked for a login: no session, an expired session, or rejected credentials."""


class FormError(AdminError):
    """A form could not be filled in or the admin rejected it with validation errors."""


class AdminBannerError(FormError):
    """The admin answered 200 with an error or warning banner (or no success message) instead of redirecting.

    A FormError subclass, so ``except FormError`` still catches it.

    Attributes:
        errors: texts of the error banners (message list at the error level, errornote, errorlist).
        warnings: texts of the warning banners.
        success: texts of the success messages the page showed.
    """

    def __init__(self, message: str, errors=(), warnings=(), success=()) -> None:
        super().__init__(message)
        self.errors = list(errors)
        self.warnings = list(warnings)
        self.success = list(success)


class AdminHTTPError(AdminError):
    """The site answered with an HTTP error status.

    Attributes:
        status_code: the HTTP status.
        url: the URL that was requested.
    """

    def __init__(self, message: str, status_code: int, url: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
