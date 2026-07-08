import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from image_video import main as main_module
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.models import Job, MediaAsset, VideoProject
from image_video.infrastructure.providers.deepseek import StoryboardPlan
from image_video.infrastructure.providers.matsca import GeneratedImage, MatscaImageTask
from image_video.main import create_app
from image_video.worker.image_handler import ImageJobHandler
from image_video.worker.runner import WorkerRunner
from image_video.worker.video_handler import (
    VideoFrameHandler,
    VideoFrameRepairHandler,
    VideoKeyframeHandler,
    VideoStitchHandler,
    VideoStoryboardHandler,
)


class FakeStoryboardPlanner:
    def __init__(self):
        self.calls = 0

    def create_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
        self.calls += 1
        return StoryboardPlan(
            global_prompt=f"same scene: {request['description']}",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 12, "description": "end", "prompt": "end"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 12, "motion": "turn head"},
            ],
        )


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), "green").save(output, format="PNG")
    return output.getvalue()


def run_storyboard_worker(app, planner: FakeStoryboardPlanner) -> None:
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={
            "video.storyboard.generate": VideoStoryboardHandler(
                service=app.state.video_project_service,
                planner=planner,
                queue=app.state.job_queue,
            )
        },
        worker_id="storyboard-integration-worker",
    )
    assert runner.run_once()


def run_keyframe_worker(app) -> None:
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={
            "video.keyframes.generate": VideoKeyframeHandler(
                service=app.state.video_project_service,
                generator=app.state.keyframe_generator,
            )
        },
        worker_id="keyframe-integration-worker",
    )
    assert runner.run_once()


def run_frame_worker(app) -> None:
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={
            "video.frames.generate": VideoFrameHandler(
                service=app.state.video_project_service,
                generator=app.state.frame_generator,
            )
        },
        worker_id="frame-integration-worker",
    )
    assert runner.run_once()


def test_web_requests_write_structured_redacted_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_settings_type = main_module.SecretSettings
    monkeypatch.setattr(
        main_module,
        "SecretSettings",
        lambda: secret_settings_type(_env_file=None),
    )

    with TestClient(create_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/health",
            headers={"Authorization": "Bearer private-token", "X-Request-ID": "request-1"},
        )

    assert response.status_code == 200
    log_path = tmp_path / "logs" / "web.jsonl"
    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["event"] == "http_request_completed"
    assert records[-1]["request_id"] == "request-1"
    assert records[-1]["data"]["path"] == "/api/v1/health"
    assert records[-1]["data"]["status_code"] == 200
    assert "private-token" not in log_path.read_text(encoding="utf-8")


def test_storyboard_review_api_queues_persistent_job(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, video_feature_enabled=True)) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={
                "title": "demo",
                "description": "walk",
                "reference_images": [],
            },
        )
        project_id = created.json()["data"]["project_id"]
        version = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions",
            json={
                "source": "user",
                "plan": {
                    "global_prompt": "scene",
                    "character_lock": "hero",
                    "scene_lock": "street",
                    "camera_lock": "wide",
                    "keyframes": [
                        {"frame": 0, "description": "start", "prompt": "start"}
                    ],
                    "segments": [],
                },
                "suggestion": "",
            },
        )
        version_id = version.json()["data"]["version_id"]

        response = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/review",
            json={"version_id": version_id},
        )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["project_id"] == project_id
    assert data["version_id"] == version_id
    assert data["status"] == "queued"
    assert data["job_id"]


def run_frame_repair_worker(app) -> None:
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={
            "video.frame.repair": VideoFrameRepairHandler(
                service=app.state.video_project_service,
                generator=app.state.frame_generator,
            )
        },
        worker_id="frame-repair-integration-worker",
    )
    assert runner.run_once()


def run_stitch_worker(app) -> None:
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={
            "video.stitch": VideoStitchHandler(
                service=app.state.video_project_service,
                runner=app.state.ffmpeg_runner,
            )
        },
        worker_id="stitch-integration-worker",
    )
    assert runner.run_once()


