# django-admin-remote

Read and edit a remote Django admin site from Python, over plain HTTP, by parsing the HTML the stock admin already serves. Nothing is installed on the server: if you can use the admin in a browser, you can script it.

It is meant for the case where you have admin access to a Django site but no API and no way to deploy code to it.

- Reads change forms: editable fields, read-only fields (with the stored value recovered, not just the displayed text), yes/no icons, links, and inline formset rows.
- Reads change lists: ids, total count, all pages, with the same filters the admin puts in the URL.
- Submits add and change forms the way a browser does: every field is sent back, selects can be set by label, inline rows can be added and deleted, custom submit buttons can be pressed, validation errors are raised.
- Logs in with a username and password, or reuses the cookies of a browser session for sites behind SSO.

## Install

```bash
pip install django-admin-remote
```

Python 3.10 or newer. Depends on `requests` and `beautifulsoup4`.

## Quickstart

```python
from django_admin_remote import AdminClient, FormError

admin = AdminClient("https://admin.example.com", delay=0.5)
admin.login("alice", "correct horse battery staple")

# ids of every matching row, across all pages of the change list
ids = list(admin.changelist("/admin/blog/post/", status__exact="draft", limit=50))

# read one object, including read-only fields and inline rows
post = admin.read(f"/admin/blog/post/{ids[0]}/change/")
print(post["fields"]["title"]["value"], post["inlines"]["comment_set"])
# change it like a browser would: untouched fields are sent back as they are
form = admin.form(f"/admin/blog/post/{ids[0]}/change/")
form.set("title", "A better title")
form.set("status", "Published")              # a select: option value or visible label
form.add_row("comment_set", {"text": "First!"})
try:
    saved = form.submit("_continue")         # "Save and continue editing"
except FormError as err:
    print("the admin rejected the form:", err)
```

To create an object, load the add page (`admin.form("/admin/blog/post/add/")`), set the fields, submit, and read `saved.object_id()`.

## Authentication

**Username and password.** `admin.login(username, password)` uses the standard admin login form at `/admin/login/` (change it with `login_path=`). The password is posted once and not kept.

**Existing cookies.** Sites that log in through SSO (Google, Okta and so on) have no password form to post to. Log in with a real browser once and hand the session cookies over:

```python
admin = AdminClient("https://admin.example.com", cookies={"sessionid": "..."})
# or a Playwright storage_state file, as saved by context.storage_state(path="state.json")
admin = AdminClient("https://admin.example.com", storage_state="state.json")
```

Playwright is not a dependency. Only the JSON file it writes is read, and only cookies whose domain matches the base URL are used.

When the session is missing or has expired the client raises `NotLoggedIn`. It notices this from a redirect to a login page or to another host, and from the login form showing up where an admin page was expected.

## API overview

| Call | What it does |
| --- | --- |
| `AdminClient(base_url, cookies=None, storage_state=None, delay=0.4, user_agent=None, timeout=60, tz=None, login_path="/admin/login/", session=None)` | One client per site. Waits `delay` seconds between requests. |
| `client.login(username, password)` | Log in through the admin login form. |
| `client.get(path, params=None)` | GET a page, returns the HTML. |
| `client.post(path, data)` | POST form data, returns `(final_url, html)`. Never retried. |
| `client.changelist(path, limit=None, params=None, **filters)` | Iterator over the ids of a change list, all pages. |
| `client.read(path)` | `parse_change_form` of a page: `{"fields", "inlines", "logged_out"}`. |
| `client.form(path)` | An `AdminForm` for an add or change page. |
| `client.parse_datetime(text)` | `parse_admin_datetime` with the client's `tz`. |
| `AdminForm.has / get / set / set_if_present` | Read and change the values that will be posted. |
| `AdminForm.add_row(prefix, values) / delete_row(prefix, index)` | Inline formset rows. |
| `AdminForm.total(prefix) / initial(prefix) / row_text / row_link_id` | Inspect inline formsets. |
| `AdminForm.readonly(name) / object_id()` | Displayed read-only text, primary key from the URL. |
| `AdminForm.submit(button="_continue")` | POST the form, returns the resulting page as an `AdminForm`. |
| `parse_change_form(html)`, `parse_changelist(html)` | The parsers, usable on HTML you fetched yourself. |
| `parse_admin_datetime(text, tz)` | "Nov. 11, 2026, 1:43 p.m." to `2026-11-11T13:43:00+01:00`. |
| `NotLoggedIn`, `FormError`, `AdminHTTPError` | Exceptions, all subclasses of `AdminError`. |

Every public function and method has a docstring with the details.

### Inline formsets

Inline fields are addressed by their HTML names, `<prefix>-<index>-<field>`. The prefix is what the admin uses in the page (often the related name, such as `comment_set`); look at `parse_change_form(...)["inlines"].keys()` to find it.

