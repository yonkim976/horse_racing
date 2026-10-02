create table public.trainer_affiliation_snapshots (
    trainer_id integer not null references public.trainers(id) on delete restrict,
    observed_on date not null,
    meet_code smallint not null check (meet_code in (1, 2, 3)),
    stable_part smallint not null check (stable_part between 1 and 99),
    official_name_ko varchar(100) not null,
    stats_as_of date,
    observed_at_ms bigint not null,
    source_url text not null,
    source_sha256 varchar(64) not null check (length(source_sha256) = 64),
    primary key (trainer_id, observed_on)
);

create index ix_trainer_affiliation_snapshots_observed_meet
    on public.trainer_affiliation_snapshots (observed_on, meet_code);

alter table public.trainer_affiliation_snapshots enable row level security;
revoke all on public.trainer_affiliation_snapshots from public, anon, authenticated;
