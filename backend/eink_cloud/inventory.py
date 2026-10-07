"""Voorraad en koppelen: welk label en welk basisstation hoort bij welke klant/winkel.

Werkwijze:
1. Fabriek/magazijn: labels en basisstations komen **op voorraad** (geen winkel).
2. Bij levering: in het managementsysteem **koppelen aan een winkel** (en daarmee aan de klant),
   desgewenst met een **vast basisstation**.
3. In de winkel: een basisstation hoort labels; labels uit de voorraad die daar gehoord worden,
   kan de winkel ook zelf registreren (bewijs van fysieke aanwezigheid).
4. Retour/vervanging: **ontkoppelen** (terug naar voorraad) of verplaatsen naar een andere winkel.
"""

import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .displays import DISPLAY_TYPES
from .models import BaseStation, JobStatus, Label, LabelSighting, Shipment, ShipmentItem, Store, UpdateJob, utcnow
from .subscriptions import audit

SIGHTING_VALID = timedelta(days=1)  # zo lang telt "gehoord in deze winkel" als bewijs


MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def normalize_label_id(raw: str) -> str:
    """'c0ffee000001', 'C0-FF-EE-00-00-01' en 'C0:FF:EE:00:00:01' zijn hetzelfde label."""
    text = raw.strip().upper()
    hexonly = re.sub(r"[:\-\s]", "", text)
    if len(hexonly) == 12 and re.fullmatch(r"[0-9A-F]{12}", hexonly):
        return ":".join(hexonly[i:i + 2] for i in range(0, 12, 2))
    return text


def parse_label_list(text: str) -> list[str]:
    """Plaklijst of CSV uit de fabriek/scanner: één ID per regel, eventueel ',type' erachter."""
    ids = []
    for line in text.replace(";", "\n").splitlines():
        first = line.split(",")[0].strip()
        if first and not first.lower().startswith(("id", "label")):
            ids.append(normalize_label_id(first))
    return list(dict.fromkeys(ids))  # dubbele eruit, volgorde behouden


def _check_display_type(display_type: str) -> None:
    if display_type not in DISPLAY_TYPES:
        raise HTTPException(422, f"onbekend displaytype {display_type!r}")


def add_labels_to_stock(session: Session, label_ids: list[str], display_type: str, actor: str) -> tuple[int, list[str]]:
    """Geeft (aantal toegevoegd, al bestaande IDs) terug."""
    _check_display_type(display_type)
    existing = set(session.scalars(select(Label.id).where(Label.id.in_(label_ids))))
    new = [i for i in label_ids if i not in existing]
    for label_id in new:
        if len(label_id) > 32:
            raise HTTPException(422, f"label-ID te lang: {label_id}")
        session.add(Label(id=label_id, store_id=None, display_type=display_type))
    if new:
        audit(session, actor, "labels_to_stock", details=f"{len(new)} × {display_type}: {', '.join(new[:20])}")
    return len(new), sorted(existing)


def _get_basestation(session: Session, bs_id: str) -> BaseStation:
    bs = session.get(BaseStation, bs_id)
    if bs is None:
        raise HTTPException(404, f"basisstation {bs_id} onbekend")
    return bs


def _release(session: Session, label: Label) -> None:
    session.execute(
        update(UpdateJob)
        .where(UpdateJob.label_id == label.id, UpdateJob.status.in_((JobStatus.PENDING, JobStatus.SENT)))
        .values(status=JobStatus.SUPERSEDED, finished_at=utcnow())
    )
    label.product_sku = None
    label.basestation_id = None
    label.pinned_basestation_id = None
    label.expected_crc = None
    label.displayed_crc = None


def assign_labels(session: Session, label_ids: list[str], store: Store, actor: str, pinned_bs_id: str | None = None,
                  move: bool = False) -> int:
    """Koppelt labels aan een winkel. Labels van een andere winkel alleen met move=True."""
    if pinned_bs_id:
        bs = _get_basestation(session, pinned_bs_id)
        if bs.store_id != store.id:
            raise HTTPException(409, f"basisstation {bs.id} hoort niet bij winkel {store.id}")
    labels = {l.id: l for l in session.scalars(select(Label).where(Label.id.in_(label_ids)))}
    missing = [i for i in label_ids if i not in labels]
    if missing:
        raise HTTPException(404, f"onbekende labels (eerst op voorraad zetten): {', '.join(missing[:10])}")
    elsewhere = [l.id for l in labels.values() if l.store_id not in (None, store.id)]
    if elsewhere and not move:
        raise HTTPException(409, f"labels horen bij een andere winkel: {', '.join(elsewhere[:10])}")
    for label in labels.values():
        if label.store_id not in (None, store.id):
            audit(session, actor, "label_moved", None, label.store_id, f"{label.id} → {store.id}")
            _release(session, label)
        label.store_id = store.id
        if pinned_bs_id is not None:
            label.pinned_basestation_id = pinned_bs_id or None
    session.execute(delete(LabelSighting).where(LabelSighting.label_id.in_(label_ids)))
    audit(session, actor, "labels_assigned", store.customer_id, store.id,
          f"{len(labels)} labels" + (f", vast via {pinned_bs_id}" if pinned_bs_id else "") + f": {', '.join(list(labels)[:20])}")
    return len(labels)


