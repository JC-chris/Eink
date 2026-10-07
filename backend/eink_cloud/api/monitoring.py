from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_session
from ..models import Alert, Store, utcnow
from ..monitoring import evaluate_alerts, prometheus_metrics, store_overview
from ..schemas import AlertOut

router = APIRouter(tags=["monitoring"], dependencies=[Depends(require_admin)])


@router.get("/v1/monitoring/overview")
def overview(session: Session = Depends(get_session)):
    now = utcnow()
    evaluate_alerts(session, now)
    return [store_overview(session, s, now) for s in session.scalars(select(Store).order_by(Store.id))]


@router.get("/v1/monitoring/alerts", response_model=list[AlertOut])
def alerts(open: bool = True, store_id: str | None = None, session: Session = Depends(get_session)):
    evaluate_alerts(session)
    q = select(Alert).order_by(Alert.id.desc()).limit(500)
    if open:
        q = q.where(Alert.resolved_at.is_(None))
    if store_id:
        q = q.where(Alert.store_id == store_id)
    return session.scalars(q).all()


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(session: Session = Depends(get_session)):
    return prometheus_metrics(session, utcnow())
