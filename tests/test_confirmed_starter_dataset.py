from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import horse_racing.analysis.confirmed_starter_dataset as e2
from horse_racing.analysis.confirmed_starter_dataset import (
    END_DATE,
    FIELD_KIND,
    ConfirmedStarterConditionalManifest,
    ConfirmedStarterContractError,
    _apply_modules,
    _fetch_rows,
    _predictor_base,
    _value_equal,
    build_predictors,
    confirmed_starter_labels,
    key_sha256,
    recompute_ability_vs_actual_field,
    recompute_horse_jockey_history,
    validate_dataset_against_manifest,
    validate_retrospective_manifest,
)
from horse_racing.analysis.features import ability, form, load_source_frames, style
from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.pre_race_field_contract import SealedFieldManifest

ROOT = Path(__file__).resolve().parents[1]


def _manifest(*keys: tuple[int, int]) -> ConfirmedStarterConditionalManifest:
    return ConfirmedStarterConditionalManifest(
        manifest_id="a-test",
        source_ids=("evidence:test",),
        field_kind=FIELD_KIND,
        selection_basis="post-event confirmed starter",
        meet_code=1,
        date_start="2025-01-04",
        date_end=END_DATE,
        actual_result_upper_bound=END_DATE,
        expected_keys=keys,
        key_sha256=key_sha256(keys),
        complete=True,
    )


def _rows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_entry_id": [11, 12, 13, 14],
            "race_date_local": ["2026-05-01"] * 4,
            "scheduled_at_ms": [10_000_000] * 4,
            "finish_position": [1, 2, 92, 91],
            "finish_time_ms": [70_000, 71_000, None, 72_000],
            "rank_remark": [None, None, "주행중지", "실격"],
            "scratched": [False] * 4,
            "disqualified": [False] * 4,
            "result_id": [1, 2, 3, 4],
            "margin_text": [None] * 4,
            "horse_number": [1, 2, 3, 4],
        }
    )


def test_retrospective_manifest_is_not_pre_race_sealed_field() -> None:
    sealed = SealedFieldManifest(
        snapshot_id="pre-race",
        source_id="source",
        race_id=1,
        cutoff_at_ms=100,
        sealed_at_ms=100,
        expected_keys=((1, 11),),
        complete=True,
        completeness_basis="synthetic",
    )
    with pytest.raises(ConfirmedStarterContractError, match="cannot represent retrospective"):
        validate_retrospective_manifest(sealed)


def test_independent_a_detects_missing_extra_duplicate_and_symmetric_deletion() -> None:
    manifest = _manifest((1, 11), (1, 12), (1, 13))
    exact = pl.DataFrame({"race_id": [1, 1, 1], "race_entry_id": [11, 12, 13]})
    validate_dataset_against_manifest(manifest, exact)

    for bad in (
        exact.head(2),
        pl.DataFrame({"race_id": [1, 1, 1], "race_entry_id": [11, 12, 14]}),
        pl.DataFrame({"race_id": [1, 1, 1], "race_entry_id": [11, 12, 12]}),
    ):
        with pytest.raises(ValueError, match="missing|extra|duplicate"):
            validate_dataset_against_manifest(manifest, bad)


def test_manifest_hash_and_kind_are_fail_closed() -> None:
    manifest = _manifest((1, 11))
    with pytest.raises(ConfirmedStarterContractError, match="key hash"):
        validate_retrospective_manifest(replace(manifest, key_sha256="wrong"))
    with pytest.raises(ConfirmedStarterContractError, match="field kind"):
        validate_retrospective_manifest(replace(manifest, field_kind="pre_race_sealed"))


def test_dnf_and_disqualification_are_zero_labels_with_masked_auxiliaries() -> None:
    labeled = confirmed_starter_labels(_rows()).sort("race_entry_id")
    assert labeled["outcome_state"].to_list() == [
        "normal_finish",
        "normal_finish",
        "started_dnf",
        "disqualified",
    ]
    special = labeled.filter(pl.col("outcome_state") != "normal_finish")
    assert special.select("win", "top2", "top3").to_dict(as_series=False) == {
        "win": [0, 0],
        "top2": [0, 0],
        "top3": [0, 0],
    }
    assert special["finish_position_target"].null_count() == 2
    assert special["finish_time_ms_target"].null_count() == 2
    assert special["auxiliary_rank_observed"].to_list() == [False, False]
    assert special["auxiliary_finish_time_observed"].to_list() == [False, False]


