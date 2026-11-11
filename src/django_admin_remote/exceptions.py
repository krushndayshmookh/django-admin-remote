"""Exceptions raised by django-admin-remote."""
from __future__ import annotations


class AdminError(RuntimeError):
    """Base class for every error this package raises on purpose."""


class NotLoggedIn(AdminError):
    """The site asked for a login: no session, an expired session, or rejected credentials."""


class FormError(AdminError):
    """A form could not be filled in or the admin rejected it with validation errors."""


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
