import pytest

from django_admin_remote import AdminForm, FormError, NotLoggedIn

PAGE = """
<html><body><div id="content">
<form id="previewform" method="post"><input type="hidden" name="csrfmiddlewaretoken" value="p"></form>
<form id="thing_form" method="post"><input type="hidden" name="csrfmiddlewaretoken" value="tok">
<div class="form-row field-title"><input type="text" name="title" value="Old"></div>
<div class="form-row field-body"><textarea name="body">
line one
line two</textarea></div>
<div class="form-row field-kind"><select name="kind"><option value="1" selected>Coding</option><option value="13">Database</option></select></div>
<div class="form-row field-tags"><select name="tags" multiple><option value="1" selected>Normal</option><option value="3">Competitive</option></select></div>
<div class="form-row field-flag"><input type="checkbox" name="flag" checked></div>
<div class="form-row field-off"><input type="checkbox" name="off"></div>
<div class="form-row field-locked"><input type="text" name="locked" value="x" disabled></div>
<div class="form-row field-file"><input type="file" name="upload"></div>
<div class="form-row field-verified"><div class="readonly"><img alt="True"></div></div>
<div class="inline-group" id="rows-group">
<input type="hidden" name="rows-TOTAL_FORMS" value="1"><input type="hidden" name="rows-INITIAL_FORMS" value="1">
<input type="hidden" name="rows-MIN_NUM_FORMS" value="0"><input type="hidden" name="rows-MAX_NUM_FORMS" value="3">
<table><tbody>
<tr class="form-row has_original" id="rows-0"><td class="original"><input type="hidden" name="rows-0-id" value="77"><input type="hidden" name="rows-0-parent" value="5"></td>
<td class="field-lang"><p>Python (3.13.1)</p></td><td class="field-link"><a href="/admin/app/rowmodel/77/change/">url</a></td>
<td class="delete"><input type="checkbox" name="rows-0-DELETE"></td></tr>
<tr class="form-row empty-form" id="rows-empty"><td><input type="hidden" name="rows-__prefix__-id"><input type="hidden" name="rows-__prefix__-parent" value="5">
<select name="rows-__prefix__-lang"><option value="" selected>---------</option><option value="71">Python (3.13.1)</option><option value="1999">JavaScript (Node.js 22.11.0)</option></select>
<textarea name="rows-__prefix__-text"></textarea><input type="checkbox" name="rows-__prefix__-hidden" checked></td></tr>
</tbody></table></div>
<input type="submit" name="_save" value="Save"><input type="submit" name="_continue" value="Save and continue editing">
<input type="submit" name="_publish"><button type="submit" name="_archive" value="yes">Archive</button>
</form></div></body></html>
"""
ERROR_PAGE = PAGE.replace('<div class="form-row field-title">',
                          '<p class="errornote">Please correct the error below.</p>'
                          '<div class="form-row field-title"><ul class="errorlist"><li>This field is required.</li></ul>')


class FakeClient:
    """Stands in for AdminClient: records the POST and answers with a canned page."""

    def __init__(self, base_url=None, lands_on=None, answer=None):
        self.posted = None
        self.lands_on = lands_on
        self.answer = answer or PAGE.replace('value="Old"', 'value="New"')
        if base_url is not None:
            self.base_url = base_url

    def request(self, method, path):
        return self.lands_on or path, PAGE

    def post(self, path, data):
        self.posted = (path, data)
        return self.lands_on or path, self.answer


def form(client=None):
    return AdminForm(client or FakeClient(), "/admin/app/thing/5/change/", PAGE)


def test_picks_main_form_and_reads_like_a_browser():
    f = form()
    assert f.get("title") == "Old"
    assert f.get("body") == "line one\nline two"
    assert f.get("kind") == "1" and f.get("tags") == ["1"]
    assert f.get("flag") is True and f.get("off") is False
    assert not f.has("locked") and not f.has("upload") and f.get("locked") is None
    assert f.buttons == ["_save", "_continue", "_publish", "_archive"]
    assert f.readonly("verified") == "True" and f.readonly("title") is None
    assert f.has_inline("rows") and not f.has_inline("nope")
    assert f.initial("rows") == 1 and f.row_text("rows", 0, "lang") == "Python (3.13.1)"
    assert f.row_link_id("rows", 0, "rowmodel") == 77 and f.row_link_id("rows", 0, "other") is None
    assert f.object_id() == 5