def test_target_changes_do_not_change_predictor_base_or_a_denominator() -> None:
    labeled = confirmed_starter_labels(_rows())
    changed = labeled.with_columns(
        pl.when(pl.col("race_entry_id") == 11)
        .then(92)
        .otherwise(pl.col("finish_position"))
        .alias("finish_position"),
        pl.when(pl.col("race_entry_id") == 11)
        .then(pl.lit("주행중지"))
        .otherwise(pl.col("rank_remark"))
        .alias("rank_remark"),
        pl.when(pl.col("race_entry_id") == 12)
        .then(999_999)
        .otherwise(pl.col("finish_time_ms"))
        .alias("finish_time_ms"),
    )
    before = _predictor_base(labeled)
    after = _predictor_base(changed)
    assert before.equals(after)
    assert before["starters"].unique().to_list() == [4]
    assert "finish_position" not in before.columns
    assert "finish_time_ms" not in before.columns


def test_value_equal_distinguishes_null_transitions_and_non_finite_values() -> None:
    left = pl.Series([None, 1.0, None, 1.0, 1.0, float("nan"), float("inf")])
    right = pl.Series([2.0, None, None, 1.0 + 5e-13, 1.1, float("nan"), float("inf")])
    assert _value_equal(left, right).to_list() == [False, False, True, True, False, False, False]


def test_ability_vs_field_uses_every_actual_field_member() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1],
            "race_entry_id": [11, 12, 13],
            "outcome_state": ["normal_finish", "started_dnf", "disqualified"],
            "ability_elo_global": [1510.0, 1490.0, 1530.0],
        }
    )
    result = recompute_ability_vs_actual_field(frame)
    assert result["ability_elo_vs_field"].to_list() == pytest.approx([0.0, -30.0, 30.0])
    switched = recompute_ability_vs_actual_field(
        frame.with_columns(
            pl.Series("outcome_state", ["started_dnf", "disqualified", "normal_finish"])
        )
    )
    assert switched["ability_elo_vs_field"].to_list() == pytest.approx([0.0, -30.0, 30.0])


def test_build_predictors_does_not_branch_on_result_state(monkeypatch: pytest.MonkeyPatch) -> None:
    starters = pl.DataFrame(
        {
            "race_id": [7, 7, 7],
            "race_entry_id": [71, 72, 73],
            "race_date_local": ["2026-05-01"] * 3,
            "race_number": [1, 1, 1],
            "scheduled_at_ms": [1_800_000] * 3,
            "meet_code": [1, 1, 1],
            "distance_m": [1200, 1200, 1200],
            "horse_id": [701, 702, 703],
            "jockey_id": [801, 802, 803],
            "trainer_id": [901, 902, 903],
            "horse_number": [1, 2, 3],
            "gate_number": [1, 2, 3],
            "body_weight_kg": [470, 480, 490],
            "outcome_state": ["normal_finish", "started_dnf", "disqualified"],
            "result_id": [1, 2, 3],
            "finish_position": [1, 92, 91],
            "finish_time_ms": [72_000, None, None],
            "margin_text": [None, None, None],
            "rank_remark": [None, "주행중지", "실격"],
            "scratched": [False, False, False],
            "disqualified": [False, False, True],
        }
    )

    def fake_apply_modules(
        frame: pl.DataFrame, sources: SourceFrames, modules: tuple[object, ...]
    ) -> pl.DataFrame:
        del sources
        result = frame
        if "race_date" not in result.columns:
            result = result.with_columns(
                pl.col("race_date_local").cast(pl.Utf8).str.to_date().alias("race_date")
            )
        expressions = []
        for module in modules:
            for spec in module.FEATURES:  # type: ignore[attr-defined]
                value = (
                    1500.0 + pl.col("horse_number").cast(pl.Float64) * 10.0
                    if spec.name == "ability_elo_global"
                    else pl.col("horse_number").cast(pl.Float64)
                )
                expressions.append(value.alias(spec.name))
        return result.with_columns(expressions)

    monkeypatch.setattr(e2, "_apply_modules", fake_apply_modules)
    sources = SourceFrames(
        past_results=pl.DataFrame(
            {"race_entry_id": [999], "race_date": ["2025-01-01"]},
            schema_overrides={"race_date": pl.Date},
        ),
        sections=pl.DataFrame(schema={"race_date": pl.Date}),
    )
    before = build_predictors(starters, sources)
    changed = starters.with_columns(
        pl.Series("outcome_state", ["started_dnf", "disqualified", "normal_finish"]),
        pl.Series("finish_position", [92, 91, 3]),
        pl.Series("finish_time_ms", [None, None, 999_999], dtype=pl.Int64),
        pl.Series("rank_remark", ["주행중지", "실격", None]),
        pl.Series("disqualified", [False, True, False]),
    )
    after = build_predictors(changed, sources)
    assert before.equals(after)


