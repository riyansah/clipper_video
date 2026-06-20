from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_upload_mp4(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")

    response = client.post(
        "/videos/upload",
        files={"file": ("source-video.mp4", b"fake mp4 content", "video/mp4")},
    )

    assert response.status_code == 201
    payload = response.json()
    UUID(payload["video_id"])
    assert payload["original_filename"] == "source-video.mp4"
    assert payload["stored_filename"] == f'{payload["video_id"]}.mp4'
    assert payload["file_path"] == f'uploads/{payload["stored_filename"]}'
    assert (tmp_path / payload["file_path"]).read_bytes() == b"fake mp4 content"


def test_upload_rejects_non_mp4(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)

    response = client.post(
        "/videos/upload",
        files={"file": ("video.mov", b"video content", "video/quicktime")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only MP4 files are allowed"}
    assert not upload_dir.exists()


def test_upload_rejects_empty_mp4(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)

    response = client.post(
        "/videos/upload",
        files={"file": ("empty.mp4", b"", "video/mp4")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Uploaded file is empty"}
    assert list(upload_dir.iterdir()) == []