def test_image_job_runs_from_api_through_worker_to_controlled_media(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path)
    output = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(output, format="PNG")

    class FakeProvider:
        def generate(self, **kwargs: object) -> list[GeneratedImage]:
            del kwargs
            return [GeneratedImage(content=output.getvalue())]

        def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
            del kwargs
            return MatscaImageTask(id="task-1", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-1"
            return MatscaImageTask(
                id="task-1",
                status="completed",
                images=[GeneratedImage(content=output.getvalue())],
            )

        def edit(self, **kwargs: object) -> list[GeneratedImage]:
            del kwargs
            return [GeneratedImage(content=output.getvalue())]

    handler = ImageJobHandler(
        queue=app.state.job_queue,
        media=MediaRepository(app.state.job_queue.engine),
        output_root=tmp_path / "media",
        matsca_provider=lambda mode: FakeProvider(),
    )
    runner = WorkerRunner(
        queue=app.state.job_queue,
        handlers={"image.generate": handler},
        worker_id="integration-worker",
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/image-jobs",
            json={"model": "gpt-image-2", "prompt": "blue square"},
        )
        job_id = created.json()["data"]["job_id"]
        assert runner.run_once()
        status = client.get(f"/api/v1/image-jobs/{job_id}")
        media_url = status.json()["data"]["media"][0]["url"]
        media = client.get(media_url)

    assert status.json()["data"]["status"] == "completed"
    assert media.status_code == 200
    assert media.content == output.getvalue()


def test_health_models_and_config_status_are_available_under_v1() -> None:
    with TestClient(create_app()) as client:
        health = client.get("/api/v1/health")
        models = client.get("/api/v1/models")
        status = client.get("/api/v1/config/status")

    assert health.status_code == 200
    assert health.json()["data"]["status"] == "ok"
    assert models.status_code == 200
    assert {item["key"] for item in models.json()["data"]} == {
        "wan2.7-image",
        "wan2.7-image-pro",
        "qwen-image-2.0",
        "qwen-image-2.0-pro",
        "gpt-image-2",
    }
    assert status.status_code == 200
    assert "request_id" in status.json()


def test_root_serves_the_local_frontend(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.get("/")
        script = client.get("/assets/js/app.js")

    assert response.status_code == 200
    assert "图片生成工作台" in response.text
    assert script.status_code == 200
    assert "/api/v1/image-jobs" in script.text


def test_app_starts_without_provider_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    app = create_app(data_root=tmp_path / "data")

    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_settings_endpoint_rejects_secret_fields() -> None:
    with TestClient(create_app()) as client:
        response = client.patch(
            "/api/v1/settings",
            json={"ffmpeg_path": "D:/ffmpeg/ffmpeg.exe", "api_key": "forbidden"},
        )

    assert response.status_code == 422
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "request_id" in response.json()


def test_image_job_api_creates_and_controls_persistent_job(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        created = client.post(
            "/api/v1/image-jobs",
            json={
                "model": "gpt-image-2",
                "prompt": "cat",
                "n": 1,
                "matsca_mode": "direct",
            },
        )
        assert created.status_code == 202
        job_id = created.json()["data"]["job_id"]

        status = client.get(f"/api/v1/image-jobs/{job_id}")
        assert status.json()["data"]["status"] == "queued"

        paused = client.post(f"/api/v1/image-jobs/{job_id}/pause")
        assert paused.json()["data"]["status"] == "paused"

        resumed = client.post(f"/api/v1/image-jobs/{job_id}/resume")
        assert resumed.json()["data"]["status"] == "queued"

        cancelled = client.post(f"/api/v1/image-jobs/{job_id}/cancel")
        assert cancelled.json()["data"]["status"] == "cancelled"


def test_image_job_api_rejects_removed_app_mode(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.post(
            "/api/v1/image-jobs",
            json={
                "model": "gpt-image-2",
                "prompt": "cat",
                "matsca_mode": "app",
            },
        )

    assert response.status_code == 422


def test_unified_job_api_controls_video_jobs(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path)
    with TestClient(app) as client:
        job_id = app.state.job_queue.enqueue(
            "video.storyboard.generate", {"project_id": "archived-project"}
        )
        status = client.get(f"/api/v1/jobs/{job_id}")
        paused = client.post(f"/api/v1/jobs/{job_id}/pause")
        resumed = client.post(f"/api/v1/jobs/{job_id}/resume")
        cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert status.status_code == 200
    assert status.json()["data"]["kind"] == "video.storyboard.generate"
    assert status.json()["data"]["status"] == "queued"
    assert "project_id" not in status.text
    assert paused.json()["data"]["status"] == "paused"
    assert resumed.json()["data"]["status"] == "queued"
    assert cancelled.json()["data"]["status"] == "cancelled"


def test_video_project_api_is_archived_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
            headers={"X-Request-ID": "request-video-archived"},
        )

    assert response.status_code == 410
    payload = response.json()
    assert payload["data"] is None
    assert payload["error"] == {
        "code": "VIDEO_FEATURE_ARCHIVED",
        "message": (
            "视频功能已归档，当前默认不可用；恢复请查看 "
            "archive/video_feature_20260708/restore-notes.md"
        ),
        "details": None,
    }
    assert payload["request_id"] == "request-video-archived"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/video-projects/project-1"),
        ("patch", "/api/v1/video-projects/project-1/draft"),
        ("post", "/api/v1/video-projects/project-1/storyboard/generate"),
        ("post", "/api/v1/video-projects/project-1/storyboard/versions"),
        ("get", "/api/v1/video-projects/project-1/storyboard/versions"),
        ("post", "/api/v1/video-projects/project-1/storyboard/review"),
        ("post", "/api/v1/video-projects/project-1/storyboard/versions/version-1/confirm"),
        ("post", "/api/v1/video-projects/project-1/keyframes/generate"),
        ("get", "/api/v1/video-projects/project-1/keyframes"),
        ("get", "/api/v1/video-projects/project-1/keyframes/0/media"),
        ("get", "/api/v1/video-projects/project-1/output"),
        ("post", "/api/v1/video-projects/project-1/keyframes/0/regenerate"),
        ("post", "/api/v1/video-projects/project-1/keyframes/confirm"),
        ("post", "/api/v1/video-projects/project-1/frames/generate"),
        ("get", "/api/v1/video-projects/project-1/frames/issues"),
        ("post", "/api/v1/video-projects/project-1/frames/1/repair"),
        ("post", "/api/v1/video-projects/project-1/stitch"),
        ("delete", "/api/v1/video-projects/project-1?confirm=true"),
    ],
)
def test_video_project_subpaths_are_archived_not_404(
    tmp_path: Path, method: str, path: str
) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.request(method.upper(), path, json={})

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "VIDEO_FEATURE_ARCHIVED"
    assert response.json()["request_id"]


def test_completed_image_job_status_returns_controlled_media_urls(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path)
    now = datetime.now(UTC)
    media_path = tmp_path / "image.png"
    media_path.write_bytes(b"image")
    with Session(app.state.job_queue.engine) as session:
        session.add(
            Job(
                id="completed-image",
                kind="image.generate",
                payload={"prompt": "cat"},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="media-result",
                job_id="completed-image",
                media_type="image",
                path=media_path.as_posix(),
                thumbnail_path=media_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=5,
                sha256="0" * 64,
                created_at=now,
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/v1/image-jobs/completed-image")

    assert response.status_code == 200
    assert response.json()["data"]["media"] == [
        {"id": "media-result", "url": "/api/v1/media/media-result"}
    ]
    assert response.json()["data"]["result_urls"] == []


def test_image_job_status_returns_persisted_result_urls_before_local_media(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path)
    now = datetime.now(UTC)
    with Session(app.state.job_queue.engine) as session:
        session.add(
            Job(
                id="needs-download",
                kind="image.generate",
                payload={
                    "prompt": "cat",
                    "result_urls": ["https://official.example/image.png"],
                },
                status=JobStatus.NEEDS_ATTENTION,
                error_code="IMAGE_DOWNLOAD_FAILED",
                error_message="图片下载失败：网络请求异常",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/v1/image-jobs/needs-download")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "needs_attention"
    assert data["media"] == []
    assert data["result_urls"] == ["https://official.example/image.png"]
    assert data["error_code"] == "IMAGE_DOWNLOAD_FAILED"


def test_api_maps_missing_invalid_and_conflicting_business_errors(
    tmp_path: Path,
) -> None:
    with TestClient(
        create_app(data_root=tmp_path, video_feature_enabled=True),
        raise_server_exceptions=False,
    ) as client:
        missing = client.get("/api/v1/image-jobs/not-found")
        invalid = client.post(
            "/api/v1/image-jobs",
            json={"model": "unknown", "prompt": "cat"},
        )
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "walk"},
        )
        project_id = created.json()["data"]["project_id"]
        conflict = client.post(
            f"/api/v1/video-projects/{project_id}/keyframes/confirm"
        )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "STATE_CONFLICT"


def test_video_project_api_saves_draft_and_limits_references(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path, video_feature_enabled=True)) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={
                "title": "demo",
                "description": "turn around",
                "reference_images": [
                    {"media_id": f"media-{index}", "label": "角色"} for index in range(8)
                ],
            },
        )
        assert created.status_code == 201
        assert created.json()["data"]["status"] == "draft"

        rejected = client.post(
            "/api/v1/video-projects",
            json={
                "title": "demo",
                "description": "turn around",
                "reference_images": [
                    {"media_id": f"media-{index}", "label": "角色"} for index in range(9)
                ],
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"


def test_video_project_api_autosaves_draft(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path, video_feature_enabled=True)) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={
                "title": "demo",
                "description": "turn around",
                "start_frame": 10,
                "total_frames": 48,
                "fps": 24,
            },
        )
        project_id = created.json()["data"]["project_id"]

        saved = client.patch(
            f"/api/v1/video-projects/{project_id}/draft",
            json={
                "title": "demo updated",
                "description": "walk forward",
                "start_frame": 20,
                "total_frames": 60,
                "fps": 30,
                "reference_images": [
                    {"media_id": "media-1", "label": "角色", "note": "主角"}
                ],
            },
        )
        summary = client.get(f"/api/v1/video-projects/{project_id}")

        assert saved.status_code == 200
        assert saved.json()["data"]["title"] == "demo updated"
        assert saved.json()["data"]["reference_count"] == 1
        assert saved.json()["data"]["start_frame"] == 20
        assert saved.json()["data"]["end_frame"] == 79
        assert saved.json()["data"]["total_frames"] == 60
        assert saved.json()["data"]["fps"] == 30
        assert summary.json()["data"]["start_frame"] == 20
        assert summary.json()["data"]["end_frame"] == 79
        assert summary.json()["data"]["total_frames"] == 60
        assert summary.json()["data"]["fps"] == 30


def test_settings_endpoint_persists_cost_rates(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        saved = client.patch(
            "/api/v1/settings",
            json={
                "ffmpeg_path": "D:/ffmpeg/ffmpeg.exe",
                "native_download_proxy": "http://127.0.0.1:7890",
                "cost_rates": {
                    "image_per_image": 2.5,
                    "video_per_frame": 1.5,
                },
            },
        )
        loaded = client.get("/api/v1/settings")

    assert saved.status_code == 200
    assert saved.json()["data"]["cost_rates"] == {
        "image_per_image": 2.5,
        "video_per_frame": 1.5,
    }
    assert loaded.json()["data"]["cost_rates"] == {
        "image_per_image": 2.5,
        "video_per_frame": 1.5,
    }


def test_video_project_api_generates_edits_and_confirms_storyboard(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path, video_feature_enabled=True)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]

        generated = client.post(f"/api/v1/video-projects/{project_id}/storyboard/generate")
        assert generated.status_code == 202
        assert generated.json()["data"]["status"] == "queued"
        assert generated.json()["data"]["job_id"]
        assert app.state.storyboard_planner.calls == 0
        run_storyboard_worker(app, app.state.storyboard_planner)
        versions = client.get(f"/api/v1/video-projects/{project_id}/storyboard/versions")
        version_id = versions.json()["data"][-1]["version_id"]

        edited = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions",
            json={
                "source": "user",
                "suggestion": "加强镜头稳定性",
                "plan": {
                    "global_prompt": "same scene",
                    "character_lock": "hero",
                    "scene_lock": "street",
                    "camera_lock": "wide",
                    "keyframes": [
                        {"frame": 0, "description": "start", "prompt": "start"},
                        {"frame": 12, "description": "end", "prompt": "end"},
                    ],
                    "segments": [
                        {"start_frame": 0, "end_frame": 12, "motion": "turn head"},
                    ],
                },
            },
        )
        assert edited.status_code == 201
        version_id = edited.json()["data"]["version_id"]
        versions = client.get(f"/api/v1/video-projects/{project_id}/storyboard/versions")
        assert versions.status_code == 200
        assert versions.json()["data"][-1]["version_id"] == version_id
        assert versions.json()["data"][-1]["suggestion"] == "加强镜头稳定性"

        confirmed = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["data"]["status"] == "generating_keyframes"


