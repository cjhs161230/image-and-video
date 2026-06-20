from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.models import Job, MediaAsset
from image_video.infrastructure.providers.deepseek import StoryboardPlan
from image_video.main import create_app


class FakeStoryboardPlanner:
    def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan:
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


def test_video_project_api_saves_draft_and_limits_references(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
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
    with TestClient(create_app(data_root=tmp_path)) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]

        saved = client.patch(
            f"/api/v1/video-projects/{project_id}/draft",
            json={
                "title": "demo updated",
                "description": "walk forward",
                "reference_images": [
                    {"media_id": "media-1", "label": "角色", "note": "主角"}
                ],
            },
        )

        assert saved.status_code == 200
        assert saved.json()["data"]["title"] == "demo updated"
        assert saved.json()["data"]["reference_count"] == 1


def test_video_project_api_generates_edits_and_confirms_storyboard(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]

        generated = client.post(f"/api/v1/video-projects/{project_id}/storyboard/generate")
        assert generated.status_code == 202
        assert generated.json()["data"]["status"] == "awaiting_storyboard_approval"

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
    app = create_app(data_root=tmp_path)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    app.state.keyframe_generator = lambda prompt: f"png:{prompt}".encode()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        generated_storyboard = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        version_id = generated_storyboard.json()["data"]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )

        generated = client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")
        listed = client.get(f"/api/v1/video-projects/{project_id}/keyframes")
        regenerated = client.post(
            f"/api/v1/video-projects/{project_id}/keyframes/12/regenerate"
        )

    assert generated.status_code == 202
    assert [item["frame"] for item in generated.json()["data"]["keyframes"]] == [0, 12]
    assert listed.status_code == 200
    assert [item["frame"] for item in listed.json()["data"]] == [0, 12]
    assert regenerated.status_code == 202
    assert regenerated.json()["data"]["frame"] == 12


def test_video_project_api_generates_repairs_and_stitches_frames(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    app.state.keyframe_generator = lambda prompt: f"png:{prompt}".encode()
    app.state.frame_generator = lambda **kwargs: f"frame:{kwargs['frame']}".encode()
    app.state.ffmpeg_runner = lambda command: None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        generated_storyboard = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        version_id = generated_storyboard.json()["data"]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")

        confirmed = client.post(f"/api/v1/video-projects/{project_id}/keyframes/confirm")
        frames = client.post(f"/api/v1/video-projects/{project_id}/frames/generate")
        repaired = client.post(f"/api/v1/video-projects/{project_id}/frames/1/repair")
        stitched = client.post(f"/api/v1/video-projects/{project_id}/stitch")

    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "generating_frames"
    assert frames.status_code == 202
    assert frames.json()["data"]["frames"]
    assert repaired.status_code == 202
    assert repaired.json()["data"]["status"] == "completed"
    assert stitched.status_code == 202
    assert stitched.json()["data"]["status"] == "completed"


def test_history_api_lists_unified_history(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path)
    app.state.storyboard_planner = FakeStoryboardPlanner()
    app.state.keyframe_generator = lambda prompt: f"png:{prompt}".encode()
    app.state.frame_generator = lambda **kwargs: f"frame:{kwargs['frame']}".encode()
    app.state.ffmpeg_runner = lambda command: None
    with TestClient(app) as client:
        image_job = client.post(
            "/api/v1/image-jobs",
            json={"model": "gpt-image-2", "prompt": "cat", "matsca_mode": "direct"},
        )
        assert image_job.status_code == 202
        created = client.post(
            "/api/v1/video-projects",
            json={"title": "demo", "description": "turn around"},
        )
        project_id = created.json()["data"]["project_id"]
        generated_storyboard = client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/generate"
        )
        version_id = generated_storyboard.json()["data"]["version_id"]
        client.post(
            f"/api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm"
        )
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/generate")
        client.post(f"/api/v1/video-projects/{project_id}/keyframes/confirm")
        client.post(f"/api/v1/video-projects/{project_id}/frames/generate")
        client.post(f"/api/v1/video-projects/{project_id}/stitch")

        history = client.get("/api/v1/history?kind=video")

    assert history.status_code == 200
    assert history.json()["data"][0]["kind"] == "video"
    assert history.json()["data"][0]["cover_path"].endswith(".mp4")


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
