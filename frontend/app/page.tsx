"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type OutputFormat = "original" | "vertical_9_16";

type UploadResult = {
  video_id: string;
  original_filename: string;
  stored_filename: string;
  file_path: string;
};

type Clip = {
  clip_id: string;
  video_id: string;
  start_time_seconds: number;
  duration: number;
  output_format: OutputFormat;
  filename: string;
  file_path: string;
  download_url: string;
};

type AutoSplitResult = {
  video_id: string;
  clip_duration_seconds: number;
  max_clips: number;
  output_format: OutputFormat;
  clips: Clip[];
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new Error(`Backend tidak bisa dihubungi di ${API_URL}`);
  }

  if (!response.ok) {
    let message = `Request gagal (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status-based fallback for non-JSON responses.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export default function Home() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadedVideo, setUploadedVideo] = useState<UploadResult | null>(null);
  const [maxClips, setMaxClips] = useState(5);
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("vertical_9_16");
  const [clips, setClips] = useState<Clip[]>([]);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState("");

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setError("");
    setClips([]);
    setUploadedVideo(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    if (!file.name.toLowerCase().endsWith(".mp4")) {
      setSelectedFile(null);
      setError("File harus berformat MP4.");
      return;
    }

    setSelectedFile(file);
  }

  async function uploadVideo() {
    if (!selectedFile) {
      setError("Pilih file MP4 terlebih dahulu.");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);

    setUploading(true);
    setError("");
    setClips([]);

    try {
      const result = await apiRequest<UploadResult>("/videos/upload", {
        method: "POST",
        body: formData,
      });
      setUploadedVideo(result);
    } catch (uploadError) {
      const message = uploadError instanceof Error ? uploadError.message : "Upload gagal.";
      setError(message.includes("Backend") ? message : `Upload gagal: ${message}`);
    } finally {
      setUploading(false);
    }
  }

  async function autoSplit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!uploadedVideo) {
      setError("Upload video terlebih dahulu sebelum menjalankan auto split.");
      return;
    }

    setProcessing(true);
    setError("");

    try {
      const result = await apiRequest<AutoSplitResult>(
        `/videos/${uploadedVideo.video_id}/auto-split`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            max_clips: maxClips,
            output_format: outputFormat,
          }),
        },
      );
      setClips(result.clips);
    } catch (splitError) {
      const message = splitError instanceof Error ? splitError.message : "Auto split gagal.";
      setError(message.includes("Backend") ? message : `Auto split gagal: ${message}`);
    } finally {
      setProcessing(false);
    }
  }

  return (
    <main className="app-shell">
      <div className="grid" aria-hidden="true" />
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>CLIPPER / LOCAL</span>
        </div>
        <span className="api-url">{API_URL}</span>
      </header>

      <section className="intro-block">
        <p className="eyebrow">VIDEO CLIPPER</p>
        <h1>
          Upload MP4.
          <br />
          Auto split <em>clip.</em>
        </h1>
        <p>Frontend sederhana untuk upload video, membuat clip otomatis, preview, dan download.</p>
      </section>

      <section className="workspace" aria-label="Video clipper workspace">
        <article className="panel upload-panel">
          <div className="panel-heading">
            <span className="step">01</span>
            <div>
              <p className="kicker">UPLOAD</p>
              <h2>Pilih video</h2>
            </div>
          </div>

          <label className={`file-picker ${selectedFile ? "has-file" : ""}`}>
            <input type="file" accept="video/mp4,.mp4" onChange={selectFile} />
            <strong>{selectedFile?.name ?? "Pilih file MP4"}</strong>
            <span>
              {selectedFile
                ? `${(selectedFile.size / 1024 / 1024).toFixed(1)} MB`
                : "Belum ada file dipilih"}
            </span>
          </label>

          <button
            className="primary-button full-button"
            type="button"
            disabled={uploading || processing}
            onClick={uploadVideo}
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>

          {uploadedVideo && (
            <div className="success-note">
              <span>VIDEO_ID</span>
              <code>{uploadedVideo.video_id}</code>
            </div>
          )}
        </article>

        <article className={`panel edit-panel ${uploadedVideo ? "" : "locked"}`}>
          <div className="panel-heading">
            <span className="step">02</span>
            <div>
              <p className="kicker">AUTO SPLIT</p>
              <h2>Buat clips</h2>
            </div>
          </div>

          {!uploadedVideo && <p className="locked-copy">Upload sukses akan mengaktifkan Auto Split.</p>}

          <form className="control-form" onSubmit={autoSplit} aria-hidden={!uploadedVideo}>
            <label>
              Max clips
              <input
                type="number"
                min="1"
                max="20"
                value={maxClips}
                disabled={!uploadedVideo || uploading || processing}
                onChange={(event) => setMaxClips(Number(event.target.value))}
              />
            </label>

            <label>
              Output format
              <select
                value={outputFormat}
                disabled={!uploadedVideo || uploading || processing}
                onChange={(event) => setOutputFormat(event.target.value as OutputFormat)}
              >
                <option value="original">original</option>
                <option value="vertical_9_16">vertical_9_16</option>
              </select>
            </label>

            <button type="submit" disabled={!uploadedVideo || uploading || processing}>
              {processing ? "Processing..." : "Auto Split"}
            </button>
          </form>
        </article>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="results-section">
        <div className="results-heading">
          <div>
            <p className="eyebrow">CLIPS</p>
            <h2>Hasil clips</h2>
          </div>
          <span>{clips.length.toString().padStart(2, "0")} FILE</span>
        </div>

        {clips.length === 0 ? (
          <div className="empty-state">Hasil auto split akan muncul di sini.</div>
        ) : (
          <div className="clip-grid">
            {clips.map((clip, index) => (
              <article
                className={`clip-card ${
                  clip.output_format === "vertical_9_16" ? "vertical" : ""
                }`}
                key={clip.clip_id}
              >
                <div className="clip-index">{String(index + 1).padStart(2, "0")}</div>
                <div className="video-frame">
                  <video src={`${API_URL}${clip.download_url}`} controls preload="metadata" />
                </div>
                <div className="clip-meta">
                  <div>
                    <strong>{clip.clip_id}</strong>
                    <span>start_time_seconds: {clip.start_time_seconds}</span>
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
      </section>
    </main>
  );
}
