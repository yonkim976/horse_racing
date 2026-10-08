set local lock_timeout = '5s';
set local statement_timeout = '30s';
-- No backfill or zero default: older snapshots did not ingest current ownership.
alter table public.owner_catalog_snapshots
    add column current_owned_horses integer,
    add constraint current_owned_horses_valid
        check (current_owned_horses >= 0 and current_owned_horses <= total_registered_horses);
