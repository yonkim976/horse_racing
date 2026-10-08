-- Version aligned with the applied Supabase migration history.
set local lock_timeout = '5s';
create table public.owner_catalog_snapshots (
    ingestion_run_id integer not null references public.ingestion_runs(id) on delete restrict,
    meet_code smallint not null check (meet_code in (1,2,3)),
    kra_owner_id varchar(6) not null check (kra_owner_id ~ '^[0-9]{6}$' and kra_owner_id <> '000000'),
    owner_id integer references public.owners(id) on delete set null,
    official_name_ko varchar(100) not null,
    registration_date date,
    total_registered_horses integer not null check (total_registered_horses >= 0),
    observed_at_ms bigint not null,
    source_document_id integer not null references public.source_documents(id) on delete restrict,
    primary key (ingestion_run_id, meet_code, kra_owner_id)
);
create index ix_owner_catalog_snapshots_owner_run
    on public.owner_catalog_snapshots(owner_id, ingestion_run_id);
create index ix_owner_catalog_snapshots_source_document
    on public.owner_catalog_snapshots(source_document_id);
alter table public.owner_catalog_snapshots enable row level security;
revoke all on public.owner_catalog_snapshots from public, anon, authenticated;
