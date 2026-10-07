from datetime import UTC, date, datetime

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    # Naïeve UTC: SQLite bewaart geen tijdzones.
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SubscriptionStatus:
    TRIAL = "trial"
    ACTIVE = "active"
    CANCELLED = "cancelled"  # opgezegd: loopt door tot end_date
    SUSPENDED = "suspended"  # uitgeschakeld


class ServiceState:
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Customer(Base):
    """Klant met (maandelijks) abonnement. Eén klant kan meerdere winkels hebben."""

    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(2000))
    plan: Mapped[str] = mapped_column(String(64), default="Standaard")
    monthly_price_cents: Mapped[int] = mapped_column(default=0)
    subscription_status: Mapped[str] = mapped_column(String(16), default=SubscriptionStatus.ACTIVE)
    start_date: Mapped[date] = mapped_column(default=lambda: utcnow().date())
    end_date: Mapped[date | None]  # laatste dag van de dienst bij opzegging
    cancelled_at: Mapped[datetime | None]
    suspend_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Operator(Base):
    """Medewerker van ons die het managementsysteem gebruikt."""

    __tablename__ = "operators"
    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="support")  # "admin" of "support"
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEntry(Base):
    """Wie deed wat: belangrijk bij geschillen over opzegging en uitschakelen."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    store_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(String(1000))


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    api_key: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    # Afgeleid van het abonnement; bijgehouden zodat de overgang (labels neutraal) één keer gebeurt.
    service_state: Mapped[str] = mapped_column(String(16), default=ServiceState.ACTIVE)
    # Wie de prijzen beheert: "pos" (kassa via API) of "manual" (webinterface basisstation).
    price_source: Mapped[str] = mapped_column(String(16), default="pos")


class BaseStation(Base):
    __tablename__ = "basestations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id"))  # None = op voorraad
    token: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen: Mapped[datetime | None]
    software_version: Mapped[str | None] = mapped_column(String(32))
    uptime_s: Mapped[int | None]
    cpu_temp_c: Mapped[float | None]
    license_valid_until: Mapped[datetime | None]


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
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id"), index=True)  # None = op voorraad
    display_type: Mapped[str] = mapped_column(String(32))
    product_sku: Mapped[str | None] = mapped_column(String(64))
    # Via welk basisstation het label het laatst gehoord is (automatisch)...
    basestation_id: Mapped[str | None] = mapped_column(ForeignKey("basestations.id"))
    # ...of vast gekoppeld: dan gaan updates alleen via dit basisstation.
    pinned_basestation_id: Mapped[str | None] = mapped_column(ForeignKey("basestations.id"))
    added_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime | None]
    battery_mv: Mapped[int | None]
    rssi: Mapped[int | None]
    temperature_c: Mapped[float | None]
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    expected_crc: Mapped[int | None]
    displayed_crc: Mapped[int | None]


class PriceSource:
    POS = "pos"
    MANUAL = "manual"


class LabelSighting(Base):
    """Label gehoord door een basisstation, maar (nog) niet aan diens winkel gekoppeld."""

    __tablename__ = "label_sightings"
    label_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    basestation_id: Mapped[str] = mapped_column(ForeignKey("basestations.id"), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    rssi: Mapped[int | None]
    battery_mv: Mapped[int | None]
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)


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
    kind: Mapped[str] = mapped_column(String(16), default="price")  # "price" of "service" (buiten dienst)
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
