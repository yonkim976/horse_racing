-- Keep each observed report version and neutral paragraph/horse links.
-- These links are distinct from KRA's edited horse-specific website phrases.
create table public.steward_report_versions (
    id bigserial primary key,
    race_id integer not null references public.races(id) on delete restrict,
    source_document_id integer not null references public.source_documents(id) on delete restrict,
    latest_source_document_id integer not null references public.source_documents(id) on delete restrict,
    content_sha256 varchar(64) not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
    report_fields_json text not null check (jsonb_typeof(report_fields_json::jsonb)='object'),
    review_json text not null check (jsonb_typeof(review_json::jsonb)='array'),
    linkage_status varchar(20) not null check (linkage_status in ('linked','needs_review')),
    is_current boolean not null default false,
    first_observed_at_ms bigint not null check (first_observed_at_ms>0),
    last_observed_at_ms bigint not null check (last_observed_at_ms>=first_observed_at_ms),
    unique(race_id,content_sha256),
    check (not is_current or linkage_status='linked')
);
create unique index uq_steward_report_current_race on public.steward_report_versions(race_id) where is_current;
create index ix_steward_versions_source on public.steward_report_versions(source_document_id);
create index ix_steward_versions_latest_source on public.steward_report_versions(latest_source_document_id);

create table public.horse_steward_report_mentions (
    id bigserial primary key,
    report_version_id bigint not null references public.steward_report_versions(id) on delete restrict,
    horse_id integer not null references public.horses(id) on delete restrict,
    race_entry_id integer references public.race_entries(id) on delete restrict,
    horse_number integer not null check (horse_number>0),
    source_field varchar(50) not null,
    span_start_codepoint integer not null check (span_start_codepoint>=0),
    span_end_codepoint integer not null check (span_end_codepoint>span_start_codepoint),
    paragraph_text text not null check (length(btrim(paragraph_text))>0),
    mention_evidence_json text not null check (jsonb_typeof(mention_evidence_json::jsonb)='array'),
    unique(report_version_id,horse_id,source_field,span_start_codepoint,span_end_codepoint)
);
create index ix_horse_steward_mentions_horse on public.horse_steward_report_mentions(horse_id,report_version_id);
create index ix_horse_steward_mentions_entry on public.horse_steward_report_mentions(race_entry_id);
alter table public.steward_report_versions enable row level security;
alter table public.horse_steward_report_mentions enable row level security;
revoke all on public.steward_report_versions,public.horse_steward_report_mentions from public,anon,authenticated;
revoke all on sequence public.steward_report_versions_id_seq,public.horse_steward_report_mentions_id_seq from public,anon,authenticated;
grant select on public.steward_report_versions,public.horse_steward_report_mentions to service_role;

create view public.horse_steward_history with (security_invoker=true) as
select p.horse_id,p.race_id,p.race_entry_id,p.historical_program,p.phrase_text,
       p.text_basis,p.website_text_verified,p.first_observed_at_ms,p.last_observed_at_ms,
       p.source_published_at_ms,p.historical_publication_time_verified,
       null::bigint report_version_id,p.provenance_json
from public.horse_steward_phrases p
union all
select m.horse_id,v.race_id,m.race_entry_id,m.horse_number,m.paragraph_text,
       'official_report_paragraph'::varchar(30),false,v.first_observed_at_ms,v.last_observed_at_ms,
       null::bigint,false,v.id,m.mention_evidence_json
from public.horse_steward_report_mentions m
join public.steward_report_versions v on v.id=m.report_version_id
where v.is_current;
revoke all on public.horse_steward_history from public,anon,authenticated;
grant select on public.horse_steward_history to service_role;
comment on view public.horse_steward_history is
    'Backend-only horse history. official_website means literal KRA horse-cell wording; official_report_paragraph means a neutral number/roster reference in the latest linked race report, not a KRA-edited horse phrase or responsibility classification.';
