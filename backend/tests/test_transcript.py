import subprocess
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def seed_clip(tmp_path: Path, monkeypatch) -> tuple[Path, main.Clip]:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    source_path = output_dir / "source.mp4"
    source_path.write_bytes(b"source clip")
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)

    main.init_database()
    with main.SessionLocal() as session:
        clip = main.Clip(
            clip_id="source",
            video_id="video",
            job_id="job",
            start_time_seconds=5,
            duration=42,
            output_format="original",
            width=1280,
            height=720,
            filename=source_path.name,
            file_path=str(source_path),
            download_url="/clips/source/download",
        )
        session.add(clip)
        session.commit()
        session.refresh(clip)
        session.expunge(clip)

    return output_dir, clip


def test_transcribe_clip_creates_transcript_and_cleans_audio(tmp_path: Path, monkeypatch) -> None:
    output_dir, source_clip = seed_clip(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        commands.append(command)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        Path(command[-1]).write_bytes(b"audio bytes")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    response = client.post(f"/clips/{source_clip.clip_id}/transcribe")

    assert response.status_code == 200
    payload = response.json()
    UUID(payload["transcript_id"])
    assert payload["clip_id"] == source_clip.clip_id
    assert payload["provider"] == "dummy"
    assert payload["status"] == "completed"
    assert payload["transcript_text"] == "Ini adalah transcript dummy untuk clip ini."
    assert payload["error_message"] is None
    assert payload["segments_json"] == [
        {
            "id": 1,
            "start": 0,
            "end": 42,
            "text": "Ini adalah transcript dummy untuk clip ini.",
        }
    ]
    assert commands[0][:4] == ["ffmpeg", "-y", "-i", str(output_dir / "source.mp4")]
    assert commands[0][-1] == str(output_dir / "audio" / f'{payload["transcript_id"]}.wav')
    assert not (output_dir / "audio" / f'{payload["transcript_id"]}.wav').exists()

    detail_response = client.get(f"/clips/{source_clip.clip_id}/transcript")
    assert detail_response.status_code == 200
    assert detail_response.json() == payload


def test_transcribe_returns_404_for_missing_clip() -> None:
    response = client.post("/clips/missing/transcribe")

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip not found"}


def test_transcribe_returns_404_for_missing_file(tmp_path: Path, monkeypatch) -> None:
    output_dir, source_clip = seed_clip(tmp_path, monkeypatch)
    (output_dir / "source.mp4").unlink()

    response = client.post(f"/clips/{source_clip.clip_id}/transcribe")

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip file not found"}


def test_transcribe_marks_failed_when_ffmpeg_fails(tmp_path: Path, monkeypatch) -> None:
    _, source_clip = seed_clip(tmp_path, monkeypatch)

    def fail_ffmpeg(command, **kwargs) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(main.subprocess, "run", fail_ffmpeg)

    response = client.post(f"/clips/{source_clip.clip_id}/transcribe")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["transcript_text"] is None
    assert payload["segments_json"] == []
    assert payload["error_message"] == "FFmpeg failed to extract clip audio"


def test_get_transcript_returns_latest_completed_record(tmp_path: Path, monkeypatch) -> None:
    _, source_clip = seed_clip(tmp_path, monkeypatch)

    with main.SessionLocal() as session:
        session.add(
            main.Transcript(
                transcript_id="older",
                clip_id=source_clip.clip_id,
                transcript_text="lama",
                segments_json='[{"id":1}]',
                provider="dummy",
                status="completed",
            )
        )
        session.commit()
        session.add(
            main.Transcript(
                transcript_id="newer",
                clip_id=source_clip.clip_id,
                transcript_text="baru",
                segments_json='[{"id":2}]',
                provider="dummy",
                status="completed",
            )
        )
        session.commit()

    response = client.get(f"/clips/{source_clip.clip_id}/transcript")

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript_id"] == "newer"
    assert payload["transcript_text"] == "baru"
    assert payload["segments_json"] == [{"id": 2}]


def test_get_transcript_returns_404_when_missing(tmp_path: Path, monkeypatch) -> None:
    _, source_clip = seed_clip(tmp_path, monkeypatch)

    response = client.get(f"/clips/{source_clip.clip_id}/transcript")

    assert response.status_code == 404
    assert response.json() == {"detail": "Transcript not found"}


def test_auto_subtitle_from_transcript_returns_todo(tmp_path: Path, monkeypatch) -> None:
    _, source_clip = seed_clip(tmp_path, monkeypatch)

    response = client.post(f"/clips/{source_clip.clip_id}/auto-subtitle-from-transcript")

    assert response.status_code == 501
    assert response.json() == {
        "detail": "TODO: auto subtitle from transcript is not implemented yet"
    }


def test_init_database_creates_transcripts_table() -> None:
    main.init_database()

    with main.engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(main.text("PRAGMA table_info(transcripts)"))
        }

    assert {
        "id",
        "transcript_id",
        "clip_id",
        "transcript_text",
        "segments_json",
        "provider",
        "status",
        "error_message",
        "created_at",
        "updated_at",
    } <= columns
