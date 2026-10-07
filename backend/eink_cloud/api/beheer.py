"""Webinterface van het managementsysteem (voor onze eigen medewerkers).

Rollen: "admin" mag klanten, contracten, winkels en basisstations beheren; "support" kan alles
bekijken en storingen oplossen (labels opnieuw versturen), maar niet aan contracten komen.
"""

import hmac
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog, management, subscriptions
from ..db import get_session
from ..displays import DISPLAY_TYPES
from ..models import Alert, AuditEntry, Customer, Operator, Store, utcnow
from ..monitoring import evaluate_alerts, store_overview
from ..schemas import CustomerCreate
from ..security import hash_password, sign, verify_password
from ..subscriptions import STATUS_NAMES

COOKIE = "eink_beheer"
SESSION_TTL_S = 10 * 3600

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _euro(cents: int | None) -> str:
    if cents is None:
        return ""
    e, c = divmod(cents, 100)
    return f"€ {e:,}".replace(",", ".") + f",{c:02d}"


def _dt(v: datetime | None) -> str:
    return v.strftime("%d-%m-%Y %H:%M") if v else "—"


def _d(v: date | None) -> str:
    return v.strftime("%d-%m-%Y") if v else "—"


def _ago(v: datetime | None) -> str:
    if v is None:
        return "nooit"
    s = int((utcnow() - v).total_seconds())
    if s < 0:
        return "zojuist"
    for size, unit in ((86400, "d"), (3600, "u"), (60, "min")):
        if s >= size:
            return f"{s // size} {unit} geleden"
    return f"{s} s geleden"


def _left(v: datetime | None) -> str:
    if v is None:
        return "—"
    s = int((v - utcnow()).total_seconds())
    if s <= 0:
        return "verlopen"
    return f"nog {s // 86400} d {(s % 86400) // 3600} u"


templates.env.filters.update(euro=_euro, dt=_dt, d=_d, ago=_ago, left=_left)
templates.env.globals.update(STATUS_NAMES=STATUS_NAMES, now=utcnow)


class LoginRequired(Exception):
    pass


def _valid_sig(request: Request, op: Operator, expires: str, sig: str) -> bool:
    expected = sign(request.app.state.session_secret, f"{op.username}|{expires}|{op.password_hash}")
    return hmac.compare_digest(sig, expected)


def current_operator(request: Request, session: Session = Depends(get_session)) -> Operator:
    raw = request.cookies.get(COOKIE, "")
    parts = raw.split("|")
    if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) < time.time():
        raise LoginRequired()
    op = session.get(Operator, parts[0])
    if op is None or not _valid_sig(request, op, parts[1], parts[2]):
        raise LoginRequired()
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "ongeldige herkomst van formulier")
    return op


def require_admin_role(op: Operator = Depends(current_operator)) -> Operator:
    if op.role != "admin":
        raise HTTPException(403, "alleen voor beheerders (admin)")
    return op


router = APIRouter(prefix="/beheer", include_in_schema=False)


