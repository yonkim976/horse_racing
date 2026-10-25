"""Independent input, chronological replay and ticket metric checks."""

import argparse
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e
from scipy.special import softmax


def inputs():
    e.check()
    prepared = json.loads((e.OUT / "prepared.json").read_text())
    for p, h in prepared["sha256"].items():
        assert e.sha(e.OUT / p) == h
    f, _ = e.load()
    r = pd.read_parquet(e.OUT / "oof_runners.parquet")
    x = pd.read_parquet(e.OUT / "pair_features.parquet")
    m = pd.read_parquet(e.OUT / "pair_metadata.parquet")
    contracts = json.loads((e.OUT / "feature_contract.json").read_text())
    assert len(x) == len(m) and not m.duplicated(["rid", "first_number", "second_number"]).any()
    assert set(r.rid) == set(m.rid)
    assert not set(x) & {
        "finish",
        "truth",
        "axis_placed",
        "outcome",
        "horse_id",
        "race_date",
        "year",
    }
    assert not any("jockey" in c or "trainer" in c for c in x)
    assert np.isfinite(x.select_dtypes("number").to_numpy()).sum() > 0
    assert not np.isinf(x.to_numpy()).any()
    first = m.groupby("rid").first()
    assert m.groupby("rid").truth.sum().eq(first.axis_placed).all()
    assert m.groupby("rid").size().eq(first.pair_count).all()
    assert m.first_number.lt(m.second_number).all()
    assert m.axis_number.ne(m.first_number).all() and m.axis_number.ne(m.second_number).all()
    assert first.axis_probability.between(0, 1).all()
    joined = r.merge(f[["rid", "number", *e.HISTORY]], on=["rid", "number"], validate="one_to_one")
    # Reconstruct all arrays without truth and check sorting invariance.
    rebuilt_x, rebuilt_m = [], []
    for _rid, card in joined.groupby("rid", sort=True):
        xx, mm, cc = e.pair_card(card.drop(columns="finish"))
        assert cc == contracts
        rebuilt_x.append(xx)
        rebuilt_m.append(mm)
    xx = pd.concat(rebuilt_x, ignore_index=True)
    mm = pd.concat(rebuilt_m, ignore_index=True)
    assert np.allclose(xx, x, equal_nan=True, atol=0, rtol=0)
    assert mm[["rid", "axis_number", "first_number", "second_number"]].equals(
        m[["rid", "axis_number", "first_number", "second_number"]]
    )
    cards = list(joined.groupby("rid", sort=True))
    for _, card in cards[:: max(1, len(cards) // 60)]:
        a, am, _ = e.pair_card(card)
        b, bm, _ = e.pair_card(card.sample(frac=1, random_state=42).assign(finish=99))
        assert a.equals(b)
        assert am.axis_number.equals(bm.axis_number)
        # Independent symmetric feature definitions.
        lookup = card.set_index("number")
        for k, t in am.head(5).iterrows():
            n1, n2 = int(t.first_number), int(t.second_number)
            for c in e.HISTORY:
                u, v = float(lookup.loc[n1, c]), float(lookup.loc[n2, c])
                assert np.isclose(
                    a.loc[k, "pair_min_" + c],
                    min(u, v) if np.isfinite(u) and np.isfinite(v) else np.nan,
                    equal_nan=True,
                    rtol=2e-7,
                    atol=2e-7,
                )
                assert a.loc[k, "pair_known_" + c] == int(np.isfinite(u)) + int(np.isfinite(v))
            assert a.loc[k, "pair_gate_spacing"] == abs(n1 - n2)
    if e.SPECIES == "thoroughbred":
        for c in ["history_source_date", "profile_source_date", "weight_source_date"]:
            dates = pd.to_datetime(f[c], errors="coerce")
            assert ((dates <= f.race_date - pd.Timedelta(days=2)) | dates.isna()).all(), c
    else:
        dates = pd.to_datetime(f.latest_history_date, errors="coerce")
        assert ((dates <= f.race_date - pd.Timedelta(days=2)) | dates.isna()).all()
        trace = pd.read_csv(e.JP / "features01/history_lineage.csv")
        for scope in ["any", "same"]:
            dt = pd.to_datetime(trace[scope + "_last_date"], errors="coerce")
            current = pd.to_datetime(trace.race_date)
            assert ((dt <= current - pd.Timedelta(days=2)) | dt.isna()).all()
            assert ((dt >= current - pd.Timedelta(days=730)) | dt.isna()).all()
        for c in ["h_any_s1ftime_mean", "h_any_g3ftime_mean", "h_any_g1ftime_mean"]:
            assert (f[c].isna() | f[c].between(0, 1)).all()
    return dict(
        passed=True,
        all_pair_inputs_rebuilt=len(x),
        races=len(first),
        targets_removed_reconstruction_identical=True,
        shuffled_current_outcomes_do_not_change_features=True,
        symmetrized_pair_definitions_checked=True,
        histories_T_minus2_verified=True,
        probability_scope="conditional pair given historical rank1 axis Top3",
        inherited_timestamp_limit=True,
    )


def replay_base():
    f, cols = e.load()
    checks = []
    for folder in sorted((e.OUT / "base_models").iterdir()):
        meta = json.loads((folder / "meta.json").read_text())
        assert (
            meta["initial_train_max"]
            < meta["refit_max"]
            < meta["calibration_min"]
            <= meta["calibration_max"]
            < meta["evaluation_min"]
        )
        path = e.ROOT / meta["model_path"]
        assert e.sha(path) == meta["model_sha256"]
        one = f[(f.meet == meta["meet"]) & (f.year == meta["year"])].reset_index(drop=True)
        x, _ = e.encode(one, cols, vocab=meta["vocabulary"])
        model = lgb.Booster(model_file=str(path))
        score = model.predict(x, raw_score=True, num_threads=4)
        saved = pd.read_parquet(folder / "runners.parquet")
        assert one[["rid", "number"]].equals(saved[["rid", "number"]].reset_index(drop=True))
        err = float(np.max(abs(saved.score.to_numpy() - score)))
        assert err < 1e-12
        if not meta["reused"]:
            cal = f[(f.meet == meta["meet"]) & (f.year == meta["year"] - 1)].reset_index(drop=True)
            cx, _ = e.encode(cal, cols, vocab=meta["vocabulary"])
            cz = model.predict(cx, raw_score=True, num_threads=4)
            assert abs(e.base_temperature(cal, cz) - meta["tau"]) < 1e-9
        checks.append(dict(folder=folder.name, max_error=err))
    return checks


def final():
    result = inputs()
    result["base_replays"] = replay_base()
    x = pd.read_parquet(e.OUT / "pair_features.parquet")
    m = pd.read_parquet(e.OUT / "pair_metadata.parquet")
    p = pd.read_parquet(e.OUT / "pair_predictions.parquet")
    replays = []
    for folder in sorted((e.OUT / "pair_models").iterdir()):
        meta = json.loads((folder / "meta.json").read_text())
        assert (
            meta["initial_train_max"]
            < meta["refit_max"]
            < meta["calibration_min"]
            <= meta["calibration_max"]
            < meta["evaluation_min"]
        )
        assert e.sha(folder / "model.txt") == meta["model_sha256"]
        model = lgb.Booster(model_file=str(folder / "model.txt"))
        te = m.year.eq(meta["year"])
        ca = m.year.eq(meta["year"] - 1)
        score = model.predict(x.loc[te, meta["features"]], raw_score=True, num_threads=4)
        saved = (
            p[(p.year == meta["year"]) & (p.variant == meta["variant"])]
            .set_index("pair_index")
            .loc[np.flatnonzero(te)]
        )
        err = float(np.max(abs(saved.score.to_numpy() - score)))
        assert err < 1e-12
        cz = model.predict(x.loc[ca, meta["features"]], raw_score=True, num_threads=4)
        assert abs(e.conditional_temperature(m[ca].reset_index(drop=True), cz) - meta["tau"]) < 1e-9
        replays.append(dict(folder=folder.name, max_error=err))
    r = pd.read_csv(e.OUT / "race_metrics.csv")
    t = pd.read_parquet(e.OUT / "six_tickets.parquet")
    q = pd.read_parquet(e.OUT / "conditional_probabilities.parquet")
    test = m[m.year.ge(2024)].copy()
    test["pair_index"] = test.index
    qs = q.merge(test, on="pair_index", validate="many_to_one")
    assert np.allclose(qs.groupby(["variant", "rid"]).probability.sum(), 1, atol=1e-12)
    assert q.probability.between(0, 1).all()
    assert t.groupby(["rid", "policy"]).size().eq(6).all()
    assert not t.duplicated(["rid", "policy", "first", "second"]).any()
    assert r.groupby("policy").size().nunique() == 1
    assert r.groupby("rid").axis_number.nunique().eq(1).all()
    assert r.groupby("rid").axis_placed.nunique().eq(1).all()
    assert r.probability_sum_error.max() < 1e-12
    lookup = pd.read_parquet(e.OUT / "oof_runners.parquet")
    lookup = lookup[lookup.year.ge(2024)].set_index(["rid", "number"])
    hits = []
    for z in t.itertuples():
        truth = {int(n) for n in lookup.loc[z.rid].query("finish <= 3").index}
        hit = int({z.axis, z.first, z.second} == truth)
        assert hit == z.hit
        hits.append(hit)
    tt = t.assign(rebuilt_hit=hits)
    hh = tt.groupby(["rid", "policy"]).rebuilt_hit.sum()
    actual = r.set_index(["rid", "policy"]).six_hit
    assert hh.loc[actual.index].equals(actual.rename("rebuilt_hit"))
    assert np.allclose(
        tt.groupby(["rid", "policy"]).joint_probability.sum().loc[actual.index],
        r.set_index(["rid", "policy"]).selected_joint_probability,
    )
    # Independent baseline using rank1 and ranks2..5; no learned code involved.
    baseline = []
    for rid, g in lookup.reset_index().groupby("rid"):
        order = g.sort_values(["score", "number"], ascending=[False, True])
        truth = set(g[g.finish.le(3)].number)
        baseline.append(
            (rid, int(order.number.iloc[0] in truth and truth <= set(order.number.iloc[:5])))
        )
    expected = dict(baseline)
    base = r[r.policy.eq("fixed_axis_next4_all6")]
    assert base.six_hit.tolist() == [expected[k] for k in base.rid]
    # Conditional distributions are also checked directly from saved logits.
    for variant, g in qs.groupby("variant"):
        z = p[p.variant.eq(variant)].set_index("pair_index")
        for _, one in g.groupby("rid", sort=False):
            s = z.loc[one.pair_index]
            assert np.allclose(softmax((s.score / s.tau).to_numpy()), one.probability, atol=1e-12)
    summary = pd.read_csv(e.OUT / "summary.csv")
    for z in summary.query('scope == "all"').itertuples():
        one = r[r.policy == z.policy]
        assert z.races == len(one) and z.hits == int(one.six_hit.sum())
        assert abs(z.six_hit - one.six_hit.mean()) < 1e-12
        assert abs(z.companion_given_axis - one[one.axis_placed.eq(1)].six_hit.mean()) < 1e-12
    e.check()
    result.update(
        pair_model_replays=replays,
        ticket_rows_independently_checked=len(t),
        conditional_distributions_checked=len(q),
        baseline_recomputed=True,
        registry_and_source_hashes_unchanged=True,
        operating_changed=False,
        database_opened=False,
    )
    e.save(e.OUT / "final_verification.json", result)
    print("Final verification passed", e.SPECIES, len(t), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["preflight", "final"])
    a = p.parse_args()
    if a.phase == "preflight":
        e.save(e.OUT / "preflight_verification.json", inputs())
        print("Preflight passed", e.SPECIES, flush=True)
    else:
        final()
