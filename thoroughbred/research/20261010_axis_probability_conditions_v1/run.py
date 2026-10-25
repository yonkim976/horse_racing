"""Frozen retrospective axis probability and interpretable residual diagnostics."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parent.parent
OUT = HERE / "outputs"
SEED = 381010
B = 2000
A = R / "20261009_axis_collapse_v1/outputs/race_inputs.parquet"
S = R / "20261009_section_style_finish_v1/outputs/features.parquet"
P = R / "20261010_third_place_hypothesis_v1/outputs/races.parquet"
REGISTRY = ROOT / "config/prediction_model_registry.json"
BASE = R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json"
LABELS = ["<40%", "40–50%", "50–60%", "60–70%", "70–80%", "80–90%", "90–100%"]
SOURCES = [A, S, P, REGISTRY, BASE, HERE / "PLAN.md", HERE / "run.py", HERE / "verify.py"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for name, value in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == value, name


def period(frame):
    yield "all", frame
    for y in [2024, 2025, 2026]:
        yield str(y), frame[frame.year.eq(y)]
    yield "2025_26", frame[frame.year.ge(2025)]


def rules(d):
    """Return nullable fixed memberships: missing predictors stay unevaluable."""

    def cmp(col, value, op):
        s = d[col]
        return op(s, value).astype("boolean").mask(s.isna())

    def le(c, v):
        return cmp(c, v, lambda s, x: s.le(x))

    def ge(c, v):
        return cmp(c, v, lambda s, x: s.ge(x))

    delta = d.axis_distance_m - d.axis_section_previous_distance
    supported = d.axis_section_last600_n5.ge(3) & d.axis_section_late_n5.ge(3)
    front = ge("axis_style_role0_rate5", 0.6).mask(d.axis_style_role_n5.lt(3))
    competition = ge("other_supported_front_count", 2)
    return {
        "few_history": le("axis_history_count", 2),
        "rest56": ge("axis_days_since_last", 56),
        "rest84": ge("axis_days_since_last", 84),
        "distance_up200": delta.ge(200).astype("boolean").mask(delta.isna()),
        "distance_down200": delta.le(-200).astype("boolean").mask(delta.isna()),
        "new_distance": le("axis_section_same_distance_n5", 0).mask(d.axis_section_early_n5.lt(3)),
        "weight_up2": ge("axis_current_vs_previous_carried_weight", 2),
        "form_down": le("axis_profile_trend", -0.5),
        "volatile": ge("axis_profile_std5", 1),
        "record_below_peers": le("axis_gap_moist_last3_record_index_mean", 0),
        "early_slower": ge("axis_gap_section_early_mean3", 0),
        "late_both_slower": (
            ge("axis_gap_section_last600_mean3", 0) & ge("axis_gap_section_late_mean3", 0)
        ).mask(~supported),
        "front_axis": front,
        "front_competition": competition,
        "front_axis_competition": front & competition,
        "frequent_fade": ge("axis_style_fade_mean5", 0.4).mask(d.axis_style_fade_n5.lt(3)),
        "sparse_sections": le("minimum_section_support", 2),
        "close_top2": le("gap12", 0.1),
        "new_horses2": ge("field_new_count", 2),
        "field12": ge("field_size", 12),
        "long_distance": ge("axis_distance_m", 1700),
        "grade5": cmp("axis_grade", 5, lambda s, x: s.eq(x)),
        "grade6": cmp("axis_grade", 6, lambda s, x: s.eq(x)),
        "grade1_4": le("axis_grade", 4),
    }


NAMES = {
    "few_history": "과거2전이하",
    "rest56": "56일이상공백",
    "rest84": "84일이상공백",
    "distance_up200": "200m이상연장",
    "distance_down200": "200m이상단축",
    "new_distance": "최근5전동일거리없음",
    "weight_up2": "부담중량2kg이상증가",
    "form_down": "최근기량하락",
    "volatile": "과거기록변동큼",
    "record_below_peers": "최근보정기록경쟁마평균이하",
    "early_slower": "초반구간경쟁마보다느림",
    "late_both_slower": "G3F·G1F모두경쟁마보다느림",
    "front_axis": "과거선행성향강함",
    "front_competition": "다른선행성향마2두이상",
    "front_axis_competition": "선행성향축+경합후보2두이상",
    "frequent_fade": "과거후반밀림빈도높음",
    "sparse_sections": "구간이력부족",
    "close_top2": "평가1·2위차작음",
    "new_horses2": "신마2두이상편성",
    "field12": "12두이상",
    "long_distance": "1700m이상",
    "grade5": "5등급",
    "grade6": "6등급",
    "grade1_4": "1~4등급",
}


def weights(dates):
    dates = sorted(pd.to_datetime(pd.Series(dates)).unique())
    rng = np.random.default_rng(SEED)
    n = len(dates)
    return dates, rng.multinomial(n, np.full(n, 1 / n), B)


def stats(d, mask=None):
    """Date-cluster bootstrap, group vs complement within evaluable population."""
    if mask is None:
        mask = pd.Series(True, index=d.index, dtype="boolean")
    known = mask.notna()
    x = d.loc[known].copy()
    m = mask.loc[known].astype(bool)
    g, c = x.loc[m], x.loc[~m]
    if len(g) == 0:
        return dict(n=0, failures=0, evaluable=len(x), missing=len(d) - len(x))
    row = dict(
        n=len(g),
        failures=int(g.collapsed.sum()),
        evaluable=len(x),
        missing=len(d) - len(x),
        failure_rate=float(g.collapsed.mean()),
        expected_risk=float(g.base_risk.mean()),
        residual=float(g.residual.mean()),
        complement_n=len(c),
        complement_rate=float(c.collapsed.mean()) if len(c) else None,
        residual_diff=float(g.residual.mean() - c.residual.mean()) if len(c) else None,
    )
    dates, w = weights(x.race_date)
    boot = {}
    for label, frame in [("g", g), ("c", c)]:
        a = (
            frame.groupby("race_date")
            .agg(n=("collapsed", "size"), failed=("collapsed", "sum"), resid=("residual", "sum"))
            .reindex(dates, fill_value=0)
        )
        denominator = w @ a.n.to_numpy(dtype=float)
        for metric, col in [("rate", "failed"), ("residual", "resid")]:
            boot[label + metric] = np.divide(
                w @ a[col].to_numpy(dtype=float),
                denominator,
                out=np.full(B, np.nan),
                where=denominator > 0,
            )
    for label, v in [
        ("failure_rate", boot["grate"]),
        ("residual", boot["gresidual"]),
        ("residual_diff", boot["gresidual"] - boot["cresidual"]),
    ]:
        valid = v[np.isfinite(v)]
        bounds = np.quantile(valid, [0.025, 0.975]) if len(valid) >= 1900 else [None, None]
        row[label + "_low"], row[label + "_high"] = [
            float(z) if z is not None else None for z in bounds
        ]
    return row


def matched(d, mask):
    x = d.loc[mask.notna()].copy()
    x["member"] = mask.dropna().astype(bool)
    keys = ["year", "meet", "prob5", "distance_band", "grade_band", "field_band"]
    sums = []
    for _, g in x.groupby(keys, observed=True):
        a, b = g[g.member], g[~g.member]
        if min(len(a), len(b)) >= 3:
            sums.append(
                (
                    len(a),
                    len(b),
                    float(a.collapsed.mean()),
                    float(b.collapsed.mean()),
                    float(a.residual.mean() - b.residual.mean()),
                )
            )
    if not sums:
        return dict(
            matched_n=0,
            cells=0,
            matched_rate=None,
            standardized_complement_rate=None,
            matched_residual_diff=None,
        )
    a = np.array(sums)
    return dict(
        matched_n=int(a[:, 0].sum()),
        cells=len(a),
        matched_rate=float(np.average(a[:, 2], weights=a[:, 0])),
        standardized_complement_rate=float(np.average(a[:, 3], weights=a[:, 0])),
        matched_residual_diff=float(np.average(a[:, 4], weights=a[:, 0])),
    )


def load():
    d = pd.read_parquet(A).query("year>=2024").copy()
    s = pd.read_parquet(S)
    s = s[s.race_key.isin(d.race_key)].copy()
    s["supported_front"] = s.style_role_n5.ge(3) & s.style_role0_rate5.ge(0.6)
    count = s.groupby("race_key").supported_front.sum()
    axis = s.merge(
        d[["race_key", "axis_number", "axis_horse_id"]],
        left_on=["race_key", "program_no", "horse_id"],
        right_on=["race_key", "axis_number", "axis_horse_id"],
        validate="one_to_one",
    )
    axis["other_supported_front_count"] = axis.race_key.map(count) - axis.supported_front.astype(
        int
    )
    d = d.merge(
        axis[
            [
                "race_key",
                "other_supported_front_count",
                "history_source_date",
                "profile_source_date",
                "cutoff_date",
            ]
        ],
        on="race_key",
        validate="one_to_one",
    )
    d["minimum_section_support"] = d[
        ["axis_section_early_n5", "axis_section_last600_n5", "axis_section_late_n5"]
    ].min(axis=1, skipna=False)
    d["axis_probability"] = 1 - d.base_risk
    d["residual"] = d.collapsed - d.base_risk
    d["probability_band"] = pd.cut(
        d.axis_probability, [0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.000001], labels=LABELS, right=False
    )
    d["prob5"] = (d.axis_probability / 0.05).astype(int)
    d["distance_band"] = pd.cut(
        d.axis_distance_m, [0, 1300, 1600, 10000], labels=["short", "middle", "long"]
    )
    d["grade_band"] = np.select(
        [d.axis_grade.eq(6), d.axis_grade.eq(5), d.axis_grade.le(4)],
        ["6", "5", "1_4"],
        default="other",
    )
    d["field_band"] = pd.cut(d.field_size, [0, 9, 11, 100], labels=["<=9", "10_11", ">=12"])
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in SOURCES})
    d = load()
    d.to_parquet(OUT / "races.parquet", index=False)
    memberships = pd.DataFrame(rules(d))
    memberships.insert(0, "race_key", d.race_key)
    memberships.to_parquet(OUT / "rule_memberships.parquet", index=False)
    bins, summaries, conditions, matching = [], [], [], []
    for tag, g in period(d):
        summaries.append(dict(period=tag, **stats(g)))
        for band, h in g.groupby("probability_band", observed=True):
            bins.append(
                dict(
                    period=tag,
                    band=str(band),
                    **stats(h),
                    failure_share=float(h.collapsed.sum() / g.collapsed.sum()),
                )
            )
        for name, membership in rules(g).items():
            conditions.append(
                dict(period=tag, scope="all", rule=name, label=NAMES[name], **stats(g, membership))
            )
            h = g[g.axis_probability.ge(0.7)]
            conditions.append(
                dict(
                    period=tag,
                    scope="prob70plus",
                    rule=name,
                    label=NAMES[name],
                    **stats(h, membership.loc[h.index]),
                )
            )
            matching.append(dict(period=tag, rule=name, **matched(g, membership)))
    conditions = pd.DataFrame(conditions)
    discovery = (
        conditions.query(
            "period=='2024' and scope=='all' and n>=80 and failures>=20 and residual_diff>0"
        )
        .sort_values(["residual_diff", "rule"], ascending=[False, True])
        .head(5)
    )
    chosen = discovery.rule.tolist()
    save(
        OUT / "discovery_selection.json",
        dict(
            discovery_year=2024,
            validation_years=[2025, 2026],
            rules=chosen,
            criterion=(
                "n>=80, failures>=20, positive residual difference; "
                "largest difference, top5; ties rule ID"
            ),
        ),
    )
    validation = conditions[conditions.rule.isin(chosen)].copy()
    refs = pd.read_parquet(P)
    references = []
    for variant, g in refs.groupby("variant"):
        for band, h in g.groupby(
            pd.cut(
                g.axis_probability,
                [0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.000001],
                labels=LABELS,
                right=False,
            ),
            observed=True,
        ):
            references.append(
                dict(
                    variant=variant,
                    band=str(band),
                    n=len(h),
                    failures=int(h.axis_out.sum()),
                    failure_rate=float(h.axis_out.mean()),
                    expected_risk=float((1 - h.axis_probability).mean()),
                )
            )
    for name, data in [
        ("summary", summaries),
        ("probability_bins", bins),
        ("conditions", conditions),
        ("matched_conditions", matching),
        ("selected_validation", validation),
        ("reference_bins", references),
    ]:
        pd.DataFrame(data).to_csv(OUT / f"{name}.csv", index=False)
    save(
        OUT / "cohort.json",
        dict(
            races=len(d),
            failures=int(d.collapsed.sum()),
            min_date=str(d.race_date.min().date()),
            max_date=str(d.race_date.max().date()),
            years={str(k): int(v) for k, v in d.groupby("year").size().items()},
            conditions=len(NAMES),
            bootstrap=B,
            seed=SEED,
            new_models=0,
        ),
    )
    check()
    print(pd.DataFrame(bins).query("period=='all'").to_string(index=False), flush=True)
    print(validation.query("period=='2025_26' and scope=='all'").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
