import subprocess
from pathlib import Path
from uuid import UUID

import pytest
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
            duration=60,
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


def subtitle_request() -> dict[str, str]:
    return {
        "subtitle_text": "Teks subtitle",
        "start_time": "00:00:00",
        "end_time": "00:01:00",
    }


def test_add_subtitle_creates_srt_video_and_metadata(tmp_path: Path, monkeypatch) -> None:
    output_dir, source_clip = seed_clip(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        commands.append(command)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        Path(command[-1]).write_bytes(b"subtitled clip")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    response = client.post("/clips/source/subtitle", json=subtitle_request())

    assert response.status_code == 200
    payload = response.json()
    UUID(payload["clip_id"])
    assert payload["clip_id"] != source_clip.clip_id
    assert payload["video_id"] == source_clip.video_id
    assert payload["job_id"] == source_clip.job_id
    assert payload["start_time_seconds"] == source_clip.start_time_seconds
    assert payload["duration"] == source_clip.duration
    assert payload["output_format"] == source_clip.output_format
    assert payload["width"] == source_clip.width
    assert payload["height"] == source_clip.height
    assert payload["filename"] == f'{payload["clip_id"]}_subtitled.mp4'
    assert payload["file_path"] == f'outputs/{payload["filename"]}'
    assert payload["download_url"] == f'/clips/{payload["clip_id"]}/download'
    assert payload["parent_clip_id"] == source_clip.clip_id
    assert payload["has_subtitle"] is True
    assert payload["subtitle_text"] == "Teks subtitle"
    assert payload["created_at"]

    subtitle_path = output_dir / "subtitles" / f'{payload["clip_id"]}.srt'
    assert subtitle_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:01:00,000\n"
        "Teks subtitle\n"
    )
    command = commands[0]
    assert command[:4] == ["ffmpeg", "-y", "-i", str(output_dir / "source.mp4")]
    assert command[command.index("-vf") + 1] == main.ffmpeg_subtitle_filter(subtitle_path)
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-c:a") + 1] == "copy"
    assert (output_dir / payload["filename"]).read_bytes() == b"subtitled clip"

    detail_response = client.get(f'/clips/{payload["clip_id"]}')
    assert detail_response.status_code == 200
    assert detail_response.json() == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"subtitle_text": " ", "start_time": "00:00:00", "end_time": "00:00:01"},
        {"subtitle_text": "text", "start_time": "", "end_time": "00:00:01"},
        {"subtitle_text": "text", "start_time": "00:00:00", "end_time": ""},
        {"subtitle_text": "text", "start_time": "00:00:01", "end_time": "00:00:01"},
        {"subtitle_text": "text", "start_time": "invalid", "end_time": "00:00:01"},
        {"subtitle_text": "x" * 501, "start_time": "00:00:00", "end_time": "00:00:01"},
    ],
)
def test_subtitle_validates_request(payload: dict[str, str]) -> None:
    response = client.post("/clips/source/subtitle", json=payload)

    assert response.status_code == 422


def test_subtitle_returns_404_for_missing_clip() -> None:
    response = client.post("/clips/missing/subtitle", json=subtitle_request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip not found"}


def test_subtitle_returns_404_for_missing_file(tmp_path: Path, monkeypatch) -> None:
    output_dir, _ = seed_clip(tmp_path, monkeypatch)
    (output_dir / "source.mp4").unlink()

    response = client.post("/clips/source/subtitle", json=subtitle_request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip file not found"}


def test_subtitle_handles_ffmpeg_failure(tmp_path: Path, monkeypatch) -> None:
    output_dir, _ = seed_clip(tmp_path, monkeypatch)

    def fail_ffmpeg(command, **kwargs) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(main.subprocess, "run", fail_ffmpeg)

    response = client.post("/clips/source/subtitle", json=subtitle_request())

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg failed to burn subtitle"}
    assert list((output_dir / "subtitles").iterdir()) == []


def test_subtitle_handles_missing_output(tmp_path: Path, monkeypatch) -> None:
    output_dir, _ = seed_clip(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    response = client.post("/clips/source/subtitle", json=subtitle_request())

    assert response.status_code == 500
    assert response.json() == {
        "detail": "FFmpeg did not create a subtitled output file"
    }
    assert list((output_dir / "subtitles").iterdir()) == []


def test_init_database_adds_subtitle_columns_to_legacy_clips_table() -> None:
    with main.engine.begin() as connection:
        connection.execute(
            main.text("CREATE TABLE clips (id INTEGER PRIMARY KEY)")
        )

    main.init_database()

    with main.engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(main.text("PRAGMA table_info(clips)"))
        }
    assert {"parent_clip_id", "has_subtitle", "subtitle_text"} <= columns

