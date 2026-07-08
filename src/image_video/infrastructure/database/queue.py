"""SQLite-backed persistent job queue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.models import Job, JobEvent


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobQueue:
    def __init__(self, engine: Engine):
        self.engine = engine

    def enqueue(self, kind: str, payload: dict[str, Any]) -> str:
        now = utcnow()
        job_id = str(uuid4())
        job = Job(
            id=job_id,
            kind=kind,
            payload=payload,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as session:
            session.add(job)
            session.add(JobEvent(job_id=job.id, event="queued", data={}, created_at=now))
            session.commit()
        return job_id

    def enqueue_unique_active(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        match_keys: tuple[str, ...],
    ) -> str:
        now = utcnow()
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            active_jobs = session.scalars(
                select(Job).where(
                    Job.kind == kind,
                    Job.status.in_(
                        [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED]
                    ),
                )
            ).all()
            for job in active_jobs:
                if all(job.payload.get(key) == payload.get(key) for key in match_keys):
                    session.commit()
                    return job.id
            job_id = str(uuid4())
            session.add(
                Job(
                    id=job_id,
                    kind=kind,
                    payload=payload,
                    status=JobStatus.QUEUED,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                JobEvent(job_id=job_id, event="queued", data={}, created_at=now)
            )
            session.commit()
            return job_id

    def get(self, job_id: str) -> Job:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            session.expunge(job)
            return job

    def claim_next(
        self,
        worker_id: str,
        lease_seconds: int = 60,
        allowed_kinds: set[str] | None = None,
    ) -> Job | None:
        if allowed_kinds == set():
            return None
        now = utcnow()
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            query = (
                select(Job)
                .where(Job.status == JobStatus.QUEUED)
                .order_by(Job.created_at, Job.id)
                .limit(1)
            )
            if allowed_kinds is not None:
                query = query.where(Job.kind.in_(allowed_kinds))
            job = session.scalar(query)
            if job is None:
                session.commit()
                return None
            job.status = JobStatus.RUNNING
            job.locked_by = worker_id
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.attempt_count += 1
            job.updated_at = now
            session.add(
                JobEvent(
                    job_id=job.id,
                    event="claimed",
                    data={"worker_id": worker_id},
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(job)
            session.expunge(job)
            return job

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        now = utcnow()
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if (
                job is None
                or job.status != JobStatus.RUNNING
                or job.locked_by != worker_id
            ):
                return False
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            session.commit()
            return True

    def mark_upstream_request_sent(self, job_id: str, worker_id: str) -> None:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None or job.locked_by != worker_id:
                raise KeyError(job_id)
            job.upstream_request_sent = True
            job.updated_at = utcnow()
            session.commit()

    def update_payload(self, job_id: str, worker_id: str, updates: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if (
                job is None
                or job.status != JobStatus.RUNNING
                or job.locked_by != worker_id
            ):
                raise KeyError(job_id)
            job.payload = {**job.payload, **updates}
            job.updated_at = utcnow()
            session.commit()

    def is_running_by(self, job_id: str, worker_id: str) -> bool:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            return bool(
                job is not None
                and job.status == JobStatus.RUNNING
                and job.locked_by == worker_id
            )

    def complete(self, job_id: str, worker_id: str) -> None:
        self._finish(job_id, worker_id, JobStatus.COMPLETED)

    def fail(
        self, job_id: str, worker_id: str, *, error_code: str, error_message: str
    ) -> None:
        self._finish(
            job_id,
            worker_id,
            JobStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    def needs_attention(
        self, job_id: str, worker_id: str, *, error_code: str, error_message: str
    ) -> None:
        self._finish(
            job_id,
            worker_id,
            JobStatus.NEEDS_ATTENTION,
            error_code=error_code,
            error_message=error_message,
        )

    def pause(self, job_id: str) -> None:
        self._transition(job_id, JobStatus.PAUSED, {"queued", "running"})

    def resume(self, job_id: str) -> None:
        now = utcnow()
        recoverable_prefixes = (
            "image.",
            "video.keyframes",
            "video.keyframe",
            "video.frames",
            "video.frame",
        )
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status == JobStatus.PAUSED or (
                job.status == JobStatus.NEEDS_ATTENTION
                and job.kind.startswith(recoverable_prefixes)
            ):
                job.status = JobStatus.QUEUED
                job.locked_by = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.updated_at = now
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event=JobStatus.QUEUED.value,
                        data={},
                        created_at=now,
                    )
                )
                session.commit()

    def cancel(self, job_id: str) -> None:
        self._transition(
            job_id,
            JobStatus.CANCELLED,
            {"queued", "running", "paused", "needs_attention"},
        )

    def recover_expired(self) -> dict[str, int]:
        now = utcnow()
        counts = {"requeued": 0, "needs_attention": 0}
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            jobs = session.scalars(
                select(Job).where(
                    Job.status == JobStatus.RUNNING,
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at < now,
                )
            ).all()
            for job in jobs:
                if job.upstream_request_sent:
                    job.status = JobStatus.NEEDS_ATTENTION
                    counts["needs_attention"] += 1
                else:
                    job.status = JobStatus.QUEUED
                    counts["requeued"] += 1
                job.locked_by = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.updated_at = now
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event="lease_recovered",
                        data={"status": job.status.value},
                        created_at=now,
                    )
                )
            session.commit()
        return counts

    def _transition(
        self, job_id: str, target: JobStatus, allowed_sources: set[str]
    ) -> None:
        now = utcnow()
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status.value not in allowed_sources:
                return
            job.status = target
            job.locked_by = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.updated_at = now
            session.add(
                JobEvent(
                    job_id=job.id,
                    event=target.value,
                    data={},
                    created_at=now,
                )
            )
            session.commit()

    def _finish(
        self,
        job_id: str,
        worker_id: str,
        target: JobStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = utcnow()
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if (
                job is None
                or job.status != JobStatus.RUNNING
                or job.locked_by != worker_id
            ):
                raise KeyError(job_id)
            job.status = target
            job.locked_by = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.error_code = error_code
            job.error_message = error_message
            job.updated_at = now
            session.add(
                JobEvent(
                    job_id=job.id,
                    event=target.value,
                    data={"error_code": error_code} if error_code else {},
                    created_at=now,
                )
            )
            session.commit()
