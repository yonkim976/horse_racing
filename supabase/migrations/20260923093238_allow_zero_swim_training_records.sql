alter table public.horse_swim_training
    add column quality_status varchar(20) not null default 'valid';

alter table public.horse_swim_training
    drop constraint ck_horse_swim_training_positive_swim_count,
    add constraint ck_horse_swim_training_nonnegative_swim_count
        check (swim_count >= 0),
    add constraint ck_horse_swim_training_valid_quality_status
        check (quality_status in ('valid', 'zero_record'));

alter table public.horse_swim_training
    alter column quality_status drop default;

comment on column public.horse_swim_training.quality_status is
    'valid or zero_record. Official zero-count rows are retained but excluded from training-load features.';
