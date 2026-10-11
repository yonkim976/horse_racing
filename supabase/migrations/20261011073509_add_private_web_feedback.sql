-- Backend-only feedback storage. No Data API access or racing-data privileges.
create schema mapilog_feedback authorization postgres;
revoke all on schema mapilog_feedback from public, anon, authenticated;

create role mapilog_feedback_writer nologin nosuperuser nocreatedb nocreaterole
    noinherit noreplication nobypassrls;
grant usage on schema mapilog_feedback to mapilog_feedback_writer;

create table mapilog_feedback.entries (
    request_id uuid primary key,
    category varchar(20) not null check (category in ('오류 제보', '개선 제안', '기타 의견')),
    message text not null check (char_length(btrim(message)) between 10 and 1000),
    email varchar(254),
    page_path varchar(500),
    client_hash varchar(64) not null check (client_hash ~ '^[0-9a-f]{64}$'),
    payload_hash varchar(64) not null check (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now()
);
create index feedback_client_created_idx on mapilog_feedback.entries(client_hash, created_at);
create index feedback_created_idx on mapilog_feedback.entries(created_at);
alter table mapilog_feedback.entries enable row level security;
alter table mapilog_feedback.entries force row level security;
revoke all on mapilog_feedback.entries from public, anon, authenticated;
grant insert on mapilog_feedback.entries to mapilog_feedback_writer;
-- Only metadata can be read by the web login, for quotas and retry deduplication.
grant select (request_id, client_hash, payload_hash, created_at)
    on mapilog_feedback.entries to mapilog_feedback_writer;
create policy feedback_backend_insert on mapilog_feedback.entries
    for insert to mapilog_feedback_writer with check (true);
create policy feedback_backend_metadata on mapilog_feedback.entries
    for select to mapilog_feedback_writer using (true);
comment on table mapilog_feedback.entries is
    'Private feedback; optional reply email; hourly purge after seven days. Never expose via API.';

create extension if not exists pg_cron with schema pg_catalog;
select cron.schedule('mapilog-feedback-retention', '17 * * * *',
    $$delete from mapilog_feedback.entries where created_at < now() - interval '7 days'$$);
