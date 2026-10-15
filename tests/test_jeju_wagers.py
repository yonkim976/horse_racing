"""Full-support wager events must reproduce the frozen HY_R_FORM joint."""

from datetime import date
from itertools import combinations
from math import comb, fsum, perm

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from horse_racing.analysis.jeju_hybrid_evaluation import distribution
from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    ModelPrediction,
    OddsSnapshot,
    PredictionModelComponent,
    PredictionRun,
    Race,
    Racecourse,
    RaceEntry,
)
from horse_racing.web.jeju_wagers import load_jeju_wagers, wager_probabilities


@pytest.mark.parametrize("n", [3, 5, 7, 8, 10, 12])
def test_all_wager_events_match_frozen_distribution(n):
    rng = np.random.default_rng(n)
    rank, order = rng.normal(0, 3, (2, n))
    numbers = tuple(range(1, n + 1))
    rows = tuple(zip(numbers, rank, order, strict=True))
    pools = {code: dict(values) for code, values in wager_probabilities(rows, 0.8, 1.3)}
    _, orders, _, joint, _ = distribution(rank, order, 0.8, 1.3)
    expected = {code: {} for code in pools}
    for layout, logp in zip(orders, joint, strict=True):
        a, b, c = (numbers[index] for index in layout)
        events = {
            "WIN": [(a,)],
            "PLC": [(t,) for t in ((a, b) if n <= 7 else (a, b, c))],
            "QNL": [tuple(sorted((a, b)))],
            "EXA": [(a, b)],
            "QPL": [tuple(sorted(pair)) for pair in combinations((a, b, c), 2)],
            "TLA": [tuple(sorted((a, b, c)))],
            "TRI": [(a, b, c)],
        }
        for code, selections in events.items():
            for selection in selections:
                expected[code][selection] = expected[code].get(selection, 0) + np.exp(logp)
    counts = {
        "WIN": n,
        "PLC": n,
        "QNL": comb(n, 2),
        "QPL": comb(n, 2),
        "EXA": perm(n, 2),
        "TLA": comb(n, 3),
        "TRI": perm(n, 3),
    }
    for code, values in pools.items():
        assert len(values) == counts[code]
        assert values == pytest.approx(expected[code], abs=1e-12)
        total = 3 if code == "QPL" else (2 if n <= 7 else 3) if code == "PLC" else 1
        assert fsum(values.values()) == pytest.approx(total)


def test_zero_mass_and_extreme_scores_are_finite_and_cache_is_immutable():
    runners = ((1, 900.0, -900.0), (2, 0.0, 0.0), (3, -900.0, 900.0), (4, -950.0, 950.0))
    first = wager_probabilities(runners, 1.0, 1.0)
    assert first is wager_probabilities(runners, 1.0, 1.0)
    assert all(0 <= p <= 1 for _, values in first for _, p in values)
    assert sum(p for _, p in dict(first)["TRI"]) == pytest.approx(1)
    with pytest.raises(ValueError):
        wager_probabilities(runners, 0, 1)


@pytest.fixture
def published():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        track = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        db.add(track)
        db.flush()
        race = Race(
            racecourse_id=track.id,
            race_date_local=date(2026, 10, 9),
            race_number=1,
            status="scheduled",
            distance_m=900,
            field_size=8,
        )
        run = PredictionRun(
            public_id="test-jeju",
            experiment_run_id="test-experiment",
            model_type="registered_main_prediction",
            dataset_version="HY_R_FORM",
            as_of_policy="day_before_18",
            race_date_local=date(2026, 10, 9),
            feature_cutoff_at_ms=1,
            published_at_ms=2,
            publication_mode="live",
            model_artifact_sha256="a" * 64,
            feature_hash="b" * 64,
            predictions_sha256="c" * 64,
            domain="jeju",
            combination_algorithm_version="jeju_hybrid_distribution_v1",
        )
        db.add_all([race, run])
        db.flush()
        db.add(
            PredictionModelComponent(
                prediction_run_id=run.id,
                component="A_B_C",
                model_version="frozen_2026_HY_R_FORM",
                candidate_name="HY_R_FORM",
                artifact_sha256="a" * 64,
                parameters_json="{}",
            )
        )
        entries, predictions = [], []
        for number in range(1, 9):
            horse = Horse(kra_horse_id=f"test-{number}", name_ko=f"검증마{number}")
            db.add(horse)
            db.flush()
            entry = RaceEntry(race_id=race.id, horse_id=horse.id, horse_number=number)
            db.add(entry)
            db.flush()
            prediction = ModelPrediction(
                prediction_run_id=run.id,
                race_id=race.id,
                race_entry_id=entry.id,
                horse_number=number,
                prob_win=1 / 8,
                prob_top2=2 / 8,
                prob_top3=3 / 8,
                raw_rank_score=0,
                raw_order_score=0,
                beta_set=1,
                beta_order=1,
                field_size=8,
                starter_status="starter",
            )
            entries.append(entry)
            predictions.append(prediction)
            db.add(prediction)
        # Final odds must not be mistaken for a prepurchase quote.
        db.add(
            OddsSnapshot(
                race_id=race.id,
                bet_type="TLA",
                selection_key="1-2-3",
                odds=999.9,
                observed_at_ms=99,
            )
        )
        db.flush()
        yield db, race, entries, predictions
    engine.dispose()


