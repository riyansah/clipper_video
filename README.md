# Clipper Video

Aplikasi web lokal untuk upload MP4, manual cut, auto split, subtitle manual, transcript clip, highlight detection berbasis rule, AI highlight ranking, output `original` atau `vertical_9_16`, preview, download, riwayat, dan cleanup video/clip.

## Stack

- Backend: FastAPI
- Frontend: Next.js App Router
- Video processing: FFmpeg / FFprobe
- Storage: file lokal di `backend/uploads` dan `backend/outputs`
- Database: SQLite `backend/clipper.db`

## Fitur

- Upload video `.mp4`
- Manual cut berdasarkan `start_time`, `duration`, dan `output_format`
- Auto split video dengan pilihan durasi per clip dan job status processing
- Output `original` dan `vertical_9_16`
- Preview dan download clip dari frontend
- Halaman riwayat `/history` untuk melihat video tersimpan dan clip per video
- Metadata video, clip, job, transcript, dan highlight candidate tersimpan di SQLite
- Delete clip atau video beserta file lokal dan metadata terkait
- Subtitle manual yang di-burn ke clip dengan FFmpeg
- Transcript audio clip dengan provider `dummy` tanpa biaya API
- Highlight detection berbasis rule dari transcript tanpa AI dan tanpa API eksternal
- AI highlight ranking dari transcript dengan provider `dummy` default atau provider eksternal opsional

## Setup

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

## Konfigurasi transcript dan AI highlight

Set provider transcript dan AI highlight lewat environment variable di shell backend:

```bash
export TRANSCRIPTION_PROVIDER=dummy
export AI_HIGHLIGHT_PROVIDER=dummy
```

Default tahap ini adalah `dummy`, jadi fitur transcript dan AI ranking bisa dites tanpa API key.

Jika ingin menyiapkan provider AI eksternal:

```bash
export AI_HIGHLIGHT_PROVIDER=external
export AI_HIGHLIGHT_API_URL=https://your-provider.example/api/highlight-rank
export AI_HIGHLIGHT_API_KEY=your_api_key
export AI_HIGHLIGHT_MODEL=your-model-name
```

Provider eksternal hanya mengirim maksimum 5 kandidat dan hanya mengirim `highlight_id`, `start_time`, `end_time`, serta teks yang dipotong pendek. Jika provider gagal, backend fallback ke `DummyAIHighlightRanker`.

Jika backend tidak berjalan di `http://localhost:8000`, salin `frontend/.env.example` ke `frontend/.env.local` lalu isi `NEXT_PUBLIC_API_URL`.

## Menjalankan aplikasi

Paling mudah:

```bash
./launcher.sh
```

Launcher menjalankan backend di `http://localhost:8000` dan frontend di `http://localhost:3000`.

Manual backend:

