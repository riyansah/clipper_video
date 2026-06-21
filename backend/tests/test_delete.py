from pathlib import Path

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def seed_video_with_clip(tmp_path: Path) -> tuple[str, str, Path, Path]:
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    output_dir.mkdir()
    video_path = upload_dir / "video.mp4"
    clip_path = output_dir / "clip.mp4"
    video_path.write_bytes(b"video")
    clip_path.write_bytes(b"clip")

    main.init_database()
    with main.SessionLocal() as session:
        session.add(
            main.Video(
                video_id="video",
                original_filename="source.mp4",
                stored_filename=video_path.name,
                file_path=str(video_path),
            )
        )
        session.add(
            main.Clip(
                clip_id="clip",
                video_id="video",
                job_id="job",
                start_time_seconds=0,
                duration=10,
                output_format="original",
                width=1920,
                height=1080,
                filename=clip_path.name,
                file_path=str(clip_path),
                download_url="/clips/clip/download",
            )
        )
        session.add(main.Job(job_id="job", video_id="video", status="completed"))
        session.commit()

    return "video", "clip", video_path, clip_path


def configure_storage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path / "outputs")


def test_delete_clip_removes_file_and_metadata(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)
    _, clip_id, _, clip_path = seed_video_with_clip(tmp_path)

    response = client.delete(f"/clips/{clip_id}")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "clip_id": clip_id,
        "file_deleted": True,
        "file_not_found": False,
    }
    assert not clip_path.exists()
    assert client.get(f"/clips/{clip_id}").status_code == 404


def test_delete_clip_removes_metadata_when_file_is_missing(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)
    _, clip_id, _, clip_path = seed_video_with_clip(tmp_path)
    clip_path.unlink()

    response = client.delete(f"/clips/{clip_id}")

    assert response.status_code == 200
    assert response.json()["file_not_found"] is True
    assert client.get(f"/clips/{clip_id}").status_code == 404


def test_delete_video_removes_files_and_related_metadata(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)
    video_id, clip_id, video_path, clip_path = seed_video_with_clip(tmp_path)

    response = client.delete(f"/videos/{video_id}")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "video_id": video_id,
        "deleted_clips": 1,
        "deleted_jobs": 1,
        "deleted_files": 2,
        "files_not_found": 0,
        "missing_files": [],
    }
    assert not video_path.exists()
    assert not clip_path.exists()
    assert client.get(f"/videos/{video_id}").status_code == 404
    assert client.get(f"/clips/{clip_id}").status_code == 404
    assert client.get("/jobs/job").status_code == 404


def test_delete_returns_404_for_missing_metadata() -> None:
    assert client.delete("/clips/missing").status_code == 404
    assert client.delete("/videos/missing").status_code == 404


def test_delete_rejects_file_outside_storage(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)
    _, clip_id, _, _ = seed_video_with_clip(tmp_path)
    outside_path = tmp_path / "outside.mp4"
    outside_path.write_bytes(b"keep")
    with main.SessionLocal() as session:
        clip = session.scalar(main.select(main.Clip).where(main.Clip.clip_id == clip_id))
        assert clip is not None
        clip.file_path = str(outside_path)
        session.commit()

    response = client.delete(f"/clips/{clip_id}")

    assert response.status_code == 500
    assert response.json() == {"detail": "File path is outside the allowed storage directory"}
    assert outside_path.exists()
    assert client.get(f"/clips/{clip_id}").status_code == 200


def test_delete_keeps_metadata_when_file_delete_fails(tmp_path: Path, monkeypatch) -> None:
    configure_storage(tmp_path, monkeypatch)
    _, clip_id, _, clip_path = seed_video_with_clip(tmp_path)

    def fail_delete(file_path: str, storage_dir: Path) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(main, "delete_storage_file", fail_delete)
    response = client.delete(f"/clips/{clip_id}")

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to delete clip file"}
    assert clip_path.exists()
    assert client.get(f"/clips/{clip_id}").status_code == 200