def test_loader_complete_publication_and_page_integration(published):
    from horse_racing.web.insights import load_forecast_page
    from horse_racing.web.race_analysis import load_race_analysis_page

    db, race, _, _ = published
    result = load_jeju_wagers(db, race_id=race.id, meet_code=2)
    assert result["message"] == ""
    assert result["public_id"] == "test-jeju"
    assert len(result["pools"]) == 7
    trio = next(pool for pool in result["pools"] if pool["code"] == "TLA")
    assert trio["count"] == 56
    assert trio["rows"][0]["probability"] == pytest.approx(1 / 56)
    assert "odds" not in trio["rows"][0]
    assert load_jeju_wagers(db, race_id=race.id, meet_code=1) is None
    assert load_forecast_page(db, race_id=race.id).jeju_wagers == result
    assert load_race_analysis_page(db, race_id=race.id).jeju_wagers == result


def test_loader_does_not_reweight_after_scratch_or_fill_missing_scores(published):
    db, race, entries, predictions = published
    entries[0].scratched = True
    assert not load_jeju_wagers(db, race_id=race.id, meet_code=2)["pools"]
    entries[0].scratched = False
    predictions[0].raw_rank_score = None
    assert not load_jeju_wagers(db, race_id=race.id, meet_code=2)["pools"]
    predictions[0].raw_rank_score = 0
    predictions[0].prob_win = 0.9
    assert not load_jeju_wagers(db, race_id=race.id, meet_code=2)["pools"]


def test_desktop_and_mobile_render_full_probability_data_and_comparison_controls(published):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient

    from horse_racing.web.app import create_app

    db, race, _, _ = published
    race_id = race.id
    db.commit()
    with TestClient(create_app(session_factory=sessionmaker(db.bind))) as client:
        forecast = client.get(f"/analysis?race_id={race_id}&layout=desktop&tab=forecast")
        assert forecast.status_code == 200
        forecast_doc = BeautifulSoup(forecast.text, "html.parser")
        assert forecast_doc.select_one('[data-analysis-tab="wagers"]') is not None
        assert forecast_doc.select_one('[data-jeju-wagers]') is None
        assert forecast_doc.select_one('[data-analysis-pane="wagers"]').has_attr("hidden")
        assert "jeju-wagers.js" not in forecast.text
        for query, headers in (
            ("&layout=desktop&tab=wagers", {}),
            ("&layout=mobile", {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"}),
        ):
            response = client.get(f"/analysis?race_id={race_id}{query}", headers=headers)
            assert response.status_code == 200
            assert "승식별 확률 · 배당 비교" in response.text
            assert 'data-wager-pool="TLA"' in response.text
            assert "전체 56조합" in response.text
            assert "jeju-wagers.js" in response.text
            assert "기대수익률" in response.text
            assert "999.9" not in response.text
            if "layout=desktop" in query:
                document = BeautifulSoup(response.text, "html.parser")
                assert document.select_one('.ra-section-nav [aria-current="page"]')["data-analysis-tab"] == "wagers"
                assert not document.select_one('[data-analysis-pane="wagers"]').has_attr("hidden")
                assert document.select_one('[data-analysis-pane="forecast"]').has_attr("hidden")
                assert document.select_one('[data-jeju-wagers]').find_parent(id="analysis-pane-wagers") is not None


def test_analysis_hides_wager_tab_without_live_predictions(published):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient

    from horse_racing.web.app import create_app

    db, race, _, _ = published
    race_id = race.id
    db.query(PredictionRun).one().publication_mode = "historical"
    db.commit()
    with TestClient(create_app(session_factory=sessionmaker(db.bind))) as client:
        response = client.get(f"/analysis?race_id={race_id}&layout=desktop&tab=wagers")
    assert response.status_code == 200
    document = BeautifulSoup(response.text, "html.parser")
    assert document.select_one('[data-analysis-tab="wagers"]') is None
    assert document.select_one('[data-analysis-pane="wagers"]') is None
    assert document.select_one('[data-jeju-wagers]') is None
    assert document.select_one('.ra-section-nav [aria-current="page"]')["data-analysis-tab"] == "forecast"