def test_synthetic_dnf_null_anchor_does_not_update_future_elo() -> None:
    history = pl.DataFrame(
        {
            "race_entry_id": [1, 2, 31, 3, 4],
            "race_id": [1, 1, -31, 3, 3],
            "horse_id": [1, 2, 1, 1, 2],
            "race_date": [
                "2026-01-01",
                "2026-01-01",
                "2026-02-01",
                "2026-03-01",
                "2026-03-01",
            ],
            "meet_code": [1, 1, 1, 1, 1],
            "distance_m": [1200, 1200, 1200, 1200, 1200],
            "finish_position": [1, 2, None, 2, 1],
        },
        schema_overrides={"finish_position": pl.Int64},
    ).with_columns(pl.col("race_date").str.to_date())
    without_anchor = history.filter(pl.col("race_entry_id") != 31)

    with_result = ability.add_features(
        history.drop("finish_position"), SourceFrames(past_results=history)
    )
    without_result = ability.add_features(
        without_anchor.drop("finish_position"), SourceFrames(past_results=without_anchor)
    )
    names = [
        "ability_elo_global",
        "ability_elo_global_starts",
        "ability_elo_context",
        "ability_elo_context_starts",
        "ability_elo_uncertainty",
    ]
    assert (
        with_result.filter(pl.col("race_entry_id") == 3)
        .select(names)
        .equals(without_result.filter(pl.col("race_entry_id") == 3).select(names))
    )


def test_h1_combo_history_uses_pair_and_strict_prior_date_without_target_row() -> None:
    frame = pl.DataFrame(
        {
            "race_entry_id": [101, 102, 103, 104],
            "horse_id": [1, 1, 2, 3],
            "jockey_id": [10, 10, 20, None],
            "race_date": ["2026-01-01", "2026-03-01", "2026-03-01", "2026-03-01"],
            "horse_jockey_starts": [99, 99, 99, 99],
            "horse_jockey_wins": [99, 99, 99, 99],
            "horse_jockey_first": [99, 99, 99, 99],
        },
        schema_overrides={"jockey_id": pl.Int64},
    ).with_columns(pl.col("race_date").str.to_date())
    past = pl.DataFrame(
        {
            "race_entry_id": [1, 2, 3, 4],
            "horse_id": [1, 1, 1, 2],
            "jockey_id": [10, 10, 10, 20],
            "race_date": ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
            "finish_position": [1, 2, 1, 1],
        }
    ).with_columns(pl.col("race_date").str.to_date())

    result = recompute_horse_jockey_history(frame, past).sort("race_entry_id")
    assert result.select("horse_jockey_starts", "horse_jockey_wins", "horse_jockey_first").to_dict(
        as_series=False
    ) == {
        "horse_jockey_starts": [0, 2, 0, None],
        "horse_jockey_wins": [0, 1, 0, None],
        "horse_jockey_first": [1, 0, 1, None],
    }
    validation = e2.independently_validate_horse_jockey_history(result, past)
    assert validation["checked_rows"] == 4
    assert validation["all_match"] is True


