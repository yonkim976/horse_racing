from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from horse_racing.db.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    data_type: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    documents: Mapped[list[SourceDocument]] = relationship(
        back_populates="ingestion_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partial')",
            name="valid_status",
        ),
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(200))
    operation: Mapped[str | None] = mapped_column(String(100))
    request_params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    requested_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retrieved_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(100))
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="documents")

    __table_args__ = (
        UniqueConstraint(
            "ingestion_run_id",
            "source_url",
            "sha256",
            name="ingestion_run_source_url_sha256",
        ),
        Index("ix_source_documents_retrieved_at_ms", "retrieved_at_ms"),
    )


class Racecourse(Base):
    __tablename__ = "racecourses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_meet_code: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(100))

    races: Mapped[list[Race]] = relationship(back_populates="racecourse")


class Horse(Base):
    __tablename__ = "horses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_horse_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))
    sex: Mapped[str | None] = mapped_column(String(20))
    birth_date: Mapped[date | None] = mapped_column(Date)
    origin_country: Mapped[str | None] = mapped_column(String(50))
    grade: Mapped[str | None] = mapped_column(String(30))
    meet_code: Mapped[int | None] = mapped_column(Integer)
    sire_kra_id: Mapped[str | None] = mapped_column(String(30))
    sire_name: Mapped[str | None] = mapped_column(String(100))
    dam_kra_id: Mapped[str | None] = mapped_column(String(30))
    dam_name: Mapped[str | None] = mapped_column(String(100))
    last_sale_amount_raw: Mapped[str | None] = mapped_column(String(100))
    profile_observed_at_ms: Mapped[int | None] = mapped_column(BigInteger)

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="horse")
    rating_snapshots: Mapped[list[HorseRatingSnapshot]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    weight_history: Mapped[list[HorseWeightHistory]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    training_records: Mapped[list[HorseTraining]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    medical_records: Mapped[list[HorseMedical]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    profile_snapshots: Mapped[list[HorseProfileSnapshot]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    grade_changes: Mapped[list[HorseGradeChange]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    start_training_records: Mapped[list[HorseStartTraining]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    jockey_changes: Mapped[list[JockeyChange]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    race_scratches: Mapped[list[RaceScratch]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    equipment_records: Mapped[list[EntryEquipment]] = relationship(
        back_populates="horse", cascade="all, delete-orphan"
    )
    running_trial_results: Mapped[list[RunningTrialResult]] = relationship(
        back_populates="horse"
    )


class Jockey(Base):
    __tablename__ = "jockeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_jockey_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="jockey")
    running_trial_results: Mapped[list[RunningTrialResult]] = relationship(
        back_populates="jockey"
    )


class Trainer(Base):
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_trainer_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="trainer")
    running_trial_results: Mapped[list[RunningTrialResult]] = relationship(
        back_populates="trainer"
    )


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_owner_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="owner")


class Race(Base):
    __tablename__ = "races"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    racecourse_id: Mapped[int] = mapped_column(
        ForeignKey("racecourses.id", ondelete="RESTRICT"), nullable=False
    )
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str | None] = mapped_column(String(50))
    race_name: Mapped[str | None] = mapped_column(String(200))
    race_day_count: Mapped[int | None] = mapped_column(Integer)
    field_size: Mapped[int | None] = mapped_column(Integer)
    burden_type: Mapped[str | None] = mapped_column(String(50))
    age_condition: Mapped[str | None] = mapped_column(String(100))
    sex_condition: Mapped[str | None] = mapped_column(String(100))
    rating_condition: Mapped[str | None] = mapped_column(String(100))
    newcomer_condition: Mapped[str | None] = mapped_column(String(100))
    scheduled_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    actual_start_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    start_time_change_reason: Mapped[str | None] = mapped_column(String(300))
    weather: Mapped[str | None] = mapped_column(String(30))
    track_condition: Mapped[str | None] = mapped_column(String(30))
    track_moisture_percent: Mapped[float | None] = mapped_column(Float)
    weather_planned: Mapped[str | None] = mapped_column(String(30))
    track_condition_planned: Mapped[str | None] = mapped_column(String(30))
    track_moisture_percent_planned: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")

    racecourse: Mapped[Racecourse] = relationship(back_populates="races")
    entries: Mapped[list[RaceEntry]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )
    odds_snapshots: Mapped[list[OddsSnapshot]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("racecourse_id", "race_date_local", "race_number", name="race_identity"),
        CheckConstraint("distance_m > 0", name="positive_distance"),
        CheckConstraint("race_number > 0", name="positive_race_number"),
        Index("ix_races_date_course", "race_date_local", "racecourse_id"),
    )


class RaceEntry(Base):
    __tablename__ = "race_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="RESTRICT"), nullable=False
    )
    jockey_id: Mapped[int | None] = mapped_column(ForeignKey("jockeys.id"))
    trainer_id: Mapped[int | None] = mapped_column(ForeignKey("trainers.id"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"))
    horse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_number: Mapped[int | None] = mapped_column(Integer)
    carried_weight_kg: Mapped[float | None] = mapped_column(Float)
    body_weight_kg: Mapped[int | None] = mapped_column(Integer)
    body_weight_change_kg: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    equipment: Mapped[str | None] = mapped_column(Text)
    running_style: Mapped[str | None] = mapped_column(String(30))
    scratched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    race: Mapped[Race] = relationship(back_populates="entries")
    horse: Mapped[Horse] = relationship(back_populates="entries")
    jockey: Mapped[Jockey | None] = relationship(back_populates="entries")
    trainer: Mapped[Trainer | None] = relationship(back_populates="entries")
    owner: Mapped[Owner | None] = relationship(back_populates="entries")
    result: Mapped[RaceResult | None] = relationship(
        back_populates="race_entry", cascade="all, delete-orphan", uselist=False
    )
    section_results: Mapped[list[RaceSectionResult]] = relationship(
        back_populates="race_entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("race_id", "horse_number", name="race_horse_number"),
        UniqueConstraint("race_id", "horse_id", name="race_horse"),
        CheckConstraint("horse_number > 0", name="positive_horse_number"),
        Index("ix_race_entries_horse_race", "horse_id", "race_id"),
    )


class RaceResult(Base):
    __tablename__ = "race_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("race_entries.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    finish_position: Mapped[int | None] = mapped_column(Integer)
    finish_time_ms: Mapped[int | None] = mapped_column(Integer)
    margin_text: Mapped[str | None] = mapped_column(String(50))
    prize_money_krw: Mapped[int | None] = mapped_column(BigInteger)
    bonus_prize_money_krw: Mapped[int | None] = mapped_column(BigInteger)
    rank_remark: Mapped[str | None] = mapped_column(String(200))
    disqualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    race_entry: Mapped[RaceEntry] = relationship(back_populates="result")

    __table_args__ = (
        CheckConstraint(
            "finish_position IS NULL OR finish_position > 0", name="positive_finish_position"
        ),
        CheckConstraint("finish_time_ms IS NULL OR finish_time_ms > 0", name="positive_time"),
    )


class RaceSectionResult(Base):
    __tablename__ = "race_section_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("race_entries.id", ondelete="CASCADE"), nullable=False
    )
    section_code: Mapped[str] = mapped_column(String(20), nullable=False)
    distance_from_start_m: Mapped[int | None] = mapped_column(Integer)
    elapsed_time_ms: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    gap_to_leader_lengths: Mapped[float | None] = mapped_column(Float)
    group_notation_raw: Mapped[str | None] = mapped_column(Text)

    race_entry: Mapped[RaceEntry] = relationship(back_populates="section_results")

    __table_args__ = (
        UniqueConstraint("race_entry_id", "section_code", name="entry_section"),
        CheckConstraint(
            "distance_from_start_m IS NULL OR distance_from_start_m >= 0",
            name="nonnegative_distance",
        ),
        CheckConstraint("position IS NULL OR position > 0", name="positive_position"),
        Index("ix_race_section_results_code", "section_code"),
    )


class HorseRatingSnapshot(Base):
    __tablename__ = "horse_rating_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int | None] = mapped_column(Integer)
    rating_1: Mapped[float | None] = mapped_column(Float)
    rating_2: Mapped[float | None] = mapped_column(Float)
    rating_3: Mapped[float | None] = mapped_column(Float)
    rating_4: Mapped[float | None] = mapped_column(Float)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="rating_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "horse_id", "observed_at_ms", name="uq_horse_rating_snapshots_horse_observed"
        ),
        Index("ix_horse_rating_snapshots_horse_observed", "horse_id", "observed_at_ms"),
    )


class HorseProfileSnapshot(Base):
    __tablename__ = "horse_profile_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str | None] = mapped_column(String(30))
    rating: Mapped[float | None] = mapped_column(Float)
    race_count_total: Mapped[int | None] = mapped_column(Integer)
    race_count_year: Mapped[int | None] = mapped_column(Integer)
    win_count_total: Mapped[int | None] = mapped_column(Integer)
    win_count_year: Mapped[int | None] = mapped_column(Integer)
    second_count_total: Mapped[int | None] = mapped_column(Integer)
    second_count_year: Mapped[int | None] = mapped_column(Integer)
    third_count_total: Mapped[int | None] = mapped_column(Integer)
    third_count_year: Mapped[int | None] = mapped_column(Integer)
    prize_money_total_krw: Mapped[int | None] = mapped_column(Integer)
    last_sale_amount_raw: Mapped[str | None] = mapped_column(String(100))
    trainer_kra_id: Mapped[str | None] = mapped_column(String(30))
    trainer_name: Mapped[str | None] = mapped_column(String(100))
    owner_kra_id: Mapped[str | None] = mapped_column(String(30))
    owner_name: Mapped[str | None] = mapped_column(String(100))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="profile_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "observed_at_ms",
            name="uq_horse_profile_snapshots_horse_observed",
        ),
        Index("ix_horse_profile_snapshots_horse_observed", "horse_id", "observed_at_ms"),
    )


class HorseWeightHistory(Base):
    __tablename__ = "horse_weight_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int | None] = mapped_column(Integer)
    horse_number: Mapped[int | None] = mapped_column(Integer)
    body_weight_kg: Mapped[int | None] = mapped_column(Integer)
    body_weight_change_kg: Mapped[int | None] = mapped_column(Integer)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="weight_history")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            name="uq_horse_weight_history_natural",
        ),
        Index("ix_horse_weight_history_horse_date", "horse_id", "race_date_local"),
    )


