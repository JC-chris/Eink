import hmac

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import BaseStation, Store


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authorization: Bearer <token> ontbreekt")
    return authorization.removeprefix("Bearer ")


def require_admin(request: Request, authorization: str | None = Header(None)) -> None:
    if not hmac.compare_digest(_bearer(authorization), request.app.state.admin_token):
        raise HTTPException(403, "geen admin-toegang")


def require_store(
    store_id: str,
    request: Request,
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
) -> Store:
    """Kassa (winkel-API-sleutel) of admin heeft toegang tot een winkel."""
    token = _bearer(authorization)
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "winkel onbekend")
    if not (hmac.compare_digest(token, store.api_key) or hmac.compare_digest(token, request.app.state.admin_token)):
        raise HTTPException(403, "geen toegang tot deze winkel")
    return store


def require_basestation(
    authorization: str | None = Header(None), session: Session = Depends(get_session)
) -> BaseStation:
    token = _bearer(authorization)
    bs = session.scalar(select(BaseStation).where(BaseStation.token == token))
    if bs is None:
        raise HTTPException(403, "onbekend basisstation")
    return bs
