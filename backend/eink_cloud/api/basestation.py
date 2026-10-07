"""API voor basisstations: heartbeat, jobs ophalen, resultaten terugmelden."""

import base64

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_basestation
from ..db import get_session
from ..jobs import claim_jobs, record_result
from ..models import BaseStation, Label, UpdateJob, utcnow
from ..schemas import Heartbeat, JobOut, JobResult, LabelTelemetry

router = APIRouter(prefix="/v1/basestation", tags=["basisstation"])


def apply_telemetry(session: Session, bs: BaseStation, t: LabelTelemetry) -> None:
    label = session.get(Label, t.label_id)
    if label is None or label.store_id != bs.store_id:
        return  # onbekend of vreemd label (bv. van de buren) negeren
    label.last_seen = utcnow()
    label.basestation_id = bs.id
    for field in ("rssi", "battery_mv", "temperature_c", "firmware_version", "displayed_crc"):
        value = getattr(t, field)
        if value is not None:
            setattr(label, field, value)


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    bs.last_seen = utcnow()
    bs.software_version = body.software_version
    bs.uptime_s = body.uptime_s
    bs.cpu_temp_c = body.cpu_temp_c
    for t in body.labels_seen:
        apply_telemetry(session, bs, t)
    session.commit()
    return {"ok": True}


@router.get("/jobs", response_model=list[JobOut])
def get_jobs(limit: int = 20, bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    jobs = claim_jobs(session, bs, min(max(limit, 1), 100))
    session.commit()
    return [JobOut(job_id=j.id, label_id=j.label_id, frame_b64=base64.b64encode(j.frame).decode(), crc32=j.crc32) for j in jobs]


@router.post("/jobs/{job_id}/result")
def post_result(job_id: int, body: JobResult, bs: BaseStation = Depends(require_basestation), session: Session = Depends(get_session)):
    job = session.get(UpdateJob, job_id)
    if job is None or job.store_id != bs.store_id:
        raise HTTPException(404, "job onbekend")
    if body.telemetry is not None:
        apply_telemetry(session, bs, body.telemetry)
    record_result(session, job, body.success, body.displayed_crc, body.error)
    session.commit()
    return {"status": job.status}
