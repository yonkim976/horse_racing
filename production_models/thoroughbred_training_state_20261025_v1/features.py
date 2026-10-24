"""Rebuild the promoted 136-column contract from a complete card and dated sources."""

from pathlib import Path
import hashlib, json
import duckdb
import numpy as np
import pandas as pd
import feature_math as math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KEY = ["race_key", "program_no", "horse_id"]
CONTRACT = json.loads((HERE / "feature_contract.json").read_text())
BASIC = CONTRACT["basic_training"]
PERSONAL = CONTRACT["personal_training"]
PERSONAL_SOURCE = CONTRACT["personal_sources"]
REQUIRED = [
    "meet",
    "race_date",
    "race_no",
    "program_no",
    "horse_id",
    "distance_m",
    "grade_raw",
    "current_carried_weight",
]


def require(condition, message="Invalid model input"):
    if not condition:
        raise ValueError(message)


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_card(card, *, multiple_dates=False):
    missing = set(REQUIRED) - set(card)
    require(not missing, ("Missing card fields", sorted(missing)))
    require(
        not any(
            x in card
            for x in [
                "outcome",
                "finish_order",
                "finish_raw",
                "win_odds",
                "place_odds",
                "race_time_s",
            ]
        ),
        "Result/odds columns in input card",
    )
    f = card.copy()
    f["race_date"] = pd.to_datetime(f.race_date).dt.normalize()
    require(len(f) > 0 and f.meet.isin([1, 3]).all(), "Only Seoul/Busan are enabled")
    require(multiple_dates or f.race_date.nunique() == 1, "One race day per live card")
    require(
        f.horse_id.map(lambda x: isinstance(x, str) and len(x) == 7 and x.isdigit()).all(),
        "Official horse IDs must keep leading zeros",
    )
    require(
        f.program_no.between(1, 30).all() and (f.program_no % 1).eq(0).all(),
        "Model validation failed",
    )
    require(
        f.race_no.between(1, 30).all() and (f.race_no % 1).eq(0).all(),
        "Race numbers must be positive integers",
    )
    require(f.distance_m.between(800, 4000).all(), "Model validation failed")
    require(
        f.current_carried_weight.isna().all()
        or f.current_carried_weight.dropna().between(40, 70).all(),
        "Model validation failed",
    )
    f["meet"] = f.meet.astype(int)
    f["race_no"] = f.race_no.astype(int)
    f["program_no"] = f.program_no.astype(int)
    f["race_key"] = (
        f.meet.astype(str) + ":" + f.race_date.dt.strftime("%Y%m%d") + ":" + f.race_no.astype(str)
    )
    require(
        not f.duplicated(KEY).any()
        and not f.duplicated(["race_key", "horse_id"]).any()
        and not f.duplicated(["race_key", "program_no"]).any(),
        "Duplicate card runner identity or program number",
    )
    actual = f.groupby("race_key").horse_id.transform("size")
    if "field_size" in f:
        require(f.field_size.eq(actual).all(), "Card roster is incomplete or stale")
    if "scratched" in f:
        require(f.scratched.dropna().isin([True, False]).all(), "Model validation failed")
        f = f[~f.scratched.fillna(False)].copy()
        actual = f.groupby("race_key").horse_id.transform("size")
    f["field_size"] = actual
    require(actual.between(3, 20).all(), "Model validation failed")
    require(f.groupby("race_key").distance_m.nunique().eq(1).all(), "Model validation failed")
    require(f.groupby("race_key").grade_raw.nunique().eq(1).all(), "Model validation failed")
    f["cutoff_date"] = f.race_date - pd.Timedelta(days=2)
    f["year"] = f.race_date.dt.year
    require(
        f.year.eq(2026).all(),
        "This frozen profile is valid for2026; prepare a separately reviewed2027 profile",
    )
    f["grade"] = pd.to_numeric(f.grade_raw.str.extract(r"([1-6])", expand=False), errors="coerce")
    f["grade_kind"] = f.grade_raw.str.extract(r"^(국|혼)", expand=False).fillna("other")
    f = f.sort_values(["meet", "race_date", "race_no", "program_no"]).reset_index(drop=True)
    f["row_number"] = np.arange(len(f))
    return f


