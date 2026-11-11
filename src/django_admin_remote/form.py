"""A Django admin form, submitted the way a browser would submit it.

Load an add or change page, change values, add or delete inline rows, then submit.
Every field the page shows is sent back unchanged unless set, exactly like pressing
Save in the browser.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import Tag

from .exceptions import FormError, NotLoggedIn
from .parse import is_login_page, soup

SKIP_TYPES = {"submit", "button", "file", "image", "reset"}
_CONTROLS = ["input", "select", "textarea"]


def _textarea(el: Tag) -> str:
    text = el.get_text()
    return text[1:] if text.startswith("\n") else text


def _options(el: Tag) -> List[Tuple[str, str]]:
    return [(o.get("value", ""), o.get_text(strip=True)) for o in el.find_all("option")]


def _kind(el: Tag) -> str:
    if el.name == "select":
        return "multiselect" if el.has_attr("multiple") else "select"
    if el.name == "input":
        return (el.get("type") or "text").lower()
    return el.name


def _default_values(el: Tag) -> Optional[List[str]]:
    """Values a browser would send for this control, None if it sends nothing."""
    if el.has_attr("disabled"):
        return None
    if el.name == "textarea":
        return [_textarea(el)]
    if el.name == "select":
        chosen = [o.get("value", "") for o in el.find_all("option") if o.has_attr("selected")]
        if chosen or el.has_attr("multiple"):
            return chosen
        opts = el.find_all("option")
        return [opts[0].get("value", "")] if opts else []
    kind = (el.get("type") or "text").lower()
    if kind in SKIP_TYPES:
        return None
    if kind in ("checkbox", "radio"):
        return [el.get("value", "on")] if el.has_attr("checked") else []
    return [el.get("value", "")]


class AdminForm:
    """One admin add or change form.

    Usually obtained from :meth:`AdminClient.form`. Field names are the HTML ``name``
    attributes, so inline cells are addressed as ``<prefix>-<index>-<field>``.

    Args:
        client: an :class:`AdminClient` (anything with ``request``, ``post`` and
            optionally ``base_url`` works).
        path: path of the page, for example ``/admin/app/model/5/change/``.
        text: HTML of the page if already fetched. If omitted the page is requested.

    Attributes:
        path: path of the page relative to the client's base URL.
        fields: ``{name: [values]}`` exactly as they would be posted.
        buttons: names of the submit buttons on the form.
        messages: texts of the admin's message list (for example "... was changed successfully.").
        errors: validation errors shown on the page.
    """

    def __init__(self, client: Any, path: str, text: Optional[str] = None) -> None:
        self.client = client
        self.path = self._relative(path)
        if text is None:
            url, text = client.request("GET", path)
            self.path = self._relative(url)
        self._parse(text)

    def _relative(self, url: str) -> str:
        """Strip the client's base URL so the path can be compared and posted back."""
        base = (getattr(self.client, "base_url", "") or "").rstrip("/")
        if base and (url == base or url.startswith((base + "/", base + "?"))):
            rest = url[len(base):]
            return rest if rest.startswith("/") else "/" + rest
        return url

    # ---------- parsing ----------
    def _parse(self, text: str) -> None:
        doc = soup(text)
        if is_login_page(doc):
            raise NotLoggedIn(f"{self.path} returned the login form: no session or it expired")
        self.doc = doc
        # The model form is the one with the most controls (pages can hold small helper forms too).
        forms = [f for f in (doc.select("#content form") or doc.select("form"))
                 if f.find("input", attrs={"name": "csrfmiddlewaretoken"})]
        form = max(forms, key=lambda f: len(f.find_all(_CONTROLS)), default=None)
        self.form_count = len(forms)
        self.form = form
        self.fields: Dict[str, List[str]] = {}
        self.kinds: Dict[str, str] = {}
        self.choices: Dict[str, List[Tuple[str, str]]] = {}
        self.templates: Dict[str, Dict[str, Tag]] = {}
        self.buttons: List[str] = []
        self._button_values: Dict[str, str] = {}
        self.messages = [li.get_text(" ", strip=True) for li in doc.select("ul.messagelist li")]
        self.errors = [e.get_text(" ", strip=True) for e in doc.select("p.errornote, ul.errorlist li")]
        if form is None:
            return
        for el in form.find_all(_CONTROLS + ["button"]):
            name = el.get("name")
            if not name:
                continue
            kind = (el.get("type") or "").lower()
            if kind == "submit" or (el.name == "button" and kind in ("", "submit")):
                if name not in self.buttons:
                    self.buttons.append(name)
                    self._button_values[name] = el.get("value") or "1"
                continue
            if el.name == "button":
                continue
            m = re.match(r"(.+)-__prefix__-(.+)$", name)
            if m:
                self.templates.setdefault(m.group(1), {})[m.group(2)] = el
                continue
            vals = _default_values(el)
            if vals is None:
                continue
            kind = _kind(el)
            if kind in ("checkbox", "radio") and name in self.fields:
                self.fields[name].extend(vals)   # several boxes sharing one name
            else:
                self.fields[name] = vals
            self.kinds[name] = kind
            if el.name == "select":
                self.choices[name] = _options(el)

    # ---------- reading ----------
    def has(self, name: str) -> bool:
        """True if the form would post a field with this name (it is editable)."""
        return name in self.fields

    def get(self, name: str) -> Any:
        """Current value: bool for a checkbox, list for a multiple select, else a string.

        Returns None if the field is not editable on this page.
        """
        v = self.fields.get(name)
        if v is None:
            return None
        if self.kinds.get(name) == "checkbox":
            return bool(v)
        if self.kinds.get(name) == "multiselect":
            return list(v)
        return v[0] if v else ""

    def total(self, prefix: str) -> int:
        """TOTAL_FORMS of an inline formset: saved rows plus rows added so far."""
        return int(self.get(f"{prefix}-TOTAL_FORMS") or 0)

    def initial(self, prefix: str) -> int:
        """INITIAL_FORMS of an inline formset: rows already saved on the server."""
        return int(self.get(f"{prefix}-INITIAL_FORMS") or 0)

    def has_inline(self, prefix: str) -> bool:
        """True if the page has an inline formset with this prefix."""
        return f"{prefix}-TOTAL_FORMS" in self.fields

    def row_text(self, prefix: str, index: int, field: str) -> Optional[str]:
        """Displayed text of one inline cell: the selected option's label or the cell text."""
        tr = self.doc.find(id=f"{prefix}-{index}")
        td = tr.select_one(f".field-{field}") if tr else None
        if td is None:
            return None
        sel = td.find("select")
        if sel is not None:
            o = sel.find("option", selected=True)
            return o.get_text(strip=True) if o else None
        return td.get_text(" ", strip=True)

    def row_link_id(self, prefix: str, index: int, model: str) -> Optional[int]:
        """Primary key from a link to ``.../<model>/<pk>/change/`` inside an inline row."""
        tr = self.doc.find(id=f"{prefix}-{index}")
        if tr is None:
            return None
        for a in tr.find_all("a", href=True):
            m = re.search(rf"/{re.escape(model)}/(\d+)/change/", a["href"])
            if m:
                return int(m.group(1))
        return None

    def readonly(self, name: str) -> Optional[str]:
        """Displayed text of a read-only field ("True", "False" or "None" for the bool icons).

        This is the whitespace-collapsed text. Use :func:`parse_change_form` when the exact
        stored value matters.
        """
        row = self.doc.select_one(f"div.form-row.field-{name} .readonly")
        if row is None:
            return None
        img = row.find("img")
        if img is not None and img.get("alt") in ("True", "False", "None"):
            return img["alt"]
        return row.get_text(" ", strip=True)

    # ---------- writing ----------
    def _resolve(self, name: str, value: Any) -> str:
        """Accept an option value or its visible label for selects."""
        value = "" if value is None else str(value)
        opts = self.choices.get(name)
        if opts is None:
            return value
        if any(v == value for v, _ in opts):
            return value
        for v, label in opts:
            if label.lower() == value.lower():
                return v
        raise FormError(f"{name}: {value!r} is not a choice. Options: {[lb for _, lb in opts][:25]}")

    def set(self, name: str, value: Any) -> None:
        """Set a field.

        Checkboxes take a truthy or falsy value. Selects take the option value or its
        visible label (case-insensitive). Multiple selects take a list of those.
        Raises FormError if the field is not editable or the choice does not exist.
        """
        if name not in self.fields:
            raise FormError(f"field {name!r} is not editable on {self.path}")
        kind = self.kinds[name]
        if kind == "checkbox":
            self.fields[name] = ["on"] if value else []
        elif kind == "multiselect":
            self.fields[name] = [self._resolve(name, v) for v in (value or [])]
        else:
            self.fields[name] = [self._resolve(name, value)]

    def set_if_present(self, name: str, value: Any) -> bool:
        """Set the field if it is editable here and value is not None. Returns whether it was set."""
        if name in self.fields and value is not None:
            self.set(name, value)
            return True
        return False

    def add_row(self, prefix: str, values: Dict[str, Any]) -> int:
        """Add a row to an inline formset and return its index.

        The row is built from the formset's ``__prefix__`` empty-form template, so hidden
        fields such as the parent key keep their defaults, and TOTAL_FORMS is increased.
        ``values`` maps the short field names of the inline to values (see :meth:`set`).
        """
        tmpl = self.templates.get(prefix)
        if tmpl is None or not self.has_inline(prefix):
            raise FormError(f"inline {prefix!r} cannot take new rows on {self.path}")
        maxn = int(self.get(f"{prefix}-MAX_NUM_FORMS") or 1000)
        index = self.total(prefix)
        if index >= maxn:
            raise FormError(f"inline {prefix!r} is full (max {maxn})")
        unknown = set(values) - set(tmpl)
        if unknown:
            raise FormError(f"inline {prefix!r} has no field(s) {sorted(unknown)}. Has: {sorted(tmpl)}")
        for field, el in tmpl.items():
            name = f"{prefix}-{index}-{field}"
            vals = _default_values(el)
            if vals is None:
                continue
            self.fields[name], self.kinds[name] = vals, _kind(el)
            if el.name == "select":
                self.choices[name] = _options(el)
            if field in values:
                self.set(name, values[field])
        self.fields[f"{prefix}-TOTAL_FORMS"] = [str(index + 1)]
        return index

    def delete_row(self, prefix: str, index: int) -> None:
        """Tick the DELETE box of a saved inline row. It is deleted when the form is submitted."""
        self.set(f"{prefix}-{index}-DELETE", True)

    def submit(self, button: str = "_continue") -> "AdminForm":
        """POST the form by "pressing" the named submit button.

        The default ``_continue`` is "Save and continue editing", which lands back on the
        change page so the result can be inspected. ``_save`` and ``_addanother`` work too,
        as do custom buttons the page defines.

        Returns the page the admin answered with as a new AdminForm. Raises FormError if
        the button does not exist or the admin reports validation errors. The POST is sent
        once and never retried.
        """
        if self.form is None:
            raise FormError(f"no form found on {self.path}")
        if button not in self.buttons:
            raise FormError(f"button {button!r} not on {self.path}. Has: {self.buttons}")
        data = [(n, v) for n, vals in self.fields.items() for v in vals]
        data.append((button, self._button_values.get(button, "1")))
        url, text = self.client.post(self.path, data)
        result = AdminForm(self.client, url, text)
        if result.errors:
            raise FormError(f"{self.path} rejected: {result.errors[:6]}")
        return result

    def object_id(self) -> Optional[int]:
        """Numeric primary key from the page path, None on an add page."""
        m = re.search(r"/(\d+)/change/", self.path)
        return int(m.group(1)) if m else None
