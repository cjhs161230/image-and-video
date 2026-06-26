"""Video task handlers for the persistent worker."""

from __future__ import annotations

from typing import cast

from image_video.application.video_projects import (
    FfmpegRunner,
    FrameGenerator,
    KeyframeGenerator,
    StoryboardPlanner,
    StoryboardReviewer,
    VideoProjectService,
)
from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue


class VideoStoryboardHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        planner: StoryboardPlanner,
        queue: JobQueue,
    ):
        self.service = service
        self.planner = planner
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        self.service.generate_storyboard(
            project_id,
            self.planner,
            on_upstream_request_sent=lambda: self.queue.mark_upstream_request_sent(
                job.id, worker_id
            ),
            can_persist=lambda: self.queue.is_running_by(job.id, worker_id),
        )


class VideoStoryboardReviewHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        reviewer: StoryboardReviewer,
        queue: JobQueue,
    ):
        self.service = service
        self.reviewer = reviewer
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        version_id = cast(str | None, job.payload.get("version_id"))
        if not project_id or not version_id:
            raise ValueError("缺失视频项目或分镜版本 ID")
        self.service.review_storyboard(
            project_id,
            version_id=version_id,
            reviewer=self.reviewer,
            on_upstream_request_sent=lambda: self.queue.mark_upstream_request_sent(
                job.id, worker_id
            ),
            can_persist=lambda: self.queue.is_running_by(job.id, worker_id),
        )


class VideoKeyframeHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        generator: KeyframeGenerator,
        queue: JobQueue | None = None,
    ):
        self.service = service
        self.generator = generator
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        queue = self.queue
        self.service.generate_keyframes(
            project_id,
            self.generator,
            can_persist=(
                None
                if queue is None
                else lambda: queue.is_running_by(job.id, worker_id)
            ),
            on_upstream_request_sent=(
                None
                if queue is None
                else lambda: queue.mark_upstream_request_sent(job.id, worker_id)
            ),
        )


class VideoKeyframeRegenerateHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        generator: KeyframeGenerator,
        queue: JobQueue | None = None,
    ):
        self.service = service
        self.generator = generator
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        frame = cast(int | None, job.payload.get("frame"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        if frame is None:
            raise ValueError("缺失帧编号")
        queue = self.queue
        self.service.regenerate_keyframe(
            project_id,
            frame=frame,
            generator=self.generator,
            can_persist=(
                None
                if queue is None
                else lambda: queue.is_running_by(job.id, worker_id)
            ),
            on_upstream_request_sent=(
                None
                if queue is None
                else lambda: queue.mark_upstream_request_sent(job.id, worker_id)
            ),
        )


class VideoFrameHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        generator: FrameGenerator,
        queue: JobQueue | None = None,
        ffmpeg_path: str | None = None,
    ):
        self.service = service
        self.generator = generator
        self.queue = queue
        self.ffmpeg_path = ffmpeg_path

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        queue = self.queue
        self.service.generate_intermediate_frames(
            project_id,
            generator=self.generator,
            can_persist=(
                None
                if queue is None
                else lambda: queue.is_running_by(job.id, worker_id)
            ),
            on_upstream_request_sent=(
                None
                if queue is None
                else lambda: queue.mark_upstream_request_sent(job.id, worker_id)
            ),
        )
        if (
            queue is not None
            and self.ffmpeg_path
            and queue.is_running_by(job.id, worker_id)
        ):
            queue.enqueue_unique_active(
                "video.stitch",
                {"project_id": project_id, "ffmpeg_path": self.ffmpeg_path},
                match_keys=("project_id",),
            )


class VideoFrameRepairHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        generator: FrameGenerator,
        queue: JobQueue | None = None,
    ):
        self.service = service
        self.generator = generator
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        frame = cast(int | None, job.payload.get("frame"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        if frame is None:
            raise ValueError("缺失帧编号")
        queue = self.queue
        self.service.repair_frame(
            project_id,
            frame=frame,
            generator=self.generator,
            can_persist=(
                None
                if queue is None
                else lambda: queue.is_running_by(job.id, worker_id)
            ),
            on_upstream_request_sent=(
                None
                if queue is None
                else lambda: queue.mark_upstream_request_sent(job.id, worker_id)
            ),
        )


class VideoStitchHandler:
    def __init__(
        self,
        *,
        service: VideoProjectService,
        runner: FfmpegRunner,
        queue: JobQueue | None = None,
    ):
        self.service = service
        self.runner = runner
        self.queue = queue

    def handle(self, job: Job, *, worker_id: str) -> None:
        project_id = cast(str | None, job.payload.get("project_id"))
        ffmpeg_path = cast(str | None, job.payload.get("ffmpeg_path"))
        if not project_id:
            raise ValueError("缺失视频项目 ID")
        if not ffmpeg_path:
            raise ValueError("缺失 FFmpeg 路径")
        queue = self.queue
        self.service.stitch_video(
            project_id,
            ffmpeg_path=ffmpeg_path,
            runner=self.runner,
            can_persist=(
                None
                if queue is None
                else lambda: queue.is_running_by(job.id, worker_id)
            ),
        )
