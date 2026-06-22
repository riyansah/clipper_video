# Clipper Video

Aplikasi web lokal untuk upload MP4, manual cut, auto split, subtitle manual, transcript clip, output `original` atau `vertical_9_16`, preview, download, riwayat, dan cleanup video/clip.

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
- Metadata video, clip, job, dan transcript tersimpan di SQLite
- Delete clip atau video beserta file lokal dan metadata terkait
- Subtitle manual yang di-burn ke clip dengan FFmpeg
- Transcript audio clip dengan provider `dummy` tanpa biaya API

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

## Konfigurasi transcript

Set provider transcript lewat environment variable di shell backend:

```bash
export TRANSCRIPTION_PROVIDER=dummy
```

Untuk tahap ini nilai yang dipakai adalah `dummy`. Provider lain sudah disiapkan di arsitektur, tetapi belum wajib dikonfigurasi.

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

`init_database()` membuat tabel ini otomatis saat backend dijalankan.

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

`segments_json` berisi satu segmen yang mengikuti durasi clip supaya mudah dipakai ke tahap berikutnya.

Endpoint `POST /clips/{clip_id}/auto-subtitle-from-transcript` saat ini baru disiapkan dan masih mengembalikan `501 TODO`.

## Test dengan curl

Generate transcript untuk clip yang sudah ada:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/transcribe
```

Lihat transcript terbaru untuk clip:

```bash
curl http://localhost:8000/clips/CLIP_ID/transcript
```

Tambah subtitle manual tetap sama seperti sebelumnya:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/subtitle \
  -H "Content-Type: application/json" \
  -d '{"subtitle_text":"teks subtitle","start_time":"00:00:00","end_time":"00:01:00"}'
```

## Test dari browser

1. Jalankan backend dengan `TRANSCRIPTION_PROVIDER=dummy` dan jalankan frontend.
2. Buka `http://localhost:3000`.
3. Upload MP4, lalu buat clip dengan manual cut atau auto split.
4. Klik `History` atau buka `http://localhost:3000/history`.
5. Klik `Lihat Clips` pada salah satu video.
6. Klik `Generate Transcript` pada clip yang ingin dites.
7. Pastikan transcript tampil dengan `transcript_text`, `provider`, `status`, dan `error_message` bila ada.
8. Klik `View Transcript` untuk mengambil transcript terbaru dari backend.
9. Jika perlu, lanjut uji `Add Subtitle`, download, dan delete untuk memastikan fitur lama tetap bekerja.

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

Rilis transcript clip dummy dicatat sebagai `0.13.0`.

## Batasan

- Tidak memakai PostgreSQL
- Tidak memakai Docker
- Tidak memakai auth atau payment
- Tidak ada AI highlight ranking atau deteksi bagian viral
- Provider transcript non-dummy belum diaktifkan di tahap ini
