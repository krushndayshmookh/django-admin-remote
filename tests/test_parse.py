from pathlib import Path

from django_admin_remote import field_value, parse_change_form, parse_changelist

FX = Path(__file__).parent / "fixtures"


def form():
    return parse_change_form((FX / "change_form.html").read_text())


def wrap(rows):
    return f'<html><body><div id="content"><form>{rows}</form></div></body></html>'


def test_fields():
    f = form()
    assert field_value(f, "question_title") == "TEST_sum_two_numbers"
    qt = field_value(f, "question_text")
    assert qt.startswith("[TEST question") and "<br />\n<br />" in qt and "<code>a</code>" in qt
    assert field_value(f, "usage") == [{"value": "1", "label": "Normal"}]
    assert field_value(f, "question_type") == "Coding"
    assert f["fields"]["question_type"]["readonly"] is True
    assert f["fields"]["question_title"]["readonly"] is False
    assert field_value(f, "peer_reviewed") is False
    assert field_value(f, "verified") is True
    assert field_value(f, "difficulty_type") == "Beginner"
    assert field_value(f, "created_by") == {"text": "alice", "links": ["/admin/auth/user/1/change/"]}
    assert field_value(f, "copy_question_share_url").endswith("/q7x2m9k4t1bz")
    assert field_value(f, "missing", "fallback") == "fallback"
    assert f["logged_out"] is False


def test_readonly_is_unescaped_once():
    assert field_value(form(), "constraints") == "-1000 &lt;= a, b &lt;= 1000\nsecond line"


def test_readonly_keeps_trailing_newlines_and_leading_spaces():
    f = parse_change_form(wrap(
        '<div class="form-row field-out"><div class="readonly">  5<br>6<br><br></div></div>'
        '<div class="form-row field-empty"><div class="readonly">-</div></div>'
        '<div class="form-row field-amp"><div class="readonly">a &amp; b &lt;i&gt;</div></div>'))
    assert field_value(f, "out") == "  5\n6\n\n"
    assert field_value(f, "empty") == ""
    assert field_value(f, "amp") == "a & b <i>"


def test_inlines():
    inl = form()["inlines"]
    lang = inl["question_language_mappings"][0]
    assert lang["id"] == "88492" and lang["language_id"] == "Python (3.13.1)"
    assert lang["_links"]["questionlanguagemapping"] == 88492
    tc = inl["question_test_case_mappings"][0]
    assert tc["input"] == "2 3\n" and tc["output"] == "5\n" and tc["hidden"] is False and tc["input_file"] == ""
    topics = inl["question_topic_mappings"]
    assert len(topics) == 1, "the empty-form template row must be skipped"
    t = topics[0]
    assert t["topic"] == {"text": "Python Input", "links": ["/admin/quiz/topic/4476/change/"]}
    assert t["_links"]["topic"] == 4476
    assert t["question_difficulty_type"] == {"value": "1", "label": "Beginner"}
    assert t["question_utility_type"]["label"] == "Application"
    assert t["relevance"] == "0" and t["mandatory"] is True and t["main_topic"] is False
    stat = inl["question_statistic"][0]
    assert (stat["attempt_count"], stat["solved_count"]) == ("4", "1")


def test_split_date_time_widget():
    f = parse_change_form(wrap(
        '<div class="form-row field-starts_at"><p class="datetime">'
        'Date: <input type="text" name="starts_at_0" value="2026-11-11" class="vDateField">'
        'Time: <input type="text" name="starts_at_1" value="13:43:00" class="vTimeField"></p></div>'
        '<div class="form-row field-ends_at"><p class="datetime">'
        '<input type="text" name="ends_at_0" value="2026-12-01"><input type="text" name="ends_at_1" value=""></p></div>'))
    assert f["fields"]["starts_at"] == {"value": "2026-11-11 13:43:00", "readonly": False}
    assert field_value(f, "ends_at") == "2026-12-01"


def test_several_fields_on_one_row():
    f = parse_change_form(wrap(
        '<div class="form-row field-first field-last"><div class="flex-container form-multiline">'
        '<div><div class="flex-container fieldBox field-first"><input type="text" name="first" value="Ada"></div></div>'
        '<div><div class="flex-container fieldBox field-last"><div class="readonly">Lovelace</div></div></div>'
        '</div></div>'))
    assert f["fields"]["first"] == {"value": "Ada", "readonly": False}
    assert f["fields"]["last"] == {"value": "Lovelace", "readonly": True}


def test_login_page_is_flagged():
    page = '<div id="content"><form id="login-form"><input name="username"></form></div>'
    assert parse_change_form(page)["logged_out"] is True
    assert parse_changelist(page)["logged_out"] is True


def test_changelist():
    c = parse_changelist((FX / "changelist.html").read_text())
    assert c["ids"] == [28436, 28435]
    assert c["total"] == 28932 and c["last_page"] == 290 and c["p_offset"] == 0


def changelist_page(paginator, rows=""):
    return f'<div id="content"><table id="result_list"><tbody>{rows}</tbody></table>{paginator}</div>'


def test_changelist_one_based_pages():
    c = parse_changelist(changelist_page(
        '<p class="paginator"><span class="this-page">1</span> <a href="?p=2">2</a> '
        '<a href="?p=3" class="end">3</a> 250 things</p>'))
    assert (c["last_page"], c["p_offset"], c["total"]) == (3, 0, 250)


def test_changelist_zero_based_pages():
    c = parse_changelist(changelist_page(
        '<p class="paginator"><span class="this-page">1</span> <a href="?p=1">2</a> '
        '<a href="?p=2" class="end">3</a> 250 things</p>'))
    assert (c["last_page"], c["p_offset"], c["total"]) == (3, -1, 250)


def test_changelist_single_page_and_last_page():
    one = parse_changelist(changelist_page('<p class="paginator">2 things</p>'))
    assert (one["last_page"], one["p_offset"], one["total"]) == (1, 0, 2)
    on_last = parse_changelist(changelist_page(
        '<p class="paginator"><a href="?p=1">1</a> <a href="?p=2">2</a> <span class="this-page">3</span> 250 things</p>'))
    assert (on_last["last_page"], on_last["p_offset"]) == (3, 0)


def test_changelist_ids_prefer_the_row_checkbox():
    rows = (
        '<tr><td class="action-checkbox"><input type="checkbox" name="_selected_action" value="7"></td>'
        '<td><a href="/admin/app/other/99/change/">related</a></td>'
        '<th><a href="/admin/app/thing/7/change/">seven</a></th></tr>'
        '<tr><th><a href="/admin/app/thing/abc-def/change/">text key</a></th></tr>')
    assert parse_changelist(changelist_page("", rows))["ids"] == [7, "abc-def"]


def test_changelist_nav_paginator_of_newer_django():
    c = parse_changelist(changelist_page(
        '<nav class="paginator" aria-labelledby="pagination"><h2 id="pagination">Pagination posts</h2><ul>'
        '<li><a role="button" href="" aria-current="page">1</a> </li>'
        '<li><a role="button" href="?p=2">2</a> </li><li><a role="button" href="?p=3">3</a> </li>'
        '</ul>251 posts</nav>'))
    assert (c["last_page"], c["p_offset"], c["total"]) == (3, 0, 251)
    on_last = parse_changelist(changelist_page(
        '<nav class="paginator"><ul><li><a href="?p=1">1</a></li><li><a href="?p=2">2</a></li>'
        '<li><a href="" aria-current="page">3</a></li></ul>251 posts</nav>'))
    assert (on_last["last_page"], on_last["p_offset"]) == (3, 0)
