import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, Float, Integer, String, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

app = FastAPI(title="Clipper API", version="0.1.0")
BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BACKEND_DIR / "uploads"
OUTPUT_DIR = BACKEND_DIR / "outputs"
DATABASE_PATH = BACKEND_DIR / "clipper.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
UPLOAD_CHUNK_SIZE = 1024 * 1024
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
OutputFormat = Literal["original", "vertical_9_16"]
JobStatus = Literal["pending", "processing", "completed", "failed"]
VALID_OUTPUT_FORMATS = {"original", "vertical_9_16"}
VALID_JOB_STATUSES = {"pending", "processing", "completed", "failed"}
VERTICAL_9_16_FILTER = (
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,gblur=sigma=30[bg];"
    "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
    "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
)

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    video_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    clip_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    start_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    output_format: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    download_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        clip_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(clips)"))
        }
        if "job_id" not in clip_columns:
            connection.execute(text("ALTER TABLE clips ADD COLUMN job_id VARCHAR"))
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_clips_job_id ON clips (job_id)")
            )


def get_db_session() -> Session:
    init_database()
    with SessionLocal() as session:
        yield session


def normalize_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def video_to_dict(video: Video) -> dict[str, int | str]:
    return {
        "id": video.id,
        "video_id": video.video_id,
        "original_filename": video.original_filename,
        "stored_filename": video.stored_filename,
        "file_path": video.file_path,
        "created_at": video.created_at.isoformat(),
    }


def clip_to_dict(clip: Clip) -> dict[str, int | float | str | None]:
    return {
        "id": clip.id,
        "clip_id": clip.clip_id,
        "video_id": clip.video_id,
        "job_id": clip.job_id,
        "start_time_seconds": normalize_number(clip.start_time_seconds),
        "duration": normalize_number(clip.duration),
        "output_format": clip.output_format,
        "width": clip.width,
        "height": clip.height,
        "filename": clip.filename,
        "file_path": clip.file_path,
        "download_url": clip.download_url,
        "created_at": clip.created_at.isoformat(),
    }


def save_clip_metadata(
    session: Session, clip_payload: dict[str, str | int | float]
) -> None:
    session.add(
        Clip(
            clip_id=str(clip_payload["clip_id"]),
            video_id=str(clip_payload["video_id"]),
            job_id=(
                str(clip_payload["job_id"]) if clip_payload.get("job_id") is not None else None
            ),
            start_time_seconds=float(clip_payload["start_time_seconds"]),
            duration=float(clip_payload["duration"]),
            output_format=str(clip_payload["output_format"]),
            width=int(clip_payload["width"]),
            height=int(clip_payload["height"]),
            filename=str(clip_payload["filename"]),
            file_path=str(clip_payload["file_path"]),
            download_url=str(clip_payload["download_url"]),
        )
    )


def job_to_dict(job: Job, clips: list[Clip] | None = None) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "video_id": job.video_id,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
        "clips": [clip_to_dict(clip) for clip in clips] if clips else [],
    }


def storage_path_from_database(file_path: str) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return BACKEND_DIR / path


def validated_storage_path(file_path: str, storage_dir: Path) -> Path:
    path = Path(file_path)
    root = storage_dir.resolve()
    if path.is_absolute():
        candidate = path
    elif path.parts and path.parts[0] == storage_dir.name:
        candidate = storage_dir.joinpath(*path.parts[1:])
    else:
        candidate = storage_dir / path

    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("File path is outside the allowed storage directory")
    return resolved


def delete_storage_file(file_path: str, storage_dir: Path) -> bool:
    path = validated_storage_path(file_path, storage_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://[^/]+:3000$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/videos/upload", status_code=status.HTTP_201_CREATED, tags=["videos"])
async def upload_video(
    file: UploadFile = File(...), session: Session = Depends(get_db_session)
) -> dict[str, str]:
    original_filename = file.filename or ""
    if Path(original_filename).suffix.lower() != ".mp4":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only MP4 files are allowed",
        )

    video_id = str(uuid4())
    stored_filename = f"{video_id}.mp4"
    destination = UPLOAD_DIR / stored_filename
    bytes_written = 0

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with destination.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                output.write(chunk)
                bytes_written += len(chunk)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        ) from exc
    finally:
        await file.close()

    if bytes_written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    payload = {
        "video_id": video_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "file_path": str(Path("uploads") / stored_filename),
    }
    try:
        session.add(Video(**payload))
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save video metadata",
        ) from exc

    return payload


@app.get("/videos", tags=["videos"])
def list_videos(session: Session = Depends(get_db_session)) -> list[dict[str, int | str]]:
    videos = session.scalars(select(Video).order_by(Video.created_at.desc())).all()
    return [video_to_dict(video) for video in videos]


