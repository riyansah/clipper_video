"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

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
  parent_clip_id: string | null;
  has_subtitle: boolean;
  subtitle_text: string | null;
  created_at: string;
};

type Transcript = {
  id: number;
  transcript_id: string;
  clip_id: string;
  transcript_text: string | null;
  segments_json: Array<Record<string, unknown>>;
  provider: string;
  status: "pending" | "processing" | "completed" | "failed";
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

type Highlight = {
  highlight_id: string;
  start_time: string;
  end_time: string;
  duration: number;
  text: string;
  score: number;
  reason: string;
};

type HighlightList = {
  clip_id: string;
  transcript_id: string;
  highlights: Highlight[];
};

type AIHighlight = {
  ai_ranking_id: string;
  highlight_id: string;
  clip_id: string;
  video_id: string;
  score: number;
  title: string;
  reason: string;
  caption: string;
  hashtags: string[];
  provider: string;
  raw_response_json: unknown;
  created_at: string;
  start_time: string | null;
  end_time: string | null;
};

type AIHighlightList = {
  clip_id: string;
  ai_highlights: AIHighlight[];
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_URL}${path}`, { ...init, cache: "no-store" });
  } catch {
    throw new Error(`Backend tidak bisa dihubungi di ${API_URL}`);
  }

  if (!response.ok) {
    let message = `Request gagal (${response.status})`;
    try {
      const payload = (await response.json()) as {
        detail?: string | Array<{ msg?: string }>;
      };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
        message = payload.detail[0].msg;
      }
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

function formatSubtitleEnd(duration: number) {
  const totalSeconds = Math.max(1, Math.ceil(duration));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

export default function HistoryPage() {
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<VideoItem | null>(null);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [loadingClips, setLoadingClips] = useState(false);
  const [deletingVideoId, setDeletingVideoId] = useState<string | null>(null);
  const [deletingClipId, setDeletingClipId] = useState<string | null>(null);
  const [subtitleClipId, setSubtitleClipId] = useState<string | null>(null);
  const [subtitleText, setSubtitleText] = useState("");
  const [subtitleStartTime, setSubtitleStartTime] = useState("00:00:00");
  const [subtitleEndTime, setSubtitleEndTime] = useState("00:00:01");
  const [generatingSubtitleId, setGeneratingSubtitleId] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, Transcript>>({});
  const [transcriptClipId, setTranscriptClipId] = useState<string | null>(null);
  const [generatingTranscriptId, setGeneratingTranscriptId] = useState<string | null>(null);
  const [loadingTranscriptId, setLoadingTranscriptId] = useState<string | null>(null);
  const [highlightsByClip, setHighlightsByClip] = useState<Record<string, HighlightList>>({});
  const [highlightClipId, setHighlightClipId] = useState<string | null>(null);
  const [detectingHighlightId, setDetectingHighlightId] = useState<string | null>(null);
  const [loadingHighlightId, setLoadingHighlightId] = useState<string | null>(null);
  const [aiHighlightsByClip, setAiHighlightsByClip] = useState<Record<string, AIHighlightList>>({});
  const [aiHighlightClipId, setAiHighlightClipId] = useState<string | null>(null);
  const [rankingAiHighlightId, setRankingAiHighlightId] = useState<string | null>(null);
  const [loadingAiHighlightId, setLoadingAiHighlightId] = useState<string | null>(null);
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
    setTranscripts({});
    setTranscriptClipId(null);
    setHighlightsByClip({});
    setHighlightClipId(null);
    setAiHighlightsByClip({});
    setAiHighlightClipId(null);
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

  async function deleteClip(clip: Clip) {
    if (!window.confirm(`Hapus clip ${clip.clip_id}?`)) return;

    setDeletingClipId(clip.clip_id);
    setError("");
    try {
      await apiRequest(`/clips/${clip.clip_id}`, { method: "DELETE" });
      setClips((currentClips) => currentClips.filter((item) => item.clip_id !== clip.clip_id));
      setTranscripts((current) => {
        const next = { ...current };
        delete next[clip.clip_id];
        return next;
      });
      setHighlightsByClip((current) => {
        const next = { ...current };
        delete next[clip.clip_id];
        return next;
      });
      setAiHighlightsByClip((current) => {
        const next = { ...current };
        delete next[clip.clip_id];
        return next;
      });
      if (transcriptClipId === clip.clip_id) setTranscriptClipId(null);
      if (highlightClipId === clip.clip_id) setHighlightClipId(null);
      if (aiHighlightClipId === clip.clip_id) setAiHighlightClipId(null);
    } catch (deleteError) {
      const message = deleteError instanceof Error ? deleteError.message : "Gagal menghapus clip.";
      setError(message.includes("Backend") ? message : `Gagal menghapus clip: ${message}`);
    } finally {
      setDeletingClipId(null);
    }
  }

  async function deleteVideo(video: VideoItem) {
    const confirmed = window.confirm(
      `Hapus video ${video.original_filename}? Semua clip dari video ini juga akan dihapus.`,
    );
    if (!confirmed) return;

    setDeletingVideoId(video.video_id);
    setError("");
    try {
      await apiRequest(`/videos/${video.video_id}`, { method: "DELETE" });
      setVideos((currentVideos) => currentVideos.filter((item) => item.video_id !== video.video_id));
      if (selectedVideo?.video_id === video.video_id) {
        setSelectedVideo(null);
        setClips([]);
        setTranscripts({});
        setTranscriptClipId(null);
        setHighlightsByClip({});
        setHighlightClipId(null);
        setAiHighlightsByClip({});
        setAiHighlightClipId(null);
      }
    } catch (deleteError) {
      const message = deleteError instanceof Error ? deleteError.message : "Gagal menghapus video.";
      setError(message.includes("Backend") ? message : `Gagal menghapus video: ${message}`);
    } finally {
      setDeletingVideoId(null);
    }
  }

  function openSubtitleForm(clip: Clip) {
    if (subtitleClipId === clip.clip_id) {
      setSubtitleClipId(null);
      return;
    }

    setSubtitleClipId(clip.clip_id);
    setSubtitleText("");
    setSubtitleStartTime("00:00:00");
    setSubtitleEndTime(formatSubtitleEnd(clip.duration));
    setError("");
  }

  async function generateSubtitle(event: FormEvent<HTMLFormElement>, clip: Clip) {
    event.preventDefault();
    setGeneratingSubtitleId(clip.clip_id);
    setError("");

    try {
      const generatedClip = await apiRequest<Clip>(`/clips/${clip.clip_id}/subtitle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subtitle_text: subtitleText,
          start_time: subtitleStartTime,
          end_time: subtitleEndTime,
        }),
      });
      setClips((currentClips) => [...currentClips, generatedClip]);
      setSubtitleClipId(null);
      setSubtitleText("");
    } catch (subtitleError) {
      const message =
        subtitleError instanceof Error ? subtitleError.message : "Gagal membuat subtitle.";
      setError(message.includes("Backend") ? message : `Gagal membuat subtitle: ${message}`);
    } finally {
      setGeneratingSubtitleId(null);
    }
  }

  async function generateTranscript(clip: Clip) {
    setGeneratingTranscriptId(clip.clip_id);
    setTranscriptClipId(clip.clip_id);
    setError("");

    try {
      const transcript = await apiRequest<Transcript>(`/clips/${clip.clip_id}/transcribe`, {
        method: "POST",
      });
      setTranscripts((current) => ({ ...current, [clip.clip_id]: transcript }));
    } catch (transcriptError) {
      const message =
        transcriptError instanceof Error ? transcriptError.message : "Gagal membuat transcript.";
      setError(message.includes("Backend") ? message : `Gagal membuat transcript: ${message}`);
    } finally {
      setGeneratingTranscriptId(null);
    }
  }

  async function viewTranscript(clip: Clip) {
    if (transcriptClipId === clip.clip_id && transcripts[clip.clip_id]) {
      setTranscriptClipId(null);
      return;
    }

    setLoadingTranscriptId(clip.clip_id);
    setError("");

    try {
      const transcript = await apiRequest<Transcript>(`/clips/${clip.clip_id}/transcript`);
      setTranscripts((current) => ({ ...current, [clip.clip_id]: transcript }));
      setTranscriptClipId(clip.clip_id);
    } catch (transcriptError) {
      const message =
        transcriptError instanceof Error ? transcriptError.message : "Gagal mengambil transcript.";
      setError(message.includes("Backend") ? message : `Gagal mengambil transcript: ${message}`);
    } finally {
      setLoadingTranscriptId(null);
    }
  }

  async function detectHighlights(clip: Clip) {
    setDetectingHighlightId(clip.clip_id);
    setHighlightClipId(clip.clip_id);
    setError("");

    try {
      const payload = await apiRequest<HighlightList>(`/clips/${clip.clip_id}/detect-highlights`, {
        method: "POST",
      });
      setHighlightsByClip((current) => ({ ...current, [clip.clip_id]: payload }));
    } catch (highlightError) {
      const message =
        highlightError instanceof Error ? highlightError.message : "Gagal mendeteksi highlight.";
      setError(message.includes("Backend") ? message : `Gagal mendeteksi highlight: ${message}`);
    } finally {
      setDetectingHighlightId(null);
    }
  }

  async function viewHighlights(clip: Clip) {
    if (highlightClipId === clip.clip_id && highlightsByClip[clip.clip_id]) {
      setHighlightClipId(null);
      return;
    }

    setLoadingHighlightId(clip.clip_id);
    setError("");

    try {
      const payload = await apiRequest<HighlightList>(`/clips/${clip.clip_id}/highlights`);
      setHighlightsByClip((current) => ({ ...current, [clip.clip_id]: payload }));
      setHighlightClipId(clip.clip_id);
    } catch (highlightError) {
      const message =
        highlightError instanceof Error ? highlightError.message : "Gagal mengambil highlight.";
      setError(message.includes("Backend") ? message : `Gagal mengambil highlight: ${message}`);
    } finally {
      setLoadingHighlightId(null);
    }
  }


  async function rankAiHighlights(clip: Clip) {
    setRankingAiHighlightId(clip.clip_id);
    setAiHighlightClipId(clip.clip_id);
    setError("");

    try {
      const payload = await apiRequest<AIHighlightList>(`/clips/${clip.clip_id}/ai-rank-highlights`, {
        method: "POST",
      });
      setAiHighlightsByClip((current) => ({ ...current, [clip.clip_id]: payload }));
    } catch (aiError) {
      const message =
        aiError instanceof Error ? aiError.message : "Gagal menjalankan AI ranking highlight.";
      setError(
        message.includes("Backend") ? message : `Gagal menjalankan AI ranking highlight: ${message}`,
      );
    } finally {
      setRankingAiHighlightId(null);
    }
  }

  async function viewAiHighlights(clip: Clip) {
    if (aiHighlightClipId === clip.clip_id && aiHighlightsByClip[clip.clip_id]) {
      setAiHighlightClipId(null);
      return;
    }

    setLoadingAiHighlightId(clip.clip_id);
    setError("");

    try {
      const payload = await apiRequest<AIHighlightList>(`/clips/${clip.clip_id}/ai-highlights`);
      setAiHighlightsByClip((current) => ({ ...current, [clip.clip_id]: payload }));
      setAiHighlightClipId(clip.clip_id);
    } catch (aiError) {
      const message =
        aiError instanceof Error ? aiError.message : "Gagal mengambil AI highlight.";
      setError(message.includes("Backend") ? message : `Gagal mengambil AI highlight: ${message}`);
    } finally {
      setLoadingAiHighlightId(null);
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
                  <div className="video-row-actions">
                    <button
                      type="button"
                      disabled={loadingClips || deletingVideoId !== null}
                      onClick={() => loadClips(video)}
                    >
                      Lihat Clips
                    </button>
                    <button
                      className="danger-button"
                      type="button"
                      disabled={deletingVideoId !== null}
                      onClick={() => deleteVideo(video)}
                    >
                      {deletingVideoId === video.video_id ? "Deleting..." : "Delete video"}
                    </button>
                  </div>
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
              {clips.map((clip, index) => {
                const transcript = transcripts[clip.clip_id];
                const transcriptOpen = transcriptClipId === clip.clip_id;
                const highlightPayload = highlightsByClip[clip.clip_id];
                const highlightOpen = highlightClipId === clip.clip_id;
                const highlightItems = [...(highlightPayload?.highlights ?? [])].sort(
                  (left, right) => right.score - left.score,
                );
                const aiHighlightPayload = aiHighlightsByClip[clip.clip_id];
                const aiHighlightOpen = aiHighlightClipId === clip.clip_id;
                const aiHighlightItems = [...(aiHighlightPayload?.ai_highlights ?? [])].sort(
                  (left, right) => right.score - left.score,
                );

                return (
                  <article
                    className={`clip-card ${clip.output_format === "vertical_9_16" ? "vertical" : ""}`}
                    key={clip.clip_id}
                  >
                    <div className="clip-index">{String(index + 1).padStart(2, "0")}</div>
                    {clip.has_subtitle && <span className="subtitle-badge">Subtitled</span>}
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
                      <button
                        type="button"
                        disabled={generatingTranscriptId !== null || loadingTranscriptId !== null}
                        onClick={() => generateTranscript(clip)}
                      >
                        {generatingTranscriptId === clip.clip_id
                          ? "Generating..."
                          : "Generate Transcript"}
                      </button>
                      <button
                        type="button"
                        disabled={generatingTranscriptId !== null || loadingTranscriptId !== null}
                        onClick={() => viewTranscript(clip)}
                      >
                        {loadingTranscriptId === clip.clip_id
                          ? "Loading..."
                          : transcriptOpen
                            ? "Hide Transcript"
                            : "View Transcript"}
                      </button>
                      <button
                        type="button"
                        disabled={detectingHighlightId !== null || loadingHighlightId !== null}
                        onClick={() => detectHighlights(clip)}
                      >
                        {detectingHighlightId === clip.clip_id
                          ? "Detecting..."
                          : "Detect Highlights"}
                      </button>
                      <button
                        type="button"
                        disabled={detectingHighlightId !== null || loadingHighlightId !== null}
                        onClick={() => viewHighlights(clip)}
                      >
                        {loadingHighlightId === clip.clip_id
                          ? "Loading..."
                          : highlightOpen
                            ? "Hide Highlights"
                            : "View Highlights"}
                      </button>
                      <button
                        type="button"
                        disabled={rankingAiHighlightId !== null || loadingAiHighlightId !== null}
                        onClick={() => rankAiHighlights(clip)}
                      >
                        {rankingAiHighlightId === clip.clip_id
                          ? "Ranking..."
                          : "AI Rank Highlights"}
                      </button>
                      <button
                        type="button"
                        disabled={rankingAiHighlightId !== null || loadingAiHighlightId !== null}
                        onClick={() => viewAiHighlights(clip)}
                      >
                        {loadingAiHighlightId === clip.clip_id
                          ? "Loading..."
                          : aiHighlightOpen
                            ? "Hide AI Highlights"
                            : "View AI Highlights"}
                      </button>
                      <button
                        type="button"
                        disabled={generatingSubtitleId !== null || deletingClipId !== null}
                        onClick={() => openSubtitleForm(clip)}
                      >
                        {subtitleClipId === clip.clip_id ? "Close" : "Add Subtitle"}
                      </button>
                      <button
                        className="danger-button"
                        type="button"
                        disabled={
                          deletingClipId !== null ||
                          generatingSubtitleId !== null ||
                          generatingTranscriptId !== null ||
                          detectingHighlightId !== null
                        }
                        onClick={() => deleteClip(clip)}
                      >
                        {deletingClipId === clip.clip_id ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                    {transcriptOpen && transcript && (
                      <section className="transcript-panel">
                        <div className="transcript-meta">
                          <span>provider: {transcript.provider}</span>
                          <span>status: {transcript.status}</span>
                          <span>updated: {formatDate(transcript.updated_at)}</span>
                        </div>
                        <p className="transcript-text">
                          {transcript.transcript_text ?? "Transcript belum tersedia."}
                        </p>
                        {transcript.error_message && (
                          <p className="transcript-error">error: {transcript.error_message}</p>
                        )}
                      </section>
                    )}
                    {highlightOpen && highlightPayload && (
                      <section className="highlights-panel">
                        <div className="transcript-meta">
                          <span>transcript: {highlightPayload.transcript_id}</span>
                          <span>candidates: {highlightItems.length}</span>
                        </div>
                        <div className="highlight-list">
                          {highlightItems.map((highlight) => (
                            <article className="highlight-item" key={highlight.highlight_id}>
                              <div className="highlight-header">
                                <strong>score: {highlight.score}</strong>
                                <span>
                                  {highlight.start_time} - {highlight.end_time}
                                </span>
                                <span>duration: {highlight.duration}</span>
                              </div>
                              <p className="highlight-reason">reason: {highlight.reason}</p>
                              <p className="highlight-text">{highlight.text}</p>
                            </article>
                          ))}
                        </div>
                      </section>
                    )}
                    {aiHighlightOpen && aiHighlightPayload && (
                      <section className="highlights-panel">
                        <div className="transcript-meta">
                          <span>provider: {aiHighlightItems[0]?.provider ?? "-"}</span>
                          <span>rankings: {aiHighlightItems.length}</span>
                        </div>
                        <div className="highlight-list">
                          {aiHighlightItems.map((highlight) => (
                            <article className="highlight-item" key={highlight.ai_ranking_id + highlight.highlight_id}>
                              <div className="highlight-header">
                                <strong>score: {highlight.score}</strong>
                                <span>{highlight.title}</span>
                                <span>
                                  {highlight.start_time ?? "-"} - {highlight.end_time ?? "-"}
                                </span>
                              </div>
                              <p className="highlight-reason">reason: {highlight.reason}</p>
                              <p className="highlight-text">caption: {highlight.caption}</p>
                              <p className="highlight-text">
                                hashtags: {highlight.hashtags.length > 0 ? highlight.hashtags.join(", ") : "-"}
                              </p>
                            </article>
                          ))}
                        </div>
                      </section>
                    )}
                    {subtitleClipId === clip.clip_id && (
                      <form className="subtitle-form" onSubmit={(event) => generateSubtitle(event, clip)}>
                        <label>
                          Subtitle
                          <textarea
                            value={subtitleText}
                            maxLength={500}
                            required
                            onChange={(event) => setSubtitleText(event.target.value)}
                          />
                        </label>
                        <div className="subtitle-time-grid">
                          <label>
                            Start time
                            <input
                              type="text"
                              value={subtitleStartTime}
                              required
                              onChange={(event) => setSubtitleStartTime(event.target.value)}
                            />
                          </label>
                          <label>
                            End time
                            <input
                              type="text"
                              value={subtitleEndTime}
                              required
                              onChange={(event) => setSubtitleEndTime(event.target.value)}
                            />
                          </label>
                        </div>
                        <button type="submit" disabled={generatingSubtitleId !== null}>
                          {generatingSubtitleId === clip.clip_id ? "Generating..." : "Generate Subtitle"}
                        </button>
                      </form>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </article>
      </section>
    </main>
  );
}
