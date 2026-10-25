"""Independent FE solves, identities, legacy equivalence and candidate checks."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsqr
from scipy.stats import t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("seoul_verify_analysis", HERE / "analyze.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def main():
    population, data = S.load()
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["input_sha256"].items():
        assert S.A.sha(S.ROOT / name) == digest, name
    for name, entry in summary["raw_verification"]["source_files"].items():
        assert S.A.sha(S.ROOT / name) == entry["sha256"], name
    p = pd.read_csv(OUT / "effect_profiles.csv", dtype={"level": str})
    c = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    params = np.load(OUT / "parameters.npz", allow_pickle=False)
    models = json.loads((OUT / "models.json").read_text())
    solves, errors, identity_errors = [], [], []
    for model in models:
        key = model["matrix_key"]
        parts = model["parts"]
        beta, vectors = params[f"{key}_beta"], params[f"{key}_vectors"]
        variance = params[f"{key}_variance"]
        q = p[p.matrix_key.eq(int(key))]
        for j, part in enumerate(parts):
            r = q[q.section.eq(part)].sort_values("contrast_index")
            good = r.estimable.to_numpy()
            assert np.allclose(r.effect_seconds.to_numpy()[good], (vectors @ beta[:, j])[good])
            assert np.allclose(r.se.to_numpy()[good] ** 2, variance[good, j])
            crit = t.ppf(0.975, model["df"])
            assert np.allclose(r.ci_low[good], r.effect_seconds[good] - crit * r.se[good])
            assert np.allclose(r.ci_high[good], r.effect_seconds[good] + crit * r.se[good])
        partition = (
            S.CORE
            if model["scope"] == "core"
            else ["early", *S.segments(model["distance_m"]), "late"]
        )
        difference = beta[:, parts.index("finish")] - sum(
            beta[:, parts.index(a)] for a in partition
        )
        identity_errors.append(float(abs(difference).max()))
        assert abs(difference).max() < 1e-6
        assert np.allclose(
            beta[:, parts.index("last600")],
            beta[:, parts.index("middle2")] + beta[:, parts.index("late")],
            atol=1e-6,
        )
        if (
            model["variant"] != "tail25"
            or model["period"] != "all_mad4"
            or model["distance_m"] not in {1200, 1300, 1700, 1800}
        ):
            continue
        s = S.sample(
            data,
            dist=model["distance_m"],
            scope=model["scope"],
            period=model["period"],
            variant=model["variant"],
        )
        x, labels, _, _ = S.OLD.design(s)
        assert labels == model["labels"]
        weights = S.L.weights(s, False)
        horse = S.OLD.codes(s.horse_id)
        dummy = sparse.csr_matrix((np.ones(len(s)), (np.arange(len(s)), horse)))
        matrix = sparse.hstack([sparse.csr_matrix(x), dummy], format="csr")
        matrix = sparse.diags(np.sqrt(weights)) @ matrix
        norm = np.sqrt(np.asarray(matrix.power(2).sum(axis=0)).ravel())
        norm[norm == 0] = 1
        scaled = matrix @ sparse.diags(1 / norm)
        targets = (
            ["middle1", "middle2"]
            if model["scope"] == "core"
            else ["2C_to_3C" if model["distance_m"] >= 1700 else "S1F_to_3C", "4C_to_G1F"]
        )
        for part in targets:
            y = s[part].to_numpy(float) * np.sqrt(weights)
            fit = lsqr(scaled, y, atol=1e-12, btol=1e-12, iter_lim=20000)
            assert fit[1] in {1, 2}, (key, part, fit[1])
            explicit = fit[0][: len(labels)] / norm[: len(labels)]
            contrasts = vectors @ explicit
            expected = vectors @ beta[:, parts.index(part)]
            estimable = q[q.section.eq(part)].sort_values("contrast_index").estimable.to_numpy()
            error = float(abs(contrasts[estimable] - expected[estimable]).max())
            assert error < 2e-5, (key, part, error)
            errors.append(error)
            solves.append(
                dict(
                    matrix_key=key,
                    distance_m=model["distance_m"],
                    scope=model["scope"],
                    section=part,
                    rows=len(s),
                    iterations=fit[2],
                    max_contrast_error=error,
                )
            )
            print("independent solve", model["distance_m"], model["scope"], part, error, flush=True)
    for key, group in c.groupby(
        ["distance_m", "scope", "period", "variant", "family", "block", "level"]
    ):
        wide = group.set_index("section")
        if not group.available.all():
            assert group.add_seconds.isna().all()
            continue
        partition = S.CORE if key[1] == "core" else ["early", *S.segments(key[0]), "late"]
        assert (
            abs(wide.loc[partition, "add_seconds"].sum() - wide.loc["finish", "add_seconds"]) < 1e-7
        )
        assert (
            abs(
                wide.loc[["middle2", "late"], "add_seconds"].sum()
                - wide.loc["last600", "add_seconds"]
            )
            < 1e-7
        )
    for key, group in c[c.available & ~c.family.eq("moisture")].groupby(
        ["distance_m", "scope", "period", "variant", "family", "block", "section"]
    ):
        values = group.add_seconds.to_numpy()
        weights = np.ones(len(group)) if key[4] == "month" else group.n.to_numpy(float)
        assert abs(np.average(values, weights=weights)) < 1e-8
    old = pd.read_csv(S.E.OUT / "joint_sensitivity_profiles.csv", dtype={"level": str})
    identities = ["distance_m", "period", "variant", "family", "block", "level", "section"]
    paired = p[p.scope.eq("core")].merge(
        old[old.meet.eq("서울")], on=identities, suffixes=("", "_old"), validate="one_to_one"
    )
    common = paired.estimable & paired.estimable_old
    old_error = float(
        abs(paired.loc[common, "effect_seconds"] - paired.loc[common, "effect_seconds_old"]).max()
    )
    assert old_error < 1e-6
    spec = importlib.util.spec_from_file_location("seoul_verify_apply", HERE / "apply.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    helper = ap.SeoulSections()
    examples = []
    for distance in [1000, 1200, 1300, 1400, 1600, 1700, 1800, 2000]:
        for scope in ["core", "corner"]:
            e = helper.lookup(
                distance=distance,
                moisture=16,
                month=7,
                horse_number=10,
                roster=list(range(1, 11)),
                as_of="2026-10-11",
                scope=scope,
            )
            examples.append(e)
            if all(r["complete"] for r in e["sections"].values()):
                partition = S.CORE if scope == "core" else ["early", *S.segments(distance), "late"]
                assert (
                    abs(
                        sum(e["sections"][part]["total_add_seconds"] for part in partition)
                        - e["sections"]["finish"]["total_add_seconds"]
                    )
                    < 1e-7
                )
    S.dump(OUT / "application_examples.json", examples)
    invalid = 0
    base = dict(
        distance=1200,
        moisture=16,
        month=7,
        horse_number=10,
        roster=list(range(1, 11)),
        as_of="2026-10-11",
    )
    for change in [
        dict(moisture=0),
        dict(month=13),
        dict(as_of="2026-10-10"),
        dict(roster=[1, 1, 10]),
        dict(horse_number=11),
        dict(scope="fake"),
        dict(roster=[1, 2], horse_number=1),
        dict(roster=list(range(1, 18))),
    ]:
        try:
            helper.lookup(**(base | change))
        except ValueError:
            invalid += 1
    assert invalid == 8
    S.dump(
        OUT / "verification.json",
        dict(
            verified_population_rows=len(population),
            models_checked=len(models),
            candidate_rows_checked=len(c),
            independent_explicit_dummy_solves=solves,
            max_explicit_contrast_error=max(errors),
            max_partition_coefficient_error=max(identity_errors),
            legacy_joint_profiles_compared=int(common.sum()),
            legacy_joint_max_error=old_error,
            invalid_requests_rejected=invalid,
            production_changed=False,
            prediction_validation=False,
        ),
    )
    print("verification passed", len(solves), max(errors), old_error)


if __name__ == "__main__":
    main()
