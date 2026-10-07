"""Kassa-API: producten/prijzen bijwerken en labels koppelen."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from .. import catalog
from ..auth import require_store
from ..db import get_session
from ..models import PriceSource, Store
from ..schemas import (
    LabelCreate, LabelLink, LabelOut, ProductBatchItem, ProductIn, ProductOut, ProductUpdateResult, StoreInfo,
)

router = APIRouter(prefix="/v1/stores/{store_id}", tags=["kassa"])


@router.get("", response_model=StoreInfo)
def get_store(store: Store = Depends(require_store)):
    return store


@router.put("/products/{sku}", response_model=ProductUpdateResult, responses={409: {"description": "winkel staat op handmatig beheer"}})
def upsert_product(sku: str, body: ProductIn, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    """Product aanmaken of prijs bijwerken. Gekoppelde labels worden automatisch ververst.

    Geeft 409 als de winkel is omgeschakeld naar beheer via de webinterface van het basisstation.
    """
    catalog.require_price_source(store, PriceSource.POS)
    result = catalog.upsert_product(session, store, sku, body)
    session.commit()
    return result


@router.post("/products:batch", response_model=list[ProductUpdateResult])
def upsert_products(body: list[ProductBatchItem], store: Store = Depends(require_store), session: Session = Depends(get_session)):
    catalog.require_price_source(store, PriceSource.POS)
    results = [catalog.upsert_product(session, store, item.sku, item) for item in body]
    session.commit()
    return results


@router.get("/products", response_model=list[ProductOut])
def list_products(store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return catalog.list_products(session, store)


@router.get("/products/{sku}", response_model=ProductOut)
def get_product(sku: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return catalog.get_product(session, store, sku)


@router.post("/labels", response_model=LabelOut, status_code=201)
def register_label(body: LabelCreate, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    label = catalog.register_label(session, store, body)
    session.commit()
    return catalog.label_out(label)


@router.get("/labels", response_model=list[LabelOut])
def list_labels(store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return catalog.list_labels(session, store)


@router.get("/labels/{label_id}", response_model=LabelOut)
def get_label(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return catalog.label_out(catalog.get_label(session, store, label_id))


@router.put("/labels/{label_id}/product", response_model=LabelOut)
def link_label(label_id: str, body: LabelLink, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    label = catalog.link_label(session, store, label_id, body.sku)
    session.commit()
    return catalog.label_out(label)


@router.post("/labels/{label_id}/refresh", response_model=LabelOut)
def refresh_label(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    """Forceer opnieuw versturen (bv. door support na een storing)."""
    label = catalog.refresh_label(session, store, label_id)
    session.commit()
    return catalog.label_out(label)


@router.get("/labels/{label_id}/preview.png", response_class=Response)
def preview(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return Response(catalog.preview_png(session, store, label_id), media_type="image/png")
