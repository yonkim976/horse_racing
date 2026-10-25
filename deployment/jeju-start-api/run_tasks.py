def run_tasks(session: Session, api, xml, website, *, days: list[date], raw_dir: Path) -> list:
    results = []
    quota_exhausted = False

    def task(name, callback, **context):
        nonlocal quota_exhausted
        if quota_exhausted:
            results.append({"kind": name, **context, "status": "not_attempted_quota"})
            return
        try:
            summary = callback()
            result = {
                "kind": name,
                **context,
                "status": "observed_empty" if not summary.records_fetched else "completed",
                "run_id": summary.run_id,
                "fetched": summary.records_fetched,
                "processed": summary.records_written,
            }
        except Exception as exc:
            session.rollback()
            quota_exhausted = isinstance(exc, KraApiRateLimitError)
            # URLs/SQL exception text can contain credentials: report type only.
            result = {"kind": name, **context, "status": "failed", "error_type": type(exc).__name__}
        session.rollback()
        results.append(result)
        emit("training_task", **result)

    for day in days:
        label = day.strftime("%Y%m%d")
        for meet in (1, 2, 3):
            task(
                "daily",
                lambda label=label, meet=meet: ingest_training(
                    session,
                    api,
                    training_date=label,
                    meet=meet,
                    raw_data_dir=raw_dir,
                ),
                day=label,
                meet=meet,
            )
            task(
                "starting",
                lambda label=label, meet=meet: ingest_start_training(
                    session,
                    api,
                    training_date=label,
                    meet=meet,
                    raw_data_dir=raw_dir,
                ),
                day=label,
                meet=meet,
                source="api22",
            )
        task(
            "swimming",
            lambda label=label: ingest_swim_training_date(
                session,
                xml,
                training_date=label,
                raw_data_dir=raw_dir,
            ),
            day=label,
        )
    task(
        "hill",
        lambda: ingest_hill_training(
            session,
            xml,
            start_date=days[0].strftime("%Y%m%d"),
            end_date=days[-1].strftime("%Y%m%d"),
            raw_data_dir=raw_dir,
        ),
        start=str(days[0]),
        end=str(days[-1]),
    )
    return results