def unassign_labels(session: Session, label_ids: list[str], actor: str) -> int:
    """Terug naar voorraad (retour, defect, vervanging)."""
    labels = session.scalars(select(Label).where(Label.id.in_(label_ids), Label.store_id.is_not(None))).all()
    for label in labels:
        audit(session, actor, "label_to_stock", None, label.store_id, label.id)
        _release(session, label)
        label.store_id = None
    return len(labels)


def pin_label(session: Session, label: Label, bs_id: str | None, actor: str) -> None:
    if bs_id:
        bs = _get_basestation(session, bs_id)
        if bs.store_id != label.store_id:
            raise HTTPException(409, f"basisstation {bs.id} hoort niet bij de winkel van dit label")
    label.pinned_basestation_id = bs_id or None
    audit(session, actor, "label_pinned", None, label.store_id, f"{label.id} → {bs_id or 'automatisch'}")
    if bs_id:
        # Openstaande update opnieuw laten oppakken via het juiste basisstation.
        session.execute(update(UpdateJob).where(UpdateJob.label_id == label.id, UpdateJob.status == JobStatus.SENT)
                        .values(status=JobStatus.PENDING))


def add_basestation_to_stock(session: Session, bs_id: str, actor: str) -> BaseStation:
    import secrets

    if session.get(BaseStation, bs_id):
        raise HTTPException(409, "basisstation bestaat al")
    bs = BaseStation(id=bs_id, store_id=None, token=secrets.token_urlsafe(32))
    session.add(bs)
    audit(session, actor, "basestation_to_stock", details=bs_id)
    return bs


def assign_basestation(session: Session, bs: BaseStation, store: Store | None, actor: str) -> None:
    """Basisstation naar een (andere) winkel of terug naar voorraad."""
    old = bs.store_id
    if store is not None and old == store.id:
        return
    # Labels die vast aan dit basisstation hingen gaan terug naar automatisch.
    session.execute(update(Label).where(Label.pinned_basestation_id == bs.id).values(pinned_basestation_id=None))
    session.execute(update(Label).where(Label.basestation_id == bs.id).values(basestation_id=None))
    session.execute(delete(LabelSighting).where(LabelSighting.basestation_id == bs.id))
    bs.store_id = store.id if store else None
    bs.license_valid_until = None
    audit(session, actor, "basestation_assigned", store.customer_id if store else None, store.id if store else old,
          f"{bs.id}: {old or 'voorraad'} → {store.id if store else 'voorraad'}")


def record_sighting(session: Session, bs: BaseStation, label_id: str, rssi: int | None, battery_mv: int | None) -> None:
    s = session.get(LabelSighting, (label_id, bs.id))
    if s is None:
        s = LabelSighting(label_id=label_id, basestation_id=bs.id, store_id=bs.store_id)
        session.add(s)
    s.store_id, s.rssi, s.battery_mv, s.last_seen = bs.store_id, rssi, battery_mv, utcnow()


def heard_in_store(session: Session, label_id: str, store_id: str, now: datetime | None = None) -> bool:
    since = (now or utcnow()) - SIGHTING_VALID
    return session.scalar(select(LabelSighting.label_id).where(
        LabelSighting.label_id == label_id, LabelSighting.store_id == store_id, LabelSighting.last_seen >= since)) is not None


def sightings(session: Session, store_id: str) -> list[dict]:
    """Ongekoppelde labels die de basisstations van deze winkel horen, met hun huidige status."""
    rows = session.execute(
        select(LabelSighting, Label).outerjoin(Label, Label.id == LabelSighting.label_id)
        .where(LabelSighting.store_id == store_id).order_by(LabelSighting.rssi.desc())
    ).all()
    result: dict[str, dict] = {}
    for s, label in rows:
        if label is not None and label.store_id == store_id:
            continue
        status = "unknown" if label is None else ("stock" if label.store_id is None else "other_store")
        entry = result.get(s.label_id)
        if entry is None or (s.rssi or -999) > (entry["rssi"] or -999):
            result[s.label_id] = {"label_id": s.label_id, "basestation_id": s.basestation_id, "rssi": s.rssi,
                                  "battery_mv": s.battery_mv, "last_seen": s.last_seen, "status": status,
                                  "other_store": label.store_id if label is not None else None,
                                  "display_type": label.display_type if label is not None else None}
    return list(result.values())


def require_assigned(bs: BaseStation) -> str:
    if bs.store_id is None:
        raise HTTPException(409, "dit basisstation staat op voorraad en is nog niet aan een winkel gekoppeld")
    return bs.store_id


