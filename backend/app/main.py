import json
import math
import os
import re
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, select, text
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
TranscriptStatus = Literal["pending", "processing", "completed", "failed"]
VALID_OUTPUT_FORMATS = {"original", "vertical_9_16"}
VALID_JOB_STATUSES = {"pending", "processing", "completed", "failed"}
VALID_TRANSCRIPT_STATUSES = {"pending", "processing", "completed", "failed"}
TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "dummy").strip().lower() or "dummy"
AI_HIGHLIGHT_PROVIDER = os.getenv("AI_HIGHLIGHT_PROVIDER", "dummy").strip().lower() or "dummy"
AI_HIGHLIGHT_API_URL = os.getenv("AI_HIGHLIGHT_API_URL", "").strip()
AI_HIGHLIGHT_API_KEY = os.getenv("AI_HIGHLIGHT_API_KEY", "").strip()
AI_HIGHLIGHT_MODEL = os.getenv("AI_HIGHLIGHT_MODEL", "").strip()
QUESTION_KEYWORDS = {"apa", "kenapa", "mengapa", "bagaimana", "gimana", "kapan", "siapa"}
EMOTIONAL_KEYWORDS = {"penting", "wajib", "jangan", "gagal", "rahasia", "mudah", "cepat", "mahal", "murah", "bahaya", "kesalahan", "solusi", "tips"}
MAX_AI_HIGHLIGHT_CANDIDATES = 5
MAX_AI_HIGHLIGHT_TEXT_LENGTH = 400
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
    parent_clip_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    has_subtitle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subtitle_text: Mapped[str | None] = mapped_column(String, nullable=True)
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


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transcript_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    clip_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(String, nullable=True)
    segments_json: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class HighlightCandidate(Base):
    __tablename__ = "highlight_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    highlight_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    transcript_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    clip_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AIHighlightRanking(Base):
    __tablename__ = "ai_highlight_rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ai_ranking_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    highlight_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    clip_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str] = mapped_column(String, nullable=False)
    hashtags_json: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    raw_response_json: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
        if "parent_clip_id" not in clip_columns:
            connection.execute(text("ALTER TABLE clips ADD COLUMN parent_clip_id VARCHAR"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_clips_parent_clip_id "
                    "ON clips (parent_clip_id)"
                )
            )
        if "has_subtitle" not in clip_columns:
            connection.execute(
                text(
                    "ALTER TABLE clips ADD COLUMN has_subtitle BOOLEAN "
                    "NOT NULL DEFAULT 0"
                )
            )
        if "subtitle_text" not in clip_columns:
            connection.execute(text("ALTER TABLE clips ADD COLUMN subtitle_text VARCHAR"))

        transcript_table = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='transcripts'")
        ).fetchone()
        if transcript_table is not None:
            transcript_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(transcripts)"))
            }
            if "updated_at" not in transcript_columns:
                connection.execute(
                    text(
                        "ALTER TABLE transcripts ADD COLUMN updated_at DATETIME "
                        "DEFAULT CURRENT_TIMESTAMP"
                    )
                )

        highlight_table = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='highlight_candidates'")
        ).fetchone()
        if highlight_table is not None:
            highlight_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(highlight_candidates)"))
            }
            if "created_at" not in highlight_columns:
                connection.execute(
                    text(
                        "ALTER TABLE highlight_candidates ADD COLUMN created_at DATETIME "
                        "DEFAULT CURRENT_TIMESTAMP"
                    )
                )

        ai_ranking_table = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_highlight_rankings'")
        ).fetchone()
        if ai_ranking_table is not None:
            ai_ranking_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(ai_highlight_rankings)"))
            }
            if "created_at" not in ai_ranking_columns:
                connection.execute(
                    text(
                        "ALTER TABLE ai_highlight_rankings ADD COLUMN created_at DATETIME "
                        "DEFAULT CURRENT_TIMESTAMP"
                    )
                )


def get_db_session() -> Session:
    init_database()
    with SessionLocal() as session:
        yield session


def normalize_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def format_api_timestamp(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"


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
        "parent_clip_id": clip.parent_clip_id,
        "has_subtitle": clip.has_subtitle,
        "subtitle_text": clip.subtitle_text,
        "created_at": clip.created_at.isoformat(),
    }


