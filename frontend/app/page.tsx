"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type UploadResult = {
  video_id: string;
  original_filename: string;
  stored_filename: string;
  file_path: string;
};

type OutputFormat = "original" | "vertical_9_16";

type Clip = {
  clip_id: string;
  filename: string;
  download_url: string;
  duration?: number;
  start_time?: string;
  start_time_seconds?: number;
  output_format?: OutputFormat;
  width?: number;
  height?: number;
  aspect_ratio?: string;
  source_clip_id?: string;
};

type AutoSplitResult = {
  clips: Clip[];
  clip_duration_seconds: number;
  max_clips: number;
  output_format: OutputFormat;
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    let message = `Request gagal (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status-based fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export default function Home() {
  const [apiOnline, setApiOnline] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [uploadedVideo, setUploadedVideo] = useState<UploadResult | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [startTime, setStartTime] = useState("00:00:00");
  const [duration, setDuration] = useState(30);
  const [manualOutputFormat, setManualOutputFormat] = useState<OutputFormat>("original");
  const [clipDuration, setClipDuration] = useState(60);
  const [maxClips, setMaxClips] = useState(5);
  const [autoOutputFormat, setAutoOutputFormat] = useState<OutputFormat>("original");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/health`)
      .then((response) => {
        if (active) setApiOnline(response.ok);
      })
      .catch(() => {
        if (active) setApiOnline(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setError("");
    setUploadedVideo(null);
    setClips([]);

    if (!file) {
      setSelectedFile(null);
      setPreviewUrl("");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".mp4")) {
      setSelectedFile(null);
      setPreviewUrl("");
      setError("Pilih file dengan ekstensi .mp4");
      return;
    }

    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
  }

  async function uploadVideo() {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append("file", selectedFile);
    setBusy("upload");
    setError("");
    try {
      const result = await apiRequest<UploadResult>("/videos/upload", {
        method: "POST",
        body: formData,
      });
      setUploadedVideo(result);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload gagal");
    } finally {
      setBusy("");
    }
  }

  async function cutVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadedVideo) return;
    setBusy("cut");
    setError("");
    try {
      const clip = await apiRequest<Clip>(`/videos/${uploadedVideo.video_id}/cut`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_time: startTime,
          duration,
          output_format: manualOutputFormat,
        }),
      });
      setClips((current) => [clip, ...current]);
    } catch (cutError) {
      setError(cutError instanceof Error ? cutError.message : "Pemotongan gagal");
    } finally {
      setBusy("");
    }
  }

  async function autoSplit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadedVideo) return;
    setBusy("split");
    setError("");
    try {
      const result = await apiRequest<AutoSplitResult>(
        `/videos/${uploadedVideo.video_id}/auto-split`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            clip_duration_seconds: clipDuration,
            max_clips: maxClips,
            output_format: autoOutputFormat,
          }),
        },
      );
      setClips(result.clips);
    } catch (splitError) {
      setError(splitError instanceof Error ? splitError.message : "Auto split gagal");
    } finally {
      setBusy("");
    }
  }

  async function makeVertical(clipId: string) {
    setBusy(`vertical:${clipId}`);
    setError("");
    try {
      const verticalClip = await apiRequest<Clip>(`/clips/${clipId}/vertical`, {
        method: "POST",
      });
      setClips((current) => [verticalClip, ...current]);
    } catch (verticalError) {
      setError(
        verticalError instanceof Error ? verticalError.message : "Konversi vertical gagal",
      );
    } finally {
      setBusy("");
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
        <div className={`api-state ${apiOnline ? "online" : "offline"}`}>
          <span /> API {apiOnline ? "ONLINE" : "OFFLINE"}
        </div>
      </header>

      <section className="intro-block">
        <p className="eyebrow">VIDEO WORKBENCH</p>
        <h1>
          Potong cepat.
          <br />
          Publikasikan <em>tegak.</em>
        </h1>
        <p>Upload satu MP4, ambil bagian terbaik, lalu siapkan clip 9:16.</p>
      </section>

      <section className="workspace" aria-label="Video workspace">
        <article className="panel upload-panel">
          <div className="panel-heading">
            <span className="step">01</span>
            <div>
              <p className="kicker">SOURCE</p>
              <h2>Upload video</h2>
            </div>
          </div>

          <label className={`dropzone ${selectedFile ? "has-file" : ""}`}>
            <input type="file" accept="video/mp4,.mp4" onChange={selectFile} />
            {previewUrl ? (
              <video src={previewUrl} controls preload="metadata" />
            ) : (
              <div className="drop-copy">
                <strong>Tarik atau pilih MP4</strong>
                <span>File diproses lokal oleh backend</span>
              </div>
            )}
          </label>

          <div className="file-row">
            <div>
              <strong>{selectedFile?.name ?? "Belum ada file"}</strong>
              <span>
                {selectedFile ? `${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : "MP4 only"}
              </span>
            </div>
            <button
              className="primary-button"
              type="button"
              disabled={!selectedFile || Boolean(busy)}
              onClick={uploadVideo}
            >
              {busy === "upload" ? "Mengunggah..." : uploadedVideo ? "Upload ulang" : "Upload"}
            </button>
          </div>
          {uploadedVideo && (
            <div className="success-note">
              <span>READY</span>
              <code>{uploadedVideo.video_id}</code>
            </div>
          )}
        </article>

        <article className={`panel edit-panel ${uploadedVideo ? "" : "locked"}`}>
          <div className="panel-heading">
            <span className="step">02</span>
            <div>
              <p className="kicker">EDIT</p>
              <h2>Buat clip</h2>
            </div>
          </div>

          {!uploadedVideo && <p className="locked-copy">Upload video untuk membuka alat edit.</p>}
          <div className="editor-grid" aria-hidden={!uploadedVideo}>
            <form onSubmit={cutVideo}>
              <div className="tool-title">
                <span>MANUAL CUT</span>
                <small>Presisi waktu</small>
              </div>
              <label>
                Mulai
                <input
                  type="text"
                  value={startTime}
                  pattern="[0-9]{2}:[0-9]{2}:[0-9]{2}"
                  onChange={(event) => setStartTime(event.target.value)}
                  disabled={!uploadedVideo || Boolean(busy)}
                />
              </label>
              <label>
                Durasi (detik)
                <input
                  type="number"
                  min="1"
                  value={duration}
                  onChange={(event) => setDuration(Number(event.target.value))}
                  disabled={!uploadedVideo || Boolean(busy)}
                />
              </label>
              <label>
                Format output
                <select
                  value={manualOutputFormat}
                  onChange={(event) =>
                    setManualOutputFormat(event.target.value as OutputFormat)
                  }
                  disabled={!uploadedVideo || Boolean(busy)}
                >
                  <option value="original">Original</option>
                  <option value="vertical_9_16">Vertical 9:16</option>
                </select>
              </label>
              <button type="submit" disabled={!uploadedVideo || Boolean(busy)}>
                {busy === "cut" ? "Memotong..." : "Buat clip"}
              </button>
            </form>

            <form onSubmit={autoSplit}>
              <div className="tool-title">
                <span>AUTO SPLIT</span>
                <small>Batch cepat</small>
              </div>
              <label>
                Durasi / clip
                <input
                  type="number"
                  min="1"
                  value={clipDuration}
                  onChange={(event) => setClipDuration(Number(event.target.value))}
                  disabled={!uploadedVideo || Boolean(busy)}
                />
              </label>
              <label>
                Maksimum clip
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={maxClips}
                  onChange={(event) => setMaxClips(Number(event.target.value))}
                  disabled={!uploadedVideo || Boolean(busy)}
                />
              </label>
              <label>
                Format output
                <select
                  value={autoOutputFormat}
                  onChange={(event) =>
                    setAutoOutputFormat(event.target.value as OutputFormat)
                  }
                  disabled={!uploadedVideo || Boolean(busy)}
                >
                  <option value="original">Original</option>
                  <option value="vertical_9_16">Vertical 9:16</option>
                </select>
              </label>
              <button type="submit" disabled={!uploadedVideo || Boolean(busy)}>
                {busy === "split" ? "Membagi..." : "Auto split"}
              </button>
            </form>
          </div>
        </article>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="results-section">
        <div className="results-heading">
          <div>
            <p className="eyebrow">OUTPUTS</p>
            <h2>Clip hasil</h2>
          </div>
          <span>{clips.length.toString().padStart(2, "0")} FILE</span>
        </div>

        {clips.length === 0 ? (
          <div className="empty-state">Hasil clip akan muncul di sini.</div>
        ) : (
          <div className="clip-grid">
            {clips.map((clip, index) => {
              const isVertical =
                clip.output_format === "vertical_9_16" || Boolean(clip.aspect_ratio);
              const dimensions =
                clip.width && clip.height ? `${clip.width}x${clip.height}` : "";

              return (
              <article className={`clip-card ${isVertical ? "vertical" : ""}`} key={clip.clip_id}>
                <div className="clip-index">{String(index + 1).padStart(2, "0")}</div>
                <div className="video-frame">
                  <video src={`${API_URL}${clip.download_url}`} controls preload="metadata" />
                  {isVertical && <span className="ratio-badge">9:16</span>}
                </div>
                <div className="clip-meta">
                  <div>
                    <strong>{isVertical ? "Vertical clip" : "Source clip"}</strong>
                    <span>
                      {clip.duration ? `${Number(clip.duration).toFixed(0)} detik` : "Siap diunduh"}
                      {dimensions ? ` / ${dimensions}` : ""}
                    </span>
                  </div>
                  <code>{clip.clip_id.slice(0, 8)}</code>
                </div>
                <div className="clip-actions">
                  {!isVertical && (
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => makeVertical(clip.clip_id)}
                    >
                      {busy === `vertical:${clip.clip_id}` ? "Memproses..." : "Ubah 9:16"}
                    </button>
                  )}
                  <a href={`${API_URL}${clip.download_url}`}>Download MP4</a>
                </div>
              </article>
              );
            })}
          </div>
        )}
      </section>

      <footer className="footer">
        <span>LOCAL PROCESSING / NO AI</span>
        <span>NEXT.JS + FASTAPI + FFMPEG</span>
      </footer>
    </main>
  );
}
