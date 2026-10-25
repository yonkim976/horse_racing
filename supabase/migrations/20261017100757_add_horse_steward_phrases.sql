-- Official website wording attached to verified operational horse/race identities.
-- Observation time is not the original publication time of an old report.
create table public.horse_steward_phrases (
    id serial primary key,
    horse_id integer not null references public.horses(id) on delete restrict,
    race_id integer not null references public.races(id) on delete restrict,
    race_entry_id integer references public.race_entries(id) on delete restrict,
    race_steward_report_id integer references public.race_steward_reports(id) on delete restrict,
    historical_program integer not null check (historical_program > 0),
    phrase_text text not null check (length(btrim(phrase_text)) > 0),
    phrase_sha256 varchar(64) not null check (phrase_sha256 ~ '^[0-9a-f]{64}$'),
    text_basis varchar(30) not null default 'official_website' check (text_basis = 'official_website'),
    website_text_verified boolean not null check (website_text_verified),
    entry_link_status varchar(30) not null check (
        (entry_link_status = 'matched' and race_entry_id is not null)
        or (entry_link_status = 'entry_missing' and race_entry_id is null)
    ),
    provenance_json text not null check (
        jsonb_typeof(provenance_json::jsonb) = 'array'
        and jsonb_array_length(provenance_json::jsonb) > 0
    ),
    source_dataset_sha256 varchar(64) not null check (source_dataset_sha256 ~ '^[0-9a-f]{64}$'),
    source_dataset_path text not null,
    first_observed_at_ms bigint not null check (first_observed_at_ms > 0),
    last_observed_at_ms bigint not null check (last_observed_at_ms >= first_observed_at_ms),
    source_published_at_ms bigint,
    historical_publication_time_verified boolean not null default false,
    ingested_at_ms bigint not null check (ingested_at_ms >= last_observed_at_ms),
    constraint uq_horse_steward_phrases_content unique (horse_id, race_id, phrase_sha256),
    constraint ck_horse_steward_publication_evidence check (
        (not historical_publication_time_verified and source_published_at_ms is null)
        or (historical_publication_time_verified and source_published_at_ms is not null and source_published_at_ms > 0
            and source_published_at_ms <= first_observed_at_ms)
    )
);
create index ix_horse_steward_phrases_race on public.horse_steward_phrases(race_id);
create index ix_horse_steward_phrases_entry on public.horse_steward_phrases(race_entry_id);
create index ix_horse_steward_phrases_report on public.horse_steward_phrases(race_steward_report_id);
create index ix_horse_steward_phrases_observed on public.horse_steward_phrases(first_observed_at_ms);
alter table public.horse_steward_phrases enable row level security;
revoke all on public.horse_steward_phrases from public, anon, authenticated;
revoke all on sequence public.horse_steward_phrases_id_seq from public, anon, authenticated;
grant select on public.horse_steward_phrases to service_role;
comment on table public.horse_steward_phrases is
    'Backend-only literal KRA horse-specific steward phrases. No situation classification. Entry may be missing; horse and race are always linked. Historical publication time remains unknown unless separately evidenced.';