class HorseTraining(Base):
    __tablename__ = "horse_training"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    training_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    stable_part: Mapped[int | None] = mapped_column(Integer)
    stable_number: Mapped[int | None] = mapped_column(Integer)
    trainer_name: Mapped[str | None] = mapped_column(String(100))
    rider_type: Mapped[str | None] = mapped_column(String(30))
    rider_id: Mapped[str | None] = mapped_column(String(30))
    started_at_raw: Mapped[str | None] = mapped_column(String(20))
    ended_at_raw: Mapped[str | None] = mapped_column(String(20))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    canter_count: Mapped[int | None] = mapped_column(Integer)
    gallop_count: Mapped[int | None] = mapped_column(Integer)
    entry_plan: Mapped[str | None] = mapped_column(String(50))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="training_records")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "meet_code",
            "training_date_local",
            "started_at_raw",
            "ended_at_raw",
            name="uq_horse_training_natural",
        ),
        Index("ix_horse_training_horse_date", "horse_id", "training_date_local"),
    )


class HorseMedical(Base):
    __tablename__ = "horse_medical"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    clinic_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    stable_part: Mapped[int | None] = mapped_column(Integer)
    hospital_name: Mapped[str | None] = mapped_column(String(100))
    diagnosis_1: Mapped[str | None] = mapped_column(String(200))
    diagnosis_2: Mapped[str | None] = mapped_column(String(200))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="medical_records")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "meet_code",
            "clinic_date_local",
            "hospital_name",
            "diagnosis_1",
            "diagnosis_2",
            name="uq_horse_medical_natural",
        ),
        Index("ix_horse_medical_horse_date", "horse_id", "clinic_date_local"),
    )