def test_video_project_api_generates_lists_and_regenerates_keyframes(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path, video_feature_enabled=True)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    keyframe_prompts: list[str] = []
    app.state.keyframe_generator = (
        lambda prompt: keyframe_prompts.append(prompt) or png_bytes()
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        run_storyboard_worker(app, app.state.storyboard_planner)
        versions = client.get(f"/api/v1/video-projects/{project_id}/storyboard/versions")
        version_id = versions.json()["data"][-1]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )

        generated = client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")
        assert generated.status_code == 202
        assert generated.json()["data"]["status"] == "queued"
        assert generated.json()["data"]["job_id"]
        assert keyframe_prompts == []
        run_keyframe_worker(app)
        listed = client.get(f"/api/v1/video-projects/{project_id}/keyframes")
        regenerated = client.post(
            f"/api/v1/video-projects/{project_id}/keyframes/12/regenerate"
        )

    assert listed.status_code == 200
    assert [item["frame"] for item in listed.json()["data"]] == [0, 12]
    assert regenerated.status_code == 202
    assert regenerated.json()["data"]["status"] == "queued"
    assert regenerated.json()["data"]["job_id"]
    assert keyframe_prompts == ["start", "end"]
    assert regenerated.json()["data"]["frame"] == 12


def test_video_project_api_generates_repairs_and_stitches_frames(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path, video_feature_enabled=True)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    app.state.keyframe_generator = lambda prompt: png_bytes()
    frame_calls: list[int] = []
    app.state.frame_generator = (
        lambda **kwargs: frame_calls.append(kwargs["frame"])
        or png_bytes()
    )
    app.state.ffmpeg_runner = lambda command: None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        run_storyboard_worker(app, app.state.storyboard_planner)
        versions = client.get(f"/api/v1/video-projects/{project_id}/storyboard/versions")
        version_id = versions.json()["data"][-1]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")
        run_keyframe_worker(app)

        confirmed = client.post(f"/api/v1/video-projects/{project_id}/keyframes/confirm")
        frames = client.post(f"/api/v1/video-projects/{project_id}/frames/generate")
        assert frames.status_code == 202
        assert frames.json()["data"]["status"] == "queued"
        assert frames.json()["data"]["job_id"]
        assert frame_calls == []
        run_frame_worker(app)
        summary = client.get(f"/api/v1/video-projects/{project_id}")
        frame_issues = client.get(f"/api/v1/video-projects/{project_id}/frames/issues")
        repaired = client.post(f"/api/v1/video-projects/{project_id}/frames/1/repair")
        assert repaired.status_code == 202
        assert repaired.json()["data"]["status"] == "queued"
        assert repaired.json()["data"]["job_id"]
        run_frame_repair_worker(app)
        stitched = client.post(f"/api/v1/video-projects/{project_id}/stitch")
        assert stitched.status_code == 202
        assert stitched.json()["data"]["status"] == "queued"
        assert stitched.json()["data"]["job_id"]
        run_stitch_worker(app)

    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "generating_frames"
    assert summary.status_code == 200
    assert summary.json()["data"]["status"] == "generating_frames"
    assert summary.json()["data"]["keyframe_count"] == 2
    assert summary.json()["data"]["frame_stats"] == {"completed": 11}
    assert summary.json()["data"]["frame_issue_count"] == 0
    assert "path" not in summary.text
    assert frame_issues.status_code == 200
    assert frame_issues.json()["data"] == []


