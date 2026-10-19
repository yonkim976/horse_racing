-- Official website rider evidence. Original API rows remain unchanged.

CREATE TABLE horse_training_rider_observations (
	horse_training_id INTEGER NOT NULL,
	source_document_id INTEGER NOT NULL,
	source_row_no INTEGER NOT NULL,
	source_fingerprint VARCHAR(64) NOT NULL,
	rider_label_raw VARCHAR(100) NOT NULL,
	rider_role VARCHAR(30) NOT NULL,
	jockey_name VARCHAR(100),
	observed_at_ms BIGINT NOT NULL,
	CONSTRAINT pk_horse_training_rider_observations PRIMARY KEY (horse_training_id),
	CONSTRAINT ck_horse_training_rider_observations_training_rider_fingerprint CHECK (length(source_fingerprint) = 64),
	CONSTRAINT ck_horse_training_rider_observations_training_rider_source_row CHECK (source_row_no > 0),
	CONSTRAINT ck_horse_training_rider_observations_training_rider_role CHECK (rider_role IN ('기수', '조교사', '조교보', '조교승인', '교육생', '기수후보생', '주로조교', '기수트랙라이더', '미확인')),
	CONSTRAINT ck_horse_training_rider_observations_training_jockey_only_name CHECK (rider_role = '기수' OR jockey_name IS NULL),
	CONSTRAINT fk_horse_training_rider_observations_horse_training_id__db37 FOREIGN KEY(horse_training_id) REFERENCES horse_training (id) ON DELETE CASCADE,
	CONSTRAINT fk_horse_training_rider_observations_source_document_id_4bc2 FOREIGN KEY(source_document_id) REFERENCES source_documents (id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_training_rider_source_document ON horse_training_rider_observations (source_document_id);
ALTER TABLE public.horse_training_rider_observations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.horse_training_rider_observations FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.horse_training_rider_observations TO service_role;

create or replace view public.horse_training_serving
with (security_invoker = true)
as
select t.*,
       case when o.horse_training_id is not null then case when o.rider_role = '기수' then o.jockey_name end when t.rider_type = '기수' then nullif(nullif(btrim(j.name_ko), ''), '-') end::text as rider_name,
       case
           when o.horse_training_id is not null then case when o.rider_role = '기수' then coalesce(o.jockey_name, '기수') else o.rider_role end
           when t.rider_type = '기수' then coalesce(nullif(nullif(btrim(j.name_ko), ''), '-'), '기수')
           else coalesce(nullif(nullif(btrim(t.rider_type), ''), '-'), '미확인')
       end::text as rider_display_label,
       case
           when o.horse_training_id is not null then 'website_same_event'
           when t.rider_type = '기수' and nullif(nullif(btrim(j.name_ko), ''), '-') is not null then 'official_id_reference'
           when t.rider_type = '기수' then 'jockey_name_unresolved'
           when nullif(nullif(btrim(t.rider_type), ''), '-') is null then 'not_available'
           else 'role_only'
       end::text as rider_identity_status,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then null else t.canter_count end as canter_count_display,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then null else t.gallop_count end as gallop_count_display,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then 'not_available' else 'source_values' end as counts_availability_status
from public.horse_training t
left join public.jockeys j on t.rider_type = '기수' and j.kra_jockey_id = t.rider_id

left join public.horse_training_rider_observations o on o.horse_training_id = t.id
 and o.source_fingerprint = encode(sha256(convert_to(json_build_array(t.horse_id, t.meet_code, t.training_date_local::text, t.started_at_raw, t.ended_at_raw, t.duration_seconds, t.rider_type, t.rider_id)::text, 'UTF8')), 'hex');

COMMENT ON TABLE public.horse_training_rider_observations IS 'Same-event official KRA profile rider evidence; original API fields are preserved and changed source keys invalidate display evidence.';
