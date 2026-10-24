"""Frozen personal_t2 inference and one coherent podium/order probability contract."""

from pathlib import Path
import json

try:
    import torch  # noqa: F401 -- selects the macOS OpenMP runtime before LightGBM
except ImportError:
    pass
import numpy as np
import pandas as pd
import lightgbm as lgb
import features
import probability

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ALGORITHM = "trio_set_within_set_pl_v1"
PROFILE = "thoroughbred-training-state-20261025-v1"
KEY = ["race_key", "program_no", "horse_id"]
FEATURE_LABELS = json.loads((HERE / "feature_labels.json").read_text())


def require(condition, message="Invalid model input"):
    if not condition:
        raise ValueError(message)


def checked_path(item):
    p = (ROOT / item["path"]).resolve()
    require(p.is_relative_to(ROOT) and p.is_file(), "Model validation failed")
    require(features.sha(p) == item["sha256"], ("Frozen asset hash mismatch", item["path"]))
    return p


def load_spec(path=None):
    p = HERE / "model_spec.json" if path is None else Path(path)
    spec = json.loads(p.read_text())
    require(
        spec["profile"] == PROFILE and spec["algorithm_version"] == ALGORITHM,
        "Model validation failed",
    )
    return spec


def active_profile():
    path = ROOT / "config/prediction_model_registry.json"
    r = json.loads(path.read_text())
    name = r["domains"]["thoroughbred"]["active_profile"]
    p = r["profiles"][name]
    require(
        name == PROFILE and p["status"] == "production",
        "Use the registered inference entrypoint for the active profile",
    )
    require(p["combination_algorithm_version"] == ALGORITHM, "Model validation failed")
    for item in p["artifacts"].values():
        checked_path(item)
    for gate in p["verification_gates"]:
        value = json.loads((ROOT / gate["path"]).read_text())
        for key, want in gate["requires"].items():
            for subkey in key.split("."):
                value = value[subkey]
            require(value == want, (gate["path"], key))
            value = json.loads((ROOT / gate["path"]).read_text())
    return p, features.sha(path)


def probability_order(values):
    return np.argsort(-np.round(np.asarray(values), 12), kind="stable")


def readable(name):
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]
    labels = {
        "state_rank_current_field_gap": "편성 평균 대비 추정 능력",
        "state_rank_current_field_rank": "편성 내 추정 능력 순위",
        "state_form_mean": "최근 기량 상태",
        "state_risk_rate": "과거 미완주 위험 상태",
        "history_count": "과거 출전 수",
        "days_since_last": "직전 출전 후 경과일",
        "current_carried_weight": "이번 부담중량",
        "train_days28": "최근28일 조교 관측일수",
        "train_minutes14": "최근14일 유효 조교시간",
        "train_minutes14_delta_self3": "평소 출전 준비 대비14일 조교시간 변화",
        "train_minutes_per_day14_delta_self3": "평소 대비 조교 관측일당 시간 변화",
    }
    return labels.get(name, name)


