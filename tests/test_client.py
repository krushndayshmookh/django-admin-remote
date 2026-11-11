import json

import pytest

from django_admin_remote import AdminClient, AdminHTTPError, NotLoggedIn

from conftest import BASE
from test_form import PAGE

LOGIN_PAGE = """<html><body class="login"><div id="content">{error}
<form action="/admin/login/?next=/admin/" method="post" id="login-form">
<input type="hidden" name="csrfmiddlewaretoken" value="csrf123">
<input type="text" name="username" autofocus required id="id_username">
<input type="password" name="password" required id="id_password">
<input type="hidden" name="next" value="/admin/">
<div class="submit-row"><input type="submit" value="Log in"></div>
</form></div></body></html>"""
INDEX_PAGE = '<html><body><div id="content"><h1>Site administration</h1></div></body></html>'


def changelist_page(ids, labels_to_p, current, total):
    rows = "".join(f'<tr><th><a href="/admin/app/thing/{i}/change/">thing {i}</a></th></tr>' for i in ids)
    links = " ".join(f'<span class="this-page">{label}</span>' if label == current
                     else f'<a href="?status=open&amp;p={p}">{label}</a>' for label, p in labels_to_p.items())
    return (f'<div id="content"><table id="result_list"><tbody>{rows}</tbody></table>'
            f'<p class="paginator">{links} {total} things</p></div>')


def paged_site(first_p):
    """A three page change list whose ?p= starts at first_p (0 before Django 3.2, 1 after)."""
    pages = {1: [9, 8, 7], 2: [6, 5, 4], 3: [3]}
    labels = {label: label - 1 + first_p for label in pages}

    def handler(call):
        p = int(call["query"].get("p", first_p))
        label = p - first_p + 1
        return 200, {}, changelist_page(pages[label], labels, label, 7)
    return handler


@pytest.mark.parametrize("first_p", [1, 0])
def test_changelist_walks_all_pages(make_client, first_p):
    client, transport = make_client(paged_site(first_p))
    ids = list(client.changelist("/admin/app/thing/", status="open"))
    assert ids == [9, 8, 7, 6, 5, 4, 3]
    assert [c["path"] for c in transport.calls] == ["/admin/app/thing/"] * 3
    assert [c["query"] for c in transport.calls] == [
        {"status": "open"},
        {"status": "open", "p": str(first_p + 1)},
        {"status": "open", "p": str(first_p + 2)},
    ]


def test_changelist_limit_stops_fetching(make_client):
    client, transport = make_client(paged_site(1))
    assert list(client.changelist("/admin/app/thing/", limit=4)) == [9, 8, 7, 6]
    assert len(transport.calls) == 2
    assert list(client.changelist("/admin/app/thing/", limit=2, params={"created_by__id__exact": 3})) == [9, 8]
    assert transport.calls[-1]["query"] == {"created_by__id__exact": "3"}


def test_changelist_is_lazy_and_skips_repeats(make_client):
    def handler(call):
        if "p" not in call["query"]:
            return 200, {}, changelist_page([3, 2], {1: 1, 2: 2}, 1, 3)
        return 200, {}, changelist_page([2, 1], {1: 1, 2: 2}, 2, 3)   # row 2 shifted onto page 2
    client, transport = make_client(handler)
    it = client.changelist("/admin/app/thing/")
    assert transport.calls == []
    assert next(it) == 3 and len(transport.calls) == 1
    assert list(it) == [2, 1]


def test_changelist_on_login_page_raises(make_client):
    client, _ = make_client(lambda call: (200, {}, LOGIN_PAGE.format(error="")))
    with pytest.raises(NotLoggedIn):
        list(client.changelist("/admin/app/thing/"))


def login_site(password="s3cret"):
    def handler(call):
        if call["path"] == "/admin/login/" and call["method"] == "GET":
            return 200, {}, LOGIN_PAGE.format(error="")
        if call["path"] == "/admin/login/" and call["method"] == "POST":
            form = dict(call["form"])
            if form.get("password") == password and form.get("csrfmiddlewaretoken") == "csrf123":
                return 302, {"Location": form["next"]}, ""
            return 200, {}, LOGIN_PAGE.format(error='<p class="errornote">Please enter the correct username and password.</p>')
        return 200, {}, INDEX_PAGE
    return handler