@app.get("/videos/{video_id}", tags=["videos"])
def get_video(
    video_id: str, session: Session = Depends(get_db_session)
) -> dict[str, int | str]:
    video = session.scalar(select(Video).where(Video.video_id == video_id))
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    return video_to_dict(video)


@app.get("/videos/{video_id}/clips", tags=["videos"])
def list_video_clips(
    video_id: str, session: Session = Depends(get_db_session)
) -> list[dict[str, int | float | str | None]]:
    clips = session.scalars(
        select(Clip).where(Clip.video_id == video_id).order_by(Clip.created_at.desc())
    ).all()
    return [clip_to_dict(clip) for clip in clips]


@app.delete("/videos/{video_id}", tags=["videos"])
def delete_video(
    video_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    try:
        video = session.scalar(select(Video).where(Video.video_id == video_id))
        if video is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found",
            )
        clips = session.scalars(select(Clip).where(Clip.video_id == video_id)).all()
        jobs = session.scalars(select(Job).where(Job.video_id == video_id)).all()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read video metadata",
        ) from exc

    deleted_files = 0
    missing_files: list[str] = []
    try:
        for clip in clips:
            if delete_storage_file(clip.file_path, OUTPUT_DIR):
                deleted_files += 1
            else:
                missing_files.append(clip.filename)
        if delete_storage_file(video.file_path, UPLOAD_DIR):
            deleted_files += 1
        else:
            missing_files.append(video.stored_filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete video files",
        ) from exc

    try:
        for clip in clips:
            session.delete(clip)
        for job in jobs:
            session.delete(job)
        session.delete(video)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete video metadata",
        ) from exc

    return {
        "status": "success",
        "video_id": video_id,
        "deleted_clips": len(clips),
        "deleted_jobs": len(jobs),
        "deleted_files": deleted_files,
        "files_not_found": len(missing_files),
        "missing_files": missing_files,
    }


class CutVideoRequest(BaseModel):
    start_time: str
    duration: int = Field(gt=0)
    output_format: OutputFormat = "original"

    @field_validator("start_time")
    @classmethod
    def start_time_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("start_time must not be empty")
        return value

    @field_validator("output_format", mode="before")
    @classmethod
    def output_format_must_be_supported(cls, value: str) -> str:
        if value not in VALID_OUTPUT_FORMATS:
            raise ValueError("output_format must be original or vertical_9_16")
        return value


def parse_start_time_seconds(start_time: str) -> int | float:
    parts = start_time.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            total = (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            total = (int(minutes) * 60) + float(seconds)
        else:
            total = float(start_time)
    except ValueError:
        return 0

    return int(total) if total.is_integer() else total


def read_video_metadata(input_path: Path) -> dict[str, int | float]:
    probe_command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(input_path),
    ]

    try:
        probe_result = subprocess.run(
            probe_command,
            capture_output=True,
            text=True,
            check=True,
        )
        metadata = json.loads(probe_result.stdout)
        stream = metadata["streams"][0]
        duration = float(metadata["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except FileNotFoundError:
        raise
    except (
        subprocess.CalledProcessError,
        KeyError,
        IndexError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError("Failed to read video metadata") from exc

    if duration <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("Video metadata is invalid")

    return {"duration": duration, "width": width, "height": height}


def output_dimensions(
    output_format: OutputFormat, source_width: int, source_height: int
) -> tuple[int, int]:
    if output_format == "vertical_9_16":
        return VERTICAL_WIDTH, VERTICAL_HEIGHT
    return source_width, source_height


def build_clip_command(
    input_path: Path,
    output_path: Path,
    start_time: str | int | float,
    duration: int | float,
    output_format: OutputFormat,
) -> list[str]:
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_time),
        "-i",
        str(input_path),
        "-t",
        str(duration),
    ]

    video_map = "0:v:0"
    if output_format == "vertical_9_16":
        command.extend(["-filter_complex", VERTICAL_9_16_FILTER])
        video_map = "[v]"

    command.extend(
        [
            "-map",
            video_map,
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return command


@app.post("/videos/{video_id}/cut", tags=["videos"])
def cut_video(
    video_id: str,
    request: CutVideoRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, str | int | float]:
    input_path = UPLOAD_DIR / f"{video_id}.mp4"
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    clip_id = str(uuid4())
    filename = f"{clip_id}.mp4"
    output_path = OUTPUT_DIR / filename
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        metadata = read_video_metadata(input_path)
        width, height = output_dimensions(
            request.output_format,
            int(metadata["width"]),
            int(metadata["height"]),
        )
        command = build_clip_command(
            input_path,
            output_path,
            request.start_time,
            request.duration,
            request.output_format,
        )
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg failed to cut video",
        ) from exc
    except RuntimeError as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg did not create an output file",
        )

    clip_payload = {
        "clip_id": clip_id,
        "video_id": video_id,
        "start_time": request.start_time,
        "start_time_seconds": parse_start_time_seconds(request.start_time),
        "duration": request.duration,
        "output_format": request.output_format,
        "width": width,
        "height": height,
        "filename": filename,
        "file_path": str(Path("outputs") / filename),
        "download_url": f"/clips/{clip_id}/download",
    }
    try:
        save_clip_metadata(session, clip_payload)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save clip metadata",
        ) from exc

    return clip_payload


