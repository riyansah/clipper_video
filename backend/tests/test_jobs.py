import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def configure_job_split(tmp_path: Path, monkeypatch, video_duration: float = 120):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    ffmpeg_commands: list[list[str]] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        if command[0] == "ffprobe":
            payload = {
                "streams": [{"width": 1920, "height": 1080}],
                "format": {"duration": str(video_duration)},
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))

        ffmpeg_commands.append(command)
        Path(command[-1]).write_bytes(b"clip content")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    return ffmpeg_commands


def test_auto_split_job_completes_and_returns_clips(tmp_path: Path, monkeypatch) -> None:
    commands = configure_job_split(tmp_path, monkeypatch, video_duration=120)

    create_response = client.post(
        "/videos/video/auto-split-jobs",
        json={"max_clips": 2, "output_format": "vertical_9_16"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["video_id"] == "video"
    assert created["status"] == "pending"
    assert created["status_url"] == f"/jobs/{created['job_id']}"

    status_response = client.get(created["status_url"])

    assert status_response.status_code == 200
    job = status_response.json()
    assert job["job_id"] == created["job_id"]
    assert job["video_id"] == "video"
    assert job["status"] == "completed"
    assert job["progress"] == 100
    assert job["error_message"] is None
    assert len(job["clips"]) == 2
    assert all(clip["job_id"] == created["job_id"] for clip in job["clips"])
    assert all(clip["output_format"] == "vertical_9_16" for clip in job["clips"])
    assert all("-filter_complex" in command for command in commands)


def test_auto_split_job_stores_failure(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)

    def fail_ffmpeg(command, **kwargs) -> subprocess.CompletedProcess:
        if command[0] == "ffprobe":
            payload = {
                "streams": [{"width": 1920, "height": 1080}],
                "format": {"duration": "120"},
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        raise subprocess.CalledProcessError(1, command, stderr="encoding failed")

    monkeypatch.setattr(main.subprocess, "run", fail_ffmpeg)

    create_response = client.post(
        "/videos/video/auto-split-jobs",
        json={"max_clips": 2},
    )

    assert create_response.status_code == 200
    status_response = client.get(create_response.json()["status_url"])

    assert status_response.status_code == 200
    job = status_response.json()
    assert job["status"] == "failed"
    assert job["progress"] == 0
    assert job["error_message"] == "FFmpeg failed to split video"
    assert job["clips"] == []


def test_get_job_returns_404_for_missing_job() -> None:
    response = client.get("/jobs/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}
