-- Presentation only: preserve API role/employee number and all training rows.
-- New observations automatically inherit this rule; no multi-million-row rewrite.
create view public.horse_training_serving
with (security_invoker = true)
as
select t.*,
       case when t.rider_type = '기수' then nullif(nullif(btrim(j.name_ko), ''), '-') end as rider_name,
       case
           when t.rider_type = '기수' then coalesce(nullif(nullif(btrim(j.name_ko), ''), '-'), '기수')
           else coalesce(nullif(nullif(btrim(t.rider_type), ''), '-'), '미확인')
       end as rider_display_label,
       case
           when t.rider_type = '기수' and nullif(nullif(btrim(j.name_ko), ''), '-') is not null then 'official_id_reference'
           when t.rider_type = '기수' then 'jockey_name_unresolved'
           when nullif(nullif(btrim(t.rider_type), ''), '-') is null then 'not_available'
           else 'role_only'
       end as rider_identity_status,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then null else t.canter_count end as canter_count_display,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then null else t.gallop_count end as gallop_count_display,
       case when t.meet_code = 2 and t.canter_count = 0 and t.gallop_count = 0 then 'not_available' else 'source_values' end as counts_availability_status
from public.horse_training t
left join public.jockeys j on t.rider_type = '기수' and j.kra_jockey_id = t.rider_id;

revoke all on public.horse_training_serving from public, anon, authenticated;
grant select on public.horse_training_serving to service_role;

comment on view public.horse_training_serving is
    'Daily training: names only for API-declared jockeys by exact official number; otherwise source role or unavailable. Number reference is not independent event verification. Raw columns remain unchanged. Jeju all-zero canter/gallop are not usable counts.';