class JockeyChange(Base):
    __tablename__ = "jockey_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int | None] = mapped_column(
        ForeignKey("horses.id", ondelete="SET NULL")
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    horse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    jockey_before_id: Mapped[str | None] = mapped_column(String(30))
    jockey_before_name: Mapped[str | None] = mapped_column(String(100))
    jockey_after_id: Mapped[str | None] = mapped_column(String(30))
    jockey_after_name: Mapped[str | None] = mapped_column(String(100))
    carried_weight_before_kg: Mapped[float | None] = mapped_column(Float)
    carried_weight_after_kg: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(200))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse | None] = relationship(back_populates="jockey_changes")

    __table_args__ = (
        UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            "jockey_before_id",
            "jockey_after_id",
            name="uq_jockey_changes_natural",
        ),
        Index("ix_jockey_changes_date_meet", "race_date_local", "meet_code"),
    )


class RaceScratch(Base):
    __tablename__ = "race_scratches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int | None] = mapped_column(
        ForeignKey("horses.id", ondelete="SET NULL")
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    horse_number: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(200))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse | None] = relationship(back_populates="race_scratches")

    __table_args__ = (
        UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_id",
            name="uq_race_scratches_natural",
        ),
        Index("ix_race_scratches_date_meet", "race_date_local", "meet_code"),
    )


