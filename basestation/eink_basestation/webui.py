"""Lokale webinterface van het basisstation.

- Instellingen: cloudverbinding, wachtwoord, prijsbron (kassa of webinterface).
- Zonder kassakoppeling: producten en prijzen beheren, labels registreren en koppelen.

Alles gaat via de cloud-API met het token van het basisstation; de cloud blijft de bron van
waarheid, zodat monitoring en support hetzelfde zien als de winkel.
"""

import hashlib
import hmac
import socket
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import __version__
from .agent import Agent
from .cloud import ClientFactory, Cloud, CloudError
from .config import Config, hash_password, verify_password

SESSION_COOKIE = "eink_session"
SESSION_TTL_S = 12 * 3600
DEFAULT_DISPLAY_TYPE = "bwry_2_9"  # meest gebruikte vitrinelabel; later meldt het label zijn type zelf
UNITS = {"st": "per stuk", "kg": "per kg", "100g": "per 100 g", "l": "per liter", "pak": "per pak"}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def euro(cents: int | None) -> str:
    if cents is None:
        return ""
    euros, rest = divmod(cents, 100)
    return f"€ {euros:,}".replace(",", ".") + f",{rest:02d}"


def euro_input(cents: int | None) -> str:
    return "" if cents is None else f"{cents // 100},{cents % 100:02d}"


def parse_euro(text: str) -> int | None:
    """'12,95', '€ 12.95', '1.234,50' → centen. Leeg → None."""
    text = text.replace("€", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"ongeldige prijs: {text!r}") from None
    if value < 0 or value != value.quantize(Decimal("0.01")):
        raise ValueError(f"ongeldige prijs: {text!r}")
    return int(value * 100)


templates.env.filters["euro"] = euro
templates.env.filters["euro_input"] = euro_input


