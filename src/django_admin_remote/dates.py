"""Turn the dates the Django admin displays into ISO 8601 strings."""
from __future__ import annotations

import re
from datetime import datetime, tzinfo
from typing import Optional, Union
from zoneinfo import ZoneInfo

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _zone(tz: Union[str, tzinfo]) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def parse_admin_datetime(text: Optional[str], tz: Union[str, tzinfo]) -> Optional[str]:
    """Convert a date or datetime shown by the Django admin to ISO 8601 with a UTC offset.

    The admin shows datetimes in the server's current time zone without saying which one,
    so the caller has to supply it.

    Args:
        text: what the admin displayed. Understands Django's default English formats
            ("Nov. 11, 2026, 1:43 p.m.", "Sept. 29, 2026, 3:03 a.m.", "March 1, 2026, 9 p.m.",
            "Oct. 30, 2026, noon", "May 30, 2023, midnight", "May 30, 2023") and the values of
            editable date and time widgets ("2026-11-11", "2026-11-11 13:43:00").
        tz: the time zone the admin displays in, as an IANA name ("Europe/Paris") or a tzinfo.

    Returns:
        An ISO 8601 string such as "2026-11-11T13:43:00+01:00". None for empty input.
        Text that does not look like a date is returned unchanged, so nothing is lost silently.
    """
    if not text:
        return None
    zone = _zone(tz)
    iso = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*", text)
    if iso:
        y, mo, d, h, mi, sec = (int(x or 0) for x in iso.groups())
        return datetime(y, mo, d, h, mi, sec, tzinfo=zone).isoformat()
    m = re.fullmatch(r"\s*([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})(?:,\s*(.+?))?\s*", text)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        return text
    month, day, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
    clock = (m.group(4) or "midnight").lower()
    if clock == "noon":
        hour, minute = 12, 0
    elif clock == "midnight":
        hour, minute = 0, 0
    else:
        t = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", clock)
        if not t:
            return text
        hour, minute = int(t.group(1)) % 12, int(t.group(2) or 0)
        if t.group(3) == "p":
            hour += 12
    return datetime(year, month, day, hour, minute, tzinfo=zone).isoformat()
