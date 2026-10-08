"""API voor basisstations: heartbeat, jobs, resultaten — en de lokale webinterface.

De webinterface op het basisstation gebruikt de /v1/basestation/store/...-endpoints met het
token van het basisstation. Zo hoeft de winkel geen kassakoppeling te hebben.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import catalog
from ..licensing import issue_lease, public_key_b64
from ..subscriptions import lease_message, require_service
from ..auth import require_basestation
from ..inventory import record_sighting, require_assigned
from ..db import get_session
from ..displays import DISPLAY_TYPES
from ..jobs import claim_jobs, record_result
from ..models import BaseStation, Customer, Label, PriceSource, Store, UpdateJob, utcnow
from ..schemas import (
    Heartbeat, JobOut, JobResult, LabelCreate, LabelLink, LabelOut, LabelTelemetry, PriceImportIn, PriceImportOut,
    ProductIn, ProductOut, ProductUpdateResult, StoreInfo, StoreSettings,
)

router = APIRouter(prefix="/v1/basestation", tags=["basisstation"])


def apply_telemetry(session: Session, bs: BaseStation, t: LabelTelemetry) -> None:
    label = session.get(Label, t.label_id)
    if label is None or label.store_id != bs.store_id:
        # Niet van deze winkel: alleen onthouden dat het hier gehoord is (koppelen kan dan
        # vanuit het managementsysteem of de webinterface). Telemetrie niet overnemen.
        record_sighting(session, bs, t.label_id, t.rssi, t.battery_mv)
        return
    label.last_seen = utcnow()
    label.basestation_id = bs.id
    for field in ("rssi", "battery_mv", "temperature_c", "firmware_version", "displayed_crc"):
        value = getattr(t, field)
        if value is not None:
            setattr(label, field, value)


@router.get("/license-key")
def license_key(request: Request):
    """Publieke sleutel voor licentiecontrole. In productie staat deze al in de fabrieksconfig."""
    return {"algorithm": "Ed25519", "public_key": public_key_b64(request.app.state.license_key)}


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, request: Request, bs: BaseStation = Depends(require_basestation),
              session: Session = Depends(get_session)):
    """Check-in. Het antwoord bevat een ondertekende licentie die 7 dagen geldig is."""
    require_assigned(bs)
    now = utcnow()
    bs.last_seen = now
    bs.software_version = body.software_version
    bs.uptime_s = body.uptime_s
    bs.cpu_temp_c = body.cpu_temp_c
    for t in body.labels_seen:
        apply_telemetry(session, bs, t)
    store = session.get(Store, bs.store_id)
    customer = session.get(Customer, store.customer_id) if store.customer_id else None
    lease = issue_lease(request.app.state.license_key, bs, store, now, lease_message(customer, store))
    session.commit()
    return {"ok": True, "license": lease}


@router.get("/jobs", response_model=list[JobOut])
def get_jobs(limit: int = 20, bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    require_assigned(bs)
    jobs = claim_jobs(session, bs, min(max(limit, 1), 100))
    session.commit()
    return [JobOut(job_id=j.id, label_id=j.label_id, frame_b64=base64.b64encode(j.frame).decode(), crc32=j.crc32) for j in jobs]


@router.post("/jobs/{job_id}/result")
def post_result(job_id: int, body: JobResult, bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    job = session.get(UpdateJob, job_id)
    if job is None or job.store_id != bs.store_id:
        raise HTTPException(404, "job onbekend")
    if body.telemetry is not None:
        apply_telemetry(session, bs, body.telemetry)
    record_result(session, job, body.success, body.displayed_crc, body.error)
    session.commit()
    return {"status": job.status}


# --- Webinterface basisstation -------------------------------------------------------------


def station_store(bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)) -> Store:
    return session.get(Store, require_assigned(bs))


@router.get("/store", response_model=StoreInfo)
def get_store(store: Store = Depends(station_store)):
    return store


@router.put("/store/settings", response_model=StoreInfo)
def update_store_settings(body: StoreSettings, store: Store = Depends(station_store), session: Session = Depends(get_session)):
    """Omschakelen tussen kassa en webinterface als bron van de prijzen."""
    store.price_source = body.price_source
    session.commit()
    return store


@router.get("/display-types")
def display_types():
    return [{"id": d.id, "description": d.description} for d in DISPLAY_TYPES.values()]


@router.get("/store/products", response_model=list[ProductOut])
def list_products(store: Store = Depends(station_store), session: Session = Depends(get_session)):
    return catalog.list_products(session, store)


@router.put("/store/products/{sku}", response_model=ProductUpdateResult)
def upsert_product(sku: str, body: ProductIn, store: Store = Depends(station_store), session: Session = Depends(get_session)):
    require_service(session, store)
    catalog.require_price_source(store, PriceSource.MANUAL)
    result = catalog.upsert_product(session, store, sku, body)
    session.commit()
    return result


@router.post("/store/products:import", response_model=PriceImportOut)
def import_products(body: PriceImportIn, source: str = "upload", store: Store = Depends(station_store),
                    bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    """Prijslijst via het basisstation.

    `source=upload`: CSV/Excel geüpload in de webinterface (prijsbron *webinterface*).
    `source=folder`: export die weegschaal- of kassasoftware in de importmap zette (prijsbron *kassa*).
    """
    if source not in ("upload", "folder"):
        raise HTTPException(422, "source moet 'upload' of 'folder' zijn")
    require_service(session, store)
    catalog.require_price_source(store, PriceSource.MANUAL if source == "upload" else PriceSource.POS)
    result = catalog.import_price_file(session, store, body, f"basisstation:{bs.id}:{source}")
    session.commit()
    return result


@router.get("/store/labels", response_model=list[LabelOut])
def list_labels(store: Store = Depends(station_store), session: Session = Depends(get_session)):
    return catalog.list_labels(session, store)


@router.post("/store/labels", response_model=LabelOut, status_code=201)
def register_label(body: LabelCreate, request: Request, store: Store = Depends(station_store),
                   session: Session = Depends(get_session)):
    label = catalog.register_label(session, store, body, request.app.state.require_inventory)
    session.commit()
    return catalog.label_out(label)


@router.put("/store/labels/{label_id}/product", response_model=LabelOut)
def link_label(label_id: str, body: LabelLink, store: Store = Depends(station_store), session: Session = Depends(get_session)):
    label = catalog.link_label(session, store, label_id, body.sku)
    session.commit()
    return catalog.label_out(label)


@router.post("/store/labels/{label_id}/refresh", response_model=LabelOut)
def refresh_label(label_id: str, store: Store = Depends(station_store), session: Session = Depends(get_session)):
    label = catalog.refresh_label(session, store, label_id)
    session.commit()
    return catalog.label_out(label)


@router.get("/store/labels/{label_id}/preview.png", response_class=Response)
def preview(label_id: str, store: Store = Depends(station_store), session: Session = Depends(get_session)):
    return Response(catalog.preview_png(session, store, label_id), media_type="image/png")
