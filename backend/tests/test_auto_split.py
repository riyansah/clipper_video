import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def configure_auto_split(tmp_path: Path, monkeypatch, video_duration: float):
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


def test_auto_split_defaults_to_60_seconds(tmp_path: Path, monkeypatch) -> None:
    commands = configure_auto_split(tmp_path, monkeypatch, video_duration=300)

    response = client.post(
        "/videos/video/auto-split",
        json={"max_clips": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_duration_seconds"] == 60
    assert payload["max_clips"] == 5
    assert payload["output_format"] == "original"
    assert len(payload["clips"]) == 5
    assert all(clip["output_format"] == "original" for clip in payload["clips"])
    assert all(clip["width"] == 1920 for clip in payload["clips"])
    assert all(clip["height"] == 1080 for clip in payload["clips"])
    assert [command[command.index("-t") + 1] for command in commands] == [
        "60",
        "60",
        "60",
        "60",
        "60",
    ]
    assert [clip["start_time_seconds"] for clip in payload["clips"]] == [
        0,
        60,
        120,
        180,
        240,
    ]


def test_auto_split_vertical_9_16(tmp_path: Path, monkeypatch) -> None:
    commands = configure_auto_split(tmp_path, monkeypatch, video_duration=120)

    response = client.post(
        "/videos/video/auto-split",
        json={
            "clip_duration_seconds": 60,
            "max_clips": 2,
            "output_format": "vertical_9_16",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_format"] == "vertical_9_16"
    assert len(payload["clips"]) == 2
    assert all(clip["output_format"] == "vertical_9_16" for clip in payload["clips"])
    assert all(clip["width"] == 1080 for clip in payload["clips"])
    assert all(clip["height"] == 1920 for clip in payload["clips"])
    assert all("-filter_complex" in command for command in commands)
    assert all(command[command.index("-map") + 1] == "[v]" for command in commands)


def test_auto_split_allows_custom_duration(tmp_path: Path, monkeypatch) -> None:
    commands = configure_auto_split(tmp_path, monkeypatch, video_duration=150)

    response = client.post(
        "/videos/video/auto-split",
        json={"clip_duration_seconds": 30, "max_clips": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_duration_seconds"] == 30
    assert len(payload["clips"]) == 5
    assert [command[command.index("-t") + 1] for command in commands] == [
        "30",
        "30",
        "30",
        "30",
        "30",
    ]


def test_auto_split_rejects_invalid_output_format() -> None:
    response = client.post(
        "/videos/video/auto-split",
        json={"max_clips": 5, "output_format": "square"},
    )

    assert response.status_code == 422
    assert "output_format must be original or vertical_9_16" in response.text


def test_auto_split_validates_limits() -> None:
    invalid_requests = [
        {"clip_duration_seconds": 0, "max_clips": 5},
        {"max_clips": 0},
        {"max_clips": 21},
    ]

    for body in invalid_requests:
        response = client.post("/videos/video/auto-split", json=body)
        assert response.status_code == 422
