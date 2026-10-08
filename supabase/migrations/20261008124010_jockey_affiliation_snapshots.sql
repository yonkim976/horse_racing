create table public.jockey_affiliation_snapshots (
    jockey_id integer not null references public.jockeys(id) on delete restrict,
    observed_on date not null,
    meet_code smallint not null check (meet_code in (1, 2, 3)),
    official_name_ko varchar(100) not null,
    observed_at_ms bigint not null,
    source_url text not null,
    source_sha256 varchar(64) not null check (length(source_sha256) = 64),
    api_source_url text not null,
    api_sha256 varchar(64) not null check (length(api_sha256) = 64),
    primary key (jockey_id, observed_on)
);

create index ix_jockey_affiliation_snapshots_observed_meet
    on public.jockey_affiliation_snapshots (observed_on, meet_code);

alter table public.jockey_affiliation_snapshots enable row level security;
revoke all on public.jockey_affiliation_snapshots from public, anon, authenticated;
