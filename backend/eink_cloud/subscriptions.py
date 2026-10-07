"""Abonnementen: opzeggen, uitschakelen, heractiveren — en wat dat betekent voor de winkels.

Levenscyclus:  trial/active ──opzeggen──► cancelled (loopt door t/m end_date) ──► uitgeschakeld
               active/cancelled ──direct uitschakelen──► suspended
               suspended/cancelled ──heractiveren──► active

Bij uitschakelen krijgen alle labels een neutraal beeld ("Prijs aan de kassa"): een label met een
verouderde prijs is voor de winkel een groter probleem dan een label zonder prijs.
"""

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .displays import DISPLAY_TYPES
from .jobs import schedule_label_update
from .models import (
    AuditEntry, Customer, JobStatus, Label, ServiceState, Store, SubscriptionStatus, UpdateJob, utcnow,
)
from .render import notice_frame

NOTICE_TITLE = "Prijs aan de kassa"
NOTICE_SUBTITLE = "Vraag onze medewerkers naar de prijs"
STATUS_NAMES = {
    SubscriptionStatus.TRIAL: "proefperiode",
    SubscriptionStatus.ACTIVE: "actief",
    SubscriptionStatus.CANCELLED: "opgezegd",
    SubscriptionStatus.SUSPENDED: "uitgeschakeld",
}


def audit(session: Session, actor: str, action: str, customer_id: str | None = None,
          store_id: str | None = None, details: str | None = None) -> None:
    session.add(AuditEntry(actor=actor, action=action, customer_id=customer_id, store_id=store_id,
                           details=(details or "")[:1000] or None))


def service_allowed(customer: Customer | None, today: date) -> bool:
    if customer is None:
        return True  # winkel zonder klant/contract (bv. demo of eigen testwinkel)
    if customer.subscription_status == SubscriptionStatus.SUSPENDED:
        return False
    if customer.subscription_status == SubscriptionStatus.CANCELLED and customer.end_date and today > customer.end_date:
        return False
    return True


def require_service(session: Session, store: Store) -> None:
    """Weigert prijsupdates als het abonnement niet (meer) actief is."""
    if store.service_state == ServiceState.SUSPENDED:
        raise HTTPException(403, "het abonnement van deze winkel is niet actief; neem contact op met de leverancier")


def _suspend_store(session: Session, store: Store, actor: str) -> int:
    session.execute(
        update(UpdateJob)
        .where(UpdateJob.store_id == store.id, UpdateJob.status.in_((JobStatus.PENDING, JobStatus.SENT)))
        .values(status=JobStatus.SUPERSEDED, finished_at=utcnow())
    )
    labels = session.scalars(select(Label).where(Label.store_id == store.id)).all()
    for label in labels:
        frame = notice_frame(DISPLAY_TYPES[label.display_type], NOTICE_TITLE, NOTICE_SUBTITLE)
        label.expected_crc = frame.crc32
        session.add(UpdateJob(store_id=store.id, label_id=label.id, frame=frame.encode(), crc32=frame.crc32, kind="service"))
    store.service_state = ServiceState.SUSPENDED
    audit(session, actor, "store_suspended", store.customer_id, store.id, f"{len(labels)} labels op neutraal beeld")
    return len(labels)


def _activate_store(session: Session, store: Store, actor: str) -> None:
    store.service_state = ServiceState.ACTIVE
    for label in session.scalars(select(Label).where(Label.store_id == store.id)):
        label.expected_crc = None
        schedule_label_update(session, label)
    audit(session, actor, "store_activated", store.customer_id, store.id)


def apply_service_states(session: Session, now: datetime | None = None, actor: str = "systeem") -> list[str]:
    """Brengt de winkels in lijn met hun abonnement (ook automatisch bij het verlopen van een opzegging)."""
    today = (now or utcnow()).date()
    changed = []
    stores = session.scalars(select(Store)).all()
    customers = {c.id: c for c in session.scalars(select(Customer))}
    for store in stores:
        allowed = service_allowed(customers.get(store.customer_id), today)
        if not allowed and store.service_state != ServiceState.SUSPENDED:
            _suspend_store(session, store, actor)
            changed.append(store.id)
        elif allowed and store.service_state == ServiceState.SUSPENDED:
            _activate_store(session, store, actor)
            changed.append(store.id)
    return changed


def get_customer(session: Session, customer_id: str) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "klant onbekend")
    return customer


def cancel(session: Session, customer: Customer, end_date: date, actor: str) -> None:
    if customer.subscription_status == SubscriptionStatus.SUSPENDED:
        raise HTTPException(409, "abonnement is al uitgeschakeld")
    if end_date < utcnow().date():
        raise HTTPException(422, "einddatum ligt in het verleden; gebruik 'direct uitschakelen'")
    customer.subscription_status = SubscriptionStatus.CANCELLED
    customer.end_date = end_date
    customer.cancelled_at = utcnow()
    audit(session, actor, "subscription_cancelled", customer.id, details=f"dienst eindigt na {end_date.isoformat()}")
    apply_service_states(session, actor=actor)


def revoke_cancellation(session: Session, customer: Customer, actor: str) -> None:
    if customer.subscription_status != SubscriptionStatus.CANCELLED:
        raise HTTPException(409, "abonnement is niet opgezegd")
    customer.subscription_status = SubscriptionStatus.ACTIVE
    customer.end_date = None
    customer.cancelled_at = None
    audit(session, actor, "cancellation_revoked", customer.id)
    apply_service_states(session, actor=actor)


def suspend(session: Session, customer: Customer, reason: str, actor: str) -> None:
    if not reason.strip():
        raise HTTPException(422, "geef een reden op")
    customer.subscription_status = SubscriptionStatus.SUSPENDED
    customer.suspend_reason = reason.strip()[:500]
    audit(session, actor, "subscription_suspended", customer.id, details=reason)
    apply_service_states(session, actor=actor)


def reactivate(session: Session, customer: Customer, actor: str) -> None:
    customer.subscription_status = SubscriptionStatus.ACTIVE
    customer.end_date = None
    customer.cancelled_at = None
    customer.suspend_reason = None
    audit(session, actor, "subscription_reactivated", customer.id)
    apply_service_states(session, actor=actor)


def lease_message(customer: Customer | None, store: Store) -> str | None:
    """Tekst die het basisstation in zijn webinterface toont."""
    if store.service_state == ServiceState.SUSPENDED:
        return "Het abonnement is beëindigd of uitgeschakeld. Neem contact op met de leverancier."
    if customer is None:
        return None
    if customer.subscription_status == SubscriptionStatus.SUSPENDED:
        return "Het abonnement is beëindigd of uitgeschakeld. Neem contact op met de leverancier."
    if customer.subscription_status == SubscriptionStatus.CANCELLED and customer.end_date:
        return f"Het abonnement is opgezegd en eindigt na {customer.end_date.strftime('%d-%m-%Y')}."
    return None
