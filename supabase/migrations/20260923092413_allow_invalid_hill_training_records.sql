alter table public.horse_hill_training
    drop constraint ck_horse_hill_training_valid_quality_status,
    drop constraint ck_horse_hill_training_nonnegative_f1_seconds,
    drop constraint ck_horse_hill_training_nonnegative_f2_seconds,
    drop constraint ck_horse_hill_training_nonnegative_f3_seconds,
    drop constraint ck_horse_hill_training_nonnegative_total_seconds;

alter table public.horse_hill_training
    add constraint ck_horse_hill_training_valid_quality_status
    check (
        quality_status in (
            'valid', 'zero_record', 'incomplete', 'invalid_record'
        )
    );

comment on column public.horse_hill_training.quality_status is
    'valid, zero_record, incomplete, or invalid_record. Invalid official values are retained verbatim and excluded from features.';
