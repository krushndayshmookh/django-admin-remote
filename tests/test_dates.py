from datetime import timedelta, timezone

from django_admin_remote import parse_admin_datetime


def test_display_formats():
    def d(text):
        return parse_admin_datetime(text, "Asia/Tokyo")

    assert d("Nov. 11, 2026, 1:43 p.m.") == "2026-11-11T13:43:00+09:00"
    assert d("Sept. 29, 2026, 3:03 a.m.") == "2026-09-29T03:03:00+09:00"
    assert d("March 1, 2026, 9:23 p.m.") == "2026-03-01T21:23:00+09:00"
    assert d("Nov. 3, 2026, 10 a.m.") == "2026-11-03T10:00:00+09:00"
    assert d("Oct. 30, 2026, noon") == "2026-10-30T12:00:00+09:00"
    assert d("May 30, 2023, midnight") == "2023-05-30T00:00:00+09:00"
    assert d("Dec. 24, 2025, 12:07 a.m.") == "2025-12-24T00:07:00+09:00"
    assert d("June 5, 2024, 12:30 p.m.") == "2024-06-05T12:30:00+09:00"
    assert d("June 5, 2024") == "2024-06-05T00:00:00+09:00"
    assert d("not a date") == "not a date" and d(None) is None and d("") is None


def test_widget_values_and_zones():
    assert parse_admin_datetime("2026-11-11 13:43:00", "UTC") == "2026-11-11T13:43:00+00:00"
    assert parse_admin_datetime("2026-11-11", "UTC") == "2026-11-11T00:00:00+00:00"
    # the offset follows daylight saving time of the given zone
    assert parse_admin_datetime("July 1, 2026, noon", "Europe/Paris") == "2026-07-01T12:00:00+02:00"
    assert parse_admin_datetime("Jan. 1, 2026, noon", "Europe/Paris") == "2026-01-01T12:00:00+01:00"
    fixed = timezone(timedelta(hours=-3))
    assert parse_admin_datetime("Jan. 1, 2026, noon", fixed) == "2026-01-01T12:00:00-03:00"
