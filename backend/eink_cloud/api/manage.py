"""Management-API: koppeling met ons facturatie-/CRM-systeem.

Authenticatie met het admin-token. Geef met de header `X-Actor` aan welk systeem of welke
medewerker de wijziging doet (bv. `facturatie`); dat komt in het auditlog.
"""

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import management, subscriptions
from ..auth import require_admin
from ..db import get_session
from ..models import AuditEntry, Customer, utcnow
from ..schemas import AuditOut, BaseStationStatus, CancelBody, CustomerBase, CustomerCreate, CustomerOut, SuspendBody

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
