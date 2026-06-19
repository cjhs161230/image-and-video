from pathlib import Path

from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.queue import JobQueue


def make_queue(tmp_path: Path) -> JobQueue:
    engine = create_database_engine(tmp_path / "queue.db")
    initialize_database(engine)
    return JobQueue(engine)


def test_claim_is_exclusive_and_sets_lease(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {"prompt": "cat"})

    first = queue.claim_next("worker-a", lease_seconds=30)
    second = queue.claim_next("worker-b", lease_seconds=30)

    assert first is not None
    assert first.id == job_id
    assert first.status == JobStatus.RUNNING
    assert first.locked_by == "worker-a"
    assert first.lease_expires_at is not None
    assert second is None


def test_pause_resume_and_cancel_control_dispatch(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    paused_id = queue.enqueue("video.frames", {})
    cancelled_id = queue.enqueue("video.frames", {})

    queue.pause(paused_id)
    queue.cancel(cancelled_id)

    assert queue.claim_next("worker") is None
    queue.resume(paused_id)
    claimed = queue.claim_next("worker")
    assert claimed is not None
    assert claimed.id == paused_id
    assert queue.get(cancelled_id).status == JobStatus.CANCELLED


def test_recover_expired_jobs_distinguishes_unsent_and_uncertain_requests(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    queue.enqueue("image.generate", {})
    queue.enqueue("image.generate", {})
    first = queue.claim_next("dead-worker", lease_seconds=-1)
    second = queue.claim_next("dead-worker", lease_seconds=-1)
    assert first is not None
    assert second is not None
    unsent_id = first.id
    uncertain_id = second.id
    queue.mark_upstream_request_sent(uncertain_id, "dead-worker")

    recovered = queue.recover_expired()

    assert recovered == {"requeued": 1, "needs_attention": 1}
    assert queue.get(unsent_id).status == JobStatus.QUEUED
    assert queue.get(uncertain_id).status == JobStatus.NEEDS_ATTENTION


def test_heartbeat_extends_current_worker_lease(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    queue.enqueue("image.generate", {})
    claimed = queue.claim_next("worker-a", lease_seconds=5)
    assert claimed is not None
    old_expiry = claimed.lease_expires_at

    assert queue.heartbeat(claimed.id, "worker-a", lease_seconds=60)
    refreshed = queue.get(claimed.id)
    assert refreshed.lease_expires_at is not None
    assert old_expiry is not None
    assert refreshed.lease_expires_at > old_expiry
    assert not queue.heartbeat(claimed.id, "worker-b", lease_seconds=60)