```python
form = admin.form("/admin/blog/post/7/change/")
form.set("comment_set-0-text", "edited")           # change a saved row
form.delete_row("comment_set", 1)                  # tick its DELETE box
index = form.add_row("comment_set", {"text": "new"})  # built from the empty-form template
form.submit()
```

`add_row` copies the formset's `__prefix__` template row, so hidden fields keep their defaults, and it updates `TOTAL_FORMS`. It refuses to go past `MAX_NUM_FORMS`.

### Dates

The admin shows datetimes in the server's time zone without naming it. Pass the zone to get an unambiguous value:

```python
from django_admin_remote import parse_admin_datetime
parse_admin_datetime("Sept. 29, 2026, 3:03 a.m.", "Europe/Paris")   # '2026-09-29T03:03:00+02:00'
```

## How it reads read-only fields

An editable field carries its exact value in the HTML (`value="..."`, the textarea body, the selected option). A read-only field is only displayed, so the stored value has to be worked out from what Django rendered.

For plain values Django's admin renders a read-only field as `linebreaksbr(escape(value))`: the value is HTML-escaped, then every newline becomes `<br>`. The parser reverses exactly those two steps on the cell's inner HTML:

1. `<br>` is turned back into a newline.
2. The result is HTML-unescaped once.

The parser strips and collapses nothing. Whatever is in the cell comes back: inner newlines, a trailing newline, leading spaces, and a stored `a &lt; b` (text that itself contains an entity) as `a &lt; b` and not as `a < b`. Taking the visible text of the cell, as a generic scraper would, loses these.

One caveat is on Django's side. Newer Django versions strip leading and trailing whitespace from a read-only string before rendering it (seen on Django 6.1, where `display_for_value` calls `strip()`). On such a site the outer whitespace never reaches the HTML, so a stored `5\n` reads as `5`. Older versions render it in full. If exact outer whitespace matters, check what your site sends.

The other cases:

- The yes / no / unknown icons become `True`, `False` and `None`.
- A cell made only of links (a foreign key with a link, for example) becomes `{"text": ..., "links": [...]}`.
- A cell showing just `-` is Django's placeholder for an empty value and becomes `""`.

What cannot be recovered: anything the admin formats before display. Dates come back as displayed text (see `parse_admin_datetime`), numbers may be localized, foreign keys show the object's `str()`, and a read-only method that returns HTML through `format_html` or `mark_safe` comes back with that markup. A stored value that is literally `-` is indistinguishable from an empty one.

## Limitations

- **It relies on stock admin markup.** The parsers look for the classes and ids Django's own templates produce (`form-row`, `field-<name>`, `readonly`, `inline-group`, `result_list`, `paginator`, `login-form`). Custom admin themes and replacement admin skins change that markup and may break parsing partly or completely. Check against your site before relying on it. The offline tests use markup saved from an older Django; a manual run against Django 6.1 (login, change list pages and filters, read, save, inline add and delete) also passed.
- **Be polite to production sites.** Every call is a real page render on someone's server. Keep the default delay or raise it, use `limit`, and do not run it in parallel against a site you do not operate. Only use it where you are allowed to automate.
- **POSTs are never retried.** If a POST fails or times out, the client raises and leaves it to you: the save may or may not have happened, and a blind repeat could create a duplicate. A GET that gets a 5xx answer is retried a few times.
- **A submit sends what the page showed.** Like a browser, the form posts every field back. If someone else edits the same object between your load and your submit, their change is overwritten.
- No file uploads. File inputs are left out of the POST, which keeps the existing file.
- No JavaScript. Widgets that load their choices by AJAX (`autocomplete_fields`) only list the options present in the HTML; set those fields to the primary key directly. `raw_id_fields` are plain text inputs and work.
- Change list parsing returns ids, the count and the pages, not the column values. Read each object for its data.
- The total count and the dates assume an English-language admin with default formats.
- Primary keys in `AdminForm.object_id()`, `row_link_id()` and inline `_links` are assumed to be integers.
- Admin actions (the dropdown above the change list) and the delete confirmation page are not wrapped. `client.get` and `client.post` are there if you need them.

## Prior art

[`django-admin-client`](https://pypi.org/project/django-admin-client/) had the same idea first: a Python client for a Django admin site that works over HTTP. Its last release on PyPI is 0.2.4 from March 2019. It logs in with a username and password, offers list, get, add, change and delete, and can generate a client spec for a site. If that covers your case, look at it first.

`django-admin-remote` was written for things its documentation does not mention:

- inline formsets (read, add and delete rows),
- read-only fields with the stored value recovered,
- change list filters and pagination across pages, on both old and new Django page numbering,
- sessions from browser cookies, for admin sites behind SSO,
- custom submit buttons, and built-in request pacing.

On the other side, this package has no delete helper and no spec generation.

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

The tests run offline against saved admin HTML and a fake HTTP transport.

## License

MIT. See [LICENSE](LICENSE).

## License

MIT. See [LICENSE](LICENSE).
