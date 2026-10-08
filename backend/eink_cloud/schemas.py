from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .displays import DISPLAY_TYPES

Unit = Literal["st", "kg", "100g", "l", "pak"]


class StoreCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{2,64}$", examples=["slagerij-jansen"])
    name: str
    price_source: Literal["pos", "manual"] = "pos"
    customer_id: str | None = Field(None, description="klant/contract waaronder deze winkel valt")


PriceSourceT = Literal["pos", "manual"]


class StoreCreated(BaseModel):
    id: str
    name: str
    api_key: str
    price_source: PriceSourceT


class StoreSettings(BaseModel):
    price_source: PriceSourceT = Field(description="pos = kassa via API, manual = webinterface basisstation")


class StoreInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    price_source: PriceSourceT


class BaseStationCreate(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9-]{2,64}$", examples=["bs-jansen-1"])


class BaseStationCreated(BaseModel):
    id: str
    store_id: str | None
    token: str


class ProductIn(BaseModel):
    name: str = Field(max_length=200, examples=["Runderbiefstuk"])
    price_cents: int = Field(ge=0, examples=[1295])
    unit: Unit = "st"
    unit_price_cents: int | None = Field(None, ge=0, description="Eenheidsprijs (verplicht bij voorverpakt per gewicht)")
    unit_price_unit: Literal["kg", "l"] = "kg"
    origin: str | None = Field(None, max_length=100)
    promo_text: str | None = Field(None, max_length=100)


class ProductBatchItem(ProductIn):
    sku: str = Field(max_length=64)


class ProductOut(ProductIn):
    model_config = ConfigDict(from_attributes=True)
    sku: str
    updated_at: datetime


class ProductUpdateResult(BaseModel):
    sku: str
    labels_scheduled: int


class LabelCreate(BaseModel):
    label_id: str = Field(max_length=32, examples=["C0:FF:EE:00:00:01"])
    display_type: str = Field(examples=["bwry_2_9"])

    @field_validator("display_type")
    @classmethod
    def known_display(cls, v: str) -> str:
        if v not in DISPLAY_TYPES:
            raise ValueError(f"onbekend displaytype, kies uit {sorted(DISPLAY_TYPES)}")
        return v


class LabelLink(BaseModel):
    sku: str | None = Field(description="null = ontkoppelen")


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_type: str
    product_sku: str | None
    basestation_id: str | None
    pinned_basestation_id: str | None
    last_seen: datetime | None
    battery_mv: int | None
    rssi: int | None
    temperature_c: float | None
    firmware_version: str | None
    expected_crc: int | None
    displayed_crc: int | None
    in_sync: bool


class LabelTelemetry(BaseModel):
    label_id: str
    rssi: int | None = None
    battery_mv: int | None = None
    temperature_c: float | None = None
    firmware_version: str | None = None
    displayed_crc: int | None = None


class Heartbeat(BaseModel):
    software_version: str
    uptime_s: int
    cpu_temp_c: float | None = None
    labels_seen: list[LabelTelemetry] = []


class JobOut(BaseModel):
    job_id: int
    label_id: str
    frame_b64: str
    crc32: int


class JobResult(BaseModel):
    success: bool
    displayed_crc: int | None = None
    error: str | None = None
    telemetry: LabelTelemetry | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    store_id: str
    kind: str
    subject_id: str
    severity: str
    message: str
    created_at: datetime
    resolved_at: datetime | None


# --- Managementsysteem -------------------------------------------------------------------------


class CustomerBase(BaseModel):
    name: str = Field(max_length=200, examples=["Slagerij Jansen B.V."])
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=2000)
    plan: str = Field("Standaard", max_length=64)
    monthly_price_cents: int = Field(0, ge=0, examples=[4900])


class CustomerCreate(CustomerBase):
    id: str = Field(pattern=r"^[a-z0-9-]{2,64}$", examples=["jansen"])
    subscription_status: Literal["trial", "active"] = "active"
    start_date: date | None = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    subscription_status: str
    start_date: date
    end_date: date | None
    cancelled_at: datetime | None
    suspend_reason: str | None
    service_active: bool
    store_ids: list[str]


class CancelBody(BaseModel):
    end_date: date = Field(description="laatste dag waarop de dienst werkt")


class SuspendBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500, examples=["Contract opgezegd, einde looptijd"])


class BaseStationStatus(BaseModel):
    id: str
    store_id: str | None
    customer_id: str | None
    online: bool
    last_seen: datetime | None
    license_valid_until: datetime | None
    software_version: str | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    at: datetime
    actor: str
    action: str
    customer_id: str | None
    store_id: str | None
    details: str | None


class StockLabelsIn(BaseModel):
    label_ids: list[str] = Field(min_length=1, max_length=5000)
    display_type: str

    @field_validator("display_type")
    @classmethod
    def known_display(cls, v: str) -> str:
        if v not in DISPLAY_TYPES:
            raise ValueError(f"onbekend displaytype, kies uit {sorted(DISPLAY_TYPES)}")
        return v


class StockLabelsResult(BaseModel):
    added: int
    already_known: list[str]


class AssignLabelsIn(BaseModel):
    label_ids: list[str] = Field(min_length=1, max_length=5000)
    store_id: str
    basestation_id: str | None = Field(None, description="vast basisstation; leeg = automatisch")
    move: bool = Field(False, description="ook labels die nu bij een andere winkel horen verplaatsen")


class LabelIdsIn(BaseModel):
    label_ids: list[str] = Field(min_length=1, max_length=5000)


class PinIn(BaseModel):
    basestation_id: str | None = Field(description="null = automatisch (best hoorbare basisstation)")


class StockLabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_type: str
    store_id: str | None
    pinned_basestation_id: str | None
    basestation_id: str | None
    last_seen: datetime | None
    battery_mv: int | None
    added_at: datetime


class ShipmentIn(BaseModel):
    store_id: str
    codes: list[str] = Field(min_length=1, max_length=5000, description="gescande barcodes (basisstation en displays)")
    pin: bool = Field(True, description="displays vast aan het gescande basisstation koppelen")
    reference: str | None = Field(None, max_length=100, description="ordernummer")
    new_display_type: str = Field("bwry_2_9", description="type voor displays die nog niet op voorraad stonden")


class ShipmentOut(BaseModel):
    id: int
    customer_id: str | None
    store_id: str
    basestation_id: str | None
    reference: str | None
    pinned: bool
    created_by: str
    created_at: datetime
    label_ids: list[str]


class BaseStationAssignIn(BaseModel):
    store_id: str | None = Field(description="null = terug naar voorraad")


class PriceImportIn(BaseModel):
    filename: str = Field(max_length=200, examples=["prijzen.csv"])
    content_b64: str = Field(description="inhoud van het CSV- of Excel-bestand, base64")
    mapping: dict[str, str] | None = Field(None, description="productveld → kolomnaam; leeg = bewaarde of herkende indeling")
    dry_run: bool = Field(True, description="true = alleen controleren en voorbeeld tonen")
    default_unit: Literal["st", "kg", "100g", "l", "pak"] = "st"


class PriceImportOut(BaseModel):
    dry_run: bool
    columns: list[str]
    mapping: dict[str, str]
    fields: dict[str, str]
    rows_total: int
    valid: int
    skipped: int
    errors: list[dict]
    preview: list[ProductBatchItem]
    imported: int = 0
    labels_scheduled: int = 0