class EntryEquipment(Base):
    __tablename__ = "entry_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int | None] = mapped_column(
        ForeignKey("horses.id", ondelete="SET NULL")
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    horse_number: Mapped[int | None] = mapped_column(Integer)
    equipment_raw: Mapped[str | None] = mapped_column(String(200))
    bleeding_count: Mapped[int | None] = mapped_column(Integer)
    bleeding_date_raw: Mapped[str | None] = mapped_column(String(40))
    illness_note: Mapped[str | None] = mapped_column(String(200))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse | None] = relationship(back_populates="equipment_records")

    __table_args__ = (
        UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            name="uq_entry_equipment_natural",
        ),
        Index("ix_entry_equipment_horse_date", "horse_id", "race_date_local"),
    )


class HorseGradeChange(Base):
    __tablename__ = "horse_grade_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int | None] = mapped_column(Integer)
    blood_type: Mapped[str | None] = mapped_column(String(50))
    grade_before: Mapped[str | None] = mapped_column(String(30))
    grade_after: Mapped[str | None] = mapped_column(String(30))
    start_date_local: Mapped[date | None] = mapped_column(Date)
    end_date_local: Mapped[date | None] = mapped_column(Date)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="grade_changes")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "start_date_local",
            "grade_before",
            "grade_after",
            name="uq_horse_grade_changes_natural",
        ),
        Index("ix_horse_grade_changes_horse_start", "horse_id", "start_date_local"),
    )


class HorseStartTraining(Base):
    __tablename__ = "horse_start_training"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horse_id: Mapped[int] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"), nullable=False
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    training_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    stable_part: Mapped[int | None] = mapped_column(Integer)
    stable_number: Mapped[int | None] = mapped_column(Integer)
    rider_name: Mapped[str | None] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(200))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    horse: Mapped[Horse] = relationship(back_populates="start_training_records")

    __table_args__ = (
        UniqueConstraint(
            "horse_id",
            "meet_code",
            "training_date_local",
            "stable_part",
            "stable_number",
            "rider_name",
            name="uq_horse_start_training_natural",
        ),
        Index("ix_horse_start_training_horse_date", "horse_id", "training_date_local"),
    )


class RaceStewardReport(Base):
    __tablename__ = "race_steward_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weather: Mapped[str | None] = mapped_column(String(100))
    members: Mapped[str | None] = mapped_column(Text)
    judgement: Mapped[str | None] = mapped_column(Text)
    additional_judgement: Mapped[str | None] = mapped_column(Text)
    jockey_change_note: Mapped[str | None] = mapped_column(Text)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            name="uq_race_steward_reports_natural",
        ),
        Index("ix_race_steward_reports_date_meet", "race_date_local", "meet_code"),
    )


class RunningTrial(Base):
    __tablename__ = "running_trials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )
    meet_code: Mapped[int] = mapped_column(Integer, nullable=False)
    trial_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    trial_round: Mapped[int | None] = mapped_column(Integer)
    trial_race_number: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    weather: Mapped[str | None] = mapped_column(String(30))
    track_condition: Mapped[str | None] = mapped_column(String(30))
    track_moisture_percent: Mapped[float | None] = mapped_column(Float)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    results: Mapped[list[RunningTrialResult]] = relationship(
        back_populates="trial", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "meet_code",
            "trial_date_local",
            "trial_race_number",
            name="uq_running_trials_natural",
        ),
        CheckConstraint("trial_race_number > 0", name="ck_running_trials_positive_race"),
        CheckConstraint("distance_m > 0", name="ck_running_trials_positive_distance"),
        Index("ix_running_trials_date_meet", "trial_date_local", "meet_code"),
    )


