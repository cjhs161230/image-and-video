"""Video project draft application service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from image_video.infrastructure.database.models import (
    VideoFrame,
    VideoKeyframe,
    VideoProject,
    VideoReferenceImage,
    VideoStoryboardVersion,
)
from image_video.infrastructure.providers.deepseek import StoryboardPlan
from image_video.infrastructure.providers.download import download_image
from image_video.infrastructure.providers.matsca import GeneratedImage

ReferenceLabel = Literal["角色", "场景", "风格"]


class VideoReferenceImageInput(BaseModel):
    media_id: str
    label: ReferenceLabel
    note: str = ""


class VideoProjectDraftRequest(BaseModel):
    title: str
    description: str
    reference_images: list[VideoReferenceImageInput] = Field(
        default_factory=list[VideoReferenceImageInput]
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> VideoProjectDraftRequest:
        if len(self.reference_images) > 8:
            raise ValueError("最多 8 张参考图")
        return self


class StoryboardPlanner(Protocol):
    def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan: ...


class KeyframeGenerator(Protocol):
    def __call__(self, prompt: str) -> bytes: ...


class FrameGenerator(Protocol):
    def __call__(
        self,
        *,
        frame: int,
        prompt: str,
        references: list[str],
        previous_frame_path: str | None,
        anchor_frame_paths: list[str],
    ) -> bytes: ...


class ImageDownloader(Protocol):
    def __call__(self, url: str) -> bytes: ...


class FfmpegRunner(Protocol):
    def __call__(self, command: list[str]) -> None: ...


class MatscaKeyframeImageProvider(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        style: str,
        n: int,
        background: str = "auto",
        output_format: str = "png",
    ) -> list[GeneratedImage]: ...


class MatscaKeyframeGenerator:
    def __init__(
        self,
        provider: MatscaKeyframeImageProvider,
        *,
        downloader: ImageDownloader = download_image,
    ):
        self.provider = provider
        self.downloader = downloader

    def __call__(self, prompt: str) -> bytes:
        images = self.provider.generate(
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            style="natural",
            n=1,
            output_format="png",
        )
        image = images[0]
        if image.content is not None:
            return image.content
        if image.url is not None:
            return self.downloader(image.url)
        if image.content is None:
            raise ValueError("关键帧生成未返回 PNG 内容")
        raise RuntimeError("unreachable")


class KeyframeGeneratorFactory(Protocol):
    def __call__(self) -> KeyframeGenerator: ...


class LazyKeyframeGenerator:
    def __init__(self, factory: KeyframeGeneratorFactory):
        self.factory = factory

    def __call__(self, prompt: str) -> bytes:
        return self.factory()(prompt)


class VideoProjectService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create_draft(self, request: VideoProjectDraftRequest) -> str:
        now = datetime.now(UTC)
        project_id = str(uuid4())
        with Session(self.engine) as session:
            session.add(
                VideoProject(
                    id=project_id,
                    title=request.title,
                    description=request.description,
                    status="draft",
                    settings={},
                    created_at=now,
                    updated_at=now,
                )
            )
            for position, reference in enumerate(request.reference_images):
                session.add(
                    VideoReferenceImage(
                        id=str(uuid4()),
                        project_id=project_id,
                        media_id=reference.media_id,
                        label=reference.label,
                        note=reference.note,
                        position=position,
                        created_at=now,
                    )
                )
            session.commit()
        return project_id

    def update_draft(
        self, project_id: str, request: VideoProjectDraftRequest
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            if project.status != "draft":
                raise ValueError("只有草稿状态可自动保存")
            project.title = request.title
            project.description = request.description
            project.updated_at = now
            session.execute(
                delete(VideoReferenceImage).where(
                    VideoReferenceImage.project_id == project_id
                )
            )
            for position, reference in enumerate(request.reference_images):
                session.add(
                    VideoReferenceImage(
                        id=str(uuid4()),
                        project_id=project_id,
                        media_id=reference.media_id,
                        label=reference.label,
                        note=reference.note,
                        position=position,
                        created_at=now,
                    )
                )
            session.commit()
            return {
                "project_id": project_id,
                "status": project.status,
                "title": project.title,
                "reference_count": len(request.reference_images),
            }

    def generate_storyboard(self, project_id: str, planner: StoryboardPlanner) -> str:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            project.status = "planning"
            project.updated_at = datetime.now(UTC)
            storyboard_request: Mapping[str, object] = {
                "title": project.title,
                "description": project.description,
                "references": self._reference_labels(session, project_id),
            }
            session.commit()

        plan = planner.create_storyboard(storyboard_request)
        self._validate_storyboard(plan)
        version_id = self.save_storyboard_version(project_id, source="ai", plan=plan)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            project.status = "awaiting_storyboard_approval"
            project.updated_at = datetime.now(UTC)
            session.commit()
        return version_id

    def save_storyboard_version(
        self,
        project_id: str,
        *,
        source: Literal["ai", "user"],
        plan: StoryboardPlan,
        suggestion: str = "",
    ) -> str:
        self._validate_storyboard(plan)
        now = datetime.now(UTC)
        version_id = str(uuid4())
        with Session(self.engine) as session:
            if session.get(VideoProject, project_id) is None:
                raise KeyError(project_id)
            latest_version = session.scalar(
                select(func.max(VideoStoryboardVersion.version)).where(
                    VideoStoryboardVersion.project_id == project_id
                )
            )
            session.add(
                VideoStoryboardVersion(
                    id=version_id,
                    project_id=project_id,
                    version=(latest_version or 0) + 1,
                    source=source,
                    plan=plan.model_dump(),
                    suggestion=suggestion,
                    created_at=now,
                )
            )
            session.commit()
        return version_id

    def list_storyboard_versions(self, project_id: str) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            if session.get(VideoProject, project_id) is None:
                raise KeyError(project_id)
            versions = session.scalars(
                select(VideoStoryboardVersion)
                .where(VideoStoryboardVersion.project_id == project_id)
                .order_by(VideoStoryboardVersion.version)
            ).all()
            return [
                {
                    "version_id": version.id,
                    "version": version.version,
                    "source": version.source,
                    "suggestion": version.suggestion,
                    "plan": version.plan,
                    "created_at": version.created_at.isoformat(),
                }
                for version in versions
            ]

    def confirm_storyboard(self, project_id: str, version_id: str) -> None:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            version = session.get(VideoStoryboardVersion, version_id)
            if project is None or version is None or version.project_id != project_id:
                raise KeyError(project_id)
            project.status = "generating_keyframes"
            project.settings = {
                **project.settings,
                "approved_storyboard_version_id": version_id,
            }
            project.updated_at = datetime.now(UTC)
            session.commit()

    def generate_keyframes(
        self, project_id: str, generator: KeyframeGenerator
    ) -> list[dict[str, object]]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            if project.status != "generating_keyframes":
                raise ValueError("只有关键帧生成状态可生成关键帧")
            version_id = project.settings.get("approved_storyboard_version_id")
            if not isinstance(version_id, str):
                raise ValueError("缺少已确认分镜版本")
            version = session.get(VideoStoryboardVersion, version_id)
            if version is None or version.project_id != project_id:
                raise KeyError(project_id)

            session.execute(
                delete(VideoKeyframe).where(VideoKeyframe.project_id == project_id)
            )
            output_dir = Path("data") / "video_projects" / project_id / "keyframes"
            output_dir.mkdir(parents=True, exist_ok=True)
            generated: list[dict[str, object]] = []
            for item in version.plan["keyframes"]:
                frame = int(item["frame"])
                prompt = str(item["prompt"])
                path = output_dir / f"keyframe_{frame:06d}.png"
                path.write_bytes(generator(prompt))
                keyframe = VideoKeyframe(
                    id=str(uuid4()),
                    project_id=project_id,
                    storyboard_version_id=version_id,
                    frame=frame,
                    prompt=prompt,
                    description=str(item.get("description", "")),
                    path=path.as_posix(),
                    status="completed",
                    created_at=now,
                    updated_at=now,
                )
                session.add(keyframe)
                generated.append(
                    {
                        "keyframe_id": keyframe.id,
                        "frame": frame,
                        "path": keyframe.path,
                        "status": keyframe.status,
                    }
                )
            project.status = "awaiting_keyframe_approval"
            project.updated_at = now
            session.commit()
            return generated

    def regenerate_keyframe(
        self, project_id: str, *, frame: int, generator: KeyframeGenerator
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            keyframe = session.scalar(
                select(VideoKeyframe).where(
                    VideoKeyframe.project_id == project_id,
                    VideoKeyframe.frame == frame,
                )
            )
            if keyframe is None:
                raise KeyError(project_id)
            version = session.get(VideoStoryboardVersion, keyframe.storyboard_version_id)
            if version is None:
                raise KeyError(project_id)
            Path(keyframe.path).write_bytes(generator(keyframe.prompt))
            keyframe.updated_at = now
            project = session.get(VideoProject, project_id)
            invalidated_segments = self._adjacent_segments(version.plan, frame)
            if project is not None:
                project.settings = {
                    **project.settings,
                    "invalidated_segments": invalidated_segments,
                }
                project.updated_at = now
            result = self._keyframe_preview(keyframe)
            result["invalidated_segments"] = invalidated_segments
            session.commit()
            return result

    def list_keyframes(self, project_id: str) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            if session.get(VideoProject, project_id) is None:
                raise KeyError(project_id)
            keyframes = session.scalars(
                select(VideoKeyframe)
                .where(VideoKeyframe.project_id == project_id)
                .order_by(VideoKeyframe.frame)
            ).all()
            return [self._keyframe_preview(keyframe) for keyframe in keyframes]

    def confirm_keyframes(self, project_id: str) -> None:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            if project.status != "awaiting_keyframe_approval":
                raise ValueError("只有等待关键帧确认状态可继续生成连续帧")
            project.status = "generating_frames"
            project.updated_at = datetime.now(UTC)
            session.commit()

    def generate_intermediate_frames(
        self, project_id: str, *, generator: FrameGenerator
    ) -> list[dict[str, object]]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            if project.status != "generating_frames":
                raise ValueError("只有连续帧生成状态可生成中间帧")
            version_id = project.settings.get("approved_storyboard_version_id")
            if not isinstance(version_id, str):
                raise ValueError("缺少已确认分镜版本")
            version = session.get(VideoStoryboardVersion, version_id)
            if version is None or version.project_id != project_id:
                raise KeyError(project_id)
            keyframes = {
                keyframe.frame: keyframe.path
                for keyframe in session.scalars(
                    select(VideoKeyframe).where(VideoKeyframe.project_id == project_id)
                ).all()
            }
            user_references = [
                reference.media_id
                for reference in session.scalars(
                    select(VideoReferenceImage)
                    .where(VideoReferenceImage.project_id == project_id)
                    .order_by(VideoReferenceImage.position)
                ).all()
            ]
            output_dir = Path("data") / "video_projects" / project_id / "frames"
            output_dir.mkdir(parents=True, exist_ok=True)
            generated: list[dict[str, object]] = []
            segments = self._storyboard_segments(version.plan)
            previous_paths = {
                index: keyframes.get(segment["start_frame"])
                for index, segment in enumerate(segments)
            }
            max_span = max(
                (segment["end_frame"] - segment["start_frame"] for segment in segments),
                default=0,
            )
            for offset in range(1, max_span):
                for index, segment in enumerate(segments):
                    frame = segment["start_frame"] + offset
                    if frame >= segment["end_frame"]:
                        continue
                    anchor_frame_paths = [
                        path
                        for path in [
                            keyframes.get(segment["start_frame"]),
                            keyframes.get(segment["end_frame"]),
                        ]
                        if path is not None
                    ]
                    path = output_dir / f"frame_{frame:06d}.png"
                    path.write_bytes(
                        generator(
                            frame=frame,
                            prompt=segment["prompt"],
                            references=(
                                user_references[:7]
                                if previous_paths[index]
                                == keyframes.get(segment["start_frame"])
                                else user_references[:6]
                            ),
                            previous_frame_path=previous_paths[index],
                            anchor_frame_paths=anchor_frame_paths,
                        )
                    )
                    video_frame = VideoFrame(
                        id=str(uuid4()),
                        project_id=project_id,
                        frame=frame,
                        segment_start_frame=segment["start_frame"],
                        segment_end_frame=segment["end_frame"],
                        prompt=segment["prompt"],
                        path=path.as_posix(),
                        status="completed",
                        error_message="",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(video_frame)
                    previous_paths[index] = video_frame.path
                    generated.append(
                        {
                            "frame_id": video_frame.id,
                            "frame": frame,
                            "path": video_frame.path,
                            "status": video_frame.status,
                        }
                    )
            project.updated_at = now
            session.commit()
            return generated

    def repair_frame(
        self, project_id: str, *, frame: int, generator: FrameGenerator
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            video_frame = session.scalar(
                select(VideoFrame).where(
                    VideoFrame.project_id == project_id,
                    VideoFrame.frame == frame,
                )
            )
            if video_frame is None:
                raise KeyError(project_id)
            previous_frame = session.scalar(
                select(VideoFrame)
                .where(
                    VideoFrame.project_id == project_id,
                    VideoFrame.frame < frame,
                    VideoFrame.status == "completed",
                )
                .order_by(VideoFrame.frame.desc())
            )
            keyframes = {
                keyframe.frame: keyframe.path
                for keyframe in session.scalars(
                    select(VideoKeyframe).where(VideoKeyframe.project_id == project_id)
                ).all()
            }
            references = [
                reference.media_id
                for reference in session.scalars(
                    select(VideoReferenceImage)
                    .where(VideoReferenceImage.project_id == project_id)
                    .order_by(VideoReferenceImage.position)
                ).all()
            ][:6]
            anchor_frame_paths = [
                path
                for path in [
                    keyframes.get(video_frame.segment_start_frame),
                    keyframes.get(video_frame.segment_end_frame),
                ]
                if path is not None
            ]
            try:
                Path(video_frame.path).write_bytes(
                    generator(
                        frame=frame,
                        prompt=video_frame.prompt,
                        references=references,
                        previous_frame_path=(
                            previous_frame.path if previous_frame is not None else None
                        ),
                        anchor_frame_paths=anchor_frame_paths,
                    )
                )
                video_frame.status = "completed"
                video_frame.error_message = ""
            except TimeoutError as exc:
                video_frame.status = "needs_attention"
                video_frame.error_message = str(exc)
            video_frame.updated_at = now
            session.commit()
            return {
                "frame_id": video_frame.id,
                "frame": video_frame.frame,
                "path": video_frame.path,
                "status": video_frame.status,
            }

    def stitch_video(
        self, project_id: str, *, ffmpeg_path: str, runner: FfmpegRunner
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            project.status = "stitching"
            keyframes = session.scalars(
                select(VideoKeyframe)
                .where(VideoKeyframe.project_id == project_id)
                .order_by(VideoKeyframe.frame)
            ).all()
            frames = session.scalars(
                select(VideoFrame)
                .where(VideoFrame.project_id == project_id)
                .order_by(VideoFrame.frame)
            ).all()
            incomplete = [frame for frame in frames if frame.status != "completed"]
            if incomplete:
                raise ValueError("存在未完成或需人工处理的帧")
            all_frames = sorted(
                [(frame.frame, frame.path) for frame in keyframes]
                + [(frame.frame, frame.path) for frame in frames],
                key=lambda item: item[0],
            )
            if not all_frames:
                raise ValueError("没有可合成的帧")
            output_dir = Path("data") / "video_projects" / project_id / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            concat_path = output_dir / "frames.txt"
            concat_path.write_text(
                "".join(f"file '{Path(path).as_posix()}'\n" for _, path in all_frames),
                encoding="utf-8",
            )
            output_path = output_dir / "video.mp4"
            runner(
                [
                    ffmpeg_path,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_path.as_posix(),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    output_path.as_posix(),
                ]
            )
            project.status = "completed"
            project.settings = {
                **project.settings,
                "output_video_path": output_path.as_posix(),
            }
            project.updated_at = now
            session.commit()
            return {
                "project_id": project_id,
                "status": project.status,
                "path": output_path.as_posix(),
            }

    @staticmethod
    def _keyframe_preview(keyframe: VideoKeyframe) -> dict[str, object]:
        return {
            "keyframe_id": keyframe.id,
            "frame": keyframe.frame,
            "path": keyframe.path,
            "status": keyframe.status,
        }

    @staticmethod
    def _adjacent_segments(
        plan: Mapping[str, object], frame: int
    ) -> list[dict[str, int]]:
        segments = plan.get("segments", [])
        if not isinstance(segments, list):
            return []
        adjacent: list[dict[str, int]] = []
        typed_segments = cast(list[dict[str, Any]], segments)
        for segment in typed_segments:
            start_frame = int(segment["start_frame"])
            end_frame = int(segment["end_frame"])
            if start_frame == frame or end_frame == frame:
                adjacent.append(
                    {"start_frame": start_frame, "end_frame": end_frame}
                )
        return adjacent

    @staticmethod
    def _storyboard_segments(plan: Mapping[str, object]) -> list[dict[str, Any]]:
        segments = plan.get("segments", [])
        if not isinstance(segments, list):
            return []
        normalized: list[dict[str, Any]] = []
        for segment in cast(list[dict[str, Any]], segments):
            start_frame = int(segment["start_frame"])
            end_frame = int(segment["end_frame"])
            normalized.append(
                {
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "prompt": str(segment.get("prompt") or segment.get("motion", "")),
                }
            )
        return normalized

    @staticmethod
    def _validate_storyboard(plan: StoryboardPlan) -> None:
        frames = [keyframe.frame for keyframe in plan.keyframes]
        if frames[0] != 0:
            raise ValueError("首个关键帧必须从 0 开始")
        if frames != sorted(set(frames)):
            raise ValueError("关键帧必须按帧号递增且不能重复")
        for segment in plan.segments:
            if segment.end_frame <= segment.start_frame:
                raise ValueError("片段结束帧必须大于开始帧")

    @staticmethod
    def _reference_labels(session: Session, project_id: str) -> list[dict[str, str]]:
        references = session.scalars(
            select(VideoReferenceImage)
            .where(VideoReferenceImage.project_id == project_id)
            .order_by(VideoReferenceImage.position)
        ).all()
        return [
            {"label": reference.label, "note": reference.note}
            for reference in references
        ]
