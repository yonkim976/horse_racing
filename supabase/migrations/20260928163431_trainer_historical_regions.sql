create table public.trainer_historical_regions (
    trainer_id integer not null references public.trainers(id) on delete restrict,
    region_code varchar(16) not null check (region_code in ('SEOUL', 'JEJU', 'YEONGNAM')),
    observed_on date not null,
    source_end_date date not null,
    retired_list_confirmed boolean not null,
    observed_at_ms bigint not null,
    source_url text not null,
    source_sha256 varchar(64) not null check (length(source_sha256) = 64),
    primary key (trainer_id, region_code, observed_on)
);

create index ix_trainer_historical_regions_region_date
    on public.trainer_historical_regions (region_code, observed_on);

alter table public.trainer_historical_regions enable row level security;
revoke all on public.trainer_historical_regions from public, anon, authenticated;