def redirect(path: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    for key, value in (("msg", msg), ("err", err)):
        if value:
            path += ("&" if "?" in path else "?") + f"{key}={quote(value)}"
    return RedirectResponse(path, status_code=303)


def render(request: Request, name: str, op: Operator | None, **ctx) -> HTMLResponse:
    ctx.update(op=op, msg=request.query_params.get("msg"), err=ctx.get("err") or request.query_params.get("err"),
               path=request.url.path)
    return templates.TemplateResponse(request, f"beheer/{name}", ctx)


def actor(op: Operator) -> str:
    return f"medewerker:{op.username}"


# --- inloggen ---------------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html", None)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    op = session.get(Operator, username.strip())
    if op is None or not verify_password(password, op.password_hash):
        time.sleep(1)
        return render(request, "login.html", None, err="Onjuiste gebruikersnaam of wachtwoord")
    expires = str(int(time.time()) + SESSION_TTL_S)
    value = f"{op.username}|{expires}|{sign(request.app.state.session_secret, f'{op.username}|{expires}|{op.password_hash}')}"
    resp = redirect("/beheer")
    resp.set_cookie(COOKIE, value, max_age=SESSION_TTL_S, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https")
    return resp


@router.post("/logout")
def logout():
    resp = redirect("/beheer/login")
    resp.delete_cookie(COOKIE)
    return resp


# --- dashboard --------------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    evaluate_alerts(session)
    return render(request, "dashboard.html", op, d=management.dashboard(session, utcnow()))


# --- klanten ----------------------------------------------------------------------------------


@router.get("/klanten", response_class=HTMLResponse)
def customers(request: Request, q: str = "", op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    query = select(Customer).order_by(Customer.name)
    if q:
        query = query.where(Customer.name.ilike(f"%{q}%") | Customer.id.ilike(f"%{q}%"))
    items = [management.customer_out(session, c) for c in session.scalars(query)]
    return render(request, "customers.html", op, customers=items, q=q, today=utcnow().date())


@router.post("/klanten")
def create_customer(
    id: str = Form(...), name: str = Form(...), contact_email: str = Form(""), contact_phone: str = Form(""),
    plan: str = Form("Standaard"), monthly_price: str = Form("0"), subscription_status: str = Form("active"),
    op: Operator = Depends(require_admin_role), session: Session = Depends(get_session),
):
    try:
        body = CustomerCreate(id=id.strip(), name=name.strip(), contact_email=contact_email.strip() or None,
                              contact_phone=contact_phone.strip() or None, plan=plan.strip() or "Standaard",
                              monthly_price_cents=_parse_cents(monthly_price), subscription_status=subscription_status)
        management.create_customer(session, body, actor(op))
        session.commit()
    except (ValueError, HTTPException) as exc:
        return redirect("/beheer/klanten", err=_error(exc))
    return redirect(f"/beheer/klanten/{body.id}", msg=f"Klant {body.name} aangemaakt")


def _parse_cents(text: str) -> int:
    text = text.replace("€", "").replace(" ", "").replace(".", "").replace(",", ".") if "," in text else text.replace("€", "").strip()
    try:
        value = round(float(text or 0) * 100)
    except ValueError:
        raise ValueError(f"ongeldig bedrag: {text}") from None
    if value < 0:
        raise ValueError("bedrag mag niet negatief zijn")
    return value


def _error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors())
    return str(exc)


@router.get("/klanten/{customer_id}", response_class=HTMLResponse)
def customer_detail(customer_id: str, request: Request, op: Operator = Depends(current_operator),
                    session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    now = utcnow()
    stores = session.scalars(select(Store).where(Store.customer_id == c.id).order_by(Store.id)).all()
    log = session.scalars(select(AuditEntry).where(AuditEntry.customer_id == c.id).order_by(AuditEntry.id.desc()).limit(50)).all()
    return render(request, "customer.html", op, c=management.customer_out(session, c),
                  stores=[store_overview(session, s, now) for s in stores], log=log, today=now.date())


@router.post("/klanten/{customer_id}")
def update_customer(customer_id: str, name: str = Form(...), contact_email: str = Form(""), contact_phone: str = Form(""),
                    plan: str = Form(...), monthly_price: str = Form(...), notes: str = Form(""),
                    op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    try:
        values = dict(name=name.strip(), contact_email=contact_email.strip() or None, contact_phone=contact_phone.strip() or None,
                      plan=plan.strip(), monthly_price_cents=_parse_cents(monthly_price), notes=notes.strip() or None)
    except ValueError as exc:
        return redirect(f"/beheer/klanten/{customer_id}", err=str(exc))
    changed = sorted(k for k, v in values.items() if getattr(c, k) != v)
    for k, v in values.items():
        setattr(c, k, v)
    if changed:
        subscriptions.audit(session, actor(op), "customer_updated", c.id, details=", ".join(changed))
    session.commit()
    return redirect(f"/beheer/klanten/{customer_id}", msg="Gegevens opgeslagen")


def _contract_action(customer_id: str, session: Session, fn, msg: str):
    c = subscriptions.get_customer(session, customer_id)
    try:
        fn(c)
        session.commit()
    except HTTPException as exc:
        session.rollback()
        return redirect(f"/beheer/klanten/{customer_id}", err=str(exc.detail))
    return redirect(f"/beheer/klanten/{customer_id}", msg=msg)


@router.post("/klanten/{customer_id}/opzeggen")
def cancel(customer_id: str, end_date: date = Form(...), op: Operator = Depends(require_admin_role),
           session: Session = Depends(get_session)):
    return _contract_action(customer_id, session, lambda c: subscriptions.cancel(session, c, end_date, actor(op)),
                            f"Opzegging geregistreerd; de dienst stopt na {end_date:%d-%m-%Y}")


@router.post("/klanten/{customer_id}/opzegging-intrekken")
def revoke(customer_id: str, op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    return _contract_action(customer_id, session, lambda c: subscriptions.revoke_cancellation(session, c, actor(op)),
                            "Opzegging ingetrokken")


@router.post("/klanten/{customer_id}/uitschakelen")
def suspend(customer_id: str, reason: str = Form(""), confirm: str = Form(""), op: Operator = Depends(require_admin_role),
            session: Session = Depends(get_session)):
    if confirm.strip() != customer_id:
        return redirect(f"/beheer/klanten/{customer_id}", err="Typ ter bevestiging de klant-ID over")
    return _contract_action(customer_id, session, lambda c: subscriptions.suspend(session, c, reason, actor(op)),
                            "Systeem uitgeschakeld; labels krijgen 'Prijs aan de kassa'")


@router.post("/klanten/{customer_id}/heractiveren")
def reactivate(customer_id: str, op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    return _contract_action(customer_id, session, lambda c: subscriptions.reactivate(session, c, actor(op)),
                            "Abonnement weer actief; labels krijgen hun prijzen terug")


@router.post("/klanten/{customer_id}/winkels", response_class=HTMLResponse)
def create_store(customer_id: str, request: Request, store_id: str = Form(...), name: str = Form(...),
                 price_source: str = Form("pos"), op: Operator = Depends(require_admin_role),
                 session: Session = Depends(get_session)):
    c = subscriptions.get_customer(session, customer_id)
    try:
        from ..schemas import StoreCreate

        body = StoreCreate(id=store_id.strip(), name=name.strip(), price_source=price_source)
        store = management.create_store(session, c, body.id, body.name, body.price_source, actor(op))
        session.commit()
    except (ValueError, HTTPException) as exc:
        return redirect(f"/beheer/klanten/{customer_id}", err=_error(exc))
    # Geheimen nooit in een URL: direct tonen, één keer.
    return _store_page(request, op, session, store, secret=("API-sleutel voor de kassa", store.api_key))


# --- winkels ----------------------------------------------------------------------------------


def _store_page(request: Request, op: Operator, session: Session, store: Store, secret: tuple[str, str] | None = None):
    now = utcnow()
    customer = session.get(Customer, store.customer_id) if store.customer_id else None
    stations = [s for s in management.basestation_statuses(session, now) if s.store_id == store.id]
    alerts = session.scalars(select(Alert).where(Alert.store_id == store.id, Alert.resolved_at.is_(None))).all()
    return render(request, "store.html", op, store=store, customer=customer, overview=store_overview(session, store, now),
                  stations=stations, labels=catalog.list_labels(session, store), alerts=alerts, secret=secret,
                  display_types=DISPLAY_TYPES)


def _get_store(session: Session, store_id: str) -> Store:
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "winkel onbekend")
    return store


@router.get("/winkels/{store_id}", response_class=HTMLResponse)
def store_detail(store_id: str, request: Request, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return _store_page(request, op, session, _get_store(session, store_id))


@router.post("/winkels/{store_id}/basisstations", response_class=HTMLResponse)
def create_basestation(store_id: str, request: Request, bs_id: str = Form(...), op: Operator = Depends(require_admin_role),
                       session: Session = Depends(get_session)):
    store = _get_store(session, store_id)
    try:
        bs = management.create_basestation(session, store, bs_id.strip(), actor(op))
        session.commit()
    except HTTPException as exc:
        return redirect(f"/beheer/winkels/{store_id}", err=str(exc.detail))
    return _store_page(request, op, session, store, secret=(f"Token voor basisstation {bs.id}", bs.token))


@router.post("/winkels/{store_id}/api-sleutel", response_class=HTMLResponse)
def rotate_key(store_id: str, request: Request, op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    store = _get_store(session, store_id)
    key = management.rotate_api_key(session, store, actor(op))
    session.commit()
    return _store_page(request, op, session, store, secret=("Nieuwe API-sleutel voor de kassa (de oude werkt niet meer)", key))


@router.post("/winkels/{store_id}/labels/{label_id}/opnieuw")
def refresh_label(store_id: str, label_id: str, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    store = _get_store(session, store_id)
    catalog.refresh_label(session, store, label_id)
    subscriptions.audit(session, actor(op), "label_refresh", store.customer_id, store.id, label_id)
    session.commit()
    return redirect(f"/beheer/winkels/{store_id}", msg=f"Label {label_id} wordt opnieuw verstuurd")


# --- overzichten ------------------------------------------------------------------------------


@router.get("/basisstations", response_class=HTMLResponse)
def basestations(request: Request, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return render(request, "basestations.html", op, stations=management.basestation_statuses(session, utcnow()))


@router.get("/storingen", response_class=HTMLResponse)
def alerts(request: Request, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    open_alerts = evaluate_alerts(session)
    resolved = session.scalars(select(Alert).where(Alert.resolved_at.is_not(None)).order_by(Alert.resolved_at.desc()).limit(50)).all()
    return render(request, "alerts.html", op, open_alerts=open_alerts, resolved=resolved)


@router.get("/audit", response_class=HTMLResponse)
def audit_log(request: Request, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return render(request, "audit.html", op, log=session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(300)).all())


@router.get("/medewerkers", response_class=HTMLResponse)
def operators(request: Request, op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    return render(request, "operators.html", op, operators=session.scalars(select(Operator).order_by(Operator.username)).all())


@router.post("/medewerkers")
def create_operator(username: str = Form(...), password: str = Form(...), role: str = Form("support"),
                    op: Operator = Depends(require_admin_role), session: Session = Depends(get_session)):
    username = username.strip()
    if not username or len(password) < 10 or role not in ("admin", "support"):
        return redirect("/beheer/medewerkers", err="Gebruikersnaam verplicht, wachtwoord minimaal 10 tekens")
    existing = session.get(Operator, username)
    target = existing or Operator(username=username)
    target.password_hash = hash_password(password)
    target.role = role
    session.add(target)
    subscriptions.audit(session, actor(op), "operator_saved", details=f"{username} ({role})")
    session.commit()
    return redirect("/beheer/medewerkers", msg=f"Medewerker {username} opgeslagen")


def install(app) -> None:
    @app.exception_handler(LoginRequired)
    def _login(request: Request, exc: LoginRequired):
        return RedirectResponse("/beheer/login", status_code=303)

    app.include_router(router)
