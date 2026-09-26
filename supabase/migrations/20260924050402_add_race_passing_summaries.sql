create table public.race_passing_summaries (
    id bigint generated always as identity primary key,
    race_id integer not null
        references public.races(id) on delete cascade,
    source_document_id integer
        references public.source_documents(id) on delete set null,
    corner_1_raw text,
    corner_2_raw text,
    corner_3_raw text,
    corner_4_raw text,
    corner_5_raw text,
    corner_6_raw text,
    corner_7_raw text,
    corner_8_raw text,
    corner_9_raw text,
    pass_time_3f_raw varchar(20),
    pass_time_4f_raw varchar(20),
    pass_time_3f_ms integer,
    pass_time_4f_ms integer,
    tempo_raw varchar(10),
    tempo_level smallint,
    quality_status varchar(20) not null,
    source_row_hash varchar(64) not null,
    observed_at_ms bigint not null,
    constraint uq_race_passing_summaries_race unique (race_id),
    constraint ck_race_passing_summaries_valid_tempo_level
        check (tempo_level is null or tempo_level between 1 and 5),
    constraint ck_race_passing_summaries_valid_quality_status
        check (quality_status in ('valid', 'incomplete')),
    constraint ck_race_passing_summaries_positive_pass_time_3f
        check (pass_time_3f_ms is null or pass_time_3f_ms > 0),
    constraint ck_race_passing_summaries_positive_pass_time_4f
        check (pass_time_4f_ms is null or pass_time_4f_ms > 0)
);

create index ix_race_passing_summaries_source_document
    on public.race_passing_summaries (source_document_id);
create index ix_race_passing_summaries_tempo
    on public.race_passing_summaries (tempo_level);

alter table public.race_passing_summaries enable row level security;
revoke all on table public.race_passing_summaries from public, anon, authenticated;
revoke all on sequence public.race_passing_summaries_id_seq from public, anon, authenticated;

comment on table public.race_passing_summaries is
    'Official KRA API303 race-level passing-group strings, passage times, and track-tempo class.';
comment on column public.race_passing_summaries.corner_7_raw is
    'Official S-1F passing-group notation returned by API303.';
comment on column public.race_passing_summaries.corner_8_raw is
    'Official G-1F passing-group notation returned by API303.';
comment on column public.race_passing_summaries.tempo_level is
    'Numeric form of official track-tempo symbols 1 through 5; lower means faster.';