def test_history_api_lists_unified_history(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path, video_feature_enabled=True)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    app.state.keyframe_generator = lambda prompt: png_bytes()
    app.state.frame_generator = lambda **kwargs: png_bytes()

    def write_fake_mp4(command: list[str]) -> None:
        Path(command[-1]).write_bytes(b"mp4")

    app.state.ffmpeg_runner = write_fake_mp4
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        run_storyboard_worker(app, app.state.storyboard_planner)
        versions = client.get(f"/api/v1/video-projects/{project_id}/storyboard/versions")
        version_id = versions.json()["data"][-1]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")
        run_keyframe_worker(app)
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/confirm")
        client.post(f"/api/v1/video-projects/{project_id}/frames/generate")
        run_frame_worker(app)
        client.post(f"/api/v1/video-projects/{project_id}/stitch")
        run_stitch_worker(app)

        history = client.get("/api/v1/history?kind=video")
        item = history.json()["data"][0]
        cover = client.get(item["cover_url"])
        output = client.get(item["media_url"])

    assert history.status_code == 200
    assert item["kind"] == "video"
    assert "path" not in item
    assert item["media_url"].endswith("/output")
    assert item["cover_url"].endswith("/keyframes/0/media")
    assert cover.status_code == 200
    assert cover.content.startswith(b"\x89PNG")
    assert output.status_code == 200
    assert output.content == b"mp4"


