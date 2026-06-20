import subprocess
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def configure_outputs(tmp_path: Path, monkeypatch) -> Path:
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    return output_dir


def test_convert_clip_to_vertical(tmp_path: Path, monkeypatch) -> None:
    output_dir = configure_outputs(tmp_path, monkeypatch)
    output_dir.mkdir()
    (output_dir / "source.mp4").write_bytes(b"source clip")

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        assert command[0:4] == [
            "ffmpeg",
            "-y",
            "-i",
            str(output_dir / "source.mp4"),
        ]
        video_filter = command[command.index("-filter_complex") + 1]
        assert "scale=1080:1920" in video_filter
        assert "gblur=sigma=30" in video_filter
        assert "overlay=(W-w)/2:(H-h)/2" in video_filter
        assert "[v]" in video_filter
        assert command[command.index("-map") + 1] == "[v]"
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        Path(command[-1]).write_bytes(b"vertical clip")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    response = client.post("/clips/source/vertical")

    assert response.status_code == 200
    payload = response.json()
    UUID(payload["clip_id"])
    assert payload == {
        "clip_id": payload["clip_id"],
        "source_clip_id": "source",
        "aspect_ratio": "9:16",
        "output_format": "vertical_9_16",
        "width": 1080,
        "height": 1920,
        "filename": f'{payload["clip_id"]}.mp4',
        "file_path": f'outputs/{payload["clip_id"]}.mp4',
        "download_url": f'/clips/{payload["clip_id"]}/download',
    }


def test_vertical_returns_404_for_missing_clip(tmp_path: Path, monkeypatch) -> None:
    configure_outputs(tmp_path, monkeypatch)

    response = client.post("/clips/missing/vertical")

    assert response.status_code == 404
    assert response.json() == {"detail": "Clip not found"}


def test_vertical_handles_ffmpeg_failure(tmp_path: Path, monkeypatch) -> None:
    output_dir = configure_outputs(tmp_path, monkeypatch)
    output_dir.mkdir()
    (output_dir / "source.mp4").write_bytes(b"source clip")

    def fail_ffmpeg(command, **kwargs) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(main.subprocess, "run", fail_ffmpeg)

    response = client.post("/clips/source/vertical")

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg failed to convert clip"}
    assert list(output_dir.iterdir()) == [output_dir / "source.mp4"]


def test_vertical_handles_missing_output(tmp_path: Path, monkeypatch) -> None:
    output_dir = configure_outputs(tmp_path, monkeypatch)
    output_dir.mkdir()
    (output_dir / "source.mp4").write_bytes(b"source clip")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    response = client.post("/clips/source/vertical")

    assert response.status_code == 500
    assert response.json() == {"detail": "FFmpeg did not create an output file"}