class RunningTrialResult(Base):
    __tablename__ = "running_trial_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    running_trial_id: Mapped[int] = mapped_column(
        ForeignKey("running_trials.id", ondelete="CASCADE"), nullable=False
    )
    horse_id: Mapped[int | None] = mapped_column(
        ForeignKey("horses.id", ondelete="SET NULL")
    )
    jockey_id: Mapped[int | None] = mapped_column(
        ForeignKey("jockeys.id", ondelete="SET NULL")
    )
    trainer_id: Mapped[int | None] = mapped_column(
        ForeignKey("trainers.id", ondelete="SET NULL")
    )
    horse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    horse_name_raw: Mapped[str] = mapped_column(String(100), nullable=False)
    finish_position: Mapped[int | None] = mapped_column(Integer)
    finish_rank_raw: Mapped[str | None] = mapped_column(String(10))
    origin_country: Mapped[str | None] = mapped_column(String(30))
    sex: Mapped[str | None] = mapped_column(String(20))
    age: Mapped[int | None] = mapped_column(Integer)
    carried_weight_base_kg: Mapped[float | None] = mapped_column(Float)
    carried_weight_extra_kg: Mapped[float | None] = mapped_column(Float)
    carried_weight_raw: Mapped[str | None] = mapped_column(String(30))
    jockey_name_raw: Mapped[str | None] = mapped_column(String(100))
    trainer_name_raw: Mapped[str | None] = mapped_column(String(100))
    body_weight_kg: Mapped[int | None] = mapped_column(Integer)
    finish_time_ms: Mapped[int | None] = mapped_column(Integer)
    margin_text: Mapped[str | None] = mapped_column(String(50))
    judgement: Mapped[str | None] = mapped_column(String(20))
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    inspection_reason: Mapped[str | None] = mapped_column(String(150))
    g3f_ms: Mapped[int | None] = mapped_column(Integer)
    s1f_ms: Mapped[int | None] = mapped_column(Integer)
    corner_3_ms: Mapped[int | None] = mapped_column(Integer)
    corner_4_ms: Mapped[int | None] = mapped_column(Integer)
    g1f_ms: Mapped[int | None] = mapped_column(Integer)
    section_400_ms: Mapped[int | None] = mapped_column(Integer)
    final_400_ms: Mapped[int | None] = mapped_column(Integer)
    passing_order_raw: Mapped[str | None] = mapped_column(String(100))
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    trial: Mapped[RunningTrial] = relationship(back_populates="results")
    horse: Mapped[Horse | None] = relationship(back_populates="running_trial_results")
    jockey: Mapped[Jockey | None] = relationship(back_populates="running_trial_results")
    trainer: Mapped[Trainer | None] = relationship(back_populates="running_trial_results")

    __table_args__ = (
        UniqueConstraint(
            "running_trial_id",
            "horse_number",
            name="uq_running_trial_results_natural",
        ),
        CheckConstraint(
            "horse_number > 0", name="ck_running_trial_results_positive_horse_number"
        ),
        CheckConstraint(
            "finish_position IS NULL OR finish_position > 0",
            name="ck_running_trial_results_positive_finish_position",
        ),
        Index(
            "ix_running_trial_results_horse_trial",
            "horse_id",
            "running_trial_id",
        ),
    )


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    bet_type: Mapped[str] = mapped_column(String(30), nullable=False)
    selection_key: Mapped[str] = mapped_column(String(50), nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    race: Mapped[Race] = relationship(back_populates="odds_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "race_id",
            "bet_type",
            "selection_key",
            "observed_at_ms",
            name="odds_observation",
        ),
        CheckConstraint("odds > 0", name="positive_odds"),
        Index("ix_odds_snapshots_race_time", "race_id", "observed_at_ms"),
    )


class PredictionRun(Base):
    """One immutable publication of pre-race probabilities."""

    __tablename__ = "prediction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    experiment_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    as_of_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    race_date_local: Mapped[date] = mapped_column(Date, nullable=False)
    feature_cutoff_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    publication_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    model_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    predictions_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    notes: Mapped[str | None] = mapped_column(Text)

    predictions: Mapped[list[ModelPrediction]] = relationship(
        back_populates="prediction_run", cascade="all, delete-orphan"
    )
    settlement: Mapped[PredictionSettlement | None] = relationship(
        back_populates="prediction_run", uselist=False
    )

    __table_args__ = (
        CheckConstraint(
            "publication_mode IN ('live', 'historical')",
            name="ck_prediction_runs_publication_mode",
        ),
        CheckConstraint(
            "feature_cutoff_at_ms <= published_at_ms",
            name="ck_prediction_runs_cutoff_before_publication",
        ),
        Index("ix_prediction_runs_date_mode", "race_date_local", "publication_mode"),
    )


