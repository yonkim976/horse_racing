"""Web display policy; retain all original API medical observations."""

from sqlalchemy import func

from horse_racing.db.models import HorseMedical


def medical_display_filter():
    """Exclude explicitly named farriers, without treating missing diagnoses as farriery."""
    return func.coalesce(HorseMedical.hospital_name, "").not_like("%장제%")
