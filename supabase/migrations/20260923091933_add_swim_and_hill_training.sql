create table public.horse_swim_training (
    id bigint generated always as identity primary key,
    source_document_id integer references public.source_documents(id) on delete set null,
    horse_id integer references public.horses(id) on delete set null,
    kra_horse_id_raw varchar(30) not null,
    horse_name_raw varchar(100) not null,
    meet_code smallint not null,
    training_date_local date not null,
    swim_count smallint not null,
    stable_part smallint,
    stable_note text,
    trainer_part smallint,
    trainer_name varchar(100),
    observed_at_ms bigint not null,
    constraint ck_horse_swim_training_valid_meet_code
        check (meet_code in (1, 2, 3, 4)),
    constraint ck_horse_swim_training_positive_swim_count
        check (swim_count > 0),
    constraint uq_horse_swim_training_natural
        unique (kra_horse_id_raw, meet_code, training_date_local)
);

create index ix_horse_swim_training_horse_date
    on public.horse_swim_training (horse_id, training_date_local);
create index ix_horse_swim_training_raw_horse_date
    on public.horse_swim_training (kra_horse_id_raw, training_date_local);
create index ix_horse_swim_training_source_document
    on public.horse_swim_training (source_document_id);

create table public.horse_hill_training (
    id bigint generated always as identity primary key,
    source_document_id integer references public.source_documents(id) on delete set null,
    horse_id integer references public.horses(id) on delete set null,
    kra_horse_id_raw varchar(30) not null,
    horse_name_raw varchar(100) not null,
    farm_name varchar(50) not null,
    tag_id varchar(30),
    chip_id varchar(30),
    sex_raw varchar(20),
    birth_date date,
    sire_name_raw varchar(100),
    dam_name_raw varchar(100),
    training_operator_name varchar(100),
    owner_name_raw varchar(100),
    farm_entry_date date,
    farm_entry_reason varchar(100),
    training_date_local date not null,
    training_time_local time,
    f1_seconds numeric(6, 1),
    f2_seconds numeric(6, 1),
    f3_seconds numeric(6, 1),
    total_seconds numeric(7, 1),
    quality_status varchar(20) not null,
    source_row_hash varchar(64) not null,
    observed_at_ms bigint not null,
    constraint ck_horse_hill_training_valid_quality_status
        check (quality_status in ('valid', 'zero_record', 'incomplete')),
    constraint ck_horse_hill_training_nonnegative_f1_seconds
        check (f1_seconds is null or f1_seconds >= 0),
    constraint ck_horse_hill_training_nonnegative_f2_seconds
        check (f2_seconds is null or f2_seconds >= 0),
    constraint ck_horse_hill_training_nonnegative_f3_seconds
        check (f3_seconds is null or f3_seconds >= 0),
    constraint ck_horse_hill_training_nonnegative_total_seconds
        check (total_seconds is null or total_seconds >= 0),
    constraint uq_horse_hill_training_source_row_hash unique (source_row_hash)
);

create index ix_horse_hill_training_horse_date
    on public.horse_hill_training (horse_id, training_date_local);
create index ix_horse_hill_training_raw_horse_date
    on public.horse_hill_training (kra_horse_id_raw, training_date_local);
create index ix_horse_hill_training_source_document
    on public.horse_hill_training (source_document_id);

alter table public.horse_swim_training enable row level security;
alter table public.horse_hill_training enable row level security;

revoke all on table public.horse_swim_training from anon, authenticated;
revoke all on table public.horse_hill_training from anon, authenticated;

comment on table public.horse_swim_training is
    'Official KRA daily swimming-training counts. Raw rows are retained independently from ordinary track training.';
comment on table public.horse_hill_training is
    'Official KRA Jeju/Jangsu hill-track training events, including rest and rehabilitation stays.';
comment on column public.horse_hill_training.source_row_hash is
    'SHA-256 of the normalized official row; exact duplicates collapse while same-second distinct records remain.';
comment on column public.horse_hill_training.quality_status is
    'valid, zero_record, or incomplete. Raw zero records are retained but excluded from model features.';
