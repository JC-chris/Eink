"""Producten en labels van een winkel; gedeeld door de kassa-API en de basisstation-API."""

import io

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .displays import DISPLAY_TYPES
from .jobs import content_for, schedule_label_update, schedule_product_update
from .models import Label, Product, Store, utcnow
from .render import quantize, render_image
from .schemas import LabelCreate, LabelOut, ProductIn, ProductUpdateResult

PRICE_SOURCE_NAMES = {"pos": "de kassa", "manual": "de webinterface van het basisstation"}


def require_price_source(store: Store, source: str) -> None:
    """Voorkomt dat kassa en webinterface elkaars prijzen overschrijven."""
    if store.price_source != source:
        raise HTTPException(
            409,
            f"prijzen van deze winkel worden beheerd via {PRICE_SOURCE_NAMES[store.price_source]}; "
            "schakel om via de instellingen van het basisstation",
        )


def upsert_product(session: Session, store: Store, sku: str, body: ProductIn) -> ProductUpdateResult:
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))
    if product is None:
        product = Product(store_id=store.id, sku=sku)
        session.add(product)
    for field in ProductIn.model_fields:
        setattr(product, field, getattr(body, field))
    product.updated_at = utcnow()
    session.flush()
    return ProductUpdateResult(sku=sku, labels_scheduled=schedule_product_update(session, product))


def list_products(session: Session, store: Store) -> list[Product]:
    return list(session.scalars(select(Product).where(Product.store_id == store.id).order_by(Product.sku)))


def get_product(session: Session, store: Store, sku: str) -> Product:
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))
    if product is None:
        raise HTTPException(404, "product onbekend")
    return product


def label_out(label: Label) -> LabelOut:
    data = {k: getattr(label, k) for k in LabelOut.model_fields if k != "in_sync"}
    return LabelOut(**data, in_sync=label.expected_crc is not None and label.expected_crc == label.displayed_crc)


def list_labels(session: Session, store: Store) -> list[LabelOut]:
    return [label_out(l) for l in session.scalars(select(Label).where(Label.store_id == store.id).order_by(Label.id))]


def get_label(session: Session, store: Store, label_id: str) -> Label:
    label = session.get(Label, label_id)
    if label is None or label.store_id != store.id:
        raise HTTPException(404, "label onbekend")
    return label


def register_label(session: Session, store: Store, body: LabelCreate) -> Label:
    existing = session.get(Label, body.label_id)
    if existing is not None and existing.store_id != store.id:
        raise HTTPException(409, "label is aan een andere winkel gekoppeld")
    label = existing or Label(id=body.label_id, store_id=store.id)
    label.display_type = body.display_type
    session.add(label)
    session.flush()
    schedule_label_update(session, label)
    return label


def link_label(session: Session, store: Store, label_id: str, sku: str | None) -> Label:
    # Koppelen aan een SKU die (nog) niet bestaat mag: de kassa kan het product later sturen.
    label = get_label(session, store, label_id)
    label.product_sku = sku
    schedule_label_update(session, label)
    return label


def refresh_label(session: Session, store: Store, label_id: str) -> Label:
    if store.service_state == "suspended":
        raise HTTPException(403, "het abonnement van deze winkel is niet actief")
    label = get_label(session, store, label_id)
    label.expected_crc = None
    schedule_label_update(session, label)
    return label


def preview_png(session: Session, store: Store, label_id: str) -> bytes:
    """Exact het beeld zoals het label het (na de update) toont."""
    label = get_label(session, store, label_id)
    if label.product_sku is None:
        raise HTTPException(404, "label is niet aan een product gekoppeld")
    product = get_product(session, store, label.product_sku)
    display = DISPLAY_TYPES[label.display_type]
    buf = io.BytesIO()
    quantize(render_image(content_for(product), display), display).save(buf, "PNG")
    return buf.getvalue()
