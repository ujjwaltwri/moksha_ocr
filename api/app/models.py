import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RegStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    approved = "approved"
    review = "review"
    rejected = "rejected"


reg_status = ENUM(RegStatus, name="reg_status", create_type=False)

# Statuses covered by the one_active_roll unique index.
LIVE_STATUSES = (RegStatus.pending, RegStatus.processing, RegStatus.approved)


class College(Base):
    __tablename__ = "colleges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    email_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    roll_regex: Mapped[str | None] = mapped_column(Text)
    template: Mapped[dict | None] = mapped_column(JSONB)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text)
    college_id: Mapped[int | None] = mapped_column(ForeignKey("colleges.id"))
    college_other: Mapped[str | None] = mapped_column(Text)
    roll_no: Mapped[str] = mapped_column(Text)
    course: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)  # citext in the database
    college_email: Mapped[bool] = mapped_column(Boolean, default=False)
    phone: Mapped[str | None] = mapped_column(Text)
    id_image_key: Mapped[str] = mapped_column(Text)
    photo_crop_key: Mapped[str | None] = mapped_column(Text)
    image_phash: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[RegStatus] = mapped_column(reg_status, default=RegStatus.pending)
    ocr: Mapped[dict | None] = mapped_column(JSONB)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    consent_entry: Mapped[bool] = mapped_column(Boolean)
    consent_dataset: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_version: Mapped[str] = mapped_column(Text)
    status_token: Mapped[str] = mapped_column(Text, unique=True)
    client_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