def test_h1_actual_modules_ignore_target_presence_state_values_and_synthetic_future() -> None:
    engine = create_engine(f"sqlite:///file:{ROOT / 'data/horse_racing.sqlite3'}?mode=ro&uri=true")
    with Session(engine) as session:
        starters = confirmed_starter_labels(_fetch_rows(session)).filter(pl.col("race_id") == 1849)
        loaded = load_source_frames(session, race_date_max=END_DATE)
    engine.dispose()

    horse_ids = starters["horse_id"].unique().to_list()
    reduced: dict[str, pl.DataFrame] = {}
    for name in loaded.__dataclass_fields__:
        source = getattr(loaded, name)
        reduced[name] = (
            source.filter(pl.col("horse_id").is_in(horse_ids))
            if "horse_id" in source.columns
            else source.head(0)
        )
    sources = replace(loaded, **reduced)
    baseline = build_predictors(starters, sources)
    selected = e2.select_profile_features(
        e2.feature_names(baseline, feature_set=e2.FEATURE_SET), e2.MODEL_PROFILE
    )

    target_date = date(2025, 1, 26)
    no_target = replace(
        sources,
        past_results=sources.past_results.filter(pl.col("race_date") < target_date),
        sections=sources.sections.filter(pl.col("race_date") < target_date),
    )
    switched = starters.with_columns(
        pl.when(pl.col("outcome_state") == "normal_finish")
        .then(pl.lit("started_dnf"))
        .otherwise(pl.lit("normal_finish"))
        .alias("outcome_state"),
        pl.lit(91).alias("finish_position"),
        pl.lit(999_999).alias("finish_time_ms"),
        pl.lit("합성 변경").alias("rank_remark"),
    )
    without_target = build_predictors(switched, no_target)

    changed_current = replace(
        sources,
        past_results=sources.past_results.with_columns(
            pl.when(pl.col("race_date") == target_date)
            .then(89)
            .otherwise(pl.col("finish_position"))
            .alias("finish_position"),
            pl.when(pl.col("race_date") == target_date)
            .then(999_999)
            .otherwise(pl.col("finish_time_ms"))
            .alias("finish_time_ms"),
        ),
        sections=sources.sections.with_columns(
            pl.when(pl.col("race_date") == target_date)
            .then(99)
            .otherwise(pl.col("position"))
            .alias("position"),
            pl.when(pl.col("race_date") == target_date)
            .then(999_999)
            .otherwise(pl.col("elapsed_time_ms"))
            .alias("elapsed_time_ms"),
        ),
    )
    with_changed_current = build_predictors(switched, changed_current)

    future_past = no_target.past_results.head(1).with_columns(
        pl.lit(9_000_001).alias("race_entry_id"),
        pl.lit(9_000_001).alias("race_id"),
        pl.lit(date(2026, 6, 1)).alias("race_date"),
        pl.lit(1).alias("finish_position"),
        pl.lit(60_000).alias("finish_time_ms"),
    )
    future_sections = no_target.sections.head(1).with_columns(
        pl.lit(9_000_001).alias("race_entry_id"),
        pl.lit(9_000_001).alias("race_id"),
        pl.lit(date(2026, 6, 1)).alias("race_date"),
        pl.lit(1).alias("position"),
        pl.lit(1).alias("elapsed_time_ms"),
    )
    with_future = build_predictors(
        switched,
        replace(
            no_target,
            past_results=pl.concat([no_target.past_results, future_past], how="vertical_relaxed"),
            sections=pl.concat([no_target.sections, future_sections], how="vertical_relaxed"),
        ),
    )

    for candidate in (without_target, with_changed_current, with_future):
        for name in selected:
            assert _value_equal(baseline[name], candidate[name]).all(), name


def test_did_not_start_and_conflict_are_not_coerced_to_zero() -> None:
    extra = pl.DataFrame(
        {
            **_rows().to_dict(as_series=False),
        }
    ).with_columns(
        pl.when(pl.col("race_entry_id") == 14)
        .then(95)
        .otherwise(pl.col("finish_position"))
        .alias("finish_position"),
        pl.when(pl.col("race_entry_id") == 14)
        .then(pl.lit("출전취소"))
        .otherwise(pl.col("rank_remark"))
        .alias("rank_remark"),
        pl.when(pl.col("race_entry_id") == 14)
        .then(True)
        .otherwise(pl.col("scratched"))
        .alias("scratched"),
    )
    labeled = confirmed_starter_labels(extra)
    assert 14 not in labeled["race_entry_id"].to_list()