```bash
cd backend
export TRANSCRIPTION_PROVIDER=dummy
export AI_HIGHLIGHT_PROVIDER=dummy
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Manual frontend:

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## Endpoint utama

- `GET /health`
- `POST /videos/upload`
- `GET /videos`
- `GET /videos/{video_id}`
- `GET /videos/{video_id}/clips`
- `DELETE /videos/{video_id}`
- `POST /videos/{video_id}/cut`
- `POST /videos/{video_id}/auto-split`
- `POST /videos/{video_id}/auto-split-jobs`
- `GET /jobs/{job_id}`
- `GET /clips/{clip_id}`
- `GET /clips/{clip_id}/download`
- `POST /clips/{clip_id}/subtitle`
- `POST /clips/{clip_id}/transcribe`
- `GET /clips/{clip_id}/transcript`
- `POST /clips/{clip_id}/detect-highlights`
- `GET /clips/{clip_id}/highlights`
- `POST /clips/{clip_id}/ai-rank-highlights`
- `GET /clips/{clip_id}/ai-highlights`
- `POST /clips/{clip_id}/auto-subtitle-from-transcript`
- `DELETE /clips/{clip_id}`

## Struktur tabel transcripts

Tabel `transcripts` di SQLite berisi:

- `id`
- `transcript_id`
- `clip_id`
- `transcript_text`
- `segments_json`
- `provider`
- `status`
- `error_message`
- `created_at`
- `updated_at`

Status transcript yang dipakai:

- `pending`
- `processing`
- `completed`
- `failed`

## Struktur tabel highlight_candidates

Tabel `highlight_candidates` di SQLite berisi:

- `id`
- `highlight_id`
- `transcript_id`
- `clip_id`
- `video_id`
- `start_time`
- `end_time`
- `duration`
- `text`
- `score`
- `reason`
- `created_at`

## Struktur tabel ai_highlight_rankings

Tabel `ai_highlight_rankings` di SQLite berisi:

- `id`
- `ai_ranking_id`
- `highlight_id`
- `clip_id`
- `video_id`
- `score`
- `title`
- `reason`
- `caption`
- `hashtags_json`
- `provider`
- `raw_response_json`
- `created_at`

`init_database()` membuat tabel transcript, highlight candidate, dan AI highlight ranking otomatis saat backend dijalankan.

## Cara kerja TranscriptionProvider

Backend memakai arsitektur provider sederhana di `backend/app/main.py`:

- `TranscriptionProvider` sebagai interface/protocol
- `DummyTranscriptionProvider` untuk testing lokal tanpa biaya API
- `LocalWhisperProvider` dan `APITranscriptionProvider` sebagai placeholder yang belum diwajibkan

Alur `POST /clips/{clip_id}/transcribe`:

1. Backend cari metadata clip di database.
2. Backend validasi file clip di `backend/outputs`.
3. Backend buat record transcript dengan status `pending`.
4. FFmpeg extract audio sementara ke `backend/outputs/audio/{transcript_id}.wav`.
5. Provider dijalankan sesuai `TRANSCRIPTION_PROVIDER`.
6. Hasil `transcript_text` dan `segments_json` disimpan ke SQLite.
7. Jika sukses status jadi `completed`; jika gagal status jadi `failed` dan `error_message` disimpan.

Untuk provider `dummy`, transcript contoh yang dikembalikan adalah:

```text
Ini adalah transcript dummy untuk clip ini.
```

## Cara kerja AIHighlightRanker

Backend memakai arsitektur provider sederhana di `backend/app/main.py`:

- `AIHighlightRanker` sebagai interface/protocol.
- `DummyAIHighlightRanker` sebagai default untuk testing lokal tanpa API key.
- `ExternalAIHighlightRanker` sebagai provider opsional berbasis HTTP dengan API key dari environment variable.

Alur `POST /clips/{clip_id}/ai-rank-highlights`:

1. Backend mengambil highlight candidate untuk `clip_id` dan memilih maksimum 5 score tertinggi.
2. Backend hanya mengirim `highlight_id`, `start_time`, `end_time`, dan teks transcript yang dipotong pendek ke provider AI.
3. Prompt meminta output JSON array dengan field `highlight_id`, `score`, `title`, `reason`, `caption`, dan `hashtags`.
4. Backend memvalidasi `score` 0-100, `title` dan `reason` tidak kosong, serta `hashtags` harus array.
5. Hasil disimpan ke `ai_highlight_rankings` dan bisa diambil ulang lewat `GET /clips/{clip_id}/ai-highlights`.
6. Jika provider eksternal gagal, backend fallback ke `DummyAIHighlightRanker`.

Cara pakai provider dummy:

```bash
export AI_HIGHLIGHT_PROVIDER=dummy
```

Dengan nilai ini tidak perlu API key dan tombol AI ranking di `/history` langsung bisa dipakai.

## Rule scoring highlight

`POST /clips/{clip_id}/detect-highlights` mengambil transcript terbaru yang harus berstatus `completed`, lalu menjalankan scoring rule-based dari `segments_json` tanpa AI.

Rule yang dipakai:

- Durasi segment 20-60 detik mendapat skor lebih tinggi.
- Segment yang mengandung kata tanya mendapat tambahan skor.
- Segment yang mengandung angka mendapat tambahan skor.
- Segment yang mengandung kata emosional mendapat tambahan skor.
- Segment yang terlalu pendek kurang dari 10 detik mendapat penalti.
- Segment yang terlalu panjang lebih dari 90 detik mendapat penalti.

Kata tanya awal:

- `apa`
- `kenapa`
- `mengapa`
- `bagaimana`
- `gimana`
- `kapan`
- `siapa`

Kata emosional awal:

- `penting`
- `wajib`
- `jangan`
- `gagal`
- `rahasia`
- `mudah`
- `cepat`
- `mahal`
- `murah`
- `bahaya`
- `kesalahan`
- `solusi`
- `tips`

Jika transcript hanya punya satu segment panjang, backend tetap membuat minimal satu candidate dan membatasi durasi ke maksimum 60 detik bila memungkinkan.

Endpoint `POST /clips/{clip_id}/auto-subtitle-from-transcript` saat ini masih placeholder dan mengembalikan `501 TODO`.

## Test dengan curl

Generate transcript untuk clip yang sudah ada:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/transcribe
```