@app.get("/clips/{clip_id}/download", tags=["clips"])
def download_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> FileResponse:
    clip = session.scalar(select(Clip).where(Clip.clip_id == clip_id))
    if clip is not None:
        database_clip_path = storage_path_from_database(clip.file_path)
        if database_clip_path.is_file():
            return FileResponse(
                path=database_clip_path,
                media_type="video/mp4",
                filename=database_clip_path.name,
            )

    clip_path = OUTPUT_DIR / f"{clip_id}.mp4"
    if not clip_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )

    return FileResponse(
        path=clip_path,
        media_type="video/mp4",
        filename=clip_path.name,
    )


class AutoSplitRequest(BaseModel):
    clip_duration_seconds: int = Field(default=60, gt=0)
    max_clips: int = Field(gt=0, le=20)
    output_format: OutputFormat = "original"

    @field_validator("output_format", mode="before")
    @classmethod
    def output_format_must_be_supported(cls, value: str) -> str:
        if value not in VALID_OUTPUT_FORMATS:
            raise ValueError("output_format must be original or vertical_9_16")
        return value


def update_job_state(
    session: Session,
    job: Job,
    status_value: JobStatus | None = None,
    progress: int | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> None:
    if status_value is not None:
        job.status = status_value
    if progress is not None:
        job.progress = max(0, min(progress, 100))
    job.error_message = error_message
    job.updated_at = utc_now()
    if completed:
        job.completed_at = utc_now()
    session.commit()


def auto_split_error_message(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "FFmpeg executable was not found"
    if isinstance(exc, subprocess.CalledProcessError):
        return "FFmpeg failed to split video"
    if isinstance(exc, SQLAlchemyError):
        return "Failed to save clip metadata"
    return str(exc)


def build_auto_split_clips(
    video_id: str,
    clip_duration_seconds: int,
    max_clips: int,
    output_format: OutputFormat,
    session: Session | None = None,
    job_id: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, str | int | float]]:
    input_path = UPLOAD_DIR / f"{video_id}.mp4"
    metadata = read_video_metadata(input_path)
    video_duration = float(metadata["duration"])
    width, height = output_dimensions(
        output_format,
        int(metadata["width"]),
        int(metadata["height"]),
    )

    if video_duration <= 0:
        raise RuntimeError("Video duration is invalid")

    clip_count = min(max_clips, math.ceil(video_duration / clip_duration_seconds))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    created_paths: list[Path] = []
    current_path: Path | None = None
    clips: list[dict[str, str | int | float]] = []

    try:
        for index in range(clip_count):
            start_seconds = index * clip_duration_seconds
            duration = min(clip_duration_seconds, video_duration - start_seconds)
            clip_id = str(uuid4())
            filename = f"{clip_id}.mp4"
            output_path = OUTPUT_DIR / filename
            current_path = output_path
            created_paths.append(output_path)
            command = build_clip_command(
                input_path,
                output_path,
                start_seconds,
                duration,
                output_format,
            )

            subprocess.run(command, capture_output=True, text=True, check=True)
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create an output file")

            clip_payload: dict[str, str | int | float] = {
                "clip_id": clip_id,
                "video_id": video_id,
                "start_time_seconds": start_seconds,
                "duration": duration,
                "output_format": output_format,
                "width": width,
                "height": height,
                "filename": filename,
                "file_path": str(Path("outputs") / filename),
                "download_url": f"/clips/{clip_id}/download",
            }
            if job_id is not None:
                clip_payload["job_id"] = job_id

            clips.append(clip_payload)
            if session is not None:
                save_clip_metadata(session, clip_payload)
                session.commit()
            if progress_callback is not None:
                progress_callback(index + 1, clip_count)
            current_path = None
    except SQLAlchemyError:
        if session is not None:
            session.rollback()
        if current_path is not None:
            current_path.unlink(missing_ok=True)
        raise
    except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError):
        if session is None:
            for path in created_paths:
                path.unlink(missing_ok=True)
        elif current_path is not None:
            current_path.unlink(missing_ok=True)
        raise

    return clips


