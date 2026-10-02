create table public.trainer_people (
    person_key text primary key,
    canonical_name_en text not null,
    birth_date date,
    identity_basis text not null check (
        identity_basis in ('birth_date_and_name', 'english_name_and_visit', 'mixed')
    ),
    decision_source text not null,
    decided_on date not null
);

create table public.trainer_person_links (
    trainer_ref text primary key,
    person_key text not null references public.trainer_people(person_key) on delete restrict,
    ref_kind text not null check (ref_kind in ('official_tr_no', 'text_ingest_id')),
    name_at_source text not null,
    link_basis text not null check (
        link_basis in ('birth_date_match', 'english_name_and_visit', 'archived_race_candidate')
    ),
    source_reference text not null,
    evidence_note text
);

create index ix_trainer_person_links_person_key
    on public.trainer_person_links (person_key);

alter table public.trainer_people enable row level security;
alter table public.trainer_person_links enable row level security;
revoke all on public.trainer_people from public, anon, authenticated;
revoke all on public.trainer_person_links from public, anon, authenticated;
