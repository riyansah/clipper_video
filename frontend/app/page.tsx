"use client";

import Link from "next/link";
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
  start_time?: string;
  start_time_seconds: number;
  duration: number;
  output_format: OutputFormat;
  filename: string;
  file_path: string;
  download_url: string;
};

type JobStatus = "pending" | "processing" | "completed" | "failed";

type AutoSplitJobCreateResult = {
  job_id: string;
  video_id: string;
  status: "pending";
  status_url: string;
};

type AutoSplitJobStatus = {
  job_id: string;
  video_id: string;
  status: JobStatus;
  progress: number;
  error_message: string | null;
  clips: Clip[];
};

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  const [clipLookupVideoId, setClipLookupVideoId] = useState("");
  const [startTime, setStartTime] = useState("00:00:00");
  const [duration, setDuration] = useState(60);
  const [manualOutputFormat, setManualOutputFormat] = useState<OutputFormat>("original");
  const [maxClips, setMaxClips] = useState(5);
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("vertical_9_16");
  const [clips, setClips] = useState<Clip[]>([]);
  const [autoSplitJob, setAutoSplitJob] = useState<AutoSplitJobStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [cutting, setCutting] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [loadingStoredClips, setLoadingStoredClips] = useState(false);
  const [error, setError] = useState("");
  const busy = uploading || cutting || processing || loadingStoredClips;

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setError("");
    setClips([]);
    setAutoSplitJob(null);
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
    setAutoSplitJob(null);

    try {
      const result = await apiRequest<UploadResult>("/videos/upload", {
        method: "POST",
        body: formData,
      });
      setUploadedVideo(result);
      setClipLookupVideoId(result.video_id);
    } catch (uploadError) {
      const message = uploadError instanceof Error ? uploadError.message : "Upload gagal.";
      setError(message.includes("Backend") ? message : `Upload gagal: ${message}`);
    } finally {
      setUploading(false);
    }
  }

  async function manualCut(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!uploadedVideo) {
      setError("Upload video terlebih dahulu sebelum menjalankan manual cut.");
      return;
    }

    setCutting(true);
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
      setClips((currentClips) => [clip, ...currentClips]);
    } catch (cutError) {
      const message = cutError instanceof Error ? cutError.message : "Manual cut gagal.";
      setError(message.includes("Backend") ? message : `Manual cut gagal: ${message}`);
    } finally {
      setCutting(false);
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
    setClips([]);
    setAutoSplitJob(null);

    try {
      const createdJob = await apiRequest<AutoSplitJobCreateResult>(
        `/videos/${uploadedVideo.video_id}/auto-split-jobs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            max_clips: maxClips,
            output_format: outputFormat,
          }),
        },
      );
      setAutoSplitJob({
        job_id: createdJob.job_id,
        video_id: createdJob.video_id,
        status: createdJob.status,
        progress: 0,
        error_message: null,
        clips: [],
      });

      while (true) {
        await wait(2000);
        const job = await apiRequest<AutoSplitJobStatus>(createdJob.status_url);
        setAutoSplitJob(job);

        if (job.status === "completed") {
          setClips(job.clips);
          break;
        }

        if (job.status === "failed") {
          setError(job.error_message ? `Auto split gagal: ${job.error_message}` : "Auto split gagal.");
          break;
        }
      }
    } catch (splitError) {
      const message = splitError instanceof Error ? splitError.message : "Auto split gagal.";
      setError(message.includes("Backend") ? message : `Auto split gagal: ${message}`);
    } finally {
      setProcessing(false);
    }
  }

  async function loadStoredClips() {
    const videoId = clipLookupVideoId.trim() || uploadedVideo?.video_id;
    if (!videoId) {
      setError("Isi video_id terlebih dahulu.");
      return;
    }

    setLoadingStoredClips(true);
    setError("");

    try {
      const storedClips = await apiRequest<Clip[]>(`/videos/${videoId}/clips`);
      setClips(storedClips);
    } catch (storedClipError) {
      const message =
        storedClipError instanceof Error ? storedClipError.message : "Gagal mengambil clips.";
      setError(message.includes("Backend") ? message : `Gagal mengambil clips: ${message}`);
    } finally {
      setLoadingStoredClips(false);
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
        <div className="top-actions">
          <Link href="/history">History</Link>
          <span className="api-url">{API_URL}</span>
        </div>
      </header>

      <section className="intro-block">
        <p className="eyebrow">VIDEO CLIPPER</p>
        <h1>
          Cut manual.
          <br />
          Auto split <em>clip.</em>
        </h1>
        <p>Upload MP4, buat clip manual, auto split, preview, dan download hasilnya.</p>
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
            disabled={busy}
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

          <div className="clip-lookup">
            <label htmlFor="clip-lookup-video-id">Ambil clips by video_id</label>
            <div className="clip-lookup-row">
              <input
                id="clip-lookup-video-id"
                type="text"
                value={clipLookupVideoId}
                disabled={busy}
                placeholder="VIDEO_ID"
                onChange={(event) => setClipLookupVideoId(event.target.value)}
              />
              <button
                type="button"
                disabled={busy || (!clipLookupVideoId.trim() && !uploadedVideo)}
                onClick={loadStoredClips}
              >
                {loadingStoredClips ? "Loading..." : "Load Clips"}
              </button>
            </div>
          </div>
        </article>

        <article className={`panel edit-panel ${uploadedVideo ? "" : "locked"}`}>
          <div className="panel-heading">
            <span className="step">02</span>
            <div>
              <p className="kicker">CUT</p>
              <h2>Buat clips</h2>
            </div>
          </div>

          {!uploadedVideo && <p className="locked-copy">Upload sukses akan mengaktifkan alat clip.</p>}

          <div className="tool-grid" aria-hidden={!uploadedVideo}>
            <form className="control-form secondary" onSubmit={manualCut}>
              <div className="tool-title">
                <span>MANUAL CUT</span>
                <small>Presisi waktu</small>
              </div>

              <label>
                Start time
                <input
                  type="text"
                  pattern="[0-9]{2}:[0-9]{2}:[0-9]{2}"
                  value={startTime}
                  disabled={!uploadedVideo || busy}
                  onChange={(event) => setStartTime(event.target.value)}
                />
              </label>

              <label>
                Duration
                <input
                  type="number"
                  min="1"
                  value={duration}
                  disabled={!uploadedVideo || busy}
                  onChange={(event) => setDuration(Number(event.target.value))}
                />
              </label>

              <label>
                Output format
                <select
                  value={manualOutputFormat}
                  disabled={!uploadedVideo || busy}
                  onChange={(event) => setManualOutputFormat(event.target.value as OutputFormat)}
                >
                  <option value="original">original</option>
                  <option value="vertical_9_16">vertical_9_16</option>
                </select>
              </label>

              <button type="submit" disabled={!uploadedVideo || busy}>
                {cutting ? "Cutting..." : "Manual Cut"}
              </button>
            </form>

            <form className="control-form" onSubmit={autoSplit}>
              <div className="tool-title">
                <span>AUTO SPLIT</span>
                <small>Default 60 detik</small>
              </div>

              <label>
                Max clips
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={maxClips}
                  disabled={!uploadedVideo || busy}
                  onChange={(event) => setMaxClips(Number(event.target.value))}
                />
              </label>

              <label>
                Output format
                <select
                  value={outputFormat}
                  disabled={!uploadedVideo || busy}
                  onChange={(event) => setOutputFormat(event.target.value as OutputFormat)}
                >
                  <option value="original">original</option>
                  <option value="vertical_9_16">vertical_9_16</option>
                </select>
              </label>

              <button type="submit" disabled={!uploadedVideo || busy}>
                {processing ? "Processing..." : "Auto Split"}
              </button>
            </form>
          </div>

          {autoSplitJob && (
            <div className={`job-status ${autoSplitJob.status}`}>
              <div className="job-status-row">
                <span>{autoSplitJob.status}</span>
                <strong>{autoSplitJob.progress}%</strong>
              </div>
              <div className="progress-track" aria-hidden="true">
                <span style={{ width: `${autoSplitJob.progress}%` }} />
              </div>
              <code>{autoSplitJob.job_id}</code>
              {autoSplitJob.status === "failed" && autoSplitJob.error_message && (
                <p>{autoSplitJob.error_message}</p>
              )}
            </div>
          )}
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
          <div className="empty-state">Hasil manual cut atau auto split akan muncul di sini.</div>
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
