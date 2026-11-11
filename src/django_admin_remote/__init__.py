"""Drive a remote Django admin site over HTTP by parsing its stock HTML.

Nothing is installed on the server. See the README for a quickstart.
"""
__version__ = "0.1.0"

from .client import AdminClient
from .dates import parse_admin_datetime
from .exceptions import AdminError, AdminHTTPError, FormError, NotLoggedIn
from .form import AdminForm
from .parse import field_value, parse_change_form, parse_changelist

__all__ = [
    "AdminClient",
    "AdminForm",
    "AdminError",
    "AdminHTTPError",
    "FormError",
    "NotLoggedIn",
    "field_value",
    "parse_admin_datetime",
    "parse_change_form",
    "parse_changelist",
    "__version__",
]
