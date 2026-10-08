"""Producten en labels van een winkel; gedeeld door de kassa-API en de basisstation-API."""

import io

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .displays import DISPLAY_TYPES
from .jobs import content_for, schedule_label_update, schedule_product_update
from .models import Label, Product, Store, utcnow
from .render import quantize, render_image
from .schemas import LabelCreate, LabelOut, PriceImportIn, PriceImportOut, ProductIn, ProductUpdateResult
from .subscriptions import audit

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


def import_price_file(session: Session, store: Store, body: PriceImportIn, actor: str) -> PriceImportOut:
    """Prijslijst controleren (dry_run) of importeren. Alles of niets: met fouten wordt niets ingelezen."""
    import base64
    import binascii
    import json

    from .pricefile import FIELD_LABELS, PriceFileError, build_items, guess_mapping, read_table

    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "bestand niet goed meegestuurd (geen geldige base64)") from None
    try:
        table = read_table(data, body.filename)
        saved = json.loads(store.import_mapping) if store.import_mapping else None
        mapping = body.mapping if body.mapping is not None else (
            saved if saved and all(c in table.columns for c in saved.values()) else guess_mapping(table.columns))
        result = build_items(table, mapping, body.default_unit)
    except PriceFileError as exc:
        raise HTTPException(422, str(exc)) from None

    out = PriceImportOut(dry_run=body.dry_run, columns=result.columns, mapping=result.mapping, fields=FIELD_LABELS,
                         rows_total=result.rows_total, valid=len(result.items), skipped=result.skipped,
                         errors=result.errors[:200], preview=result.items[:20])
    if body.dry_run or result.errors or not result.items:
        return out
    scheduled = sum(upsert_product(session, store, item.sku, item).labels_scheduled for item in result.items)
    store.import_mapping = json.dumps(result.mapping)
    audit(session, actor, "price_import", store.customer_id, store.id,
          f"{body.filename}: {len(result.items)} producten, {scheduled} labels bijgewerkt")
    out.imported, out.labels_scheduled = len(result.items), scheduled
    return out


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


def register_label(session: Session, store: Store, body: LabelCreate, require_inventory: bool = False) -> Label:
    """Registratie door de winkel zelf (kassa-API of webinterface basisstation).

    - label al van deze winkel: alleen displaytype bijwerken;
    - label van een andere winkel: geweigerd;
    - label op voorraad: alleen als een basisstation van deze winkel het recent gehoord heeft
      (anders kan iedereen willekeurige labels uit onze voorraad claimen); het displaytype
      komt dan uit de voorraad;
    - onbekend label: aangemaakt, tenzij `require_inventory` (productie: alles via de voorraad).
    """
    from .inventory import heard_in_store, normalize_label_id

    label_id = normalize_label_id(body.label_id)
    existing = session.get(Label, label_id)
    if existing is not None and existing.store_id not in (None, store.id):
        raise HTTPException(409, "label is aan een andere winkel gekoppeld")
    if existing is not None and existing.store_id is None:
        if not heard_in_store(session, label_id, store.id):
            raise HTTPException(403, "label staat op voorraad en is niet door een basisstation van deze winkel "
                                     "gehoord; koppel het via het managementsysteem")
        existing.store_id = store.id
        audit(session, f"winkel:{store.id}", "label_claimed", store.customer_id, store.id, label_id)
    elif existing is None:
        if require_inventory:
            raise HTTPException(403, "onbekend label; alleen labels uit onze voorraad kunnen gekoppeld worden")
        existing = Label(id=label_id, store_id=store.id, display_type=body.display_type)
    else:
        existing.display_type = body.display_type
    label = existing
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
    quantize(render_image(content_for(product, store.label_template), display), display).save(buf, "PNG")
    return buf.getvalue()


SAMPLE_PRODUCT = dict(name="Runderbiefstuk", price_cents=2995, unit="kg", origin="Nederland",
                      description="Malse biefstuk van Hollandse weiderunderen", promo_text=None, was_price_cents=None)
# Voorbeeldproduct dat bij het ontwerp past (alleen voor de voorbeelden in de webinterfaces).
SAMPLE_PER_TEMPLATE = {
    "vis": dict(SAMPLE_PRODUCT, name="Kabeljauwfilet", price_cents=3295, origin="FAO 27 Noordoost-Atlantische Oceaan",
                description="Gadus morhua · wild gevangen · sleepnet"),
    "bakker": dict(SAMPLE_PRODUCT, name="Desembrood volkoren", price_cents=445, unit="st", origin=None,
                   description="Met zuurdesem, 800 g"),
    "info": dict(SAMPLE_PRODUCT, name="Saucijzenbroodje", price_cents=295, unit="st",
                 description="Bladerdeeg (tarwebloem, boter), varkensgehakt, ui, kruiden. "
                             "Allergenen: gluten, melk, ei. Opwarmen: 10 min op 180 °C."),
    "ambachtelijk": dict(SAMPLE_PRODUCT, name="Ossenworst", price_cents=1895, origin="Eigen makelij",
                         description="Amsterdams recept"),
}


def template_preview_png(session: Session, store: Store, template: str, display_type: str, sku: str | None = None,
                         promo: bool = False) -> bytes:
    """Voorbeeld van een ontwerp, met een product van de winkel of een voorbeeldproduct."""
    from .label_templates import TEMPLATES
    from .render import LabelContent

    if template not in TEMPLATES:
        raise HTTPException(404, "onbekend ontwerp")
    if display_type not in DISPLAY_TYPES:
        raise HTTPException(404, "onbekend displaytype")
    if sku:
        content = content_for(get_product(session, store, sku), template)
        content.template = template
    else:
        content = LabelContent(**SAMPLE_PER_TEMPLATE.get(template, SAMPLE_PRODUCT), template=template)
        if promo:
            content.promo_text, content.was_price_cents = "Weekaanbieding", content.price_cents
            content.price_cents = content.price_cents * 4 // 5
    display = DISPLAY_TYPES[display_type]
    buf = io.BytesIO()
    quantize(render_image(content, display), display).save(buf, "PNG")
    return buf.getvalue()


def update_store_settings(session: Session, store: Store, body, actor: str) -> int:
    """Prijsbron en/of standaardontwerp wijzigen. Bij een ander ontwerp krijgen alle labels het nieuwe beeld."""
    if body.price_source is not None:
        store.price_source = body.price_source
    rescheduled = 0
    if body.label_template is not None and body.label_template != store.label_template:
        store.label_template = body.label_template
        audit(session, actor, "label_template", store.customer_id, store.id, body.label_template)
        for label in session.scalars(select(Label).where(Label.store_id == store.id, Label.product_sku.is_not(None))):
            if schedule_label_update(session, label):
                rescheduled += 1
    return rescheduled
