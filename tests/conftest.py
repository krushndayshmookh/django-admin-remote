"""Offline test helpers: a fake transport plugged into requests, so the real client code runs."""
from urllib.parse import parse_qs, parse_qsl, urlparse

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from django_admin_remote import AdminClient

BASE = "https://admin.example.com"


class FakeTransport(BaseAdapter):
    """Answers requests from a handler(call) -> (status, headers, body). Records every call."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.calls = []

    def send(self, request, **kwargs):
        url = urlparse(request.url)
        body = request.body.decode() if isinstance(request.body, bytes) else (request.body or "")
        call = {
            "method": request.method,
            "url": request.url,
            "path": url.path,
            "query": {k: v[0] for k, v in parse_qs(url.query).items()},
            "form": parse_qsl(body, keep_blank_values=True),
            "headers": dict(request.headers),
        }
        self.calls.append(call)
        status, headers, text = self.handler(call)
        response = requests.Response()
        response.status_code = status
        response.headers = CaseInsensitiveDict(headers)
        response._content = text.encode("utf-8")
        response.encoding = "utf-8"
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


@pytest.fixture
def make_client():
    def make(handler, **kwargs):
        transport = FakeTransport(handler)
        session = requests.Session()
        session.mount("https://", transport)
        session.mount("http://", transport)
        kwargs.setdefault("delay", 0)
        client = AdminClient(kwargs.pop("base_url", BASE), session=session, **kwargs)
        client.retry_backoff = 0
        return client, transport
    return make