def test_video_project_output_delete_and_storage_estimate_api(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path, video_feature_enabled=True)
    now = datetime.now(UTC)
    output_path = tmp_path / "video_projects" / "project-api" / "output" / "video.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"mp4")
    with Session(app.state.job_queue.engine) as session:
        session.add(
            VideoProject(
                id="project-api",
                title="api",
                description="api",
                status="completed",
                settings={"output_video_path": output_path.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with TestClient(app) as client:
        output = client.get("/api/v1/video-projects/project-api/output")
        estimate = client.get("/api/v1/estimates/storage")
        blocked = client.delete("/api/v1/video-projects/project-api")
        deleted = client.delete("/api/v1/video-projects/project-api?confirm=true")
        missing_output = client.get("/api/v1/video-projects/project-api/output")

    assert output.status_code == 200
    assert output.content == b"mp4"
    assert estimate.status_code == 200
    assert estimate.json()["data"]["source"] == "real"
    assert estimate.json()["data"]["video_output_mb_per_project"] == round(3 / 1024 / 1024, 4)
    assert blocked.status_code == 409
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert missing_output.status_code == 404


def test_media_api_serves_only_registered_data_paths(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path)
    safe_path = tmp_path / "safe.png"
    safe_path.write_bytes(b"safe")
    now = datetime.now(UTC)
    with Session(app.state.job_queue.engine) as session:
        session.add(
            Job(
                id="job-media",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="media-safe",
                job_id="job-media",
                media_type="image",
                path=safe_path.as_posix(),
                thumbnail_path=safe_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=4,
                sha256="0" * 64,
                created_at=now,
            )
        )
        session.commit()

    with TestClient(app) as client:
        served = client.get("/api/v1/media/media-safe")
        missing = client.get("/api/v1/media/missing")

    assert served.status_code == 200
    assert served.content == b"safe"
    assert missing.status_code == 404

    with TestClient(app) as client:
        blocked = client.delete("/api/v1/media/media-safe")
        deleted = client.delete("/api/v1/media/media-safe?confirm=true")

    assert blocked.status_code == 409
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"


def test_media_upload_api_persists_controlled_image_asset(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path)
    image_bytes = BytesIO()
    Image.new("RGB", (16, 12), "green").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/v1/media/upload",
            files={"file": ("reference.png", image_bytes.getvalue(), "image/png")},
        )

        assert uploaded.status_code == 201
        payload = uploaded.json()["data"]
        assert payload["media_id"]
        assert payload["url"] == f"/api/v1/media/{payload['media_id']}"
        assert payload["width"] == 16
        assert payload["height"] == 12

        served = client.get(payload["url"])

    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")
