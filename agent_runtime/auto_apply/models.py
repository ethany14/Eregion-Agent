"""Durable application state; no browser cookies or remote credentials are stored."""
from sqlalchemy import Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from api.db import Base


class AutoApplicationRow(Base):
    __tablename__ = "auto_applications"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    posting_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    resume_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class ApplicationMemoryRow(Base):
    __tablename__ = "application_answer_memory"
    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class SavedCandidateRow(Base):
    __tablename__ = "saved_application_candidate"
    slot: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    resume_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    resume_name: Mapped[str] = mapped_column(String(250), nullable=False)
    extracted: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)
