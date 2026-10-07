"""Gedeelde logica voor de management-API en de beheer-webinterface."""

import secrets
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Alert, BaseStation, Customer, Label, ServiceState, Store, SubscriptionStatus, utcnow
from .monitoring import BASESTATION_OFFLINE_AFTER, BATTERY_LOW_MV, LABEL_OFFLINE_AFTER
from .schemas import BaseStationStatus, CustomerCreate, CustomerOut
from .subscriptions import apply_service_states, audit, service_allowed


def customer_out(session: Session, c: Customer) -> CustomerOut:
    store_ids = list(session.scalars(select(Store.id).where(Store.customer_id == c.id).order_by(Store.id)))
    data = {k: getattr(c, k) for k in CustomerOut.model_fields if k not in ("service_active", "store_ids")}
    return CustomerOut(**data, service_active=service_allowed(c, utcnow().date()), store_ids=store_ids)


def create_customer(session: Session, body: CustomerCreate, actor: str) -> Customer:
    if session.get(Customer, body.id):
        raise HTTPException(409, "klant bestaat al")
    c = Customer(**body.model_dump(exclude={"start_date"}), start_date=body.start_date or utcnow().date())
    session.add(c)
    audit(session, actor, "customer_created", c.id, details=f"{c.plan}, € {c.monthly_price_cents // 100},{c.monthly_price_cents % 100:02d} per maand")
    return c


def create_store(session: Session, customer: Customer, store_id: str, name: str, price_source: str, actor: str) -> Store:
    if session.get(Store, store_id):
        raise HTTPException(409, "winkel bestaat al")
    store = Store(id=store_id, name=name, api_key=secrets.token_urlsafe(32), price_source=price_source,
                  customer_id=customer.id)
    session.add(store)
    session.flush()
    audit(session, actor, "store_created", customer.id, store_id)
    apply_service_states(session, actor=actor)
    return store


def create_basestation(session: Session, store: Store, bs_id: str, actor: str) -> BaseStation:
    if session.get(BaseStation, bs_id):
        raise HTTPException(409, "basisstation bestaat al")
    bs = BaseStation(id=bs_id, store_id=store.id, token=secrets.token_urlsafe(32))
    session.add(bs)
    audit(session, actor, "basestation_created", store.customer_id, store.id, bs_id)
    return bs


def rotate_api_key(session: Session, store: Store, actor: str) -> str:
    store.api_key = secrets.token_urlsafe(32)
    audit(session, actor, "store_api_key_rotated", store.customer_id, store.id)
    return store.api_key


def basestation_statuses(session: Session, now: datetime) -> list[BaseStationStatus]:
    rows = session.execute(select(BaseStation, Store.customer_id).outerjoin(Store, Store.id == BaseStation.store_id)
                           .order_by(BaseStation.store_id, BaseStation.id)).all()
    return [
        BaseStationStatus(
            id=bs.id, store_id=bs.store_id, customer_id=customer_id,
            online=bool(bs.store_id and bs.last_seen and bs.last_seen >= now - BASESTATION_OFFLINE_AFTER),
            last_seen=bs.last_seen, license_valid_until=bs.license_valid_until, software_version=bs.software_version,
        )
        for bs, customer_id in rows
    ]


def dashboard(session: Session, now: datetime) -> dict:
    customers = session.scalars(select(Customer)).all()
    today: date = now.date()
    by_status = {s: 0 for s in (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED,
                                SubscriptionStatus.SUSPENDED)}
    mrr = 0
    for c in customers:
        effective = c.subscription_status if service_allowed(c, today) else SubscriptionStatus.SUSPENDED
        by_status[effective] += 1
        if effective in (SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED):
            mrr += c.monthly_price_cents
    all_stations = basestation_statuses(session, now)
    stations = [s for s in all_stations if s.store_id]
    labels = session.scalars(select(Label).where(Label.store_id.is_not(None))).all()
    stock_labels = session.scalar(select(func.count()).select_from(Label).where(Label.store_id.is_(None)))
    alerts = session.scalars(select(Alert).where(Alert.resolved_at.is_(None))
                             .order_by(Alert.severity, Alert.created_at.desc())).all()
    ending_soon = [c for c in customers if c.subscription_status == SubscriptionStatus.CANCELLED
                   and c.end_date and c.end_date >= today]
    return {
        "customers": by_status,
        "customers_total": len(customers),
        "mrr_cents": mrr,
        "stores_total": session.scalar(select(func.count()).select_from(Store)),
        "stores_suspended": session.scalar(select(func.count()).select_from(Store)
                                           .where(Store.service_state == ServiceState.SUSPENDED)),
        "basestations_total": len(stations),
        "basestations_online": sum(1 for s in stations if s.online),
        "basestations_license_expired": [s for s in stations if s.license_valid_until and s.license_valid_until < now],
        "labels_total": len(labels),
        "labels_stock": stock_labels,
        "basestations_stock": len(all_stations) - len(stations),
        "labels_online": sum(1 for l in labels if l.last_seen and l.last_seen >= now - LABEL_OFFLINE_AFTER),
        "labels_battery_low": sum(1 for l in labels if l.battery_mv is not None and l.battery_mv < BATTERY_LOW_MV),
        "labels_out_of_sync": sum(1 for l in labels if l.expected_crc is not None and l.expected_crc != l.displayed_crc),
        "alerts": alerts,
        "alerts_critical": sum(1 for a in alerts if a.severity == "critical"),
        "ending_soon": sorted(ending_soon, key=lambda c: c.end_date),
    }