def test_login_posts_credentials_with_csrf_and_referer(make_client):
    client, transport = make_client(login_site())
    assert client.login("alice", "s3cret") is None
    get, post, landed = transport.calls
    assert (get["method"], get["path"]) == ("GET", "/admin/login/")
    assert (post["method"], post["path"], post["query"]) == ("POST", "/admin/login/", {"next": "/admin/"})
    assert sorted(post["form"]) == sorted([("csrfmiddlewaretoken", "csrf123"), ("next", "/admin/"),
                                           ("username", "alice"), ("password", "s3cret")])
    assert post["headers"]["Referer"].startswith(BASE + "/admin/login/")
    assert "Referer" not in get["headers"]
    assert (landed["method"], landed["path"], landed["form"]) == ("GET", "/admin/", [])
    assert client.posts_made == 1 and client.requests_made == 3


def test_login_rejected(make_client):
    client, transport = make_client(login_site())
    with pytest.raises(NotLoggedIn, match="correct username and password"):
        client.login("alice", "wrong")
    assert [c["method"] for c in transport.calls] == ["GET", "POST"]


def test_login_when_already_logged_in(make_client):
    def handler(call):
        if call["path"] == "/admin/login/":
            return 302, {"Location": "/admin/"}, ""
        return 200, {}, INDEX_PAGE
    client, transport = make_client(handler)
    client.login("alice", "s3cret")
    assert [c["method"] for c in transport.calls] == ["GET", "GET"]


def test_redirect_to_login_means_not_logged_in(make_client):
    client, transport = make_client(
        lambda call: (302, {"Location": "/admin/login/?next=/admin/app/thing/5/change/"}, ""))
    with pytest.raises(NotLoggedIn):
        client.get("/admin/app/thing/5/change/")
    assert len(transport.calls) == 1


def test_redirect_to_another_host_means_not_logged_in(make_client):
    client, transport = make_client(
        lambda call: (302, {"Location": "https://sso.example.org/authorize?x=1"}, ""))
    with pytest.raises(NotLoggedIn):
        client.read("/admin/app/thing/5/change/")
    assert len(transport.calls) == 1, "the other host must never be contacted"


def test_a_model_called_login_something_is_not_a_login_redirect(make_client):
    def handler(call):
        if call["path"] == "/admin/app/loginattempt/5/":
            return 302, {"Location": "/admin/app/loginattempt/5/change/"}, ""
        return 200, {}, PAGE
    client, _ = make_client(handler)
    assert client.form("/admin/app/loginattempt/5/").path == "/admin/app/loginattempt/5/change/"


def test_urls_outside_the_base_url_are_refused(make_client):
    client, transport = make_client(lambda call: (200, {}, INDEX_PAGE))
    with pytest.raises(ValueError):
        client.get("https://elsewhere.example.org/admin/")
    assert transport.calls == []
    assert client.get(BASE + "/admin/") == INDEX_PAGE and client.get("admin/") == INDEX_PAGE
    with pytest.raises(ValueError):
        AdminClient("admin.example.com")


def test_post_is_never_retried_but_get_is(make_client):
    state = {"fail": 2}

    def handler(call):
        if call["method"] == "POST":
            return 502, {}, "bad gateway"
        if state["fail"]:
            state["fail"] -= 1
            return 503, {}, "busy"
        return 200, {}, INDEX_PAGE
    client, transport = make_client(handler)
    assert client.get("/admin/") == INDEX_PAGE
    assert len(transport.calls) == 3
    with pytest.raises(AdminHTTPError) as err:
        client.post("/admin/app/thing/add/", [("csrfmiddlewaretoken", "t")])
    assert err.value.status_code == 502
    assert [c["method"] for c in transport.calls].count("POST") == 1


def test_get_gives_up_after_retries_and_4xx_is_not_retried(make_client):
    client, transport = make_client(lambda call: (500, {}, "boom"))
    with pytest.raises(AdminHTTPError):
        client.get("/admin/")
    assert len(transport.calls) == 1 + client.get_retries
    client, transport = make_client(lambda call: (404, {}, "nope"))
    with pytest.raises(AdminHTTPError) as err:
        client.get("/admin/missing/")
    assert err.value.status_code == 404 and len(transport.calls) == 1


