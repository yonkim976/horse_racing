-- Applied to horse-racing-prod as migration 20260929080214.
create table public.trainer_status_observations (
    official_tr_no text not null,
    observed_on date not null,
    canonical_name_ko text not null,
    region_code text not null check (region_code in ('SEOUL', 'JEJU', 'YEONGNAM')),
    status_code text not null check (
        status_code in ('active', 'retired_confirmed', 'domestic_registration_ended')
    ),
    status_label_ko text not null,
    source_end_date date,
    classification_basis text not null,
    source_url text not null,
    source_api_sha256 text not null check (length(source_api_sha256) = 64),
    retired_list_sha256 text check (
        retired_list_sha256 is null or length(retired_list_sha256) = 64
    ),
    primary key (official_tr_no, observed_on),
    check (
        (status_code = 'active' and source_end_date is null and status_label_ko = '현역')
        or (status_code = 'retired_confirmed' and source_end_date is not null
            and status_label_ko = '은퇴 확정')
        or (status_code = 'domestic_registration_ended' and source_end_date is not null
            and status_label_ko = '국내 등록 종료(은퇴 미확인)')
    )
);

create index ix_trainer_status_observations_status_date
    on public.trainer_status_observations (status_code, observed_on);

create table public.trainer_identity_resolutions (
    temporary_trainer_ref text primary key references public.trainers(kra_trainer_id)
        on delete restrict,
    official_tr_no text not null,
    source_name_ko text not null,
    canonical_name_ko text not null,
    resolution_status text not null check (
        resolution_status in ('confirmed', 'official_id_candidate')
    ),
    matched_race_rows integer not null check (matched_race_rows > 0),
    source_reference text not null,
    reviewed_on date not null
);

create index ix_trainer_identity_resolutions_official_no
    on public.trainer_identity_resolutions (official_tr_no);

alter table public.trainer_status_observations enable row level security;
alter table public.trainer_identity_resolutions enable row level security;
revoke all on public.trainer_status_observations from public, anon, authenticated;
revoke all on public.trainer_identity_resolutions from public, anon, authenticated;
