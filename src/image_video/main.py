"""FastAPI application factory."""

from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from image_video.api.base import default_settings_store, router
from image_video.api.errors import BusinessValidationError
from image_video.api.history import router as history_router
from image_video.api.image_jobs import router as image_jobs_router
from image_video.api.jobs import router as jobs_router
from image_video.api.media import router as media_router
from image_video.api.video_projects import router as video_projects_router
from image_video.application.history import HistoryService
from image_video.application.image_jobs import ImageJobService
from image_video.application.media_uploads import MediaUploadService
from image_video.application.video_projects import (
    FrameGenerator,
    LazyFrameGenerator,
    LazyKeyframeGenerator,
    MatscaFrameGenerator,
    MatscaKeyframeGenerator,
    VideoProjectService,
)
from image_video.infrastructure.config import SecretSettings
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.deepseek import DeepSeekPlanner
from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
)


class StructuredRequestLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, logger: JsonlLogger):
        super().__init__(app)
        self.logger = logger

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = perf_counter()
        response = await call_next(request)
        self.logger.write(
            level="info",
            event="http_request_completed",
            request_id=request_id,
            data={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


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


def create_frame_generator(
    secrets: SecretSettings, media: MediaRepository
) -> FrameGenerator:
    def load_references(media_ids: list[str]) -> list[bytes]:
        return [Path(asset.path).read_bytes() for asset in media.by_ids(media_ids)]

    return LazyFrameGenerator(
        lambda: MatscaFrameGenerator(
            MatscaProvider(
                MatscaCredentials(
                    mode=MatscaMode.DIRECT,
                    base_url=secrets.matsca_direct_base_url,
                    api_key=secrets.matsca_direct_api_key,
                )
            ),
            reference_loader=load_references,
        )
    )


def run_ffmpeg(command: list[str]) -> None:
    subprocess.run(command, check=True)


def create_app(data_root: Path | None = None) -> FastAPI:
    root = data_root or Path("data")
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    engine = create_database_engine(root / "db" / "workbench.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        del app
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="图像与视频工作台", docs_url="/api/docs", lifespan=lifespan)
    app.add_middleware(
        StructuredRequestLogMiddleware,
        logger=JsonlLogger(root / "logs" / "web.jsonl"),
    )
    app.state.secrets = SecretSettings()
    app.state.settings_store = default_settings_store(root)
    initialize_database(engine)
    app.state.job_queue = JobQueue(engine)
    app.state.media_repository = MediaRepository(engine)
    app.state.media_upload_service = MediaUploadService(
        engine, app.state.media_repository, data_root=root
    )
    app.state.image_job_service = ImageJobService(app.state.job_queue)
    app.state.video_project_service = VideoProjectService(engine, data_root=root)
    app.state.history_service = HistoryService(engine, data_root=root)
    app.state.storyboard_planner = DeepSeekPlanner(
        api_key=app.state.secrets.deepseek_api_key,
        base_url=app.state.secrets.deepseek_base_url,
        model=app.state.secrets.deepseek_model,
    )
    app.state.keyframe_generator = LazyKeyframeGenerator(
        lambda: create_keyframe_generator(app.state.secrets)
    )
    app.state.frame_generator = create_frame_generator(
        app.state.secrets, app.state.media_repository
    )
    app.state.ffmpeg_runner = run_ffmpeg
    app.include_router(router)
    app.include_router(history_router)
    app.include_router(image_jobs_router)
    app.include_router(jobs_router)
    app.include_router(media_router)
    app.include_router(video_projects_router)
    app.mount("/assets", StaticFiles(directory=frontend_root), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return FileResponse(frontend_root / "index.html")

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

    def business_error_response(
        request: Request, *, status_code: int, code: str, message: str
    ) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        return JSONResponse(
            status_code=status_code,
            content={
                "data": None,
                "error": {"code": code, "message": message, "details": None},
                "request_id": request_id,
            },
        )

    @app.exception_handler(KeyError)
    async def not_found_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: KeyError
    ) -> JSONResponse:
        del exc
        return business_error_response(
            request, status_code=404, code="NOT_FOUND", message="资源不存在"
        )

    @app.exception_handler(BusinessValidationError)
    async def business_validation_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: BusinessValidationError
    ) -> JSONResponse:
        return business_error_response(
            request,
            status_code=422,
            code="BUSINESS_VALIDATION_ERROR",
            message=str(exc),
        )

    @app.exception_handler(ValueError)
    async def state_conflict_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return business_error_response(
            request,
            status_code=409,
            code="STATE_CONFLICT",
            message=str(exc),
        )

    return app


app = create_app()
