"""Matched definitions and joint-cluster Busan-minus-Seoul contrasts."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("busan_comparison_analysis", HERE / "analyze.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


def support(s):
    return dict(
        rows=len(s),
        races=int(s.race_key.nunique()),
        days=int(s.date.nunique()),
        years=int(s.year.nunique()),
    )


def context(module, data, model, params):
    s = module.sample(data, model["distance_m"], "core", model["period"], "tail25")
    x, labels, _, _ = B.OLD.design(s)
    assert labels == model["labels"]
    w = B.L.weights(s, False)
    xd, _ = B.OLD.within(x, B.OLD.codes(s.horse_id), w)
    yd, _ = B.OLD.within(
        s[B.CORE + ["finish", "last600"]].to_numpy(float), B.OLD.codes(s.horse_id), w
    )
    gram = xd.T @ (w[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    beta = params[f"{model['matrix_key']}_beta"]
    residual = yd - xd @ beta
    return dict(
        data=s,
        xd=xd,
        w=w,
        inv=inv,
        beta=beta,
        residual=residual,
        labels=labels,
        projection=inv @ gram,
        factor=(len(s) - 1) / model["residual_df"],
        model=model,
    )


def moist_vector(ctx, positive, negative):
    v = np.zeros(len(ctx["labels"]))
    columns = {
        float(name.rsplit(":", 1)[1]): i
        for i, name in enumerate(ctx["labels"])
        if name.startswith("control:moisture:")
    }
    for sign, weights in [(1, positive), (-1, negative)]:
        for number, share in weights.items():
            if number in columns:
                v[columns[number]] += sign * share
    return v


def main():
    _, bd = B.load()
    _, sd = B.S.load()
    models = json.loads((OUT / "models.json").read_text())
    smodels = json.loads((B.SEOUL / "outputs/models.json").read_text())
    bp = np.load(OUT / "parameters.npz", allow_pickle=False)
    sp = np.load(B.SEOUL / "outputs/parameters.npz", allow_pickle=False)
    models = [m for m in models if m["scope"] == "core" and m["variant"] == "tail25"]
    smodels = {
        (m["distance_m"], m["period"]): m
        for m in smodels
        if m["scope"] == "core" and m["variant"] == "tail25"
    }
    bprofiles = pd.read_csv(OUT / "effect_profiles.csv", dtype={"level": str})
    sprofiles = pd.read_csv(B.SEOUL / "outputs/effect_profiles.csv", dtype={"level": str})
    rows, mixes, audit, arrays = [], {}, [], {}
    for bm in models:
        key = (bm["distance_m"], bm["period"])
        if key not in smodels:
            continue
        sm = smodels[key]
        cb, cs = context(B, bd, bm, bp), context(B.S, sd, sm, sp)
        specs = []
        baseline_b = B.sample(bd, key[0], "core", key[1], "baseline")
        baseline_s = B.S.sample(sd, key[0], "core", key[1], "baseline")
        common_numbers = set(cb["data"].moisture) & set(cs["data"].moisture)
        pooled = pd.concat(
            [
                baseline_b.groupby("race_key")[["moisture", "band"]].first(),
                baseline_s.groupby("race_key")[["moisture", "band"]].first(),
            ]
        )
        pooled = pooled[pooled.moisture.isin(common_numbers)]
        mix = {
            band: {
                float(number): float(share)
                for number, share in g.moisture.value_counts(normalize=True).items()
            }
            for band, g in pooled.groupby("band", observed=True)
        }
        mixes[f"{key[0]}:{key[1]}"] = dict(
            weights=mix,
            common_numeric_levels=sorted(common_numbers),
            original_numeric_levels_busan=sorted(set(baseline_b.moisture)),
            original_numeric_levels_seoul=sorted(set(baseline_s.moisture)),
        )
        for band in ["양호", "다습", "포화", "불량"]:
            if band not in mix or "건조" not in mix:
                continue
            details = []
            for ctx in [cb, cs]:
                for state in [band, "건조"]:
                    details.append(
                        support(
                            ctx["data"][
                                ctx["data"].band.eq(state) & ctx["data"].moisture.isin(mix[state])
                            ]
                        )
                    )
            ok = all(r["races"] >= 50 and r["days"] >= 20 for r in details)
            specs.append(
                (
                    moist_vector(cb, mix[band], mix["건조"]),
                    moist_vector(cs, mix[band], mix["건조"]),
                    dict(
                        family="moisture_common_mix",
                        block="common_numeric_mix",
                        level=band,
                        supported=ok,
                        support=details,
                    ),
                )
            )
        # Compare raw annual curves and identical gate numbers, with the original profile support.
        rb = bprofiles[
            bprofiles.matrix_key.eq(int(bm["matrix_key"])) & bprofiles.section.eq("early")
        ]
        rs = sprofiles[
            sprofiles.matrix_key.eq(int(sm["matrix_key"])) & sprofiles.section.eq("early")
        ]
        pair = rb.merge(
            rs, on=["family", "block", "level"], suffixes=("_b", "_s"), validate="one_to_one"
        )
        pair = pair[
            pair.family.eq("month")
            | (pair.family.eq("number") & pair.block.isin(["exact10", "exact12"]))
        ]
        for r in pair.itertuples():
            vb = bp[f"{bm['matrix_key']}_vectors"][r.contrast_index_b]
            vs = sp[f"{sm['matrix_key']}_vectors"][r.contrast_index_s]
            specs.append(
                (
                    vb,
                    vs,
                    dict(
                        family=r.family,
                        block=r.block,
                        level=r.level,
                        supported=bool(r.supported_b and r.supported_s),
                        support=[json.loads(r.support_b), json.loads(r.support_s)],
                    ),
                )
            )
        vb, vs = np.vstack([r[0] for r in specs]), np.vstack([r[1] for r in specs])
        estimable = np.array(
            [
                np.allclose(v @ cb["projection"], v, atol=1e-6)
                and np.allclose(u @ cs["projection"], u, atol=1e-6)
                for v, u in zip(vb, vs, strict=True)
            ]
        )
        # Rows are independent venue fits; shared horse/day clusters connect the influence scores.
        leverage_b = cb["xd"] @ cb["inv"] @ vb.T
        leverage_s = cs["xd"] @ cs["inv"] @ vs.T
        horse = pd.concat([cb["data"].horse_id, cs["data"].horse_id], ignore_index=True)
        day = pd.concat([cb["data"].date, cs["data"].date], ignore_index=True)
        df = (
            min(
                cb["data"].horse_id.nunique(),
                cs["data"].horse_id.nunique(),
                cb["data"].date.nunique(),
                cs["data"].date.nunique(),
            )
            - 1
        )
        critical = t.ppf(0.975, df)
        for j, part in enumerate(B.CORE + ["finish", "last600"]):
            ib = leverage_b * (cb["w"] * cb["residual"][:, j] * np.sqrt(cb["factor"]))[:, None]
            iss = leverage_s * (cs["w"] * cs["residual"][:, j] * np.sqrt(cs["factor"]))[:, None]
            score = np.vstack([ib, -iss])
            # Calculate cluster variances without forming a large cross-contrast covariance.
            variance = []
            for values in [horse, day, horse + ":" + day.astype(str)]:
                codes = B.OLD.codes(values)
                count = int(codes.max()) + 1
                total = np.column_stack([np.bincount(codes, weights=v) for v in score.T])
                variance.append((total**2).sum(axis=0) * count / max(count - 1, 1))
            vh, vd, vi = variance
            se = np.sqrt(np.maximum.reduce([vh + vd - vi, vh, vd, np.zeros(len(specs))]))
            eb, es = vb @ cb["beta"][:, j], vs @ cs["beta"][:, j]
            for i, (_, _, identity) in enumerate(specs):
                ok = bool(estimable[i])
                difference = eb[i] - es[i]
                rows.append(
                    dict(
                        distance_m=key[0],
                        period=key[1],
                        section=part,
                        estimable=ok,
                        supported=bool(ok and identity["supported"]),
                        busan_effect=float(eb[i]) if ok else None,
                        seoul_effect=float(es[i]) if ok else None,
                        busan_minus_seoul=float(difference) if ok else None,
                        se=float(se[i]) if ok else None,
                        ci_low=float(difference - critical * se[i]) if ok else None,
                        ci_high=float(difference + critical * se[i]) if ok else None,
                        p=float(2 * t.sf(abs(difference) / max(se[i], 1e-15), df)) if ok else None,
                        df=int(df),
                        comparison_key=f"{key[0]}:{key[1]}:{part}:{i}",
                    )
                    | (identity | {"supported": bool(ok and identity["supported"])})
                )
            # Save complete influence vectors for a small representative common-moisture audit.
            if (
                key[0] in {1200, 1400}
                and key[1] == "all_mad4"
                and part in {"early", "middle1", "late"}
            ):
                i = next(i for i, spec in enumerate(specs) if spec[2]["level"] == "포화")
                akey = f"{key[0]}_{part}"
                arrays[f"{akey}_score"] = score[:, i]
                arrays[f"{akey}_horse"] = B.OLD.codes(horse)
                arrays[f"{akey}_day"] = B.OLD.codes(day)
                audit.append(
                    dict(
                        key=akey,
                        comparison_key=f"{key[0]}:{key[1]}:{part}:{i}",
                        variance_horse=float(vh[i]),
                        variance_day=float(vd[i]),
                        variance_intersection=float(vi[i]),
                    )
                )
        print("venue contrasts", key, len(specs) * 6, flush=True)
    frame = B.E.fdr(pd.DataFrame(rows), ["period", "section", "family"])
    frame["support"] = frame.support.map(json.dumps)
    frame.to_csv(OUT / "venue_raw_direct_contrasts.csv", index=False)
    B.dump(OUT / "common_moisture_mix.json", mixes)
    B.dump(OUT / "contrast_variance_audit.json", audit)
    np.savez_compressed(OUT / "contrast_influence_audit.npz", **arrays)
    # Candidate deltas are descriptive; different n-shrink and cap scales remain visible.
    bc = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    sc = pd.read_csv(B.SEOUL / "outputs/correction_components.csv", dtype={"level": str})
    b = bc[bc.scope.eq("core") & bc.variant.eq("tail25")]
    s = sc[sc.scope.eq("core") & sc.variant.eq("tail25")]
    ids = ["distance_m", "period", "family", "block", "level", "section"]
    c = b.merge(s, on=ids, suffixes=("_busan", "_seoul"), validate="one_to_one")
    c["both_available"] = c.available_busan & c.available_seoul
    c["candidate_busan_minus_seoul"] = (c.add_seconds_busan - c.add_seconds_seoul).where(
        c.both_available
    )
    c["comparison_type"] = (
        "descriptive_candidate_difference_including_different_shrink_and_moisture_mix"
    )
    c.to_csv(OUT / "venue_candidate_comparison.csv", index=False)
    B.dump(
        OUT / "comparison_summary.json",
        dict(
            direct_contrasts=len(frame),
            supported_direct_contrasts=int(frame.supported.sum()),
            candidate_pairs=len(c),
            both_available_candidate_pairs=int(c.both_available.sum()),
            comparison_method=(
                "independent venue fits, shared numeric moisture mix, "
                "combined horse/day influence clusters"
            ),
            next_race_prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