def save_clip_metadata(session: Session, clip_payload: dict[str, object]) -> Clip:
    clip = Clip(
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
        parent_clip_id=(
            str(clip_payload["parent_clip_id"])
            if clip_payload.get("parent_clip_id") is not None
            else None
        ),
        has_subtitle=bool(clip_payload.get("has_subtitle", False)),
        subtitle_text=(
            str(clip_payload["subtitle_text"])
            if clip_payload.get("subtitle_text") is not None
            else None
        ),
    )
    session.add(clip)
    return clip


def job_to_dict(job: Job, clips: list[Clip] | None = None) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "video_id": job.video_id,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
        "clips": [clip_to_dict(clip) for clip in clips] if clips else [],
    }


def deserialize_segments(segments_json: str | None) -> list[dict[str, object]]:
    if not segments_json:
        return []
    try:
        payload = json.loads(segments_json)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def transcript_to_dict(transcript: Transcript) -> dict[str, object]:
    return {
        "id": transcript.id,
        "transcript_id": transcript.transcript_id,
        "clip_id": transcript.clip_id,
        "transcript_text": transcript.transcript_text,
        "segments_json": deserialize_segments(transcript.segments_json),
        "provider": transcript.provider,
        "status": transcript.status,
        "error_message": transcript.error_message,
        "created_at": transcript.created_at.isoformat(),
        "updated_at": transcript.updated_at.isoformat(),
    }


def highlight_to_dict(highlight: HighlightCandidate) -> dict[str, object]:
    return {
        "highlight_id": highlight.highlight_id,
        "start_time": format_api_timestamp(highlight.start_time),
        "end_time": format_api_timestamp(highlight.end_time),
        "duration": normalize_number(highlight.duration),
        "text": highlight.text,
        "score": highlight.score,
        "reason": highlight.reason,
    }


def deserialize_hashtags(hashtags_json: str | None) -> list[str]:
    if not hashtags_json:
        return []
    try:
        payload = json.loads(hashtags_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item).strip()]


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


class TranscriptionProviderResult(BaseModel):
    transcript_text: str
    segments: list[dict[str, object]]


class TranscriptionProvider(Protocol):
    provider_name: str

    def transcribe(self, audio_path: Path, clip: Clip) -> TranscriptionProviderResult:
        ...


class DummyTranscriptionProvider:
    provider_name = "dummy"

    def transcribe(self, audio_path: Path, clip: Clip) -> TranscriptionProviderResult:
        transcript_text = "Ini adalah transcript dummy untuk clip ini."
        return TranscriptionProviderResult(
            transcript_text=transcript_text,
            segments=[
                {
                    "id": 1,
                    "start": 0,
                    "end": round(float(clip.duration), 3),
                    "text": transcript_text,
                }
            ],
        )


class LocalWhisperProvider:
    provider_name = "local_whisper"

    def transcribe(self, audio_path: Path, clip: Clip) -> TranscriptionProviderResult:
        raise RuntimeError("Local whisper provider is not configured")


class APITranscriptionProvider:
    provider_name = "api"

    def transcribe(self, audio_path: Path, clip: Clip) -> TranscriptionProviderResult:
        raise RuntimeError("API transcription provider is not configured")


def get_transcription_provider() -> TranscriptionProvider:
    if TRANSCRIPTION_PROVIDER == "dummy":
        return DummyTranscriptionProvider()
    if TRANSCRIPTION_PROVIDER == "local_whisper":
        return LocalWhisperProvider()
    if TRANSCRIPTION_PROVIDER == "api":
        return APITranscriptionProvider()
    raise RuntimeError(f"Unsupported transcription provider: {TRANSCRIPTION_PROVIDER}")


