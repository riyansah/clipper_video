import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main

client = TestClient(main.app)


def seed_clip(tmp_path: Path, monkeypatch) -> main.Clip:
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
            start_time_seconds=0,
            duration=120,
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
    return clip


def seed_transcript(
    clip_id: str,
    *,
    transcript_id: str,
    status: str = "completed",
    transcript_text: str = "default transcript",
    segments: list[dict[str, object]] | None = None,
) -> None:
    with main.SessionLocal() as session:
        session.add(
            main.Transcript(
                transcript_id=transcript_id,
                clip_id=clip_id,
                transcript_text=transcript_text,
                segments_json=json.dumps(segments or [], ensure_ascii=False),
                provider="dummy",
                status=status,
            )
        )
        session.commit()


def test_detect_highlights_creates_sorted_candidates(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-1",
        transcript_text="transcript utama",
        segments=[
            {"start": 0, "end": 30, "text": "Kenapa 3 tips penting ini wajib dicoba?"},
            {"start": 30, "end": 35, "text": "halo"},
            {"start": 35, "end": 100, "text": "Bagian panjang biasa"},
        ],
    )

    response = client.post(f"/clips/{clip.clip_id}/detect-highlights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_id"] == clip.clip_id
    assert payload["transcript_id"] == "tx-1"
    assert len(payload["highlights"]) == 3
    assert payload["highlights"][0]["score"] >= payload["highlights"][1]["score"]
    assert payload["highlights"][1]["score"] >= payload["highlights"][2]["score"]
    top = payload["highlights"][0]
    assert top["start_time"] == "00:00:00"
    assert top["end_time"] == "00:00:30"
    assert top["duration"] == 30
    assert top["score"] == 100
    assert "question keyword" in top["reason"].lower()
    assert "number" in top["reason"].lower()
    assert "emotional keyword" in top["reason"].lower()

    with main.SessionLocal() as session:
        stored = session.scalars(select(main.HighlightCandidate)).all()
    assert len(stored) == 3


def test_get_highlights_returns_saved_candidates_sorted_by_score(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-2",
        segments=[
            {"start": 0, "end": 25, "text": "Apa solusi cepat 5 langkah?"},
            {"start": 25, "end": 33, "text": "pendek"},
        ],
    )

    detect_response = client.post(f"/clips/{clip.clip_id}/detect-highlights")
    assert detect_response.status_code == 200

    response = client.get(f"/clips/{clip.clip_id}/highlights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_id"] == clip.clip_id
    assert payload["transcript_id"] == "tx-2"
    assert len(payload["highlights"]) == 2
    assert payload["highlights"][0]["score"] >= payload["highlights"][1]["score"]


def test_detect_highlights_returns_404_when_transcript_missing(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)

    response = client.post(f"/clips/{clip.clip_id}/detect-highlights")

    assert response.status_code == 404
    assert response.json() == {"detail": "Transcript not found"}


def test_detect_highlights_returns_clear_error_when_latest_transcript_not_completed(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(clip.clip_id, transcript_id="older", status="completed")
    seed_transcript(clip.clip_id, transcript_id="newer", status="processing")

    response = client.post(f"/clips/{clip.clip_id}/detect-highlights")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Transcript status must be completed, got processing"
    }


def test_detect_highlights_caps_single_long_segment_to_60_seconds(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-long",
        transcript_text="segment panjang",
        segments=[
            {"start": 0, "end": 120, "text": "Ini segment panjang penting 7 langkah"},
        ],
    )

    response = client.post(f"/clips/{clip.clip_id}/detect-highlights")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["highlights"]) == 1
    highlight = payload["highlights"][0]
    assert highlight["start_time"] == "00:00:00"
    assert highlight["end_time"] == "00:01:00"
    assert highlight["duration"] == 60
    assert "single segment fallback" in highlight["reason"].lower()


def test_get_highlights_returns_404_when_missing(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)

    response = client.get(f"/clips/{clip.clip_id}/highlights")

    assert response.status_code == 404
    assert response.json() == {"detail": "Highlight candidates not found"}


def test_init_database_creates_highlight_candidates_table() -> None:
    main.init_database()

    with main.engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(main.text("PRAGMA table_info(highlight_candidates)"))
        }

    assert {
        "id",
        "highlight_id",
        "transcript_id",
        "clip_id",
        "video_id",
        "start_time",
        "end_time",
        "duration",
        "text",
        "score",
        "reason",
        "created_at",
    } <= columns