def test_post_redirected_with_307_is_not_resent(make_client):
    client, transport = make_client(lambda call: (307, {"Location": "/admin/elsewhere/"}, ""))
    with pytest.raises(AdminHTTPError):
        client.post("/admin/app/thing/add/", [("a", "b")])
    assert len(transport.calls) == 1


def test_form_round_trip_through_the_real_client(make_client):
    def handler(call):
        if call["method"] == "POST":
            return 302, {"Location": "/admin/app/thing/5/change/"}, ""
        return 200, {}, PAGE
    client, transport = make_client(handler, user_agent="my-tool/1.0")
    form = client.form("/admin/app/thing/5/change/")
    form.set("title", "New")
    result = form.submit("_continue")
    post = transport.calls[1]
    assert post["method"] == "POST" and ("title", "New") in post["form"]
    assert ("csrfmiddlewaretoken", "tok") in post["form"]
    assert post["headers"]["Referer"] == BASE + "/admin/app/thing/5/change/"
    assert post["headers"]["User-Agent"] == "my-tool/1.0"
    assert result.path == "/admin/app/thing/5/change/" and result.object_id() == 5
    assert client.read("/admin/app/thing/5/change/")["fields"]["title"]["value"] == "Old"


def test_default_user_agent_names_the_package(make_client):
    client, transport = make_client(lambda call: (200, {}, INDEX_PAGE))
    client.get("/admin/")
    assert transport.calls[0]["headers"]["User-Agent"].startswith("django-admin-remote/")


def test_cookie_dict_is_sent(make_client):
    client, transport = make_client(lambda call: (200, {}, INDEX_PAGE), cookies={"sessionid": "abc"})
    client.get("/admin/")
    assert transport.calls[0]["headers"]["Cookie"] == "sessionid=abc"


def test_storage_state_uses_only_matching_cookies(make_client, tmp_path):
    state = {"cookies": [
        {"name": "sessionid", "value": "abc", "domain": "admin.example.com", "path": "/"},
        {"name": "shared", "value": "s", "domain": ".example.com", "path": "/"},
        {"name": "other", "value": "nope", "domain": "accounts.example.org", "path": "/"},
        {"name": "sibling", "value": "nope", "domain": "www.example.com", "path": "/"},
        {"name": "lookalike", "value": "nope", "domain": "evil-example.com", "path": "/"},
    ]}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    for source in (state, path, str(path)):
        client, transport = make_client(lambda call: (200, {}, INDEX_PAGE), storage_state=source)
        client.get("/admin/")
        sent = dict(c.split("=") for c in transport.calls[0]["headers"]["Cookie"].split("; "))
        assert sent == {"sessionid": "abc", "shared": "s"}


def test_storage_state_on_localhost(make_client):
    state = {"cookies": [{"name": "sessionid", "value": "abc", "domain": "localhost", "path": "/"}]}
    client, transport = make_client(lambda call: (200, {}, INDEX_PAGE),
                                    base_url="http://localhost:8000", storage_state=state)
    client.get("/admin/")
    assert transport.calls[0]["headers"]["Cookie"] == "sessionid=abc"


def test_delay_is_kept_between_requests(make_client, monkeypatch):
    import django_admin_remote.client as mod
    slept = []
    monkeypatch.setattr(mod.time, "sleep", slept.append)
    client, _ = make_client(lambda call: (200, {}, INDEX_PAGE), delay=30)
    client.get("/admin/")
    client.get("/admin/")
    assert len(slept) == 1 and 29 < slept[0] <= 30


def test_parse_datetime_uses_the_client_zone(make_client):
    client, _ = make_client(lambda call: (200, {}, INDEX_PAGE), tz="UTC")
    assert client.parse_datetime("Oct. 30, 2026, noon") == "2026-10-30T12:00:00+00:00"
    client, _ = make_client(lambda call: (200, {}, INDEX_PAGE))
    with pytest.raises(ValueError):
        client.parse_datetime("Oct. 30, 2026, noon")