class AIHighlightRankingItem(BaseModel):
    highlight_id: str
    score: int = Field(ge=0, le=100)
    title: str
    reason: str
    caption: str
    hashtags: list[str] = Field(default_factory=list)

    @field_validator("title", "reason")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @field_validator("caption")
    @classmethod
    def caption_must_be_string(cls, value: str) -> str:
        return value.strip()

    @field_validator("hashtags", mode="before")
    @classmethod
    def hashtags_must_be_array(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("hashtags must be an array")
        return value


class AIHighlightRankerResult(BaseModel):
    rankings: list[AIHighlightRankingItem]
    raw_response: object


class AIHighlightRanker(Protocol):
    provider_name: str

    def rank_highlights(
        self, clip: Clip, candidates: list[HighlightCandidate]
    ) -> AIHighlightRankerResult:
        ...


def truncate_candidate_text(text_value: str) -> str:
    normalized = re.sub(r"\s+", " ", text_value).strip()
    return normalized[:MAX_AI_HIGHLIGHT_TEXT_LENGTH]


def build_ai_highlight_prompt(candidates: list[HighlightCandidate]) -> str:
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.append(
            json.dumps(
                {
                    "highlight_id": candidate.highlight_id,
                    "start_time": format_api_timestamp(candidate.start_time),
                    "end_time": format_api_timestamp(candidate.end_time),
                    "text": truncate_candidate_text(candidate.text),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(
        [
            "Rank the following highlight candidates for short-form video potential.",
            "Return only valid JSON.",
            "Score must be an integer between 0 and 100.",
            "Use this exact JSON array shape:",
            "[",
            '  {"highlight_id":"...","score":85,"title":"...","reason":"...","caption":"...","hashtags":["...","..."]}',
            "]",
            "Candidates:",
            *candidate_lines,
        ]
    )


def parse_external_ranking_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rankings", "highlights", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, list):
                    return parsed
        for key in ("output_text", "content", "text"):
            value = payload.get(key)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, list):
                    return parsed
    raise RuntimeError("External AI provider returned unsupported JSON payload")


def validate_ai_ranking_items(
    ranking_items: list[object],
    candidates: list[HighlightCandidate],
) -> list[AIHighlightRankingItem]:
    candidate_map = {candidate.highlight_id: candidate for candidate in candidates}
    validated: list[AIHighlightRankingItem] = []
    for raw_item in ranking_items[:MAX_AI_HIGHLIGHT_CANDIDATES]:
        item = AIHighlightRankingItem.model_validate(raw_item)
        if item.highlight_id not in candidate_map:
            raise RuntimeError(f"Unknown highlight_id returned by AI: {item.highlight_id}")
        validated.append(item)
    if not validated:
        raise RuntimeError("AI provider returned no valid highlight rankings")
    validated.sort(
        key=lambda item: (
            -item.score,
            candidates.index(candidate_map[item.highlight_id]),
        )
    )
    return validated


class DummyAIHighlightRanker:
    provider_name = "dummy"

    def rank_highlights(
        self, clip: Clip, candidates: list[HighlightCandidate]
    ) -> AIHighlightRankerResult:
        rankings: list[AIHighlightRankingItem] = []
        for index, candidate in enumerate(candidates[:MAX_AI_HIGHLIGHT_CANDIDATES], start=1):
            score = max(0, min(100, candidate.score + 5 - index))
            short_text = truncate_candidate_text(candidate.text)
            rankings.append(
                AIHighlightRankingItem(
                    highlight_id=candidate.highlight_id,
                    score=score,
                    title=f"Highlight #{index}: {short_text[:40] or 'Clip moment'}",
                    reason=(
                        f"Dummy ranking memilih kandidat ini karena rule score {candidate.score} "
                        f"dan durasi {normalize_number(candidate.duration)} detik."
                    ),
                    caption=f"{short_text} #{index}",
                    hashtags=["highlight", "clipper", f"clip{index}"],
                )
            )
        rankings.sort(key=lambda item: -item.score)
        return AIHighlightRankerResult(
            rankings=rankings,
            raw_response=[item.model_dump() for item in rankings],
        )


class ExternalAIHighlightRanker:
    provider_name = "external"

    def rank_highlights(
        self, clip: Clip, candidates: list[HighlightCandidate]
    ) -> AIHighlightRankerResult:
        if not AI_HIGHLIGHT_API_URL:
            raise RuntimeError("AI_HIGHLIGHT_API_URL is not configured")
        if not AI_HIGHLIGHT_API_KEY:
            raise RuntimeError("AI_HIGHLIGHT_API_KEY is not configured")

        payload = {
            "model": AI_HIGHLIGHT_MODEL or "generic-highlight-ranker",
            "prompt": build_ai_highlight_prompt(candidates),
        }
        request = urllib_request.Request(
            AI_HIGHLIGHT_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {AI_HIGHLIGHT_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"External AI provider returned HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"External AI provider request failed: {exc.reason}") from exc

        try:
            payload_json = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("External AI provider returned invalid JSON") from exc

        ranking_items = parse_external_ranking_payload(payload_json)
        return AIHighlightRankerResult(
            rankings=validate_ai_ranking_items(ranking_items, candidates),
            raw_response=payload_json,
        )


def get_ai_highlight_ranker() -> AIHighlightRanker:
    if AI_HIGHLIGHT_PROVIDER == "dummy":
        return DummyAIHighlightRanker()
    if AI_HIGHLIGHT_PROVIDER == "external":
        return ExternalAIHighlightRanker()
    raise RuntimeError(f"Unsupported AI highlight provider: {AI_HIGHLIGHT_PROVIDER}")


def extract_clip_audio(input_path: Path, audio_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)
    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not create an audio file")


def update_transcript_state(
    session: Session,
    transcript: Transcript,
    status_value: TranscriptStatus | None = None,
    transcript_text: str | None = None,
    segments_json: str | None = None,
    error_message: str | None = None,
) -> None:
    if status_value is not None:
        transcript.status = status_value
    if transcript_text is not None:
        transcript.transcript_text = transcript_text
    if segments_json is not None:
        transcript.segments_json = segments_json
    transcript.error_message = error_message
    transcript.updated_at = utc_now()
    session.commit()


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


class TranscriptResponse(BaseModel):
    id: int
    transcript_id: str
    clip_id: str
    transcript_text: str | None
    segments_json: list[dict[str, object]]
    provider: str
    status: str
    error_message: str | None
    created_at: str
    updated_at: str


class HighlightResponse(BaseModel):
    highlight_id: str
    start_time: str
    end_time: str
    duration: int | float
    text: str
    score: int
    reason: str


class HighlightListResponse(BaseModel):
    clip_id: str
    transcript_id: str
    highlights: list[HighlightResponse]


class AIHighlightResponse(BaseModel):
    ai_ranking_id: str
    highlight_id: str
    clip_id: str
    video_id: str
    score: int
    title: str
    reason: str
    caption: str
    hashtags: list[str]
    provider: str
    raw_response_json: object
    created_at: str
    start_time: str | None = None
    end_time: str | None = None


class AIHighlightListResponse(BaseModel):
    clip_id: str
    ai_highlights: list[AIHighlightResponse]


def get_clip_or_404(session: Session, clip_id: str) -> Clip:
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
    return clip


def get_latest_transcript(session: Session, clip_id: str) -> Transcript | None:
    return session.scalar(
        select(Transcript)
        .where(Transcript.clip_id == clip_id)
        .order_by(Transcript.created_at.desc(), Transcript.id.desc())
    )


def transcribe_error_message(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "FFmpeg executable was not found"
    if isinstance(exc, subprocess.CalledProcessError):
        return "FFmpeg failed to extract clip audio"
    return str(exc)


def parse_segment_time(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return max(0.0, parsed)


def normalize_highlight_segments(transcript: Transcript, clip: Clip) -> list[dict[str, object]]:
    raw_segments = deserialize_segments(transcript.segments_json)
    normalized: list[dict[str, object]] = []
    for segment in raw_segments:
        start_time = parse_segment_time(segment.get("start"), 0.0)
        end_time = parse_segment_time(segment.get("end"), start_time)
        text_value = str(segment.get("text") or transcript.transcript_text or "").strip()
        if end_time <= start_time:
            continue
        if not text_value:
            continue
        normalized.append({
            "start": start_time,
            "end": min(end_time, float(clip.duration)),
            "text": text_value,
        })

    if normalized:
        return normalized

    fallback_end = min(float(clip.duration), 60.0) if clip.duration > 0 else 0.0
    fallback_text = (transcript.transcript_text or "Transcript segment is unavailable").strip()
    if fallback_end <= 0:
        fallback_end = 1.0
    return [{"start": 0.0, "end": fallback_end, "text": fallback_text}]


def build_highlight_reason(duration: float, text_value: str, single_long_fallback: bool) -> tuple[int, str]:
    score = 50
    reasons: list[str] = []
    lowered_text = text_value.casefold()
    tokens = set(re.findall(r"[0-9A-Za-z_]+", lowered_text))

    if 20 <= duration <= 60:
        score += 25
        reasons.append("ideal duration")
    elif duration < 10:
        score -= 20
        reasons.append("too short")
    elif duration > 90:
        score -= 25
        reasons.append("too long")

    if tokens & QUESTION_KEYWORDS:
        score += 15
        reasons.append("contains question keyword")
    if re.search(r"\d", text_value):
        score += 10
        reasons.append("contains number")
    if tokens & EMOTIONAL_KEYWORDS:
        score += 15
        reasons.append("contains emotional keyword")
    if single_long_fallback:
        reasons.append("single segment fallback")

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("base segment score")
    return score, " and ".join(reason.capitalize() for reason in reasons)


def detect_highlight_candidates(transcript: Transcript, clip: Clip) -> list[dict[str, object]]:
    segments = normalize_highlight_segments(transcript, clip)
    candidates: list[dict[str, object]] = []
    single_segment = len(segments) == 1

    for segment in segments:
        start_time = float(segment["start"])
        end_time = float(segment["end"])
        single_long_fallback = False
        if single_segment and (end_time - start_time) > 60:
            end_time = min(start_time + 60.0, float(clip.duration))
            single_long_fallback = True
        duration = max(1.0, end_time - start_time)
        score, reason = build_highlight_reason(duration, str(segment["text"]), single_long_fallback)
        candidates.append({
            "highlight_id": str(uuid4()),
            "transcript_id": transcript.transcript_id,
            "clip_id": clip.clip_id,
            "video_id": clip.video_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "text": str(segment["text"]),
            "score": score,
            "reason": reason,
        })

    candidates.sort(key=lambda item: (-int(item["score"]), float(item["start_time"])))
    return candidates


def save_highlight_candidates(
    session: Session,
    clip: Clip,
    transcript: Transcript,
    candidates: list[dict[str, object]],
) -> list[HighlightCandidate]:
    session.query(HighlightCandidate).filter(HighlightCandidate.clip_id == clip.clip_id).delete()
    stored: list[HighlightCandidate] = []
    for candidate in candidates:
        highlight = HighlightCandidate(
            highlight_id=str(candidate["highlight_id"]),
            transcript_id=transcript.transcript_id,
            clip_id=clip.clip_id,
            video_id=clip.video_id,
            start_time=float(candidate["start_time"]),
            end_time=float(candidate["end_time"]),
            duration=float(candidate["duration"]),
            text=str(candidate["text"]),
            score=int(candidate["score"]),
            reason=str(candidate["reason"]),
        )
        session.add(highlight)
        stored.append(highlight)
    session.commit()
    for highlight in stored:
        session.refresh(highlight)
    stored.sort(key=lambda item: (-item.score, item.start_time))
    return stored


def get_clip_highlights(session: Session, clip_id: str) -> list[HighlightCandidate]:
    return session.scalars(
        select(HighlightCandidate)
        .where(HighlightCandidate.clip_id == clip_id)
        .order_by(HighlightCandidate.score.desc(), HighlightCandidate.start_time.asc())
    ).all()


def get_top_highlight_candidates(session: Session, clip_id: str) -> list[HighlightCandidate]:
    return session.scalars(
        select(HighlightCandidate)
        .where(HighlightCandidate.clip_id == clip_id)
        .order_by(HighlightCandidate.score.desc(), HighlightCandidate.start_time.asc())
        .limit(MAX_AI_HIGHLIGHT_CANDIDATES)
    ).all()


def build_ai_highlight_response(
    ranking: AIHighlightRanking,
    highlight_map: dict[str, HighlightCandidate],
) -> dict[str, object]:
    highlight = highlight_map.get(ranking.highlight_id)
    return {
        "ai_ranking_id": ranking.ai_ranking_id,
        "highlight_id": ranking.highlight_id,
        "clip_id": ranking.clip_id,
        "video_id": ranking.video_id,
        "score": ranking.score,
        "title": ranking.title,
        "reason": ranking.reason,
        "caption": ranking.caption,
        "hashtags": deserialize_hashtags(ranking.hashtags_json),
        "provider": ranking.provider,
        "raw_response_json": json.loads(ranking.raw_response_json),
        "created_at": ranking.created_at.isoformat(),
        "start_time": format_api_timestamp(highlight.start_time) if highlight else None,
        "end_time": format_api_timestamp(highlight.end_time) if highlight else None,
    }


def save_ai_highlight_rankings(
    session: Session,
    clip: Clip,
    rankings: list[AIHighlightRankingItem],
    provider_name: str,
    raw_response: object,
) -> list[AIHighlightRanking]:
    ai_ranking_id = str(uuid4())
    raw_response_json = json.dumps(raw_response, ensure_ascii=False)
    session.query(AIHighlightRanking).filter(AIHighlightRanking.clip_id == clip.clip_id).delete()
    stored: list[AIHighlightRanking] = []
    for ranking in rankings:
        item = AIHighlightRanking(
            ai_ranking_id=ai_ranking_id,
            highlight_id=ranking.highlight_id,
            clip_id=clip.clip_id,
            video_id=clip.video_id,
            score=ranking.score,
            title=ranking.title,
            reason=ranking.reason,
            caption=ranking.caption,
            hashtags_json=json.dumps(ranking.hashtags, ensure_ascii=False),
            provider=provider_name,
            raw_response_json=raw_response_json,
        )
        session.add(item)
        stored.append(item)
    session.commit()
    for item in stored:
        session.refresh(item)
    stored.sort(key=lambda item: (-item.score, item.id))
    return stored


def get_clip_ai_rankings(session: Session, clip_id: str) -> list[AIHighlightRanking]:
    return session.scalars(
        select(AIHighlightRanking)
        .where(AIHighlightRanking.clip_id == clip_id)
        .order_by(AIHighlightRanking.score.desc(), AIHighlightRanking.id.asc())
    ).all()


@app.post("/clips/{clip_id}/transcribe", tags=["clips"], response_model=TranscriptResponse)
def transcribe_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    source_clip = get_clip_or_404(session, clip_id)

    try:
        input_path = validated_storage_path(source_clip.file_path, OUTPUT_DIR)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip file not found",
        ) from exc
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip file not found",
        )

    provider = get_transcription_provider()
    transcript = Transcript(
        transcript_id=str(uuid4()),
        clip_id=source_clip.clip_id,
        provider=provider.provider_name,
        status="pending",
    )
    try:
        session.add(transcript)
        session.commit()
        session.refresh(transcript)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save transcript metadata",
        ) from exc

    audio_dir = OUTPUT_DIR / "audio"
    audio_path = audio_dir / f"{transcript.transcript_id}.wav"

    try:
        audio_dir.mkdir(parents=True, exist_ok=True)
        update_transcript_state(session, transcript, status_value="processing")
        extract_clip_audio(input_path, audio_path)
        result = provider.transcribe(audio_path, source_clip)
        update_transcript_state(
            session,
            transcript,
            status_value="completed",
            transcript_text=result.transcript_text,
            segments_json=json.dumps(result.segments, ensure_ascii=False),
            error_message=None,
        )
    except SQLAlchemyError as exc:
        session.rollback()
        audio_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update transcript metadata",
        ) from exc
    except Exception as exc:
        session.rollback()
        transcript = session.scalar(select(Transcript).where(Transcript.id == transcript.id))
        if transcript is not None:
            update_transcript_state(
                session,
                transcript,
                status_value="failed",
                error_message=transcribe_error_message(exc),
            )
            session.refresh(transcript)
        audio_path.unlink(missing_ok=True)
        if transcript is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=transcribe_error_message(exc),
            ) from exc
        return transcript_to_dict(transcript)

    audio_path.unlink(missing_ok=True)
    session.refresh(transcript)
    return transcript_to_dict(transcript)


@app.get("/clips/{clip_id}/transcript", tags=["clips"], response_model=TranscriptResponse)
def get_clip_transcript(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    get_clip_or_404(session, clip_id)
    transcript = get_latest_transcript(session, clip_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    return transcript_to_dict(transcript)


@app.post("/clips/{clip_id}/detect-highlights", tags=["clips"], response_model=HighlightListResponse)
def detect_clip_highlights(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    clip = get_clip_or_404(session, clip_id)
    transcript = get_latest_transcript(session, clip_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    if transcript.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transcript status must be completed, got {transcript.status}",
        )

    candidates = detect_highlight_candidates(transcript, clip)
    try:
        stored_candidates = save_highlight_candidates(session, clip, transcript, candidates)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save highlight candidates",
        ) from exc

    return {
        "clip_id": clip.clip_id,
        "transcript_id": transcript.transcript_id,
        "highlights": [highlight_to_dict(highlight) for highlight in stored_candidates],
    }


@app.get("/clips/{clip_id}/highlights", tags=["clips"], response_model=HighlightListResponse)
def list_clip_highlights(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    clip = get_clip_or_404(session, clip_id)
    highlights = get_clip_highlights(session, clip_id)
    if not highlights:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Highlight candidates not found",
        )
    return {
        "clip_id": clip.clip_id,
        "transcript_id": highlights[0].transcript_id,
        "highlights": [highlight_to_dict(highlight) for highlight in highlights],
    }


@app.post("/clips/{clip_id}/ai-rank-highlights", tags=["clips"], response_model=AIHighlightListResponse)
def ai_rank_clip_highlights(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    clip = get_clip_or_404(session, clip_id)
    candidates = get_top_highlight_candidates(session, clip_id)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No highlight candidates found. Run detect-highlights first.",
        )

    provider = get_ai_highlight_ranker()
    try:
        result = provider.rank_highlights(clip, candidates)
        provider_name = provider.provider_name
        raw_response = result.raw_response
        rankings = result.rankings
    except Exception as exc:
        if provider.provider_name == "dummy":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"AI highlight ranking failed: {exc}",
            ) from exc
        fallback = DummyAIHighlightRanker()
        fallback_result = fallback.rank_highlights(clip, candidates)
        provider_name = fallback.provider_name
        raw_response = {
            "fallback_from": provider.provider_name,
            "error": str(exc),
            "rankings": [item.model_dump() for item in fallback_result.rankings],
        }
        rankings = fallback_result.rankings

    try:
        stored_rankings = save_ai_highlight_rankings(
            session,
            clip,
            rankings,
            provider_name=provider_name,
            raw_response=raw_response,
        )
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save AI highlight rankings",
        ) from exc

    highlight_map = {candidate.highlight_id: candidate for candidate in candidates}
    return {
        "clip_id": clip.clip_id,
        "ai_highlights": [
            build_ai_highlight_response(ranking, highlight_map)
            for ranking in stored_rankings
        ],
    }


@app.get("/clips/{clip_id}/ai-highlights", tags=["clips"], response_model=AIHighlightListResponse)
def list_clip_ai_highlights(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    get_clip_or_404(session, clip_id)
    rankings = get_clip_ai_rankings(session, clip_id)
    if not rankings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI highlight rankings not found",
        )
    highlight_ids = [ranking.highlight_id for ranking in rankings]
    highlights = session.scalars(
        select(HighlightCandidate).where(HighlightCandidate.highlight_id.in_(highlight_ids))
    ).all()
    highlight_map = {highlight.highlight_id: highlight for highlight in highlights}
    return {
        "clip_id": clip_id,
        "ai_highlights": [
            build_ai_highlight_response(ranking, highlight_map)
            for ranking in rankings
        ],
    }


@app.post("/clips/{clip_id}/auto-subtitle-from-transcript", tags=["clips"])
def auto_subtitle_from_transcript(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, str]:
    get_clip_or_404(session, clip_id)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="TODO: auto subtitle from transcript is not implemented yet",
    )


def parse_subtitle_timestamp(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("time must use HH:MM:SS format")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError as exc:
        raise ValueError("time must use HH:MM:SS format") from exc

    if (
        hours < 0
        or minutes < 0
        or minutes >= 60
        or seconds < 0
        or seconds >= 60
        or not math.isfinite(seconds)
    ):
        raise ValueError("time must use a valid HH:MM:SS value")
    return (hours * 3600) + (minutes * 60) + seconds


def format_srt_timestamp(seconds: float) -> str:
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


class SubtitleRequest(BaseModel):
    subtitle_text: str = Field(max_length=500)
    start_time: str
    end_time: str

    @field_validator("subtitle_text")
    @classmethod
    def subtitle_text_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("subtitle_text must not be empty")
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def subtitle_time_must_be_valid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("subtitle time must not be empty")
        parse_subtitle_timestamp(value)
        return value

    @model_validator(mode="after")
    def end_time_must_follow_start_time(self) -> "SubtitleRequest":
        if parse_subtitle_timestamp(self.end_time) <= parse_subtitle_timestamp(
            self.start_time
        ):
            raise ValueError("end_time must be greater than start_time")
        return self


def ffmpeg_subtitle_filter(subtitle_path: Path) -> str:
    escaped_path = (
        str(subtitle_path)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    return f"subtitles=filename='{escaped_path}'"


@app.post("/clips/{clip_id}/subtitle", tags=["clips"])
def add_clip_subtitle(
    clip_id: str,
    request: SubtitleRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    source_clip = get_clip_or_404(session, clip_id)

    try:
        input_path = validated_storage_path(source_clip.file_path, OUTPUT_DIR)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip file not found",
        ) from exc
    if not input_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip file not found",
        )

    new_clip_id = str(uuid4())
    filename = f"{new_clip_id}_subtitled.mp4"
    output_path = OUTPUT_DIR / filename
    subtitle_dir = OUTPUT_DIR / "subtitles"
    subtitle_path = subtitle_dir / f"{new_clip_id}.srt"
    subtitle_content = (
        "1\n"
        f"{format_srt_timestamp(parse_subtitle_timestamp(request.start_time))} --> "
        f"{format_srt_timestamp(parse_subtitle_timestamp(request.end_time))}\n"
        f"{request.subtitle_text}\n"
    )

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        subtitle_path.write_text(subtitle_content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subtitle file",
        ) from exc

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        ffmpeg_subtitle_filter(subtitle_path),
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        output_path.unlink(missing_ok=True)
        subtitle_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg executable was not found",
        ) from exc
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        subtitle_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg failed to burn subtitle",
        ) from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        subtitle_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FFmpeg did not create a subtitled output file",
        )

    clip_payload: dict[str, object] = {
        "clip_id": new_clip_id,
        "video_id": source_clip.video_id,
        "job_id": source_clip.job_id,
        "start_time_seconds": source_clip.start_time_seconds,
        "duration": source_clip.duration,
        "output_format": source_clip.output_format,
        "width": source_clip.width,
        "height": source_clip.height,
        "filename": filename,
        "file_path": str(Path("outputs") / filename),
        "download_url": f"/clips/{new_clip_id}/download",
        "parent_clip_id": source_clip.clip_id,
        "has_subtitle": True,
        "subtitle_text": request.subtitle_text,
    }
    try:
        new_clip = save_clip_metadata(session, clip_payload)
        session.commit()
        session.refresh(new_clip)
    except SQLAlchemyError as exc:
        session.rollback()
        output_path.unlink(missing_ok=True)
        subtitle_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save subtitled clip metadata",
        ) from exc

    return clip_to_dict(new_clip)


@app.get("/clips/{clip_id}", tags=["clips"])
def get_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, int | float | str | None]:
    return clip_to_dict(get_clip_or_404(session, clip_id))


@app.delete("/clips/{clip_id}", tags=["clips"])
def delete_clip(
    clip_id: str, session: Session = Depends(get_db_session)
) -> dict[str, str | bool]:
    clip = get_clip_or_404(session, clip_id)

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