def load_sources(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    paths = {}
    for name, item in manifest["assets"].items():
        p = (ROOT / item["path"]).resolve()
        require(p.is_relative_to(ROOT) and p.is_file(), "Model validation failed")
        require(sha(p) == item["sha256"], ("Source snapshot hash changed", name))
        paths[name] = p
    return paths, manifest


def base_features(f, h, core):
    with duckdb.connect(str(core), read_only=True) as db:
        meta = db.execute("""SELECT cast(source_meet AS VARCHAR)||':'||cast(result_date AS VARCHAR)||':'||cast(cast(result_race_no AS INTEGER) AS VARCHAR) race_key,
          cast(horse_program_no_raw AS INTEGER) program_no,horse_id_raw horse_id,
          try_cast(horse_age_raw AS DOUBLE) age,horse_sex_raw sex,try_cast(carried_weight_raw AS DOUBLE) carried
          FROM confirmed_runners WHERE source_meet IN ('1','3')""").df()
    require(not meta.duplicated(KEY).any(), "Model validation failed")
    history = (
        h[KEY + ["race_date"]]
        .merge(meta, on=KEY, how="left", validate="one_to_one")
        .sort_values(["horse_id", "race_date"])
    )
    require(not history.duplicated(["horse_id", "race_date"]).any(), "Model validation failed")
    history["age"] = history.age.where(history.age.between(1, 20))
    history["carried"] = history.carried.where(history.carried.between(40, 70))
    history["history_count"] = history.groupby("horse_id", sort=False).cumcount() + 1
    history = history.rename(
        columns={
            "race_date": "history_source_date",
            "age": "previous_age",
            "sex": "previous_sex",
            "carried": "previous_carried_weight",
        }
    )
    left = f.copy()
    left["_row"] = np.arange(len(left))
    right = history[
        [
            "horse_id",
            "history_source_date",
            "history_count",
            "previous_age",
            "previous_sex",
            "previous_carried_weight",
        ]
    ]
    out = (
        pd.merge_asof(
            left.sort_values("cutoff_date"),
            right.sort_values("history_source_date"),
            by="horse_id",
            left_on="cutoff_date",
            right_on="history_source_date",
            direction="backward",
        )
        .sort_values("_row")
        .drop(columns="_row")
        .reset_index(drop=True)
    )
    out["history_count"] = out.history_count.fillna(0)
    out["days_since_last"] = (out.race_date - out.history_source_date).dt.days
    out["current_vs_previous_carried_weight"] = (
        out.current_carried_weight - out.previous_carried_weight
    )
    return out


def state_observations(h, db_path):
    with duckdb.connect(str(db_path), read_only=True) as db:
        raw = db.execute("""SELECT cast(e.canonical_meet AS VARCHAR)||':'||strftime(e.race_date,'%Y%m%d')||':'||cast(e.race_no AS VARCHAR) race_key,
          e.chul_no program_no,e.hr_no horse_id,e.finish_order,e.result_status,r.distance_m official_distance
          FROM entry_result e JOIN race r USING(race_id) WHERE e.canonical_meet IN (1,3) AND e.race_date>=DATE '2010-01-01'""").df()
    g = h.merge(raw, on=KEY, how="left", validate="one_to_one")
    g = g[g.result_status.isin(["finished", "did_not_finish", "disqualified"])].copy()
    g["result_distance"] = g.result_distance.fillna(g.official_distance)
    g = g[g.result_distance.notna()]
    for raw_col, adjusted in [("early", "early_adjusted"), ("last600", "last600_adjusted")]:
        g[adjusted] = g[adjusted].fillna(g[raw_col])
    return g.sort_values(["race_date", "race_key", "program_no"]).reset_index(drop=True)


def training_features(card, core, data):
    horses = card[["horse_id"]].drop_duplicates()
    last = card.cutoff_date.max()
    with duckdb.connect(str(data), read_only=True) as db:
        db.register("model_horses", horses)
        anchors = db.execute(
            """SELECT cast(canonical_meet AS INTEGER) meet,
          cast(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||cast(race_no AS VARCHAR) race_key,
          chul_no program_no,hr_no horse_id,race_date FROM entry_result
          JOIN model_horses ON hr_no=model_horses.horse_id
          WHERE canonical_meet IN (1,3) AND result_status IN ('finished','did_not_finish','disqualified','special_result') AND race_date<=?
          ORDER BY canonical_meet,hr_no,race_date,race_no,chul_no""",
            [last.to_pydatetime()],
        ).df()
    missing = card[["meet", *KEY, "race_date"]].merge(
        anchors[KEY], on=KEY, how="left", indicator=True
    )
    missing = missing[missing._merge.eq("left_only")].drop(columns="_merge")
    anchors = (
        pd.concat([anchors, missing], ignore_index=True)
        .sort_values(["meet", "horse_id", "race_date"])
        .reset_index(drop=True)
    )
    require(
        not anchors.duplicated(["meet", "horse_id", "race_date"]).any(), "Model validation failed"
    )
    anchors["anchor_id"] = np.arange(len(anchors))
    anchors["cutoff"] = anchors.race_date - pd.Timedelta(days=2)
    with duckdb.connect(str(core), read_only=True) as db:
        db.execute("SET threads=4")
        db.register("model_horses", horses)
        db.register("anchors", anchors)
        query = (
            (HERE / "daily_sql.sql")
            .read_text()
            .replace(
                "WHERE v.coverage_status=",
                "WHERE t.official_horse_id IN (SELECT horse_id FROM model_horses) AND v.coverage_status=",
            )
        )
        db.execute("CREATE TEMP TABLE study_daily AS " + query)
        z = db.execute((HERE / "window_sql.sql").read_text()).df()
    require(np.array_equal(anchors.anchor_id, z.anchor_id), "Model validation failed")
    f = pd.concat([anchors, z.drop(columns="anchor_id")], axis=1)
    f["train_minutes_per_day14"] = f.train_minutes14 / f.train_days14.replace(0, np.nan)
    f["train_gap_days28"] = (f.race_date - f.training_source_max_date).dt.days.astype(float)
    f.loc[f.train_coverage28.lt(1), [v for v in BASIC if v != "train_coverage28"]] = np.nan
    values = f[PERSONAL_SOURCE].to_numpy(float)
    added = np.full((len(f), len(PERSONAL)), np.nan)
    for ix in f.groupby(["meet", "horse_id"], sort=False).indices.values():
        days = f.iloc[ix].race_date.to_numpy(dtype="datetime64[D]")
        ends = np.searchsorted(days, days - np.timedelta64(2, "D"), side="right")
        pos = ends[:, None] - np.arange(1, 4)[None, :]
        exists = pos >= 0
        past = values[ix][np.maximum(pos, 0)].copy()
        past[~exists] = np.nan
        complete = np.isfinite(past).all(axis=2)
        n = complete.sum(1)
        past[~complete] = np.nan
        mean = np.nansum(past, axis=1) / np.maximum(n, 1)[:, None]
        delta = values[ix] - mean
        delta[n < 2] = np.nan
        sd = np.sqrt(np.nansum((past[:, :, 1] - mean[:, None, 1]) ** 2, axis=1) / np.maximum(n, 1))
        sd[n < 2] = np.nan
        added[ix, :6] = delta
        added[ix, 6] = n
        added[ix, 7] = sd
    f[PERSONAL] = added
    return card[KEY].merge(
        f[KEY + BASIC + PERSONAL + ["training_source_max_date"]],
        on=KEY,
        how="left",
        validate="one_to_one",
    )


def build(card, manifest_path, *, dry_run=False, progress=False):
    f = validate_card(card, multiple_dates=dry_run)
    paths, manifest = load_sources(manifest_path)
    h = (
        pd.read_parquet(paths["section_history"])
        .sort_values(["horse_id", "race_date"])
        .reset_index(drop=True)
    )
    require(not h.duplicated(["horse_id", "race_date"]).any(), "Model validation failed")
    f = base_features(f, h, paths["core_database"])
    records = pd.read_parquet(paths["profile_records"])
    records = h[KEY + ["race_date", "supported"]].merge(
        records[KEY + ["candidate_index"]], on=KEY, validate="one_to_one"
    )
    f = math.profile_frame(records, f)
    ix = math.slots(f, h)
    f = pd.concat([f, math.historical_features(f, h, ix, True)], axis=1)
    events = (
        pd.read_parquet(paths["role_history"])
        .sort_values(["horse_id", "race_date"])
        .reset_index(drop=True)
    )
    # The slot indexes are defined by the section history, so align explicitly by identity.
    events = h[KEY].merge(events, on=KEY, validate="one_to_one")
    f = pd.concat([f, math.conditional_profiles(events, ix), math.gate_features(f)], axis=1)
    state = math.generate(f, state_observations(h, paths["dataset_database"]), progress=progress)
    require(np.array_equal(state.row_number, f.row_number), "Model validation failed")
    f = pd.concat([f, state.drop(columns="row_number")], axis=1)
    training = training_features(f, paths["core_database"], paths["dataset_database"])
    f = pd.concat([f, training.drop(columns=KEY)], axis=1)
    missing = set(CONTRACT["features"]) - set(f)
    require(not missing, sorted(missing))
    require(not f.columns.duplicated().any(), "Model validation failed")
    for name in [
        "history_source_date",
        "candidate_source_date",
        "state_source_date",
        "training_source_max_date",
    ]:
        require((f[name].isna() | f[name].le(f.cutoff_date)).all(), name)
    require(
        not np.isinf(
            f[[x for x in CONTRACT["features"] if pd.api.types.is_numeric_dtype(f[x])]].to_numpy(
                float
            )
        ).any(),
        "Model validation failed",
    )
    metadata = {
        "source_manifest_sha256": sha(manifest_path),
        "history_latest_date": str(h.race_date.max().date()),
        "card_dates": sorted(f.race_date.dt.strftime("%Y-%m-%d").unique().tolist()),
        "cutoff_policy": "T-2",
        "source_hashes": {k: manifest["assets"][k]["sha256"] for k in paths},
        "all_runner_rosters_preserved": True,
        "races": int(f.race_key.nunique()),
        "runners": len(f),
        "partial_training_windows": int(f.train_coverage28.lt(1).sum()),
        "historical_publication_times_certified": False,
        "dry_run": bool(dry_run),
    }
    return f, metadata
