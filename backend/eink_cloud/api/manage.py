"""Management-API: koppeling met ons facturatie-/CRM-systeem.

Authenticatie met het admin-token. Geef met de header `X-Actor` aan welk systeem of welke
medewerker de wijziging doet (bv. `facturatie`); dat komt in het auditlog.
"""

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException

from .. import inventory, management, subscriptions
from ..auth import require_admin
from ..db import get_session
from ..models import AuditEntry, BaseStation, Customer, Label, Shipment, ShipmentItem, Store, utcnow
from ..schemas import (
    AssignLabelsIn, AuditOut, BaseStationAssignIn, BaseStationCreate, BaseStationCreated, BaseStationStatus,
    CancelBody, CustomerBase, CustomerCreate, CustomerOut, LabelIdsIn, PinIn, ShipmentIn, ShipmentOut, StockLabelOut,
    StockLabelsIn, StockLabelsResult, SuspendBody,
)

router = APIRouter(prefix="/v1/manage", tags=["management"], dependencies=[Depends(require_admin)])


def actor(x_actor: str | None = Header(None)) -> str:
    return f"api:{(x_actor or 'admin')[:80]}"


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(session: Session = Depends(get_session)):
    return [management.customer_out(session, c) for c in session.scalars(select(Customer).order_by(Customer.id))]


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerCreate, who: str = Depends(actor), session: Session = Depends(get_session)):
    c = management.create_customer(session, body, who)
    session.commit()
    return management.customer_out(session, c)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, session: Session = Depends(get_session)):
    return management.customer_out(session, subscriptions.get_customer(session, customer_id))


@router.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: str, body: CustomerBase, who: str = Depends(actor), session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    changes = {k: v for k, v in body.model_dump().items() if getattr(c, k) != v}
    for k, v in changes.items():
        setattr(c, k, v)
    if changes:
        subscriptions.audit(session, who, "customer_updated", c.id, details=", ".join(sorted(changes)))
    session.commit()
    return management.customer_out(session, c)