def process_auto_split_job(
    job_id: str,
    video_id: str,
    clip_duration_seconds: int,
    max_clips: int,
    output_format: OutputFormat,
) -> None:
    init_database()
    with SessionLocal() as session:
        job = session.scalar(select(Job).where(Job.job_id == job_id))
        if job is None:
            return

        try:
            update_job_state(session, job, status_value="processing", progress=0)

            def update_progress(done: int, total: int) -> None:
                update_job_state(session, job, progress=round((done / total) * 100))

            build_auto_split_clips(
                video_id,
                clip_duration_seconds,
                max_clips,
                output_format,
                session=session,
                job_id=job_id,
                progress_callback=update_progress,
            )
            update_job_state(session, job, status_value="completed", progress=100, completed=True)
        except Exception as exc:
            session.rollback()
            job = session.scalar(select(Job).where(Job.job_id == job_id))
            if job is None:
                return
            update_job_state(
                session,
                job,
                status_value="failed",
                error_message=auto_split_error_message(exc),
                completed=True,
            )


@app.post("/videos/{video_id}/auto-split-jobs", tags=["videos"])
def create_auto_split_job(
    video_id: str,
    request: AutoSplitRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    input_path = UPLOAD_DIR / f"{video_id}.mp4"
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    job_id = str(uuid4())
    job = Job(job_id=job_id, video_id=video_id, status="pending", progress=0)
    try:
        session.add(job)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save job metadata",
        ) from exc

    background_tasks.add_task(
        process_auto_split_job,
        job_id,
        video_id,
        request.clip_duration_seconds,
        request.max_clips,
        request.output_format,
    )
    return {
        "job_id": job_id,
        "video_id": video_id,
        "status": "pending",
        "status_url": f"/jobs/{job_id}",
    }


@app.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str, session: Session = Depends(get_db_session)) -> dict[str, object]:
    job = session.scalar(select(Job).where(Job.job_id == job_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    clips: list[Clip] = []
    if job.status == "completed":
        clips = session.scalars(
            select(Clip).where(Clip.job_id == job_id).order_by(Clip.created_at.asc())
        ).all()
    return job_to_dict(job, clips)


@app.post("/videos/{video_id}/auto-split", tags=["videos"])
def auto_split_video(
    video_id: str,
    request: AutoSplitRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, str | int | list[dict[str, str | int | float]]]:
    input_path = UPLOAD_DIR / f"{video_id}.mp4"
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    try:
        clips = build_auto_split_clips(
            video_id,
            request.clip_duration_seconds,
            request.max_clips,
            request.output_format,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg failed to split video",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    created_paths = [OUTPUT_DIR / str(clip_payload["filename"]) for clip_payload in clips]
    try:
        for clip_payload in clips:
            save_clip_metadata(session, clip_payload)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save clip metadata",
        ) from exc

    return {
        "video_id": video_id,
        "clip_duration_seconds": request.clip_duration_seconds,
        "max_clips": request.max_clips,
        "output_format": request.output_format,
        "clips": clips,
    }


@app.get("/clips/{clip_id}", tags=["clips"])
def get_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, int | float | str | None]:
    clip = session.scalar(select(Clip).where(Clip.clip_id == clip_id))
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )
    return clip_to_dict(clip)


@app.delete("/clips/{clip_id}", tags=["clips"])
def delete_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, str | bool]:
    try:
        clip = session.scalar(select(Clip).where(Clip.clip_id == clip_id))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read clip metadata",
        ) from exc

    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )

    try:
        file_deleted = delete_storage_file(clip.file_path, OUTPUT_DIR)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete clip file",
        ) from exc

    try:
        session.delete(clip)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete clip metadata",
        ) from exc

    return {
        "status": "success",
        "clip_id": clip_id,
        "file_deleted": file_deleted,
        "file_not_found": not file_deleted,
    }


@app.post("/clips/{clip_id}/vertical", tags=["clips"])
def convert_clip_to_vertical(clip_id: str) -> dict[str, str | int]:
    input_path = OUTPUT_DIR / f"{clip_id}.mp4"
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )

    vertical_clip_id = str(uuid4())
    filename = f"{vertical_clip_id}.mp4"
    output_path = OUTPUT_DIR / filename
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        VERTICAL_9_16_FILTER,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg failed to convert clip",
        ) from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg did not create an output file",
        )

    return {
        "clip_id": vertical_clip_id,
        "source_clip_id": clip_id,
        "aspect_ratio": "9:16",
        "output_format": "vertical_9_16",
        "width": VERTICAL_WIDTH,
        "height": VERTICAL_HEIGHT,
        "filename": filename,
        "file_path": str(Path("outputs") / filename),
        "download_url": f"/clips/{vertical_clip_id}/download",
    }