class LoginRequired(Exception):
    pass


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _redirect(path: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    if msg:
        path += ("&" if "?" in path else "?") + "msg=" + quote(msg)
    if err:
        path += ("&" if "?" in path else "?") + "err=" + quote(err)
    return RedirectResponse(path, status_code=303)


def _ip_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        return sorted({i[4][0] for i in infos})
    except OSError:
        return []


def create_webui(config: Config, config_path: Path, agent: Agent, client_factory: ClientFactory) -> FastAPI:
    app = FastAPI(title="Eink basisstation", docs_url=None, redoc_url=None, openapi_url=None)

    def cloud() -> Cloud:
        return Cloud(client_factory(config))

    def session_cookie() -> str:
        # Wachtwoordhash zit in de handtekening: na wachtwoordwijziging zijn oude sessies ongeldig.
        expires = str(int(time.time()) + SESSION_TTL_S)
        return f"{expires}.{_sign(config.session_secret, expires + config.password_hash)}"

    def require_login(request: Request) -> None:
        raw = request.cookies.get(SESSION_COOKIE, "")
        expires, _, sig = raw.partition(".")
        valid = (
            expires.isdigit()
            and int(expires) > time.time()
            and hmac.compare_digest(sig, _sign(config.session_secret, expires + config.password_hash))
        )
        if not valid:
            raise LoginRequired()
        if request.method == "POST":
            # CSRF: naast SameSite=Strict ook de herkomst van formulieren controleren.
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                raise LoginRequired()

    @app.exception_handler(LoginRequired)
    def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse("/login", status_code=303)

    def render(request: Request, name: str, **context) -> HTMLResponse:
        context.update(
            msg=request.query_params.get("msg"),
            err=context.get("err") or request.query_params.get("err"),
            version=__version__,
            path=request.url.path,
        )
        return templates.TemplateResponse(request, name, context)

    def store_or_error() -> tuple[dict | None, str | None]:
        try:
            return cloud().store(), None
        except CloudError as exc:
            return None, str(exc)

    # --- inloggen ---------------------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    def login(request: Request, password: str = Form(...)):
        if not verify_password(password, config.password_hash):
            time.sleep(1)  # vertraagt raden
            return render(request, "login.html", err="Onjuist wachtwoord")
        resp = _redirect("/")
        resp.set_cookie(SESSION_COOKIE, session_cookie(), max_age=SESSION_TTL_S, httponly=True, samesite="strict")
        return resp

    @app.post("/logout")
    def logout():
        resp = _redirect("/login")
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # --- status -----------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def status(request: Request):
        store, err = store_or_error() if config.token else (None, None)
        return render(request, "status.html", store=store, cloud_err=err, agent=agent.status,
                      uptime_s=agent.uptime_s, configured=bool(config.token))

    # --- producten --------------------------------------------------------------------------

    @app.get("/producten", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def products(request: Request, edit: str | None = None):
        store, err = store_or_error()
        items = []
        if store:
            try:
                items = cloud().products()
            except CloudError as exc:
                err = str(exc)
        editing = next((p for p in items if p["sku"] == edit), None)
        return render(request, "products.html", store=store, products=items, editing=editing, units=UNITS, err=err)

    @app.post("/producten", dependencies=[Depends(require_login)])
    def save_product(
        sku: str = Form(...),
        name: str = Form(...),
        price: str = Form(...),
        unit: str = Form("st"),
        unit_price: str = Form(""),
        origin: str = Form(""),
        promo_text: str = Form(""),
    ):
        sku = sku.strip()
        try:
            price_cents = parse_euro(price)
            if price_cents is None:
                raise ValueError("prijs is verplicht")
            body = {
                "name": name.strip(),
                "price_cents": price_cents,
                "unit": unit,
                "unit_price_cents": parse_euro(unit_price),
                "origin": origin.strip() or None,
                "promo_text": promo_text.strip() or None,
            }
            result = cloud().upsert_product(sku, body)
        except (ValueError, CloudError) as exc:
            return _redirect("/producten" + (f"?edit={quote(sku)}" if sku else ""), err=str(exc))
        n = result["labels_scheduled"]
        return _redirect("/producten", msg=f"{name} opgeslagen" + (f", {n} label(s) worden bijgewerkt" if n else ""))

    # --- labels -----------------------------------------------------------------------------

    @app.get("/labels", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def labels(request: Request):
        store, err = store_or_error()
        registered, items, display_types = [], [], []
        if store:
            try:
                c = cloud()
                registered, items, display_types = c.labels(), c.products(), c.display_types()
            except CloudError as exc:
                err = str(exc)
        known = {l["id"] for l in registered}
        new = [s for s in agent.status.labels_seen if s.label_id not in known]
        return render(request, "labels.html", store=store, labels=registered, products=items,
                      display_types=display_types, new_labels=new, err=err,
                      default_display_type=DEFAULT_DISPLAY_TYPE)

    @app.post("/labels/registreren", dependencies=[Depends(require_login)])
    def register_label(label_id: str = Form(...), display_type: str = Form(...)):
        try:
            cloud().register_label(label_id.strip(), display_type)
        except CloudError as exc:
            return _redirect("/labels", err=str(exc))
        return _redirect("/labels", msg=f"Label {label_id} geregistreerd")

    @app.post("/labels/{label_id}/koppelen", dependencies=[Depends(require_login)])
    def link_label(label_id: str, sku: str = Form("")):
        try:
            cloud().link_label(label_id, sku or None)
        except CloudError as exc:
            return _redirect("/labels", err=str(exc))
        return _redirect("/labels", msg=f"Label {label_id} " + (f"gekoppeld aan {sku}" if sku else "ontkoppeld"))

    @app.post("/labels/{label_id}/opnieuw", dependencies=[Depends(require_login)])
    def refresh_label(label_id: str):
        try:
            cloud().refresh_label(label_id)
        except CloudError as exc:
            return _redirect("/labels", err=str(exc))
        return _redirect("/labels", msg=f"Label {label_id} wordt opnieuw verstuurd")

    @app.get("/labels/{label_id}/preview.png", dependencies=[Depends(require_login)])
    def preview(label_id: str):
        try:
            return Response(cloud().preview(label_id), media_type="image/png")
        except CloudError as exc:
            return Response(str(exc), status_code=404)

    # --- instellingen -----------------------------------------------------------------------

    @app.get("/instellingen", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def settings(request: Request):
        store, err = store_or_error() if config.token else (None, None)
        return render(request, "settings.html", store=store, cloud_err=err, config=config,
                      hostname=socket.gethostname(), ips=_ip_addresses(), uptime_s=agent.uptime_s)

    @app.post("/instellingen/prijsbron", dependencies=[Depends(require_login)])
    def set_price_source(price_source: str = Form(...)):
        if price_source not in ("pos", "manual"):
            return _redirect("/instellingen", err="ongeldige keuze")
        try:
            cloud().set_price_source(price_source)
        except CloudError as exc:
            return _redirect("/instellingen", err=str(exc))
        text = "de kassa" if price_source == "pos" else "deze webinterface"
        return _redirect("/instellingen", msg=f"Prijzen worden nu beheerd via {text}")

    @app.post("/instellingen/cloud", dependencies=[Depends(require_login)])
    def set_cloud(server: str = Form(...), token: str = Form("")):
        server = server.strip().rstrip("/")
        if urlsplit(server).scheme not in ("http", "https"):
            return _redirect("/instellingen", err="server moet beginnen met https://")
        config.server = server
        if token.strip():
            config.token = token.strip()
        config.save(config_path)
        agent.set_client(client_factory(config) if config.token else None)
        return _redirect("/instellingen", msg="Cloudverbinding opgeslagen")

    @app.post("/instellingen/wachtwoord", dependencies=[Depends(require_login)])
    def set_password(current: str = Form(...), new: str = Form(...), repeat: str = Form(...)):
        if not verify_password(current, config.password_hash):
            return _redirect("/instellingen", err="Huidig wachtwoord onjuist")
        if len(new) < 8:
            return _redirect("/instellingen", err="Nieuw wachtwoord moet minimaal 8 tekens zijn")
        if new != repeat:
            return _redirect("/instellingen", err="Wachtwoorden komen niet overeen")
        config.password_hash = hash_password(new)
        config.save(config_path)
        resp = _redirect("/instellingen", msg="Wachtwoord gewijzigd")
        resp.set_cookie(SESSION_COOKIE, session_cookie(), max_age=SESSION_TTL_S, httponly=True, samesite="strict")
        return resp

    return app
