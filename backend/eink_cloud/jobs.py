"""Van productwijziging naar update-job voor het label."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .displays import DISPLAY_TYPES
from .models import BaseStation, JobStatus, Label, Product, ServiceState, Store, UpdateJob, utcnow
from .render import LabelContent, render_frame

MAX_ATTEMPTS = 3


def content_for(product: Product, store_template: str = "standaard") -> LabelContent:
    return LabelContent(
        was_price_cents=product.was_price_cents,
        description=product.description,
        template=product.template or store_template,
        name=product.name,
        price_cents=product.price_cents,
        unit=product.unit,
        unit_price_cents=product.unit_price_cents,
        unit_price_unit=product.unit_price_unit,
        origin=product.origin,
        promo_text=product.promo_text,
    )


def schedule_label_update(session: Session, label: Label) -> UpdateJob | None:
    """Rendert het label opnieuw en plant een job, tenzij het beeld al klopt."""
    if label.product_sku is None:
        return None
    store = session.get(Store, label.store_id)
    if store is not None and store.service_state == ServiceState.SUSPENDED:
        return None  # dienst uitgeschakeld: label houdt het neutrale beeld
    product = session.scalar(
        select(Product).where(Product.store_id == label.store_id, Product.sku == label.product_sku)
    )
    if product is None:
        return None
    frame, _ = render_frame(content_for(product, store.label_template if store else "standaard"),
                            DISPLAY_TYPES[label.display_type])
    open_jobs = (UpdateJob.label_id == label.id) & UpdateJob.status.in_((JobStatus.PENDING, JobStatus.SENT))
    if frame.crc32 == label.expected_crc and (
        frame.crc32 == label.displayed_crc or session.scalar(select(UpdateJob.id).where(open_jobs))
    ):
        return None  # niets veranderd: geen radioverkeer, spaart batterij
    session.execute(update(UpdateJob).where(open_jobs).values(status=JobStatus.SUPERSEDED, finished_at=utcnow()))
    label.expected_crc = frame.crc32
    job = UpdateJob(store_id=label.store_id, label_id=label.id, frame=frame.encode(), crc32=frame.crc32)
    session.add(job)
    return job


def schedule_product_update(session: Session, product: Product) -> int:
    labels = session.scalars(
        select(Label).where(Label.store_id == product.store_id, Label.product_sku == product.sku)
    ).all()
    return sum(1 for label in labels if schedule_label_update(session, label))


def claim_jobs(session: Session, bs: BaseStation, limit: int) -> list[UpdateJob]:
    query = (
        select(UpdateJob)
        .join(Label, Label.id == UpdateJob.label_id)
        .where(
            UpdateJob.store_id == bs.store_id,
            UpdateJob.status == JobStatus.PENDING,
            # Vast gekoppeld: alleen via dat basisstation. Anders via het laatst gehoorde (of elk).
            (Label.pinned_basestation_id == bs.id)
            | (Label.pinned_basestation_id.is_(None)
               & ((Label.basestation_id.is_(None)) | (Label.basestation_id == bs.id))),
        )
        .order_by(UpdateJob.id)
        .limit(limit)
    )
    store = session.get(Store, bs.store_id)
    if store.service_state == ServiceState.SUSPENDED:
        query = query.where(UpdateJob.kind == "service")  # alleen nog de "buiten dienst"-beelden
    jobs = session.scalars(query).all()
    now = utcnow()
    for job in jobs:
        job.status = JobStatus.SENT
        job.sent_at = now
        job.attempts += 1
    return list(jobs)


def record_result(session: Session, job: UpdateJob, success: bool, displayed_crc: int | None, error: str | None) -> None:
    label = session.get(Label, job.label_id)
    if displayed_crc is not None:
        label.displayed_crc = displayed_crc
    if job.status != JobStatus.SENT:
        return  # al vervangen door een nieuwere job of verlopen
    if success and displayed_crc not in (None, job.crc32):
        success, error = False, f"label toont CRC {displayed_crc:#010x}, verwacht {job.crc32:#010x}"
    if success:
        job.status = JobStatus.DONE
        job.finished_at = utcnow()
        label.displayed_crc = job.crc32
        job.error = None
        return
    job.error = (error or "onbekende fout")[:500]
    retry(job)


def retry(job: UpdateJob) -> None:
    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
    else:
        job.status = JobStatus.PENDING
