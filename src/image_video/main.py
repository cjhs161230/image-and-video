"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from image_video.api.base import default_settings_store, router
from image_video.api.image_jobs import router as image_jobs_router
from image_video.api.video_projects import router as video_projects_router
from image_video.application.image_jobs import ImageJobService
from image_video.application.video_projects import VideoProjectService
from image_video.infrastructure.config import SecretSettings
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.deepseek import DeepSeekPlanner


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
    app.state.storyboard_planner = DeepSeekPlanner(
        api_key=app.state.secrets.deepseek_api_key,
        base_url=app.state.secrets.deepseek_base_url,
        model=app.state.secrets.deepseek_model,
    )
    app.include_router(router)
    app.include_router(image_jobs_router)
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
