from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .displays import DISPLAY_TYPES

Unit = Literal["st", "kg", "100g", "l", "pak"]


class StoreCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{2,64}$", examples=["slagerij-jansen"])
    name: str


class StoreCreated(BaseModel):
    id: str
    name: str
    api_key: str


class BaseStationCreate(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9-]{2,64}$", examples=["bs-jansen-1"])


class BaseStationCreated(BaseModel):
    id: str
    store_id: str
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
