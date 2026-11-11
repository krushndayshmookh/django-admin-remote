"""Parsers for stock Django admin pages (change form and change list).

They rely only on the markup Django's own admin templates produce:

* change form: ``div.form-row.field-<name>`` holding an input, select, textarea or ``div.readonly``
* inlines: ``#<prefix>-group`` with ``tr.form-row.has_original`` and ``td.field-<name>``
  (tabular) or ``div.inline-related.has_original`` (stacked)
* change list: ``#result_list tbody tr`` and the ``.paginator`` element
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

_BOOL = {"True": True, "False": False, "None": None}
_CHANGE_LINK = re.compile(r"/([^/?#]+)/change/")


def soup(text: str) -> BeautifulSoup:
    """Parse HTML with the standard library parser (no lxml needed)."""
    return BeautifulSoup(text, "html.parser")


def is_login_page(doc: BeautifulSoup) -> bool:
    """True if the page is the stock admin login form."""
    return doc.select_one("#login-form") is not None


def _pk(text: str) -> Union[int, str]:
    return int(text) if text.isdigit() else text


def decode_readonly(node: Tag) -> str:
    """Recover the stored value from a read-only cell.

    Django renders read-only text as ``linebreaksbr(escape(value))``. The stored value is
    therefore: the inner HTML, with ``<br>`` turned back into a newline, HTML-unescaped
    exactly once. Nothing is stripped, so leading spaces and trailing newlines survive.

    A cell showing only "-" is Django's placeholder for an empty value and decodes to "".
    """
    inner = node.decode_contents()
    inner = re.sub(r"<br\s*/?>", "\n", inner)
    value = html.unescape(inner)
    return "" if value.strip() == "-" else value


def _readonly_value(node: Tag) -> Any:
    img = node.find("img")
    if img is not None and img.get("alt") in _BOOL and not node.get_text(strip=True):
        return _BOOL[img["alt"]]
    links = node.find_all("a")
    if links and node.get_text(strip=True) == "".join(a.get_text(strip=True) for a in links):
        return {"text": node.get_text(" ", strip=True), "links": [a.get("href") for a in links]}
    return decode_readonly(node)


def _widget_value(el: Tag) -> Any:
    if el.name == "select":
        chosen = [{"value": o.get("value", ""), "label": o.get_text(strip=True)}
                  for o in el.find_all("option") if o.has_attr("selected")]
        if el.has_attr("multiple"):
            return chosen
        return chosen[0] if chosen else None
    if el.name == "textarea":
        text = el.get_text()
        return text[1:] if text.startswith("\n") else text   # browsers drop one leading newline
    kind = el.get("type", "text")
    if kind == "checkbox":
        return el.has_attr("checked")
    if kind == "file":
        return None
    return el.get("value", "")


def _cell(container: Tag) -> Optional[Dict[str, Any]]:
    """Value of one field container (a form-row div, a fieldBox or an inline td)."""
    split = [i for i in container.find_all("input") if re.search(r"_[01]$", i.get("name", ""))]
    if len(split) == 2 and split[0].get("name", "")[:-2] == split[1].get("name", "")[:-2]:
        parts = [i.get("value", "") for i in split]      # Django's split date + time widget
        return {"value": " ".join(x for x in parts if x), "readonly": False}
    el = None
    for cand in container.find_all(["input", "select", "textarea"]):
        if cand.get("type") in ("hidden", "submit", "button"):
            continue
        el = cand
        break
    if el is not None:
        out = {"value": _widget_value(el), "readonly": False}
        if el.get("type") == "file":
            link = container.find("a")
            out["value"] = link.get("href") if link else None
        return out
    ro = container.find(class_="readonly") or container.find("p")
    if ro is not None:
        return {"value": _readonly_value(ro), "readonly": True}
    return None


def _field_names(tag: Tag) -> List[str]:
    return [cls[len("field-"):] for cls in tag.get("class", []) if cls.startswith("field-")]


def _row_cells(row: Tag) -> Dict[str, Dict[str, Any]]:
    """Fields of one form row. A row holds several when the ModelAdmin groups fields on a line."""
    names = _field_names(row)
    out: Dict[str, Dict[str, Any]] = {}
    if len(names) > 1:
        for name in names:
            box = next((b for b in row.find_all(class_="field-" + name)
                        if "fieldBox" in b.get("class", [])), None)
            cell = _cell(box) if box is not None else None
            if cell is not None:
                out[name] = cell
        if out:
            return out
    if names:
        cell = _cell(row)
        if cell is not None:
            out[names[0]] = cell
    return out


def parse_change_form(text: str) -> Dict[str, Any]:
    """Parse the HTML of an admin add or change page.

    Returns a dict with:

    * ``fields``: ``{name: {"value": ..., "readonly": bool}}`` for every field row of the
      main form. Values are: a string for text inputs and textareas, a bool for checkboxes,
      ``{"value", "label"}`` for a select (a list of those for a multiple select, None if
      nothing is selected), the current file URL or None for file inputs, "date time" for
      the split date and time widget. Read-only fields give the recovered stored string,
      a bool or None for the yes/no/unknown icons, or ``{"text", "links"}`` when the cell
      is made of links only.
    * ``inlines``: ``{prefix: [row, ...]}`` for each inline formset, saved rows only. Each
      row maps field name to value (same value rules as above), plus ``id`` (the hidden
      primary key, a string) and ``_links`` (``{model_name: pk}`` for every link in the
      row that points at an admin change page).
    * ``logged_out``: True if the page is the admin login form instead.
    """
    doc = soup(text)
    content = doc.select_one("#content") or doc
    fields: Dict[str, Dict[str, Any]] = {}
    for row in content.select("div.form-row"):
        if row.find_parent(class_="inline-group"):
            continue
        fields.update(_row_cells(row))

    inlines: Dict[str, List[Dict[str, Any]]] = {}
    for group in content.select(".inline-group"):
        prefix = group.get("id") or ""
        if prefix.endswith("-group"):
            prefix = prefix[:-len("-group")]
        rows = []
        for tr in group.select("tr.form-row.has_original, div.inline-related.has_original"):
            row: Dict[str, Any] = {}
            hidden_id = tr.find("input", attrs={"name": re.compile(r"-\d+-id$")})
            if hidden_id is not None:
                row["id"] = hidden_id.get("value")
            for td in tr.select("td[class*=field-], div.form-row[class*=field-]"):
                names = _field_names(td)
                cell = _cell(td)
                if names and cell is not None:
                    row[names[0]] = cell["value"]
            for a in tr.find_all("a", href=True):
                m = re.search(r"/([a-z0-9_]+)/([a-z0-9_]+)/(\d+)/change/", a["href"])
                if m:
                    row.setdefault("_links", {})[m.group(2)] = int(m.group(3))
            rows.append(row)
        inlines[prefix] = rows

    return {"fields": fields, "inlines": inlines, "logged_out": is_login_page(doc)}


def field_value(form: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Shortcut for ``form["fields"][name]["value"]`` on a parsed change form."""
    cell = form["fields"].get(name)
    return default if cell is None else cell["value"]


