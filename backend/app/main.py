import json
import math
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="Clipper API", version="0.1.0")
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
UPLOAD_CHUNK_SIZE = 1024 * 1024
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
OutputFormat = Literal["original", "vertical_9_16"]
VALID_OUTPUT_FORMATS = {"original", "vertical_9_16"}
VERTICAL_9_16_FILTER = (
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,gblur=sigma=30[bg];"
    "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
    "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
)

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
async def upload_video(file: UploadFile = File(...)) -> dict[str, str]:
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

    return {
        "video_id": video_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "file_path": str(Path("uploads") / stored_filename),
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
def cut_video(video_id: str, request: CutVideoRequest) -> dict[str, str | int | float]:
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

    return {
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


@app.get("/clips/{clip_id}/download", tags=["clips"])
def download_clip(clip_id: str) -> FileResponse:
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


@app.post("/videos/{video_id}/auto-split", tags=["videos"])
def auto_split_video(
    video_id: str, request: AutoSplitRequest
) -> dict[str, str | int | list[dict[str, str | int | float]]]:
    input_path = UPLOAD_DIR / f"{video_id}.mp4"
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    try:
        metadata = read_video_metadata(input_path)
        video_duration = float(metadata["duration"])
        width, height = output_dimensions(
            request.output_format,
            int(metadata["width"]),
            int(metadata["height"]),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if video_duration <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video duration is invalid",
        )

    clip_count = min(
        request.max_clips,
        math.ceil(video_duration / request.clip_duration_seconds),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    created_paths: list[Path] = []
    clips: list[dict[str, str | int | float]] = []

    try:
        for index in range(clip_count):
            start_seconds = index * request.clip_duration_seconds
            duration = min(
                request.clip_duration_seconds,
                video_duration - start_seconds,
            )
            clip_id = str(uuid4())
            filename = f"{clip_id}.mp4"
            output_path = OUTPUT_DIR / filename
            created_paths.append(output_path)
            command = build_clip_command(
                input_path,
                output_path,
                start_seconds,
                duration,
                request.output_format,
            )

            subprocess.run(command, capture_output=True, text=True, check=True)
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create an output file")

            clips.append(
                {
                    "clip_id": clip_id,
                    "video_id": video_id,
                    "start_time_seconds": start_seconds,
                    "duration": duration,
                    "output_format": request.output_format,
                    "width": width,
                    "height": height,
                    "filename": filename,
                    "file_path": str(Path("outputs") / filename),
                    "download_url": f"/clips/{clip_id}/download",
                }
            )
    except FileNotFoundError as exc:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except subprocess.CalledProcessError as exc:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg failed to split video",
        ) from exc
    except RuntimeError as exc:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return {
        "video_id": video_id,
        "clip_duration_seconds": request.clip_duration_seconds,
        "max_clips": request.max_clips,
        "output_format": request.output_format,
        "clips": clips,
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
