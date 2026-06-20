"""Local persistent queue worker entry point."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from image_video.infrastructure.config import SecretSettings, SettingsStore
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.dashscope import DashScopeProvider
from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
)
from image_video.worker.image_handler import ImageJobHandler
from image_video.worker.runner import WorkerRunner


def build_runner(data_root: Path = Path("data")) -> WorkerRunner:
    engine = create_database_engine(data_root / "db" / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    secrets = SecretSettings()
    public_settings = SettingsStore(data_root / "settings.json").load()

    def matsca_provider(mode_value: str) -> MatscaProvider:
        mode = MatscaMode(mode_value)
        if mode == MatscaMode.APP:
            credentials = MatscaCredentials(
                mode=mode,
                base_url=secrets.matsca_app_base_url,
                api_key=secrets.matsca_app_api_key,
                app_id=secrets.matsca_app_id,
                app_secret=secrets.matsca_app_secret,
            )
        elif mode == MatscaMode.NATIVE:
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
        return MatscaProvider(credentials)

    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=data_root / "media",
        matsca_provider=matsca_provider,
        dashscope_provider=lambda: DashScopeProvider(
            api_key=secrets.dashscope_api_key
        ),
        native_download_proxy=public_settings.native_download_proxy,
    )
    return WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id=f"worker-{os.getpid()}-{uuid4().hex[:8]}",
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
