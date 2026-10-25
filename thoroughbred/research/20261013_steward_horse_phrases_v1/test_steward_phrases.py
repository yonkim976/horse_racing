import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("steward_phrases.py")
spec = importlib.util.spec_from_file_location("literal_steward_phrases", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CARD = {"meet": 3, "date": "20180223", "race": 9}


def row(text="● 출발 시 바깥쪽으로 나가 ③“위닝길리”와 접촉.", historical="20171112"):
    score = (
        f'''<a href='javascript:goScore("3","{historical}","4");'>과거 경주</a>'''
        if historical
        else ""
    )
    return f"""<tr><td>7</td><td><a href='javascript:goHrProfile("3","0030166");'>강자대로</a></td>
    <td>부경</td><td>{score}</td><td><pre>{text}</pre></td></tr>"""


def page(rows):
    return f"""<html><meta charset="utf-8"><form name="form1">
    <input name="meet" value="3"><input name="rcDate" value="20180223"><input name="rcNo" value="9">
    <div class="tableType1"><table><tr><td>2018년02월23일(금) 제9경주</td></tr></table></div>
    <div id="stewardsReportTbl"><table><tbody>{rows}</tbody></table></div></form></html>""".encode()


def test_current_program_does_not_replace_historical_identity_or_contact_partner():
    r = m.parse_page(page(row()), CARD)[0]
    assert r["horse_id"] == "0030166"
    assert r["current_program"] == 7
    assert r["event_date"] == "2017-11-12"
    assert r["event_race"] == 4
    assert "③“위닝길리”" in r["website_text_raw"]


def test_blank_row_is_preserved_as_no_history_row_not_normal_running():
    r = m.parse_page(page(row(text="", historical=None)), CARD)[0]
    assert r["field_state"] == "empty"
    assert r["event_date"] is None
    assert r["website_text_raw"] == ""


def test_same_horse_repeated_history_rows_are_not_collapsed():
    result = m.parse_page(page(row() + row(historical="20171029")), CARD)
    assert len(result) == 2
    assert {x["event_date"] for x in result} == {"2017-11-12", "2017-10-29"}


def test_dated_but_blank_official_comment_is_preserved_without_a_phrase():
    result = m.parse_page(page(row(text="  ")), CARD)[0]
    assert result["field_state"] == "empty"
    assert result["event_date"] == "2017-11-12"
    assert result["website_text_raw"] == "  "


def test_nonempty_text_requires_explicit_historical_race_link():
    with pytest.raises(ValueError, match="historical race/text mismatch"):
        m.parse_page(page(row(historical=None)), CARD)


def test_different_selected_card_cannot_be_saved_under_requested_card():
    wrong = {**CARD, "race": 8}
    with pytest.raises(ValueError, match="selected-card mismatch"):
        m.parse_page(page(row()), wrong)


def test_name_alone_cannot_substitute_for_official_id_link():
    malformed = page(row()).replace(b"0030166", b"unknown")
    with pytest.raises(ValueError, match="official horse-ID"):
        m.parse_page(malformed, CARD)


def test_two_independent_parsers_agree_on_identity_history_and_literal_text():
    content = page(row() + row(text="", historical=None))
    primary = m.parse_page(content, CARD)
    secondary = m.independent_rows(content)
    for a, b in zip(primary, secondary, strict=True):
        assert (
            a["current_program"],
            a["horse_id"],
            a["event_meet"],
            a["event_date"],
            a["event_race"],
            a["website_text_raw"],
        ) == b


def test_comparison_normalization_does_not_erase_negation_or_identity():
    assert m.normalize("● 출발이 늦었음.\r\n") == m.normalize("출발이 늦었음.")
    assert m.normalize("출발이 늦었음.") != m.normalize("출발이 늦지 않았음.")
    assert m.normalize("②“가마”는 출발이 늦었음.") != m.normalize("③“나마”는 출발이 늦었음.")


def test_html_line_ending_normalization_is_only_for_parser_parity():
    content = page(row(text="● 출발이 늦었음.\r\n"))
    primary = m.parse_page(content, CARD)[0]
    secondary = m.independent_rows(content)[0]
    assert primary["website_text_raw"].endswith("\r\n")
    assert m.parity_text(primary["website_text_raw"]) == secondary[-1]


def test_explicit_number_check_uses_historical_program_and_ignores_other_horse():
    text = "⑥“쾌속볼트”가 나가 ③“상대말”과 접촉하였음."
    assert m.own_number_status(text, {"쾌속볼트"}, 6) == "explicit_own_number_agrees"
    assert m.own_number_status(text, {"쾌속볼트"}, 2) == "conflict"


def test_subject_elision_and_same_name_horses_do_not_invent_number_conflicts():
    assert m.own_number_status("③“상대말”과 접촉.", {"쾌속볼트"}, 6) == (
        "identity_from_official_website_row"
    )
    assert m.own_number_status("③“동명마”와 ⑥“동명마”가 접촉.", {"동명마"}, 6, True) == (
        "same_name_multiple_horses_identity_from_official_row"
    )
