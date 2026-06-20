"""FastAPI application factory."""

from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from image_video.api.base import default_settings_store, router
from image_video.api.history import router as history_router
from image_video.api.image_jobs import router as image_jobs_router
from image_video.api.media import router as media_router
from image_video.api.video_projects import router as video_projects_router
from image_video.application.history import HistoryService
from image_video.application.image_jobs import ImageJobService
from image_video.application.video_projects import (
    FrameGenerator,
    LazyKeyframeGenerator,
    MatscaKeyframeGenerator,
    VideoProjectService,
)
from image_video.infrastructure.config import SecretSettings
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.deepseek import DeepSeekPlanner
from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
)


def create_keyframe_generator(secrets: SecretSettings) -> MatscaKeyframeGenerator:
    return MatscaKeyframeGenerator(
        MatscaProvider(
            MatscaCredentials(
                mode=MatscaMode.DIRECT,
                base_url=secrets.matsca_direct_base_url,
                api_key=secrets.matsca_direct_api_key,
            )
        )
    )


def create_frame_generator(keyframe_generator: LazyKeyframeGenerator) -> FrameGenerator:
    def generate_frame(
        *,
        frame: int,
        prompt: str,
        references: list[str],
        previous_frame_path: str | None,
        anchor_frame_paths: list[str],
    ) -> bytes:
        del frame, references, previous_frame_path, anchor_frame_paths
        return keyframe_generator(prompt)

    return generate_frame


def run_ffmpeg(command: list[str]) -> None:
    subprocess.run(command, check=True)


def create_app(data_root: Path | None = None) -> FastAPI:
    root = data_root or Path("data")
    engine = create_database_engine(root / "db" / "workbench.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        del app
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="图像与视频工作台", docs_url="/api/docs", lifespan=lifespan)
    app.state.secrets = SecretSettings()
    app.state.settings_store = default_settings_store(root)
    initialize_database(engine)
    app.state.job_queue = JobQueue(engine)
    app.state.image_job_service = ImageJobService(app.state.job_queue)
    app.state.video_project_service = VideoProjectService(engine)
    app.state.history_service = HistoryService(engine, data_root=root)
    app.state.storyboard_planner = DeepSeekPlanner(
        api_key=app.state.secrets.deepseek_api_key,
        base_url=app.state.secrets.deepseek_base_url,
        model=app.state.secrets.deepseek_model,
    )
    app.state.keyframe_generator = LazyKeyframeGenerator(
        lambda: create_keyframe_generator(app.state.secrets)
    )
    app.state.frame_generator = create_frame_generator(app.state.keyframe_generator)
    app.state.ffmpeg_runner = run_ffmpeg
    app.include_router(router)
    app.include_router(history_router)
    app.include_router(image_jobs_router)
    app.include_router(media_router)
    app.include_router(video_projects_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "data": None,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "请求参数无效",
                        "details": exc.errors(),
                    },
                    "request_id": request_id,
                }
            ),
        )

    return app


app = create_app()
