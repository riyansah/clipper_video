import json
import subprocess
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def ffprobe_result(duration: float = 120, width: int = 1920, height: int = 1080) -> subprocess.CompletedProcess:
    payload = {
        "streams": [{"width": width, "height": height}],
        "format": {"duration": str(duration)},
    }
    return subprocess.CompletedProcess(["ffprobe"], 0, stdout=json.dumps(payload))


def configure_storage(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    return upload_dir, output_dir


def test_cut_video(tmp_path: Path, monkeypatch) -> None:
    upload_dir, output_dir = configure_storage(tmp_path, monkeypatch)
    video_id = "source-video-id"
    upload_dir.mkdir()
    (upload_dir / f"{video_id}.mp4").write_bytes(b"source video")

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        if command[0] == "ffprobe":
            return ffprobe_result(width=1920, height=1080)

        assert command[:6] == [
            "ffmpeg",
            "-y",
            "-ss",
            "00:01:00",
            "-i",
            str(upload_dir / f"{video_id}.mp4"),
        ]
        assert command[6:8] == ["-t", "30"]
        assert "-filter_complex" not in command
        Path(command[-1]).write_bytes(b"clip content")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    response = client.post(
        f"/videos/{video_id}/cut",
        json={"start_time": "00:01:00", "duration": 30},
    )

    assert response.status_code == 200
    payload = response.json()
    UUID(payload["clip_id"])
    assert payload == {
        "clip_id": payload["clip_id"],
        "video_id": video_id,
        "start_time": "00:01:00",
        "start_time_seconds": 60,
        "duration": 30,
        "output_format": "original",
        "width": 1920,
        "height": 1080,
        "filename": f'{payload["clip_id"]}.mp4',
        "file_path": f'outputs/{payload["clip_id"]}.mp4',
        "download_url": f'/clips/{payload["clip_id"]}/download',
    }
    assert (output_dir / payload["filename"]).read_bytes() == b"clip content"


def test_cut_video_vertical_9_16(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    video_id = "source-video-id"
    upload_dir.mkdir()
    (upload_dir / f"{video_id}.mp4").write_bytes(b"source video")

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        if command[0] == "ffprobe":
            return ffprobe_result(width=1920, height=1080)

        video_filter = command[command.index("-filter_complex") + 1]
        assert "gblur=sigma=30" in video_filter
        assert "overlay=(W-w)/2:(H-h)/2" in video_filter
        assert "[v]" in video_filter
        assert command[command.index("-map") + 1] == "[v]"
        Path(command[-1]).write_bytes(b"vertical clip")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    response = client.post(
        f"/videos/{video_id}/cut",
        json={
            "start_time": "00:01:00",
            "duration": 60,
            "output_format": "vertical_9_16",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_format"] == "vertical_9_16"
    assert payload["width"] == 1080
    assert payload["height"] == 1920


def test_cut_returns_404_when_video_does_not_exist(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)

    response = client.post(
        "/videos/missing/cut",
        json={"start_time": "00:00:00", "duration": 30},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Video not found"}


def test_cut_rejects_invalid_duration(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    response = client.post(
        "/videos/video/cut",
        json={"start_time": "00:00:00", "duration": 0},
    )

    assert response.status_code == 422


def test_cut_rejects_empty_start_time(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    response = client.post(
        "/videos/video/cut",
        json={"start_time": "   ", "duration": 30},
    )

    assert response.status_code == 422


def test_cut_handles_ffmpeg_failure(tmp_path: Path, monkeypatch) -> None:
    upload_dir, output_dir = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    def fail_ffmpeg(command, **kwargs) -> subprocess.CompletedProcess:
        if command[0] == "ffprobe":
            return ffprobe_result()
        raise subprocess.CalledProcessError(1, command, stderr="encoding failed")

    monkeypatch.setattr(main.subprocess, "run", fail_ffmpeg)

    response = client.post(
        "/videos/video/cut",
        json={"start_time": "00:00:00", "duration": 30},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg failed to cut video"}
    assert list(output_dir.iterdir()) == []


def test_cut_handles_missing_output_file(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")
    def create_no_output(command, **kwargs) -> subprocess.CompletedProcess:
        if command[0] == "ffprobe":
            return ffprobe_result()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", create_no_output)

    response = client.post(
        "/videos/video/cut",
        json={"start_time": "00:00:00", "duration": 30},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg did not create an output file"}


def test_cut_rejects_invalid_output_format(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    response = client.post(
        "/videos/video/cut",
        json={
            "start_time": "00:00:00",
            "duration": 30,
            "output_format": "square",
        },
    )

    assert response.status_code == 422
    assert "output_format must be original or vertical_9_16" in response.text


def test_download_clip(tmp_path: Path, monkeypatch) -> None:
    _, output_dir = configure_storage(tmp_path, monkeypatch)
    output_dir.mkdir()
    clip_id = "clip-id"
    (output_dir / f"{clip_id}.mp4").write_bytes(b"clip content")

    response = client.get(f"/clips/{clip_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"clip content"


def test_download_returns_404_when_clip_does_not_exist(
    tmp_path: Path, monkeypatch
) -> None:
    configure_storage(tmp_path, monkeypatch)

    response = client.get("/clips/missing/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip not found"}


def test_cut_handles_missing_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    def missing_ffmpeg(command, **kwargs) -> None:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(main.subprocess, "run", missing_ffmpeg)

    response = client.post(
        "/videos/video/cut",
        json={"start_time": "00:00:00", "duration": 30},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg executable was not found"}
