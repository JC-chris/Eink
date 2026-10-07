from datetime import UTC, datetime

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    # Naïeve UTC: SQLite bewaart geen tijdzones.
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    api_key: Mapped[str] = mapped_column(String(64), unique=True)


class BaseStation(Base):
    __tablename__ = "basestations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen: Mapped[datetime | None]
    software_version: Mapped[str | None] = mapped_column(String(32))
    uptime_s: Mapped[int | None]
    cpu_temp_c: Mapped[float | None]


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("store_id", "sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    price_cents: Mapped[int]
    unit: Mapped[str] = mapped_column(String(8), default="st")
    unit_price_cents: Mapped[int | None]
    unit_price_unit: Mapped[str] = mapped_column(String(8), default="kg")
    origin: Mapped[str | None] = mapped_column(String(100))
    promo_text: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Label(Base):
    __tablename__ = "labels"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # BLE-adres
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    display_type: Mapped[str] = mapped_column(String(32))
    product_sku: Mapped[str | None] = mapped_column(String(64))
    basestation_id: Mapped[str | None] = mapped_column(ForeignKey("basestations.id"))
    last_seen: Mapped[datetime | None]
    battery_mv: Mapped[int | None]
    rssi: Mapped[int | None]
    temperature_c: Mapped[float | None]
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    expected_crc: Mapped[int | None]
    displayed_crc: Mapped[int | None]


class JobStatus:
    PENDING = "pending"
    SENT = "sent"
    DONE = "done"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class UpdateJob(Base):
    __tablename__ = "update_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    label_id: Mapped[str] = mapped_column(ForeignKey("labels.id"))
    frame: Mapped[bytes] = mapped_column(LargeBinary)
    crc32: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    kind: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None]
