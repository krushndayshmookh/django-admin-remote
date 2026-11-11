"""HTTP client for a remote Django admin site."""
from __future__ import annotations

import json
import os
import time
from datetime import tzinfo
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urljoin, urlparse

import requests

from . import __version__
from .dates import parse_admin_datetime
from .exceptions import AdminHTTPError, NotLoggedIn
from .form import AdminForm
from .parse import parse_change_form, parse_changelist, soup

_REDIRECTS = (301, 302, 303, 307, 308)
FormData = Union[Mapping[str, Any], Sequence[Tuple[str, Any]]]


class AdminClient:
    """A polite client for one Django admin site.

    It waits ``delay`` seconds between requests, follows redirects itself so a bounce to
    the login page is noticed, retries a GET on a 5xx answer but never a POST, and refuses
    to talk to any host other than ``base_url``.

    Authentication is either existing session cookies (``cookies`` or ``storage_state``,
    the way to go for sites behind SSO) or :meth:`login` with a username and password.

    Args:
        base_url: scheme and host of the site, for example ``https://admin.example.com``.
            Paths given to the methods are appended to it.
        cookies: session cookies as a ``{name: value}`` dict or a cookie jar.
        storage_state: a Playwright ``storage_state`` (path to the JSON file, or the dict).
            Only cookies whose domain matches ``base_url`` are used. Playwright itself is
            not needed.
        delay: minimum seconds between two requests.
        user_agent: User-Agent header. Defaults to ``django-admin-remote/<version>``.
        timeout: seconds to wait for each response.
        tz: time zone the admin displays datetimes in (IANA name or tzinfo). Only used by
            :meth:`parse_datetime`.
        login_path: path of the admin login view.
        session: a ``requests.Session`` to use instead of a new one (for proxies, custom
            TLS settings or tests).

    Attributes:
        requests_made: number of HTTP requests sent so far.
        posts_made: number of POSTs sent so far.
        max_redirects: redirects followed per call before giving up (default 6).
        get_retries: extra attempts for a GET answered with a 5xx status (default 3).
        retry_backoff: seconds slept before retry n is ``retry_backoff * n`` (default 2).
    """

    max_redirects = 6
    get_retries = 3
    retry_backoff = 2.0

    def __init__(
        self,
        base_url: str,
        cookies: Any = None,
        storage_state: Union[str, "os.PathLike[str]", Mapping[str, Any], None] = None,
        delay: float = 0.4,
        user_agent: Optional[str] = None,
        timeout: float = 60.0,
        tz: Union[str, tzinfo, None] = None,
        login_path: str = "/admin/login/",
        session: Optional[requests.Session] = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"base_url must look like https://host, got {base_url!r}")
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self.tz = tz
        self.login_path = login_path
        self.http = session if session is not None else requests.Session()
        self.http.headers["User-Agent"] = user_agent or f"django-admin-remote/{__version__}"
        self._origin = (parsed.scheme, parsed.netloc.lower())
        self._host = (parsed.hostname or "").lower()
        self._last: Optional[float] = None
        self.requests_made = 0
        self.posts_made = 0
        if storage_state is not None:
            self._load_storage_state(storage_state)
        if cookies is not None:
            if isinstance(cookies, Mapping):
                for name, value in cookies.items():
                    self.http.cookies.set(name, value)
            else:
                self.http.cookies.update(cookies)

    # ---------- cookies ----------
    def _load_storage_state(self, state: Any) -> None:
        if not isinstance(state, Mapping):
            with open(state, encoding="utf-8") as fh:
                state = json.load(fh)
        for c in state.get("cookies", []):
            domain = (c.get("domain") or "").lower()
            bare = domain.lstrip(".")
            if not bare or not (self._host == bare or self._host.endswith("." + bare)):
                continue
            kwargs: Dict[str, Any] = {"path": c.get("path") or "/"}
            if "." in self._host:          # single-label hosts (localhost) only match domainless cookies
                kwargs["domain"] = domain
            self.http.cookies.set(c["name"], c["value"], **kwargs)

    # ---------- URLs ----------
    def _same_origin(self, url: str) -> bool:
        p = urlparse(url)
        return (p.scheme, p.netloc.lower()) == self._origin

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            if not self._same_origin(path):
                raise ValueError(f"{path} is outside {self.base_url}")
            return path
        return self.base_url + (path if path.startswith("/") else "/" + path)

    def _is_login(self, url: str) -> bool:
        path = urlparse(url).path
        return path.rstrip("/") == self.login_path.rstrip("/") or "login" in path.strip("/").split("/")

    # ---------- HTTP ----------
    def _send(self, method: str, url: str, params: Any, data: Any, referer: str) -> requests.Response:
        if self._last is not None:
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        headers = {"Referer": referer} if method == "POST" else {}
        try:
            return self.http.request(method, url, params=params, data=data, headers=headers,
                                     timeout=self.timeout, allow_redirects=False)
        finally:
            self._last = time.monotonic()
            self.requests_made += 1

    def request(self, method: str, path: str, params: Optional[Mapping[str, Any]] = None,
                data: Optional[FormData] = None) -> Tuple[str, str]:
        """Send one request and follow its redirects. Returns ``(final_url, body)``.

        Raises NotLoggedIn if the site redirects to a login page or to another host,
        AdminHTTPError on a 4xx or 5xx answer.
        """
        method = method.upper()
        url = self._url(path)
        referer = url
        redirects = failures = 0
        while True:
            r = self._send(method, url, params, data, referer)
            if r.status_code in _REDIRECTS:
                target = urljoin(r.url or url, r.headers.get("Location", ""))
                if method == "POST" and r.status_code in (307, 308):
                    raise AdminHTTPError(f"POST {url} was redirected with {r.status_code} to {target}; "
                                         "not re-sending the POST", r.status_code, url)
                if not self._same_origin(target) or self._is_login(target):
                    raise NotLoggedIn(f"{method} {url} was redirected to {target}: no session or it expired")
                redirects += 1
                if redirects > self.max_redirects:
                    raise AdminHTTPError(f"too many redirects from {url}", r.status_code, url)
                url, method, params, data = target, "GET", None, None
                continue
            if r.status_code >= 500 and method == "GET" and failures < self.get_retries:
                failures += 1
                time.sleep(self.retry_backoff * failures)
                continue
            if r.status_code >= 400:
                raise AdminHTTPError(f"{method} {url} -> HTTP {r.status_code}: {r.text[:300]!r}",
                                     r.status_code, url)
            return r.url or url, r.text

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> str:
        """GET a page and return its HTML."""
        return self.request("GET", path, params=params)[1]

    def post(self, path: str, data: FormData) -> Tuple[str, str]:
        """POST form data. Returns ``(final_url, body)`` of the page the site lands on.

        ``data`` must contain ``csrfmiddlewaretoken`` (AdminForm takes care of that). The
        Referer header Django's CSRF check wants on HTTPS is added. A POST is sent once
        and never retried: a repeated POST could create a second object.
        """
        self.posts_made += 1
        return self.request("POST", path, data=data)

    # ---------- login ----------
    def login(self, username: str, password: str) -> None:
        """Log in through the standard admin login form (``login_path``).

        Fetches the form, then posts the credentials together with its CSRF token. The
        session cookie the site sets is kept on this client. The password is not stored.
        Returns quietly if the session is already logged in. Raises NotLoggedIn if the
        site rejects the credentials or shows no login form.
        """
        url, text = self.request("GET", self.login_path)
        doc = soup(text)
        form = doc.select_one("#login-form")
        if form is None:
            pw = doc.find("input", attrs={"type": "password"})
            form = pw.find_parent("form") if pw is not None else None
        if form is None:
            if not self._is_login(url):
                return                      # redirected into the admin: already logged in
            raise NotLoggedIn(f"no login form found at {url}")
        data: List[Tuple[str, str]] = [
            (i["name"], i.get("value", "")) for i in form.find_all("input", attrs={"type": "hidden"})
            if i.get("name")]
        user_field = "username"
        if form.find("input", attrs={"name": "username"}) is None:
            other = [i for i in form.find_all("input")
                     if i.get("name") and (i.get("type") or "text").lower() in ("text", "email")]
            if other:
                user_field = other[0]["name"]
        data += [(user_field, username), ("password", password)]
        action = urljoin(url, form.get("action") or "")
        _, text = self.post(action, data)
        doc = soup(text)
        if doc.select_one("#login-form") is not None:
            note = doc.select_one(".errornote, .errorlist")
            reason = note.get_text(" ", strip=True) if note is not None else "the login form came back"
            raise NotLoggedIn(f"login rejected: {reason}")

    # ---------- admin pages ----------
    def form(self, path: str) -> AdminForm:
        """Load an add or change page as an editable :class:`AdminForm`."""
        return AdminForm(self, path)

    def read(self, path: str) -> Dict[str, Any]:
        """Fetch a change page and parse it with :func:`parse_change_form` (read-only use)."""
        parsed = parse_change_form(self.get(path))
        if parsed["logged_out"]:
            raise NotLoggedIn(f"{path} returned the login form: no session or it expired")
        return parsed

    def changelist(self, path: str, limit: Optional[int] = None,
                   params: Optional[Mapping[str, Any]] = None, **filters: Any) -> Iterator[Union[int, str]]:
        """Iterate over the primary keys of a change list, across all its pages.

        Pages are fetched lazily, one request per page, in the list's own order.

        Args:
            path: the change list, for example ``/admin/app/model/``.
            limit: stop after this many ids.
            params: query parameters as a dict, for names that are not valid keywords.
            **filters: query parameters, the same ones the admin puts in the URL when a
                filter or search is used (``status__exact=1``, ``q="text"``, ``o="-1"``).
        """
        query = dict(params or {})
        query.update(filters)
        query.pop("p", None)
        seen = set()
        page, last, offset = 1, 1, 0
        while page <= last:
            parsed = parse_changelist(self.get(path, dict(query, p=page + offset) if page > 1 else query))
            if parsed["logged_out"]:
                raise NotLoggedIn(f"{path} returned the login form: no session or it expired")
            if page == 1:
                last, offset = parsed["last_page"], parsed["p_offset"]
            if not parsed["ids"]:
                return
            for pk in parsed["ids"]:
                if pk in seen:
                    continue            # a row shifted pages while we were reading
                seen.add(pk)
                yield pk
                if limit is not None and len(seen) >= limit:
                    return
            page += 1

    def parse_datetime(self, text: Optional[str]) -> Optional[str]:
        """:func:`parse_admin_datetime` using the ``tz`` this client was created with."""
        if self.tz is None:
            raise ValueError("create the AdminClient with tz=... to parse admin datetimes")
        return parse_admin_datetime(text, self.tz)