def test_target_result_and_sections_do_not_change_target_history_predictors() -> None:
    dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    past = pl.DataFrame(
        {
            "horse_id": [1, 1, 1, 1],
            "race_entry_id": [101, 102, 103, 104],
            "race_id": [11, 12, 13, 14],
            "race_date": dates,
            "distance_m": [1200, 1200, 1200, 1200],
            "meet_code": [1, 1, 1, 1],
            "finish_position": [2, 3, 1, 4],
            "finish_time_ms": [73_000, 74_000, 70_000, 75_000],
            "starters": [10, 10, 10, 10],
        }
    ).with_columns(pl.col("race_date").str.to_date())
    sections = pl.DataFrame(
        {
            "horse_id": [1, 1, 1, 1],
            "race_entry_id": [101, 102, 103, 104],
            "race_id": [11, 12, 13, 14],
            "race_date": dates,
            "section_code": ["S1F", "S1F", "S1F", "S1F"],
            "position": [3, 4, 1, 5],
            "elapsed_time_ms": [14_000, 14_100, 13_000, 14_500],
        }
    ).with_columns(pl.col("race_date").str.to_date())
    target = pl.DataFrame(
        {
            "race_entry_id": [103],
            "horse_id": [1],
            "race_id": [13],
            "race_date_local": ["2026-03-01"],
            "distance_m": [1200],
            "meet_code": [1],
        }
    )
    before = _apply_modules(
        target, SourceFrames(past_results=past, sections=sections), (form, style)
    )
    changed_past = past.with_columns(
        pl.when(pl.col("race_entry_id").is_in([103, 104]))
        .then(88)
        .otherwise(pl.col("finish_position"))
        .alias("finish_position"),
        pl.when(pl.col("race_entry_id").is_in([103, 104]))
        .then(999_999)
        .otherwise(pl.col("finish_time_ms"))
        .alias("finish_time_ms"),
    )
    changed_sections = sections.with_columns(
        pl.when(pl.col("race_entry_id").is_in([103, 104]))
        .then(99)
        .otherwise(pl.col("position"))
        .alias("position"),
        pl.when(pl.col("race_entry_id").is_in([103, 104]))
        .then(999_999)
        .otherwise(pl.col("elapsed_time_ms"))
        .alias("elapsed_time_ms"),
    )
    after = _apply_modules(
        target,
        SourceFrames(past_results=changed_past, sections=changed_sections),
        (form, style),
    )
    names = [spec.name for module in (form, style) for spec in module.FEATURES]
    assert before.select(names).equals(after.select(names))


def test_generated_e2_artifact_has_exact_a_keys_splits_and_field_denominators() -> None:
    dataset = pl.read_parquet(
        ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/"
        "start_minus_30m/dataset.parquet"
    )
    manifest = json.loads(
        (
            ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/"
            "start_minus_30m/manifest.json"
        ).read_text()
    )
    evidence = pl.read_parquet(
        ROOT / "data/logs/pre_race_field_dnf_evidence_e1_v2_20260911.parquet"
    ).filter(pl.col("outcome_state_e1").is_in(["normal_finish", "started_dnf", "disqualified"]))
    assert set(dataset.select("race_id", "race_entry_id").iter_rows()) == set(
        evidence.select("race_id", "race_entry_id").iter_rows()
    )
    assert dataset.height == 15_579
    assert dataset["race_id"].n_unique() == 1_488
    assert dataset.filter(pl.col("race_date_local") <= "2026-02-28").height == 12_528
    assert dataset.filter(pl.col("race_date_local") >= "2026-03-01").height == 3_051
    group_sizes = dataset.group_by("race_id").len().rename({"len": "expected_starters"})
    checked = dataset.join(group_sizes, on="race_id")
    assert checked.filter(pl.col("starters") != pl.col("expected_starters")).height == 0
    special = dataset.filter(pl.col("outcome_state") != "normal_finish")
    assert special.height == 48
    assert special.select(pl.sum("win"), pl.sum("top2"), pl.sum("top3")).row(0) == (0, 0, 0)
    assert special["finish_position_target"].null_count() == 48
    assert special["finish_time_ms_target"].null_count() == 48
    assert len(manifest["selected_feature_names"]) == 136
    assert manifest["independent_horse_jockey_validation"]["all_match"] is True
    assert manifest["previous_e2_comparison"]["changed_rows"] == 30
    assert manifest["previous_e2_comparison"]["selected_changed_cells"] == 71
    independently_expected = dataset.with_columns(
        (
            pl.col("ability_elo_global")
            - (pl.col("ability_elo_global").sum().over("race_id") - pl.col("ability_elo_global"))
            / (pl.len().over("race_id") - 1)
        ).alias("expected_ability_elo_vs_field")
    )
    assert (
        independently_expected.filter(
            (pl.col("ability_elo_vs_field") - pl.col("expected_ability_elo_vs_field")).abs() > 1e-12
        ).height
        == 0
    )
    assert special.filter(pl.col("ability_elo_vs_field") == 0.0).height == 1
