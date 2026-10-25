import hashlib

import pytest

from scripts import repair_steward_entry_links as repair


def item(code=94, time="0", weight="474(-6)"):
    return {"ord": code, "chulNo": 5, "rcTime": time, "wgHr": weight, "wgBudam": 56, "rating": 0}


@pytest.mark.parametrize(
    "code,label,scratched,disqualified",
    [
        (91, "실격", False, True),
        (92, "주행중지", False, False),
        (93, "출발제외", True, False),
        (94, "출전제외", True, False),
        (95, "출전취소", True, False),
    ],
)
def test_special_results_never_become_normal_placings(code, label, scratched, disqualified):
    result = repair.normalize(item(code))
    assert result["result"] == {
        "finish_position": None,
        "finish_time_ms": None,
        "rank_remark": label,
        "disqualified": disqualified,
    }
    assert result["source_outcome_code"] == code
    assert result["entry"]["scratched"] is scratched
    assert result["entry"]["body_weight_kg"] == 474
    assert result["entry"]["body_weight_change_kg"] == -6


def test_disqualified_official_time_retained_without_placing():
    result = repair.normalize(item(91, "83.8"))
    assert result["result"]["finish_time_ms"] == 83800
    assert result["result"]["finish_position"] is None
    assert result["entry"]["rating"] is None  # source 0/unrated is not invented as a rating


@pytest.mark.parametrize("code", [1, 11, 89, 90, 96, 99, 0])
def test_unknown_or_normal_codes_not_accepted(code):
    with pytest.raises(ValueError, match="not_a_verified_special_outcome"):
        repair.normalize(item(code))


def test_zero_code_requires_independent_label():
    result = repair.normalize(item(0, weight="0(0)"), zero_label="출전취소")
    assert result["result"]["rank_remark"] == "출전취소"
    assert result["entry"]["body_weight_kg"] is None
    assert result["entry"]["body_weight_change_kg"] is None
    assert result["entry"]["scratched"] is True


@pytest.mark.parametrize(
    "weight,kg,delta", [("()", None, None), ("0()", None, None), ("458()", 458, None)]
)
def test_partial_weight_does_not_invent_delta(weight, kg, delta):
    result = repair.normalize(item(weight=weight))
    assert result["entry"]["body_weight_kg"] == kg
    assert result["entry"]["body_weight_change_kg"] == delta


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-2"])
def test_invalid_numeric_values_stop(value):
    with pytest.raises(ValueError, match="invalid_numeric"):
        repair.positive(value)


def test_unknown_weight_format_stops():
    with pytest.raises(ValueError, match="unknown_body_weight"):
        repair.normalize(item(weight="unknown"))


def test_no_flag_does_not_open_files_network_or_database(monkeypatch):
    monkeypatch.setattr(repair, "connect_engine", lambda: pytest.fail("unexpected DB access"))
    assert repair.main([]) == 0


def test_archive_path_cannot_escape():
    with pytest.raises(ValueError, match="unexpected_archive_path"):
        repair.checked_archive_path(".env")


def sample_phrase():
    phrase = "원문 그대로"
    return {
        "id": 1,
        "race_id": 2,
        "horse_id": 3,
        "phrase_text": phrase,
        "phrase_sha256": hashlib.sha256(phrase.encode()).hexdigest(),
        "race_entry_id": None,
        "entry_link_status": "entry_missing",
    }


def test_link_validation_preserves_original_text():
    before = sample_phrase()
    after = before | {"race_entry_id": 44, "entry_link_status": "matched"}
    repair.check_current_phrases([after], [before], {(2, 3): 44})
    with pytest.raises(ValueError, match="original_phrase_fields_changed"):
        repair.check_current_phrases([after | {"phrase_text": "바뀐 문구"}], [before], {(2, 3): 44})
    with pytest.raises(ValueError, match="link_mismatch"):
        repair.check_current_phrases([after], [before], {(2, 3): 55})


def test_out_of_scope_size_stops():
    with pytest.raises(ValueError, match="expected_928"):
        repair.group_phrases([])


def test_audit_files_never_overwritten(tmp_path):
    path = tmp_path / "receipt.json"
    repair.save(path, {"original": True})
    with pytest.raises(FileExistsError):
        repair.save(path, {"original": False})
