"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type OutputFormat = "original" | "vertical_9_16";

type VideoItem = {
  video_id: string;
  original_filename: string;
  stored_filename: string;
  file_path: string;
  created_at: string;
};

type Clip = {
  clip_id: string;
  video_id: string;
  job_id: string | null;
  start_time_seconds: number;
  duration: number;
  output_format: OutputFormat;
  width: number;
  height: number;
  filename: string;
  file_path: string;
  download_url: string;
  created_at: string;
};

async function apiRequest<T>(path: string): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new Error(`Backend tidak bisa dihubungi di ${API_URL}`);
  }

  if (!response.ok) {
    let message = `Request gagal (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep status fallback for non-JSON responses.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function HistoryPage() {
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<VideoItem | null>(null);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [loadingClips, setLoadingClips] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadVideos() {
      setLoadingVideos(true);
      setError("");

      try {
        const loadedVideos = await apiRequest<VideoItem[]>("/videos");
        if (active) setVideos(loadedVideos);
      } catch (videoError) {
        const message = videoError instanceof Error ? videoError.message : "Gagal mengambil video.";
        if (active) setError(message.includes("Backend") ? message : `Gagal mengambil video: ${message}`);
      } finally {
        if (active) setLoadingVideos(false);
      }
    }

    loadVideos();

    return () => {
      active = false;
    };
  }, []);

  async function loadClips(video: VideoItem) {
    setSelectedVideo(video);
    setClips([]);
    setLoadingClips(true);
    setError("");

    try {
      const loadedClips = await apiRequest<Clip[]>(`/videos/${video.video_id}/clips`);
      setClips(loadedClips);
    } catch (clipError) {
      const message = clipError instanceof Error ? clipError.message : "Gagal mengambil clips.";
      setError(message.includes("Backend") ? message : `Gagal mengambil clips: ${message}`);
    } finally {
      setLoadingClips(false);
    }
  }

  return (
    <main className="app-shell history-shell">
      <div className="grid" aria-hidden="true" />
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>CLIPPER / HISTORY</span>
        </div>
        <div className="top-actions">
          <Link href="/">Home</Link>
          <span className="api-url">{API_URL}</span>
        </div>
      </header>

      <section className="intro-block history-intro">
        <p className="eyebrow">RIWAYAT</p>
        <h1>
          Video.
          <br />
          Clip <em>history.</em>
        </h1>
        <p>Lihat video yang pernah diupload dan preview clip yang sudah dibuat.</p>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="history-layout" aria-label="Riwayat video dan clip">
        <article className="history-panel">
          <div className="results-heading">
            <div>
              <p className="eyebrow">VIDEOS</p>
              <h2>Daftar video</h2>
            </div>
            <span>{videos.length.toString().padStart(2, "0")} FILE</span>
          </div>

          {loadingVideos ? (
            <div className="empty-state">Loading video...</div>
          ) : videos.length === 0 ? (
            <div className="empty-state">Belum ada video tersimpan.</div>
          ) : (
            <div className="video-list">
              {videos.map((video) => (
                <article
                  className={`video-row ${selectedVideo?.video_id === video.video_id ? "selected" : ""}`}
                  key={video.video_id}
                >
                  <div>
                    <strong>{video.original_filename}</strong>
                    <code>{video.video_id}</code>
                    <span>{formatDate(video.created_at)}</span>
                  </div>
                  <button type="button" disabled={loadingClips} onClick={() => loadClips(video)}>
                    Lihat Clips
                  </button>
                </article>
              ))}
            </div>
          )}
        </article>

        <article className="history-panel">
          <div className="results-heading">
            <div>
              <p className="eyebrow">CLIPS</p>
              <h2>{selectedVideo ? selectedVideo.original_filename : "Pilih video"}</h2>
            </div>
            <span>{clips.length.toString().padStart(2, "0")} FILE</span>
          </div>

          {loadingClips ? (
            <div className="empty-state">Loading clips...</div>
          ) : !selectedVideo ? (
            <div className="empty-state">Klik Lihat Clips pada salah satu video.</div>
          ) : clips.length === 0 ? (
            <div className="empty-state">Video ini belum memiliki clip.</div>
          ) : (
            <div className="clip-grid history-clip-grid">
              {clips.map((clip, index) => (
                <article
                  className={`clip-card ${clip.output_format === "vertical_9_16" ? "vertical" : ""}`}
                  key={clip.clip_id}
                >
                  <div className="clip-index">{String(index + 1).padStart(2, "0")}</div>
                  <div className="video-frame">
                    <video src={`${API_URL}${clip.download_url}`} controls preload="metadata" />
                  </div>
                  <div className="clip-meta">
                    <div>
                      <strong>{clip.clip_id}</strong>
                      <span>duration: {clip.duration}</span>
                      <span>output_format: {clip.output_format}</span>
                    </div>
                  </div>
                  <div className="clip-actions">
                    <a href={`${API_URL}${clip.download_url}`} download>
                      Download
                    </a>
                  </div>
                </article>
              ))}
            </div>
          )}
        </article>
      </section>
    </main>
  );
}