def create_highlights_for_clip(clip_id: str) -> None:
    response = client.post(f"/clips/{clip_id}/detect-highlights")
    assert response.status_code == 200


def test_ai_rank_highlights_returns_dummy_rankings_and_caps_to_top_five(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-ai-1",
        segments=[
            {"start": 0, "end": 25, "text": "Kenapa 5 tips penting ini wajib dicoba?"},
            {"start": 25, "end": 55, "text": "Bagaimana 3 langkah cepat untuk hasil bagus"},
            {"start": 55, "end": 80, "text": "Apa solusi murah yang tidak gagal"},
            {"start": 80, "end": 100, "text": "Rahasia 7 ide konten yang mudah"},
            {"start": 100, "end": 120, "text": "Kapan pakai format vertical 9 16"},
            {"start": 120, "end": 140, "text": "segmen biasa tanpa banyak sinyal"},
        ],
    )
    create_highlights_for_clip(clip.clip_id)

    response = client.post(f"/clips/{clip.clip_id}/ai-rank-highlights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_id"] == clip.clip_id
    assert len(payload["ai_highlights"]) == 5
    assert payload["ai_highlights"][0]["score"] >= payload["ai_highlights"][1]["score"]
    top = payload["ai_highlights"][0]
    assert top["provider"] == "dummy"
    assert top["title"]
    assert top["reason"]
    assert isinstance(top["hashtags"], list)
    assert top["start_time"] is not None
    assert top["end_time"] is not None

    with main.SessionLocal() as session:
        stored = session.scalars(select(main.AIHighlightRanking)).all()
    assert len(stored) == 5


def test_ai_rank_highlights_returns_clear_error_when_candidates_missing(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)

    response = client.post(f"/clips/{clip.clip_id}/ai-rank-highlights")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No highlight candidates found. Run detect-highlights first."
    }


def test_get_ai_highlights_returns_saved_rankings_sorted_by_score(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-ai-2",
        segments=[
            {"start": 0, "end": 25, "text": "Kenapa 5 tips penting ini wajib dicoba?"},
            {"start": 25, "end": 45, "text": "Apa solusi cepat 3 langkah"},
        ],
    )
    create_highlights_for_clip(clip.clip_id)
    rank_response = client.post(f"/clips/{clip.clip_id}/ai-rank-highlights")
    assert rank_response.status_code == 200

    response = client.get(f"/clips/{clip.clip_id}/ai-highlights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clip_id"] == clip.clip_id
    assert len(payload["ai_highlights"]) == 2
    assert payload["ai_highlights"][0]["score"] >= payload["ai_highlights"][1]["score"]


def test_ai_rank_highlights_falls_back_to_dummy_when_external_provider_fails(tmp_path: Path, monkeypatch) -> None:
    clip = seed_clip(tmp_path, monkeypatch)
    seed_transcript(
        clip.clip_id,
        transcript_id="tx-ai-3",
        segments=[
            {"start": 0, "end": 25, "text": "Kenapa 5 tips penting ini wajib dicoba?"},
        ],
    )
    create_highlights_for_clip(clip.clip_id)
    monkeypatch.setattr(main, "AI_HIGHLIGHT_PROVIDER", "external")

    def broken_ranker(self, clip, candidates):
        raise RuntimeError("provider down")

    monkeypatch.setattr(main.ExternalAIHighlightRanker, "rank_highlights", broken_ranker)

    response = client.post(f"/clips/{clip.clip_id}/ai-rank-highlights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_highlights"][0]["provider"] == "dummy"
    assert payload["ai_highlights"][0]["raw_response_json"]["fallback_from"] == "external"


def test_init_database_creates_ai_highlight_rankings_table() -> None:
    main.init_database()

    with main.engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(main.text("PRAGMA table_info(ai_highlight_rankings)"))
        }

    assert {
        "id",
        "ai_ranking_id",
        "highlight_id",
        "clip_id",
        "video_id",
        "score",
        "title",
        "reason",
        "caption",
        "hashtags_json",
        "provider",
        "raw_response_json",
        "created_at",
    } <= columns