@router.post("/customers/{customer_id}/cancel", response_model=CustomerOut)
def cancel(customer_id: str, body: CancelBody, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Opzegging registreren. De dienst werkt tot en met `end_date` en schakelt daarna automatisch uit."""
    c = subscriptions.get_customer(session, customer_id)
    subscriptions.cancel(session, c, body.end_date, who)
    session.commit()
    return management.customer_out(session, c)


@router.post("/customers/{customer_id}/revoke-cancellation", response_model=CustomerOut)
def revoke(customer_id: str, who: str = Depends(actor), session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    subscriptions.revoke_cancellation(session, c, who)
    session.commit()
    return management.customer_out(session, c)


@router.post("/customers/{customer_id}/suspend", response_model=CustomerOut)
def suspend(customer_id: str, body: SuspendBody, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Direct uitschakelen (bv. wanbetaling). Labels krijgen een neutraal beeld zonder prijs."""
    c = subscriptions.get_customer(session, customer_id)
    subscriptions.suspend(session, c, body.reason, who)
    session.commit()
    return management.customer_out(session, c)


@router.post("/customers/{customer_id}/reactivate", response_model=CustomerOut)
def reactivate(customer_id: str, who: str = Depends(actor), session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    subscriptions.reactivate(session, c, who)
    session.commit()
    return management.customer_out(session, c)


@router.get("/basestations", response_model=list[BaseStationStatus])
def basestations(session: Session = Depends(get_session)):
    return management.basestation_statuses(session, utcnow())


@router.get("/audit", response_model=list[AuditOut])
def audit_log(customer_id: str | None = None, limit: int = 200, session: Session = Depends(get_session)):
    q = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(min(limit, 1000))
    if customer_id:
        q = q.where(AuditEntry.customer_id == customer_id)
    return session.scalars(q).all()


# --- voorraad en koppelen -----------------------------------------------------------------------


def _store(session: Session, store_id: str) -> Store:
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "winkel onbekend")
    return store


@router.get("/labels", response_model=list[StockLabelOut])
def list_labels(store_id: str | None = None, stock: bool = False, limit: int = 1000, session: Session = Depends(get_session)):
    """Alle labels; `stock=true` alleen de voorraad, of filter op winkel."""
    q = select(Label).order_by(Label.id).limit(min(limit, 10000))
    if stock:
        q = q.where(Label.store_id.is_(None))
    elif store_id:
        q = q.where(Label.store_id == store_id)
    return session.scalars(q).all()


@router.post("/labels", response_model=StockLabelsResult, status_code=201)
def add_labels(body: StockLabelsIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Labels uit de fabriek op voorraad zetten."""
    ids = [inventory.normalize_label_id(i) for i in body.label_ids if i.strip()]
    added, known = inventory.add_labels_to_stock(session, ids, body.display_type, who)
    session.commit()
    return StockLabelsResult(added=added, already_known=known)


@router.post("/labels/assign")
def assign_labels(body: AssignLabelsIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Labels koppelen aan een winkel (en daarmee de klant), optioneel vast aan een basisstation."""
    ids = [inventory.normalize_label_id(i) for i in body.label_ids]
    n = inventory.assign_labels(session, ids, _store(session, body.store_id), who, body.basestation_id or None, body.move)
    session.commit()
    return {"assigned": n}


@router.post("/labels/unassign")
def unassign_labels(body: LabelIdsIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Labels terug naar voorraad (retour, defect, vervanging)."""
    n = inventory.unassign_labels(session, [inventory.normalize_label_id(i) for i in body.label_ids], who)
    session.commit()
    return {"unassigned": n}


@router.put("/labels/{label_id}/basestation", response_model=StockLabelOut)
def pin_label(label_id: str, body: PinIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Label vast aan een basisstation koppelen, of terug naar automatisch."""
    label = session.get(Label, inventory.normalize_label_id(label_id))
    if label is None or label.store_id is None:
        raise HTTPException(404, "label onbekend of op voorraad")
    inventory.pin_label(session, label, body.basestation_id, who)
    session.commit()
    return label


@router.get("/stores/{store_id}/sightings")
def store_sightings(store_id: str, session: Session = Depends(get_session)):
    """Labels die de basisstations van deze winkel horen maar die (nog) niet aan de winkel gekoppeld zijn."""
    _store(session, store_id)
    return inventory.sightings(session, store_id)


@router.post("/basestations", response_model=BaseStationCreated, status_code=201)
def add_basestation(body: BaseStationCreate, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Basisstation op voorraad zetten (token gaat in de fabrieksconfig)."""
    bs = inventory.add_basestation_to_stock(session, body.id, who)
    session.commit()
    return BaseStationCreated(id=bs.id, store_id=None, token=bs.token)


@router.post("/basestations/{bs_id}/assign", response_model=BaseStationStatus)
def assign_basestation(bs_id: str, body: BaseStationAssignIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Basisstation koppelen aan een winkel, verplaatsen, of terug naar voorraad (`store_id: null`)."""
    bs = session.get(BaseStation, bs_id)
    if bs is None:
        raise HTTPException(404, "basisstation onbekend")
    inventory.assign_basestation(session, bs, _store(session, body.store_id) if body.store_id else None, who)
    session.commit()
    return next(s for s in management.basestation_statuses(session, utcnow()) if s.id == bs_id)


# --- leveringen (scannen bij uitlevering) -------------------------------------------------------


def _shipment_out(session: Session, s: Shipment) -> ShipmentOut:
    label_ids = list(session.scalars(select(ShipmentItem.item_id).where(
        ShipmentItem.shipment_id == s.id, ShipmentItem.kind == "label").order_by(ShipmentItem.item_id)))
    return ShipmentOut(id=s.id, customer_id=s.customer_id, store_id=s.store_id, basestation_id=s.basestation_id,
                       reference=s.reference, pinned=s.pinned, created_by=s.created_by, created_at=s.created_at,
                       label_ids=label_ids)


@router.get("/scan-check")
def scan_check(store_id: str, code: str, session: Session = Depends(get_session)):
    """Eén gescande barcode controleren (voor een scanner-app): status ok | warn | error."""
    return inventory.check_scan(session, code, _store(session, store_id))


@router.post("/shipments", response_model=ShipmentOut, status_code=201)
def create_shipment(body: ShipmentIn, who: str = Depends(actor), session: Session = Depends(get_session)):
    """Gescande barcodes in één keer aan de winkel koppelen (basisstation + displays, of alleen displays bij
    uitbreiding). Alles of niets: bij één fout wordt niets gekoppeld."""
    s = inventory.create_shipment(session, _store(session, body.store_id), body.codes, who, body.pin, body.reference,
                                  body.new_display_type)
    session.commit()
    return _shipment_out(session, s)


@router.get("/shipments", response_model=list[ShipmentOut])
def list_shipments(customer_id: str | None = None, session: Session = Depends(get_session)):
    q = select(Shipment).order_by(Shipment.id.desc()).limit(500)
    if customer_id:
        q = q.where(Shipment.customer_id == customer_id)
    return [_shipment_out(session, s) for s in session.scalars(q)]


@router.get("/shipments/{shipment_id}", response_model=ShipmentOut)
def get_shipment(shipment_id: int, session: Session = Depends(get_session)):
    s = session.get(Shipment, shipment_id)
    if s is None:
        raise HTTPException(404, "levering onbekend")
    return _shipment_out(session, s)
