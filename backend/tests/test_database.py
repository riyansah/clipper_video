import json
import subprocess
from pathlib import Path

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


def test_upload_stores_video_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")

    upload_response = client.post(
        "/videos/upload",
        files={"file": ("source.mp4", b"mp4 content", "video/mp4")},
    )

    assert upload_response.status_code == 201
    uploaded = upload_response.json()

    list_response = client.get("/videos")
    assert list_response.status_code == 200
    videos = list_response.json()
    assert len(videos) == 1
    assert videos[0]["video_id"] == uploaded["video_id"]
    assert videos[0]["original_filename"] == "source.mp4"
    assert videos[0]["stored_filename"] == uploaded["stored_filename"]
    assert videos[0]["file_path"] == uploaded["file_path"]
    assert videos[0]["created_at"]

    detail_response = client.get(f"/videos/{uploaded['video_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json() == videos[0]


def test_cut_stores_clip_metadata(tmp_path: Path, monkeypatch) -> None:
    upload_dir, output_dir = configure_storage(tmp_path, monkeypatch)
    video_id = "video-id"
    upload_dir.mkdir()
    (upload_dir / f"{video_id}.mp4").write_bytes(b"source video")

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        if command[0] == "ffprobe":
            return ffprobe_result(width=1280, height=720)
        Path(command[-1]).write_bytes(b"clip content")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    cut_response = client.post(
        f"/videos/{video_id}/cut",
        json={"start_time": "00:00:05", "duration": 15},
    )

    assert cut_response.status_code == 200
    clip = cut_response.json()

    clips_response = client.get(f"/videos/{video_id}/clips")
    assert clips_response.status_code == 200
    clips = clips_response.json()
    assert len(clips) == 1
    assert clips[0]["clip_id"] == clip["clip_id"]
    assert clips[0]["video_id"] == video_id
    assert clips[0]["start_time_seconds"] == 5
    assert clips[0]["duration"] == 15
    assert clips[0]["output_format"] == "original"
    assert clips[0]["width"] == 1280
    assert clips[0]["height"] == 720
    assert clips[0]["filename"] == clip["filename"]
    assert clips[0]["file_path"] == clip["file_path"]
    assert clips[0]["download_url"] == clip["download_url"]
    assert clips[0]["created_at"]

    detail_response = client.get(f"/clips/{clip['clip_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json() == clips[0]

    download_response = client.get(f"/clips/{clip['clip_id']}/download")
    assert download_response.status_code == 200
    assert download_response.content == b"clip content"
    assert (output_dir / clip["filename"]).is_file()


def test_auto_split_stores_all_clip_metadata(tmp_path: Path, monkeypatch) -> None:
    upload_dir, _ = configure_storage(tmp_path, monkeypatch)
    upload_dir.mkdir()
    (upload_dir / "video.mp4").write_bytes(b"source video")

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        if command[0] == "ffprobe":
            return ffprobe_result(duration=65, width=1920, height=1080)
        Path(command[-1]).write_bytes(b"clip content")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    split_response = client.post(
        "/videos/video/auto-split",
        json={"clip_duration_seconds": 30, "max_clips": 3},
    )

    assert split_response.status_code == 200
    split_payload = split_response.json()

    clips_response = client.get("/videos/video/clips")
    assert clips_response.status_code == 200
    stored_clips = clips_response.json()
    assert len(stored_clips) == 3
    assert {clip["clip_id"] for clip in stored_clips} == {
        clip["clip_id"] for clip in split_payload["clips"]
    }
    assert sorted(clip["start_time_seconds"] for clip in stored_clips) == [0, 30, 60]
    assert sorted(clip["duration"] for clip in stored_clips) == [5, 30, 30]