def predict(frame, *, explain=True, spec=None):
    spec = load_spec() if spec is None else spec
    expected = spec["features"]
    missing = set(expected) - set(frame)
    require(not missing, ("Missing promoted feature columns", sorted(missing)))
    f = frame.sort_values(["race_key", "program_no"]).reset_index(drop=True).copy()
    require(not f.duplicated(KEY).any() and f.meet.isin([1, 3]).all(), "Model validation failed")
    require(pd.to_datetime(f.race_date).dt.year.eq(2026).all(), "Model validation failed")
    require(
        f.groupby("race_key").size().eq(f.groupby("race_key").field_size.first()).all(),
        "Model validation failed",
    )
    require(
        not np.isinf(
            f[[x for x in expected if pd.api.types.is_numeric_dtype(f[x])]].to_numpy(float)
        ).any(),
        "Model validation failed",
    )
    rows = []
    explanations = []
    tickets = []
    raw_score = np.zeros(len(f))
    shap_error = 0.0
    models = {}
    for meet in [1, 3]:
        take = f.meet.eq(meet)
        if not take.any():
            continue
        item = spec["venue_models"][str(meet)]
        model = lgb.Booster(model_file=str(checked_path(item["model"])))
        meta = json.loads(checked_path(item["metadata"]).read_text())
        require(meta["features"] == expected == model.feature_name(), "Model validation failed")
        x = f.loc[take, expected].copy()
        for col, vocab in meta["category_vocabulary"].items():
            x[col] = pd.Categorical(x[col], categories=vocab)
        score = model.predict(x, raw_score=True, num_threads=4)
        raw_score[np.flatnonzero(take)] = score
        if explain:
            effects = np.asarray(model.predict(x, pred_contrib=True, num_threads=4))
            require(effects.shape == (len(x), len(expected) + 1), "Model validation failed")
            error = float(np.max(np.abs(effects.sum(1) - score)))
            shap_error = max(shap_error, error)
            require(error < 1e-6, "Model validation failed")
            for local, global_index in enumerate(np.flatnonzero(take)):
                values = effects[local, :-1]
                for sign, name in [(1, "positive"), (-1, "negative")]:
                    eligible = np.flatnonzero(values * sign > 0)
                    require(len(eligible) >= 3, "Insufficient signed explanations")
                    selected = eligible[np.argsort(-values[eligible] * sign, kind="stable")[:3]]
                    for rank, j in enumerate(selected, 1):
                        raw = f.iloc[global_index][expected[j]]
                        raw = (
                            None
                            if pd.isna(raw)
                            else raw.item()
                            if isinstance(raw, np.generic)
                            else raw
                        )
                        explanations.append(
                            {
                                "race_key": str(f.iloc[global_index].race_key),
                                "horse_id": str(f.iloc[global_index].horse_id),
                                "component": "A",
                                "feature_name": expected[j],
                                "readable_feature_name": readable(expected[j]),
                                "feature_value": raw,
                                "contribution_direction": name,
                                "contribution_value": float(values[j]),
                                "contribution_rank": rank,
                                "explanation_type": "categorical_model_effect"
                                if expected[j] in meta["category_vocabulary"]
                                else "model_feature_effect",
                                "explanation_method": "lightgbm_pred_contrib_raw_a_score",
                                "field_percentile": None,
                            }
                        )
        models[meet] = meta
    for _, g in f.groupby("race_key", sort=False):
        n = len(g)
        require(3 <= n <= 20 and g.program_no.is_monotonic_increasing, "Model validation failed")
        meta = models[int(g.meet.iloc[0])]
        score = raw_score[g.index]
        q = probability.trio_distribution(score, meta["temperature"])
        orders, mass = probability.ordered_distribution(score, q, meta["order_temperature"])
        m = probability.marginals(n, orders, mass)
        for col, total in [("win", 1), ("top2", 2), ("top3", 3)]:
            require(abs(m[col].sum() - total) < 1e-9, "Model validation failed")
        require(
            (m["win"] <= m["top2"] + 1e-12).all() and (m["top2"] <= m["top3"] + 1e-12).all(),
            "Model validation failed",
        )
        ranks = np.empty(n, int)
        ranks[probability_order(m["top3"])] = np.arange(1, n + 1)
        for i, r in enumerate(g.itertuples()):
            rows.append(
                {
                    "race_key": r.race_key,
                    "race_id": getattr(r, "race_id", r.race_key),
                    "program_no": int(r.program_no),
                    "horse_number": int(r.program_no),
                    "chul_no": int(r.program_no),
                    "horse_id": r.horse_id,
                    "hr_no": r.horse_id,
                    "race_date": str(pd.Timestamp(r.race_date).date()),
                    "meet": int(r.meet),
                    "race_no": int(r.race_no),
                    "prob_win": float(m["win"][i]),
                    "prob_top2": float(m["top2"][i]),
                    "prob_top3": float(m["top3"][i]),
                    "A_slot_inclusion_probability": float(m["top3"][i]),
                    "a_rank_in_race": int(ranks[i]),
                    "pred_rank": int(ranks[i]),
                    "field_size": n,
                    "starter_status": "starter",
                    "raw_a_top3_score": float(score[i]),
                    "raw_bc_top3_score": float(score[i]),
                    "raw_win_score": float(score[i]),
                    "model_profile": PROFILE,
                    "combination_algorithm_version": ALGORITHM,
                }
            )
        triples = probability.support(n)[0]
        ii, jj = np.triu_indices(n, 1)
        for pool, support, pr, budget in [
            ("trio", triples, q, 6),
            ("ordered", orders, mass, 6),
            ("quinella", np.column_stack([ii, jj]), m["quinella"][ii, jj], 3),
            ("qpl", np.column_stack([ii, jj]), m["qpl"][ii, jj], 3),
        ]:
            for rank, k in enumerate(probability_order(pr)[:budget], 1):
                tickets.append(
                    {
                        "race_key": g.race_key.iloc[0],
                        "pool": pool,
                        "rank": rank,
                        "programs": [int(g.program_no.iloc[i]) for i in support[k]],
                        "probability": float(pr[k]),
                    }
                )
    return (
        pd.DataFrame(rows),
        explanations,
        tickets,
        {
            "max_shap_additivity_error": shap_error,
            "runners": len(rows),
            "races": f.race_key.nunique(),
        },
    )