Lihat transcript terbaru untuk clip:

```bash
curl http://localhost:8000/clips/CLIP_ID/transcript
```

Deteksi highlight candidate untuk clip yang transcript-nya sudah `completed`:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/detect-highlights
```

Lihat daftar highlight candidate untuk clip:

```bash
curl http://localhost:8000/clips/CLIP_ID/highlights
```

Jalankan AI ranking untuk clip yang sudah punya highlight candidate:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/ai-rank-highlights
```

Lihat hasil AI highlight ranking untuk clip:

```bash
curl http://localhost:8000/clips/CLIP_ID/ai-highlights
```

Tambah subtitle manual tetap sama seperti sebelumnya:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/subtitle \
  -H "Content-Type: application/json" \
  -d '{"subtitle_text":"teks subtitle","start_time":"00:00:00","end_time":"00:01:00"}'
```

## Test dari browser

1. Jalankan backend dengan `TRANSCRIPTION_PROVIDER=dummy` dan `AI_HIGHLIGHT_PROVIDER=dummy`, lalu jalankan frontend.
2. Buka `http://localhost:3000`.
3. Upload MP4, lalu buat clip dengan manual cut atau auto split.
4. Klik `History` atau buka `http://localhost:3000/history`.
5. Klik `Lihat Clips` pada salah satu video.
6. Klik `Generate Transcript` dan pastikan transcript tampil.
7. Klik `Detect Highlights` pada clip yang transcript-nya sudah ada.
8. Pastikan daftar highlight tampil berisi `score`, `start_time`, `end_time`, `duration`, `reason`, dan `text`.
9. Klik `AI Rank Highlights` untuk menyimpan ranking AI dari maksimum 5 candidate teratas.
10. Pastikan hasil AI tampil berisi `score`, `title`, `reason`, `caption`, `hashtags`, `start_time`, dan `end_time`.
11. Klik `View AI Highlights` untuk mengambil ulang ranking dari backend dan pastikan urutannya dari score tertinggi.
12. Jika perlu, lanjut uji `Add Subtitle`, download, dan delete untuk memastikan fitur lama tetap bekerja.

## Testing

Backend:

```bash
cd backend
.venv/bin/python -m pytest
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

## Versioning dan changelog

Versi aplikasi dicatat di `VERSION`.

Setiap perubahan kode, perilaku aplikasi, atau proses proyek harus memperbarui `CHANGELOG.md`, `README.md`, dan `VERSION` dalam change set yang sama sebelum commit.

Gunakan versi semantik sederhana:

- `MAJOR` untuk perubahan besar yang tidak kompatibel
- `MINOR` untuk fitur baru
- `PATCH` untuk bug fix kecil atau dokumentasi

Rilis highlight detection berbasis rule dicatat sebagai `0.14.0`.

## Batasan

- Tidak memakai PostgreSQL
- Tidak memakai Docker
- Tidak memakai auth atau payment
- Tidak ada AI ranking, highlight ranking LLM, atau deteksi bagian viral
- Provider transcript non-dummy belum diaktifkan di tahap ini
- Belum ada auto cut dari highlight di tahap ini
