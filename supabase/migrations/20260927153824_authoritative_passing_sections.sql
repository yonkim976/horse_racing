-- Canonical passage/section payload copied from the year-by-meet score sheets.
-- Legacy operational tables remain until all consumers and source coverage are verified.
create table public.race_point_source_batches (
    id bigint generated always as identity primary key,
    source_file text not null unique,
    source_sha256 text not null check (length(source_sha256) = 64),
    meet_code smallint not null check (meet_code between 1 and 4),
    race_year smallint not null check (race_year between 2000 and 2100),
    section_row_count integer not null check (section_row_count >= 0),
    passing_group_row_count integer not null check (passing_group_row_count >= 0),
    loaded_at_ms bigint not null,
    unique (meet_code, race_year)
);

create table public.race_section_times (
    race_entry_id integer not null references public.race_entries(id) on delete cascade,
    point_code text not null,
    time_kind text not null check (time_kind in ('cumulative', 'closing', 'segment')),
    elapsed_time_ms integer check (elapsed_time_ms is null or elapsed_time_ms > 0),
    position_raw integer,
    source_name text not null,
    source_field text,
    source_batch_id bigint not null references public.race_point_source_batches(id),
    primary key (race_entry_id, point_code, time_kind)
);
create index race_section_times_point_kind_idx
    on public.race_section_times (point_code, time_kind, race_entry_id);
create index race_section_times_batch_idx
    on public.race_section_times (source_batch_id);

create table public.race_passing_groups (
    race_id integer not null references public.races(id) on delete cascade,
    point_code text not null,
    notation_raw text not null,
    source_batch_id bigint not null references public.race_point_source_batches(id),
    primary key (race_id, point_code)
);
create index race_passing_groups_batch_idx
    on public.race_passing_groups (source_batch_id);

alter table public.race_point_source_batches enable row level security;
alter table public.race_section_times enable row level security;
alter table public.race_passing_groups enable row level security;
revoke all on public.race_point_source_batches, public.race_section_times,
    public.race_passing_groups from public, anon, authenticated;
revoke all on sequence public.race_point_source_batches_id_seq
    from public, anon, authenticated;
