# Clipper MVP

Aplikasi web lokal untuk memotong video, dibuat dengan Next.js, FastAPI, dan FFmpeg.

## Struktur

```text
clipper/
├── frontend/       # Next.js App Router
├── backend/        # FastAPI dan test
├── uploads/        # Video sumber (tidak masuk Git)
└── outputs/        # Clip hasil proses (tidak masuk Git)
```

## Prasyarat

- Node.js 22 LTS dan npm
- Python 3.12+
- FFmpeg

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

Instal Node.js 22 LTS menggunakan NodeSource, `nvm`, atau package manager sistem yang sesuai.

## Menjalankan backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check tersedia di `http://localhost:8000/health` dan dokumentasi API di
`http://localhost:8000/docs`.

Jalankan test backend:

```bash
cd backend
source .venv/bin/activate
pytest
```

## Upload video MP4

Dengan backend berjalan, upload menggunakan field multipart `file`:

```bash
curl -X POST http://localhost:8000/videos/upload \
  -F "file=@/path/to/video.mp4"
```

File tersimpan di `backend/uploads/` dengan nama UUID dan tidak dimasukkan ke Git.

## Memotong dan mengunduh video

Gunakan `video_id` dari respons upload untuk membuat clip:

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/cut \
  -H "Content-Type: application/json" \
  -d '{"start_time":"00:01:00","duration":30}'
```

Gunakan `download_url` dari respons cut untuk mengunduh hasil:

```bash
curl -OJ http://localhost:8000/clips/CLIP_ID/download
```

Clip tersimpan di `backend/outputs/` dan tidak dimasukkan ke Git.

Ubah clip menjadi format vertical 9:16:

```bash
curl -X POST http://localhost:8000/clips/CLIP_ID/vertical
```

## Auto split video

Tanpa `clip_duration_seconds`, setiap clip menggunakan durasi default 60 detik:

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/auto-split \
  -H "Content-Type: application/json" \
  -d '{"max_clips":5}'
```

Durasi custom tetap dapat dikirim melalui `clip_duration_seconds`.

## Menjalankan frontend

Frontend menyediakan upload, manual cut, auto split, preview, konversi 9:16, dan download. API default menggunakan `http://localhost:8000`; salin `frontend/.env.example` ke `.env.local` jika URL perlu diubah.

Gunakan terminal terpisah:

```bash
cd frontend
npm install
npm run dev
```

Buka `http://localhost:3000`.
