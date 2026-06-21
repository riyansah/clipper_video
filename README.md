# Clipper Video

Aplikasi web lokal untuk upload MP4, manual cut, auto split, output `original` atau `vertical_9_16`, preview, download, riwayat, dan cleanup video/clip.

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
- Metadata video, clip, dan job tersimpan di SQLite
- Delete clip atau video beserta file lokal dan metadata terkait

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

Jika backend tidak berjalan di `http://localhost:8000`, salin `frontend/.env.example` ke `frontend/.env.local` lalu isi `NEXT_PUBLIC_API_URL`.

## Menjalankan aplikasi

Paling mudah:

```bash
./launcher.sh
```

Launcher menjalankan backend di `http://localhost:8000` dan frontend di `http://localhost:3000`.

Manual:

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

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
- `DELETE /clips/{clip_id}`

`GET /videos` mengembalikan `video_id`, `original_filename`, `stored_filename`, `file_path`, dan `created_at`.

`GET /videos/{video_id}/clips` mengembalikan `clip_id`, `video_id`, `job_id`, `start_time_seconds`, `duration`, `output_format`, `width`, `height`, `filename`, `file_path`, `download_url`, dan `created_at`.

Auto split menerima `clip_duration_seconds`, `max_clips`, dan `output_format`; jika durasi tidak dikirim, backend memakai default 60 detik.

## Test endpoint delete dengan curl

Ambil `clip_id` dari `GET /videos/{video_id}/clips`, lalu hapus satu clip:

```bash
curl -X DELETE http://localhost:8000/clips/CLIP_ID
```

Ambil `video_id` dari `GET /videos`, lalu hapus video beserta semua clip dan job terkait:

```bash
curl -X DELETE http://localhost:8000/videos/VIDEO_ID
```

Response sukses melaporkan metadata dan file yang dihapus. Jika metadata ada tetapi file fisiknya sudah tidak ada, delete tetap sukses dan response melaporkan file yang tidak ditemukan.

## Test dari browser

1. Jalankan backend dan frontend.
2. Buka `http://localhost:3000`.
3. Upload MP4, lalu buat clip dengan manual cut atau auto split.
4. Klik `History` atau buka `http://localhost:3000/history`.
5. Klik `Lihat Clips` pada salah satu video.
6. Klik `Delete` pada satu clip, konfirmasi, lalu pastikan clip hilang dari tampilan.
7. Klik `Delete video`, baca konfirmasi bahwa semua clip ikut dihapus, lalu konfirmasi.
8. Pastikan video hilang dan panel clip kosong jika video tersebut sebelumnya dipilih.

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

Rilis delete dan cleanup storage dicatat sebagai `0.11.0`.

## Batasan

- Tidak memakai PostgreSQL
- Tidak memakai Docker
- Tidak memakai AI
- Tidak memakai auth atau payment
- Belum memakai crop otomatis berbasis objek/wajah
