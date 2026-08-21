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

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="horse")


class Jockey(Base):
    __tablename__ = "jockeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_jockey_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="jockey")


class Trainer(Base):
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kra_trainer_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(150))

    entries: Mapped[list[RaceEntry]] = relationship(back_populates="trainer")


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
    scheduled_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    weather: Mapped[str | None] = mapped_column(String(30))
    track_condition: Mapped[str | None] = mapped_column(String(30))
    track_moisture_percent: Mapped[float | None] = mapped_column(Float)
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
