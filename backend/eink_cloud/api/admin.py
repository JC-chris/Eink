import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_session
from ..displays import DISPLAY_TYPES
from ..models import BaseStation, Customer, Store
from ..subscriptions import apply_service_states, audit
from ..schemas import BaseStationCreate, BaseStationCreated, StoreCreate, StoreCreated, StoreInfo, StoreSettings

router = APIRouter(prefix="/v1/admin", tags=["beheer"], dependencies=[Depends(require_admin)])


@router.post("/stores", response_model=StoreCreated, status_code=201)
def create_store(body: StoreCreate, session: Session = Depends(get_session)):
    if session.get(Store, body.id):
        raise HTTPException(409, "winkel bestaat al")
    if body.customer_id and session.get(Customer, body.customer_id) is None:
        raise HTTPException(404, "klant onbekend")
    store = Store(id=body.id, name=body.name, api_key=secrets.token_urlsafe(32), price_source=body.price_source,
                  customer_id=body.customer_id)
    session.add(store)
    session.flush()
    audit(session, "api:admin", "store_created", body.customer_id, store.id)
    apply_service_states(session, actor="api:admin")
    session.commit()
    return StoreCreated(id=store.id, name=store.name, api_key=store.api_key, price_source=store.price_source)


@router.put("/stores/{store_id}/settings", response_model=StoreInfo)
def update_store_settings(store_id: str, body: StoreSettings, session: Session = Depends(get_session)):
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "winkel onbekend")
    store.price_source = body.price_source
    session.commit()
    return store


@router.post("/stores/{store_id}/basestations", response_model=BaseStationCreated, status_code=201)
def create_basestation(store_id: str, body: BaseStationCreate, session: Session = Depends(get_session)):
    if session.get(Store, store_id) is None:
        raise HTTPException(404, "winkel onbekend")
    if session.get(BaseStation, body.id):
        raise HTTPException(409, "basisstation bestaat al")
    bs = BaseStation(id=body.id, store_id=store_id, token=secrets.token_urlsafe(32))
    session.add(bs)
    session.commit()
    return BaseStationCreated(id=bs.id, store_id=store_id, token=bs.token)


@router.get("/display-types")
def display_types():
    return [
        {"id": d.id, "description": d.description, "width": d.width, "height": d.height, "colors": len(d.palette)}
        for d in DISPLAY_TYPES.values()
    ]