# --- scannen bij uitlevering ---------------------------------------------------------------------
#
# Barcodes op de producten: "L:<mac>" voor een display en "B:<id>" voor een basisstation
# (ook "EINK:L:..." / "EINK:B:..." in een QR-code). Zonder voorvoegsel wordt herkend wat het is.


def parse_scan(session: Session, code: str) -> tuple[str, str]:
    """Geeft (soort, id) terug: soort is "basestation" of "label"."""
    text = code.strip()
    upper = text.upper()
    for prefix in ("EINK:",):
        if upper.startswith(prefix):
            text, upper = text[len(prefix):], upper[len(prefix):]
    if upper.startswith(("B:", "BS:")):
        return "basestation", text.split(":", 1)[1].strip()
    if upper.startswith("L:"):
        return "label", normalize_label_id(text[2:])
    if session.get(BaseStation, text) is not None:
        return "basestation", text
    return "label", normalize_label_id(text)


def check_scan(session: Session, code: str, store: Store) -> dict:
    """Controle per gescande barcode, vóór het bevestigen. status: ok | warn | error."""
    kind, item_id = parse_scan(session, code)
    result = {"code": code, "kind": kind, "id": item_id, "display_type": None, "new": False}
    if kind == "basestation":
        bs = session.get(BaseStation, item_id)
        if bs is None:
            return result | {"status": "error", "message": f"Basisstation {item_id} onbekend — eerst op voorraad zetten "
                                                            "(het token moet in de fabrieksconfig staan)"}
        if bs.store_id is None:
            return result | {"status": "ok", "message": f"Basisstation {item_id} (voorraad)"}
        if bs.store_id == store.id:
            return result | {"status": "warn", "message": f"Basisstation {item_id} is al van deze winkel"}
        return result | {"status": "error", "message": f"Basisstation {item_id} hoort bij winkel {bs.store_id}"}
    label = session.get(Label, item_id)
    if label is None:
        if not MAC_RE.match(item_id):
            return result | {"status": "error", "message": f"'{code}' is geen geldige display-barcode"}
        return result | {"status": "ok", "new": True, "message": f"Display {item_id} — nieuw, wordt op voorraad gezet"}
    result["display_type"] = label.display_type
    type_name = DISPLAY_TYPES[label.display_type].description if label.display_type in DISPLAY_TYPES else label.display_type
    if label.store_id is None:
        return result | {"status": "ok", "message": f"Display {item_id} · {type_name}"}
    if label.store_id == store.id:
        return result | {"status": "warn", "message": f"Display {item_id} is al van deze winkel"}
    return result | {"status": "error", "message": f"Display {item_id} hoort bij winkel {label.store_id}"}


def create_shipment(session: Session, store: Store, codes: list[str], actor: str, pin: bool = True,
                    reference: str | None = None, new_display_type: str = "bwry_2_9") -> Shipment:
    """Koppelt alles wat gescand is aan de winkel van de klant, in één keer (alles of niets)."""
    _check_display_type(new_display_type)
    checks = [check_scan(session, c, store) for c in dict.fromkeys(c.strip() for c in codes if c.strip())]
    errors = [c["message"] for c in checks if c["status"] == "error"]
    if errors:
        raise HTTPException(409, "; ".join(errors))
    stations = list(dict.fromkeys(c["id"] for c in checks if c["kind"] == "basestation"))
    label_ids = list(dict.fromkeys(c["id"] for c in checks if c["kind"] == "label"))
    if len(stations) > 1:
        raise HTTPException(409, "scan per levering maximaal één basisstation (of maak twee leveringen)")
    if not stations and not label_ids:
        raise HTTPException(422, "niets gescand")
    bs_id = stations[0] if stations else None

    new = [c["id"] for c in checks if c["kind"] == "label" and c["new"]]
    if new:
        add_labels_to_stock(session, new, new_display_type, actor)
        session.flush()
    if bs_id:
        assign_basestation(session, session.get(BaseStation, bs_id), store, actor)
    if label_ids:
        assign_labels(session, label_ids, store, actor, pinned_bs_id=bs_id if (pin and bs_id) else None)
    shipment = Shipment(customer_id=store.customer_id, store_id=store.id, basestation_id=bs_id, reference=reference or None,
                        pinned=bool(pin and bs_id and label_ids), created_by=actor)
    session.add(shipment)
    session.flush()
    if bs_id:
        session.add(ShipmentItem(shipment_id=shipment.id, item_id=bs_id, kind="basestation"))
    types = dict(session.execute(select(Label.id, Label.display_type).where(Label.id.in_(label_ids))).all()) if label_ids else {}
    for label_id in label_ids:
        session.add(ShipmentItem(shipment_id=shipment.id, item_id=label_id, kind="label", display_type=types.get(label_id)))
    audit(session, actor, "shipment_created", store.customer_id, store.id,
          f"levering #{shipment.id}{' (' + reference + ')' if reference else ''}: "
          f"{'basisstation ' + bs_id + ' + ' if bs_id else ''}{len(label_ids)} displays")
    return shipment