def test_set_resolves_labels_and_rejects_unknown():
    f = form()
    f.set("kind", "Database")
    assert f.get("kind") == "13"
    f.set("tags", ["Normal", "3"])
    assert f.get("tags") == ["1", "3"]
    with pytest.raises(FormError):
        f.set("kind", "Nope")
    with pytest.raises(FormError):
        f.set("locked", "y")
    assert f.set_if_present("title", "T") is True and f.get("title") == "T"
    assert f.set_if_present("title", None) is False and f.set_if_present("locked", "y") is False


def test_add_and_delete_rows():
    f = form()
    i = f.add_row("rows", {"lang": "JavaScript (Node.js 22.11.0)", "text": "hello", "hidden": False})
    assert i == 1 and f.total("rows") == 2
    assert f.get("rows-1-lang") == "1999" and f.get("rows-1-parent") == "5" and f.get("rows-1-hidden") is False
    f.delete_row("rows", 0)
    assert f.get("rows-0-DELETE") is True
    with pytest.raises(FormError):
        f.add_row("rows", {"nope": 1})
    f.add_row("rows", {})
    with pytest.raises(FormError):     # MAX_NUM_FORMS is 3
        f.add_row("rows", {})
    with pytest.raises(FormError):
        f.add_row("unknown", {})


def test_submit_sends_every_field_once():
    c = FakeClient()
    f = form(c)
    f.set("title", "New")
    f.set("off", True)
    res = f.submit("_continue")
    path, data = c.posted
    names = [n for n, _ in data]
    assert path == "/admin/app/thing/5/change/"
    assert ("csrfmiddlewaretoken", "tok") in data and ("title", "New") in data and ("off", "on") in data
    assert ("_continue", "Save and continue editing") in data and "_save" not in names and "locked" not in names
    assert names.count("title") == 1 and names.count("rows-TOTAL_FORMS") == 1
    assert not any("__prefix__" in n for n in names)
    assert res.get("title") == "New"
    with pytest.raises(FormError):
        f.submit("_missing")


def test_custom_buttons_send_their_own_value():
    c = FakeClient()
    form(c).submit("_archive")
    assert ("_archive", "yes") in c.posted[1]
    form(c).submit("_publish")
    assert ("_publish", "1") in c.posted[1]


def test_validation_errors_raise():
    with pytest.raises(FormError, match="This field is required"):
        form(FakeClient(answer=ERROR_PAGE)).submit("_save")


def test_login_page_raises_not_logged_in():
    with pytest.raises(NotLoggedIn):
        AdminForm(FakeClient(), "/admin/app/thing/5/change/", '<form id="login-form"></form>')


def test_paths_are_made_relative_to_the_client_base_url():
    base = "https://admin.example.com"
    c = FakeClient(base_url=base, lands_on=base + "/admin/app/thing/9/change/")
    f = AdminForm(c, base + "/admin/app/thing/add/?kind=1", PAGE)
    assert f.path == "/admin/app/thing/add/?kind=1" and f.object_id() is None
    res = f.submit("_continue")
    assert c.posted[0] == "/admin/app/thing/add/?kind=1"
    assert res.path == "/admin/app/thing/9/change/" and res.object_id() == 9
    # loading without text takes the path from where the GET ended up
    assert AdminForm(c, "/admin/app/thing/9/").path == "/admin/app/thing/9/change/"


def test_base_url_is_only_stripped_as_a_whole_prefix():
    c = FakeClient(base_url="https://admin.example.com/")
    other = "https://admin.example.com.evil.test/admin/app/thing/5/change/"
    assert AdminForm(c, other, PAGE).path == other
    assert AdminForm(c, "https://admin.example.com", PAGE).path == "/"
    assert AdminForm(FakeClient(), "https://x.test/admin/a/b/1/change/", PAGE).path == "https://x.test/admin/a/b/1/change/"
