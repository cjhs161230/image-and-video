"""Local persistent queue worker entry point."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

from image_video.application.video_projects import (
    MatscaFrameGenerator,
    MatscaKeyframeGenerator,
    VideoProjectService,
)
from image_video.infrastructure.config import SecretSettings, SettingsStore
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.dashscope import DashScopeProvider
from image_video.infrastructure.providers.deepseek import DeepSeekPlanner
from image_video.infrastructure.providers.executor import CredentialGate, ProviderRequestExecutor
from image_video.infrastructure.providers.limiter import AdaptiveLimiter
from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
)
from image_video.worker.image_handler import ImageJobHandler
from image_video.worker.runner import WorkerRunner
from image_video.worker.video_handler import (
    VideoFrameHandler,
    VideoFrameRepairHandler,
    VideoKeyframeHandler,
    VideoKeyframeRegenerateHandler,
    VideoStitchHandler,
    VideoStoryboardHandler,
    VideoStoryboardReviewHandler,
)


def build_runner(data_root: Path = Path("data")) -> WorkerRunner:
    engine = create_database_engine(data_root / "db" / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    secrets = SecretSettings()
    public_settings = SettingsStore(data_root / "settings.json").load()
    provider_logger = JsonlLogger(data_root / "logs" / "provider.jsonl")
    matsca_gates = {
        MatscaMode.DIRECT: CredentialGate(
            AdaptiveLimiter(
                max_concurrency=public_settings.matsca_direct_concurrency,
                current_limit=public_settings.matsca_direct_concurrency,
            )
        ),
        MatscaMode.NATIVE: CredentialGate(
            AdaptiveLimiter(
                max_concurrency=public_settings.matsca_native_concurrency,
                current_limit=public_settings.matsca_native_concurrency,
            )
        ),
    }
    matsca_executors = {
        mode: ProviderRequestExecutor(
            gate=gate,
            logger=provider_logger,
            provider=f"matsca.{mode.value}",
        )
        for mode, gate in matsca_gates.items()
    }
    dashscope_executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=1, current_limit=1)),
        logger=provider_logger,
        provider="dashscope",
    )
    deepseek_executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=1, current_limit=1)),
        logger=provider_logger,
        provider="deepseek",
    )

    def matsca_provider(mode_value: str) -> MatscaProvider:
        mode = MatscaMode(mode_value)
        if mode == MatscaMode.NATIVE:
            credentials = MatscaCredentials(
                mode=mode,
                base_url=secrets.matsca_native_base_url,
                api_key=secrets.matsca_native_api_key,
            )
        else:
            credentials = MatscaCredentials(
                mode=mode,
                base_url=secrets.matsca_direct_base_url,
                api_key=secrets.matsca_direct_api_key,
            )
        return MatscaProvider(
            credentials,
            task_gate=matsca_gates[mode],
            request_executor=matsca_executors[mode],
        )

    def keyframe_generator(prompt: str) -> bytes:
        return MatscaKeyframeGenerator(
            MatscaProvider(
                MatscaCredentials(
                    mode=MatscaMode.DIRECT,
                    base_url=secrets.matsca_direct_base_url,
                    api_key=secrets.matsca_direct_api_key,
                ),
                task_gate=matsca_gates[MatscaMode.DIRECT],
                request_executor=matsca_executors[MatscaMode.DIRECT],
            )
        )(prompt)

    def load_references(media_ids: list[str]) -> list[bytes]:
        return [Path(asset.path).read_bytes() for asset in media.by_ids(media_ids)]

    frame_generator = MatscaFrameGenerator(
        MatscaProvider(
            MatscaCredentials(
                mode=MatscaMode.DIRECT,
                base_url=secrets.matsca_direct_base_url,
                api_key=secrets.matsca_direct_api_key,
            ),
            task_gate=matsca_gates[MatscaMode.DIRECT],
            request_executor=matsca_executors[MatscaMode.DIRECT],
        ),
        reference_loader=load_references,
    )

    def run_ffmpeg(command: list[str]) -> None:
        subprocess.run(command, check=True)

    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=data_root / "media",
        matsca_provider=matsca_provider,
        dashscope_provider=lambda: DashScopeProvider(
            api_key=secrets.dashscope_api_key,
            request_executor=dashscope_executor,
        ),
        native_download_proxy=public_settings.native_download_proxy,
    )
    video_service = VideoProjectService(engine, data_root=data_root)
    deepseek_planner = DeepSeekPlanner(
        api_key=secrets.deepseek_api_key,
        base_url=secrets.deepseek_base_url,
        model=secrets.deepseek_model,
        request_executor=deepseek_executor,
    )
    storyboard_handler = VideoStoryboardHandler(
        service=video_service,
        planner=deepseek_planner,
        queue=queue,
    )
    storyboard_review_handler = VideoStoryboardReviewHandler(
        service=video_service,
        reviewer=deepseek_planner,
        queue=queue,
    )
    keyframe_handler = VideoKeyframeHandler(
        service=video_service,
        generator=keyframe_generator,
        queue=queue,
    )
    keyframe_regenerate_handler = VideoKeyframeRegenerateHandler(
        service=video_service,
        generator=keyframe_generator,
        queue=queue,
    )
    frame_handler = VideoFrameHandler(
        service=video_service,
        generator=frame_generator,
        queue=queue,
        ffmpeg_path=public_settings.ffmpeg_path,
    )
    frame_repair_handler = VideoFrameRepairHandler(
        service=video_service,
        generator=frame_generator,
        queue=queue,
    )
    stitch_handler = VideoStitchHandler(
        service=video_service,
        runner=run_ffmpeg,
        queue=queue,
    )
    return WorkerRunner(
        queue=queue,
        handlers={
            "image.generate": handler,
            "video.storyboard.generate": storyboard_handler,
            "video.storyboard.review": storyboard_review_handler,
            "video.keyframes.generate": keyframe_handler,
            "video.keyframe.regenerate": keyframe_regenerate_handler,
            "video.frames.generate": frame_handler,
            "video.frame.repair": frame_repair_handler,
            "video.stitch": stitch_handler,
        },
        worker_id=f"worker-{os.getpid()}-{uuid4().hex[:8]}",
        logger=JsonlLogger(data_root / "logs" / "worker.jsonl"),
    )


def main() -> int:
    runner = build_runner()
    try:
        runner.run_forever()
    except KeyboardInterrupt:
        runner.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