class ModelPrediction(Base):
    """Immutable runner-level probabilities belonging to a publication."""

    __tablename__ = "model_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_run_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_runs.id", ondelete="RESTRICT"), nullable=False
    )
    race_id: Mapped[int] = mapped_column(
        ForeignKey("races.id", ondelete="RESTRICT"), nullable=False
    )
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("race_entries.id", ondelete="RESTRICT"), nullable=False
    )
    horse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prob_win: Mapped[float] = mapped_column(Float, nullable=False)
    prob_top2: Mapped[float] = mapped_column(Float, nullable=False)
    prob_top3: Mapped[float] = mapped_column(Float, nullable=False)

    prediction_run: Mapped[PredictionRun] = relationship(back_populates="predictions")
    outcome: Mapped[PredictionOutcome | None] = relationship(
        back_populates="model_prediction", uselist=False
    )

    __table_args__ = (
        UniqueConstraint(
            "prediction_run_id",
            "race_entry_id",
            name="uq_model_predictions_run_entry",
        ),
        CheckConstraint("horse_number > 0", name="ck_model_predictions_positive_horse"),
        CheckConstraint(
            "prob_win >= 0 AND prob_win <= 1",
            name="ck_model_predictions_win_probability",
        ),
        CheckConstraint(
            "prob_top2 >= 0 AND prob_top2 <= 1",
            name="ck_model_predictions_top2_probability",
        ),
        CheckConstraint(
            "prob_top3 >= 0 AND prob_top3 <= 1",
            name="ck_model_predictions_top3_probability",
        ),
        Index("ix_model_predictions_race", "race_id", "prediction_run_id"),
    )


class PredictionSettlement(Base):
    """Immutable outcome snapshot and aggregate metrics for one publication."""

    __tablename__ = "prediction_settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    prediction_run_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_runs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    settled_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcomes_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    n_races: Mapped[int] = mapped_column(Integer, nullable=False)
    n_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    n_excluded_races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_log_loss: Mapped[float] = mapped_column(Float, nullable=False)
    win_brier: Mapped[float] = mapped_column(Float, nullable=False)
    win_ece: Mapped[float] = mapped_column(Float, nullable=False)
    win_top1_hit_rate: Mapped[float] = mapped_column(Float, nullable=False)
    win_top3_inclusion_rate: Mapped[float] = mapped_column(Float, nullable=False)
    top2_log_loss: Mapped[float] = mapped_column(Float, nullable=False)
    top3_log_loss: Mapped[float] = mapped_column(Float, nullable=False)

    prediction_run: Mapped[PredictionRun] = relationship(back_populates="settlement")
    outcomes: Mapped[list[PredictionOutcome]] = relationship(
        back_populates="settlement", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("n_races > 0", name="ck_prediction_settlements_positive_races"),
        CheckConstraint("n_entries > 0", name="ck_prediction_settlements_positive_entries"),
        CheckConstraint(
            "n_excluded_races >= 0 AND n_excluded_races < n_races",
            name="ck_prediction_settlements_excluded_races",
        ),
        Index("ix_prediction_settlements_settled", "settled_at_ms"),
    )


class PredictionOutcome(Base):
    """Runner-level labels frozen at settlement time."""

    __tablename__ = "prediction_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settlement_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_settlements.id", ondelete="RESTRICT"), nullable=False
    )
    model_prediction_id: Mapped[int] = mapped_column(
        ForeignKey("model_predictions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    finish_position: Mapped[int | None] = mapped_column(Integer)
    is_scored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(100))
    win: Mapped[bool | None] = mapped_column(Boolean)
    top2: Mapped[bool | None] = mapped_column(Boolean)
    top3: Mapped[bool | None] = mapped_column(Boolean)
    win_log_loss: Mapped[float | None] = mapped_column(Float)

    settlement: Mapped[PredictionSettlement] = relationship(back_populates="outcomes")
    model_prediction: Mapped[ModelPrediction] = relationship(back_populates="outcome")

    __table_args__ = (
        CheckConstraint(
            "finish_position IS NULL OR finish_position > 0",
            name="ck_prediction_outcomes_positive_finish",
        ),
        CheckConstraint(
            "(is_scored = 1 AND exclusion_reason IS NULL AND win IS NOT NULL "
            "AND top2 IS NOT NULL AND top3 IS NOT NULL AND win_log_loss IS NOT NULL) "
            "OR (is_scored = 0 AND exclusion_reason IS NOT NULL AND win IS NULL "
            "AND top2 IS NULL AND top3 IS NULL AND win_log_loss IS NULL)",
            name="ck_prediction_outcomes_scoring_state",
        ),
        Index("ix_prediction_outcomes_settlement", "settlement_id"),
    )
