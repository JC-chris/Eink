"""Kassa-API: producten/prijzen bijwerken en labels koppelen."""

import io

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_store
from ..db import get_session
from ..displays import DISPLAY_TYPES
from ..jobs import content_for, schedule_label_update, schedule_product_update
from ..models import Label, Product, Store, utcnow
from ..render import render_image, quantize
from ..schemas import (
    LabelCreate, LabelLink, LabelOut, ProductBatchItem, ProductIn, ProductOut, ProductUpdateResult,
)

router = APIRouter(prefix="/v1/stores/{store_id}", tags=["kassa"])


def _upsert(session: Session, store: Store, sku: str, body: ProductIn) -> ProductUpdateResult:
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))
    if product is None:
        product = Product(store_id=store.id, sku=sku)
        session.add(product)
    for field, value in body.model_dump().items():
        if field != "sku":
            setattr(product, field, value)
    product.updated_at = utcnow()
    session.flush()
    return ProductUpdateResult(sku=sku, labels_scheduled=schedule_product_update(session, product))


@router.put("/products/{sku}", response_model=ProductUpdateResult)
def upsert_product(sku: str, body: ProductIn, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    """Product aanmaken of prijs bijwerken. Gekoppelde labels worden automatisch ververst."""
    result = _upsert(session, store, sku, body)
    session.commit()
    return result


@router.post("/products:batch", response_model=list[ProductUpdateResult])
def upsert_products(body: list[ProductBatchItem], store: Store = Depends(require_store), session: Session = Depends(get_session)):
    results = [_upsert(session, store, item.sku, item) for item in body]
    session.commit()
    return results


@router.get("/products/{sku}", response_model=ProductOut)
def get_product(sku: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))
    if product is None:
        raise HTTPException(404, "product onbekend")
    return product


def _label_out(label: Label) -> LabelOut:
    data = {k: getattr(label, k) for k in LabelOut.model_fields if k != "in_sync"}
    return LabelOut(**data, in_sync=label.expected_crc is not None and label.expected_crc == label.displayed_crc)


def _get_label(session: Session, store: Store, label_id: str) -> Label:
    label = session.get(Label, label_id)
    if label is None or label.store_id != store.id:
        raise HTTPException(404, "label onbekend")
    return label


@router.post("/labels", response_model=LabelOut, status_code=201)
def register_label(body: LabelCreate, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    existing = session.get(Label, body.label_id)
    if existing is not None and existing.store_id != store.id:
        raise HTTPException(409, "label is aan een andere winkel gekoppeld")
    label = existing or Label(id=body.label_id, store_id=store.id)
    label.display_type = body.display_type
    session.add(label)
    session.commit()
    return _label_out(label)


@router.get("/labels", response_model=list[LabelOut])
def list_labels(store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return [_label_out(l) for l in session.scalars(select(Label).where(Label.store_id == store.id).order_by(Label.id))]


@router.get("/labels/{label_id}", response_model=LabelOut)
def get_label(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    return _label_out(_get_label(session, store, label_id))


@router.put("/labels/{label_id}/product", response_model=LabelOut)
def link_label(label_id: str, body: LabelLink, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    label = _get_label(session, store, label_id)
    label.product_sku = body.sku
    schedule_label_update(session, label)
    session.commit()
    return _label_out(label)


@router.post("/labels/{label_id}/refresh", response_model=LabelOut)
def refresh_label(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    """Forceer opnieuw versturen (bv. door support na een storing)."""
    label = _get_label(session, store, label_id)
    label.expected_crc = None
    schedule_label_update(session, label)
    session.commit()
    return _label_out(label)


@router.get("/labels/{label_id}/preview.png", response_class=Response)
def preview(label_id: str, store: Store = Depends(require_store), session: Session = Depends(get_session)):
    """Exact het beeld zoals het label het (na de update) toont."""
    label = _get_label(session, store, label_id)
    if label.product_sku is None:
        raise HTTPException(404, "label is niet aan een product gekoppeld")
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == label.product_sku))
    if product is None:
        raise HTTPException(404, "product onbekend")
    display = DISPLAY_TYPES[label.display_type]
    buf = io.BytesIO()
    quantize(render_image(content_for(product), display), display).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")