def parse_changelist(text: str) -> Dict[str, Any]:
    """Parse the HTML of one admin change list page.

    Returns a dict with:

    * ``ids``: primary keys of the rows on this page, in display order (int when numeric,
      otherwise the string as it appears in the page).
    * ``total``: the result count the paginator shows, or None if it could not be read.
    * ``last_page``: number of the last page as labelled in the paginator (1 if there is
      only one page).
    * ``p_offset``: what to add to a page label to get its ``?p=`` value. Django's ``p``
      is 0-based before 3.2 (offset -1) and 1-based from 3.2 on (offset 0); this is read
      off the paginator links, so no Django version has to be configured.
    * ``logged_out``: True if the page is the admin login form instead.
    """
    doc = soup(text)
    ids: List[Union[int, str]] = []
    for tr in doc.select("#result_list tbody tr"):
        box = tr.find("input", attrs={"name": "_selected_action"})
        if box is not None and box.get("value"):
            ids.append(_pk(box["value"]))
            continue
        a = tr.find("a", href=_CHANGE_LINK)
        if a is not None:
            ids.append(_pk(_CHANGE_LINK.search(a["href"]).group(1)))
    pag = doc.select_one(".paginator")
    total = None
    pages: Dict[int, int] = {}
    last = 1
    if pag is not None:
        nums = re.findall(r"(\d[\d,]*)\s+[a-z]", pag.get_text(" ", strip=True))
        if nums:
            total = int(nums[-1].replace(",", ""))
        for a in pag.find_all("a", href=True):
            label = a.get_text(strip=True)
            p = parse_qs(urlparse(a["href"]).query).get("p")
            if label.isdigit() and p and p[0].isdigit():
                pages[int(label)] = int(p[0])
        current = pag.select_one(".this-page, [aria-current]")
        if current is not None and current.get_text(strip=True).isdigit():
            last = int(current.get_text(strip=True))
    offset = 0
    if pages:
        label, p = next(iter(pages.items()))
        offset = p - label
        last = max(last, max(pages))
    return {"ids": ids, "total": total, "last_page": last, "p_offset": offset,
            "logged_out": is_login_page(doc)}
