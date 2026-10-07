"""Storingsdetectie: alerts aanmaken en automatisch sluiten."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .jobs import retry
from .models import Alert, BaseStation, JobStatus, Label, ServiceState, Store, UpdateJob, utcnow

BASESTATION_OFFLINE_AFTER = timedelta(minutes=5)
LABEL_OFFLINE_AFTER = timedelta(hours=6)
JOB_TIMEOUT = timedelta(minutes=10)
LICENSE_WARNING = timedelta(days=2)  # waarschuwen als de wekelijkse check-in dreigt te verlopen
BATTERY_LOW_MV = 2400


@dataclass(frozen=True)
class Problem:
    store_id: str
    kind: str
    subject_id: str
    severity: str
    message: str


def requeue_stale_jobs(session: Session, now: datetime) -> int:
    stale = session.scalars(
        select(UpdateJob).where(UpdateJob.status == JobStatus.SENT, UpdateJob.sent_at < now - JOB_TIMEOUT)
    ).all()
    for job in stale:
        job.error = "geen antwoord van basisstation"
        retry(job)
    return len(stale)


def find_problems(session: Session, now: datetime) -> list[Problem]:
    problems: list[Problem] = []
    # Uitgeschakelde winkels geven geen storingsmeldingen: daar is uitval verwacht.
    suspended = set(session.scalars(select(Store.id).where(Store.service_state == ServiceState.SUSPENDED)))
    for bs in session.scalars(select(BaseStation)):
        if bs.store_id in suspended:
            continue
        if bs.last_seen is None or bs.last_seen < now - BASESTATION_OFFLINE_AFTER:
            problems.append(Problem(bs.store_id, "basestation_offline", bs.id, "critical",
                                    f"Basisstation {bs.id} geeft geen heartbeat meer (laatst: {bs.last_seen})"))
        if bs.license_valid_until is not None:
            if bs.license_valid_until < now:
                problems.append(Problem(bs.store_id, "license_expired", bs.id, "critical",
                                        f"Basisstation {bs.id}: wekelijkse check-in gemist, licentie verlopen op "
                                        f"{bs.license_valid_until:%d-%m-%Y %H:%M} — systeem staat stil"))
            elif bs.license_valid_until < now + LICENSE_WARNING:
                problems.append(Problem(bs.store_id, "license_expiring", bs.id, "warning",
                                        f"Basisstation {bs.id}: licentie verloopt op {bs.license_valid_until:%d-%m-%Y %H:%M} "
                                        "als het geen verbinding maakt"))
    for label in session.scalars(select(Label)):
        if label.store_id in suspended:
            continue
        if label.last_seen is not None and label.last_seen < now - LABEL_OFFLINE_AFTER:
            problems.append(Problem(label.store_id, "label_offline", label.id, "warning",
                                    f"Label {label.id} niet gehoord sinds {label.last_seen}"))
        if label.battery_mv is not None and label.battery_mv < BATTERY_LOW_MV:
            problems.append(Problem(label.store_id, "battery_low", label.id, "warning",
                                    f"Batterij label {label.id}: {label.battery_mv} mV"))
    # Alleen de laatste job per label telt: een latere geslaagde update lost het op.
    latest = select(func.max(UpdateJob.id)).where(UpdateJob.status != JobStatus.SUPERSEDED).group_by(UpdateJob.label_id)
    for job in session.scalars(select(UpdateJob).where(UpdateJob.id.in_(latest), UpdateJob.status == JobStatus.FAILED)):
        if job.store_id in suspended:
            continue
        problems.append(Problem(job.store_id, "update_failed", job.label_id, "critical",
                                f"Update label {job.label_id} {job.attempts}x mislukt: {job.error}"))
    return problems


def evaluate_alerts(session: Session, now: datetime | None = None) -> list[Alert]:
    """Opent alerts voor nieuwe problemen en sluit alerts waarvan het probleem weg is."""
    from .subscriptions import apply_service_states

    now = now or utcnow()
    apply_service_states(session, now)  # o.a. opzeggingen waarvan de einddatum verstreken is
    requeue_stale_jobs(session, now)
    current = {(p.kind, p.subject_id): p for p in find_problems(session, now)}
    open_alerts = {(a.kind, a.subject_id): a for a in session.scalars(select(Alert).where(Alert.resolved_at.is_(None)))}
    for key, alert in open_alerts.items():
        if key not in current:
            alert.resolved_at = now
    for key, p in current.items():
        if key not in open_alerts:
            session.add(Alert(store_id=p.store_id, kind=p.kind, subject_id=p.subject_id,
                              severity=p.severity, message=p.message, created_at=now))
    session.commit()
    return list(session.scalars(select(Alert).where(Alert.resolved_at.is_(None)).order_by(Alert.id)))


def store_overview(session: Session, store: Store, now: datetime) -> dict:
    labels = session.scalars(select(Label).where(Label.store_id == store.id)).all()
    stations = session.scalars(select(BaseStation).where(BaseStation.store_id == store.id)).all()
    job_counts = dict(session.execute(
        select(UpdateJob.status, func.count()).where(UpdateJob.store_id == store.id).group_by(UpdateJob.status)
    ).all())
    open_alerts = session.scalar(
        select(func.count()).select_from(Alert).where(Alert.store_id == store.id, Alert.resolved_at.is_(None))
    )
    online = [l for l in labels if l.last_seen and l.last_seen >= now - LABEL_OFFLINE_AFTER]
    return {
        "store_id": store.id,
        "name": store.name,
        "labels_total": len(labels),
        "labels_online": len(online),
        "labels_never_seen": sum(1 for l in labels if l.last_seen is None),
        "labels_battery_low": sum(1 for l in labels if l.battery_mv is not None and l.battery_mv < BATTERY_LOW_MV),
        "labels_out_of_sync": sum(1 for l in labels if l.expected_crc is not None and l.expected_crc != l.displayed_crc),
        "jobs": {s: job_counts.get(s, 0) for s in (JobStatus.PENDING, JobStatus.SENT, JobStatus.DONE, JobStatus.FAILED)},
        "basestations": [
            {
                "id": bs.id,
                "online": bool(bs.last_seen and bs.last_seen >= now - BASESTATION_OFFLINE_AFTER),
                "last_seen": bs.last_seen,
                "software_version": bs.software_version,
                "uptime_s": bs.uptime_s,
                "cpu_temp_c": bs.cpu_temp_c,
            }
            for bs in stations
        ],
        "open_alerts": open_alerts,
    }


def prometheus_metrics(session: Session, now: datetime) -> str:
    lines = [
        "# HELP eink_labels_total Aantal labels per winkel", "# TYPE eink_labels_total gauge",
        "# HELP eink_labels_online Labels gehoord binnen de offline-drempel", "# TYPE eink_labels_online gauge",
        "# HELP eink_labels_battery_low Labels met lage batterij", "# TYPE eink_labels_battery_low gauge",
        "# HELP eink_labels_out_of_sync Labels die (nog) niet het verwachte beeld tonen", "# TYPE eink_labels_out_of_sync gauge",
        "# HELP eink_jobs Update-jobs per status", "# TYPE eink_jobs gauge",
        "# HELP eink_basestation_up 1 als het basisstation recent een heartbeat stuurde", "# TYPE eink_basestation_up gauge",
        "# HELP eink_alerts_open Open alerts", "# TYPE eink_alerts_open gauge",
    ]
    for store in session.scalars(select(Store).order_by(Store.id)):
        o = store_overview(session, store, now)
        s = f'store="{store.id}"'
        lines += [
            f"eink_labels_total{{{s}}} {o['labels_total']}",
            f"eink_labels_online{{{s}}} {o['labels_online']}",
            f"eink_labels_battery_low{{{s}}} {o['labels_battery_low']}",
            f"eink_labels_out_of_sync{{{s}}} {o['labels_out_of_sync']}",
            f"eink_alerts_open{{{s}}} {o['open_alerts']}",
        ]
        lines += [f'eink_jobs{{{s},status="{k}"}} {v}' for k, v in o["jobs"].items()]
        lines += [f'eink_basestation_up{{{s},basestation="{b["id"]}"}} {int(b["online"])}' for b in o["basestations"]]
    return "\n".join(lines) + "\n"
