-- Preserve every source-version row. This private, invoker-security read model
-- collapses metadata-only changes, never different same-second measurements.
create view public.horse_hill_training_current
with (security_invoker = true)
as
select id, source_document_id, horse_id, kra_horse_id_raw, horse_name_raw,
       farm_name, tag_id, chip_id, sex_raw, birth_date, sire_name_raw, dam_name_raw,
       training_operator_name, owner_name_raw, farm_entry_date, farm_entry_reason,
       training_date_local, training_time_local, f1_seconds, f2_seconds, f3_seconds,
       total_seconds, quality_status, source_row_hash, observed_at_ms,
       metadata_version_count
from (
    select h.*,
           row_number() over (
               partition by kra_horse_id_raw, farm_name, training_date_local,
                            training_time_local, tag_id, chip_id,
                            f1_seconds, f2_seconds, f3_seconds, total_seconds,
                            case when training_time_local is null then source_row_hash end
               order by observed_at_ms desc, id desc
           ) as metadata_version_rank,
           count(*) over (
               partition by kra_horse_id_raw, farm_name, training_date_local,
                            training_time_local, tag_id, chip_id,
                            f1_seconds, f2_seconds, f3_seconds, total_seconds,
                            case when training_time_local is null then source_row_hash end
           ) as metadata_version_count
    from public.horse_hill_training h
) ranked
where metadata_version_rank = 1;

revoke all on public.horse_hill_training_current from public, anon, authenticated;
grant select on public.horse_hill_training_current to service_role;

comment on view public.horse_hill_training_current is
    'Metadata-deduplicated hill measurements. Base rows are immutable history for this view. Different split times/sensor IDs and unknown times remain separate; not a declaration that every measurement is a distinct physical training session.';
