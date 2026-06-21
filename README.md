# Clipper Video

Clipper Video adalah aplikasi web lokal untuk upload video MP4, memotong clip manual, auto split video, dan membuat output vertikal 9:16 dengan FFmpeg.

Stack:

- Backend: FastAPI
- Frontend: Next.js App Router
- Video processing: FFmpeg / FFprobe
- Storage: file lokal di `backend/uploads` dan `backend/outputs`
- Database: SQLite `backend/clipper.db`

## Fitur

- Upload video `.mp4`
- Manual cut berdasarkan `start_time` dan `duration`
- Auto split video dengan default durasi 60 detik per clip
- Output format:
  - `original`
  - `vertical_9_16`
- Output vertical 9:16 menghasilkan MP4 `1080x1920`
- Vertical 9:16 memakai blur background; video utama tetap utuh di tengah
- Preview dan download hasil clip dari frontend
- Metadata video dan clip tersimpan di SQLite
- API download clip tetap di `/clips/{clip_id}/download`

## Struktur proyek

```text
clipper/
├── backend/          # FastAPI app, SQLite database runtime, requirements, dan test
├── frontend/         # Next.js frontend
├── uploads/          # Placeholder folder upload
├── outputs/          # Placeholder folder output
├── launcher.sh       # Script menjalankan backend + frontend
└── README.md
```

File upload dan output runtime disimpan di:

- `backend/uploads/`
- `backend/outputs/`
- `backend/clipper.db`

Folder runtime tersebut tidak ditujukan untuk masuk Git.

## Prasyarat

- Python 3.12+
- Node.js 22 LTS dan npm
- FFmpeg dan FFprobe

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

## Setup backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Setup frontend

```bash
cd frontend
npm install
```

Jika API backend tidak berjalan di `http://localhost:8000`, salin env example:

```bash
cd frontend
cp .env.example .env.local
```

Lalu sesuaikan `NEXT_PUBLIC_API_URL`.

## Cara menjalankan aplikasi

Cara paling mudah:

```bash
./launcher.sh
```

Launcher akan menjalankan:

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:3000`

Buka aplikasi di:

```text
http://localhost:3000
```

Hentikan dengan `Ctrl+C`.

## Menjalankan manual tanpa launcher

Terminal 1:

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## API

### Health check

```bash
curl http://localhost:8000/health
```

### Upload video MP4

```bash
curl -X POST http://localhost:8000/videos/upload \
  -F "file=@/path/to/video.mp4"
```

Contoh response:

```json
{
  "video_id": "VIDEO_ID",
  "original_filename": "video.mp4",
  "stored_filename": "VIDEO_ID.mp4",
  "file_path": "uploads/VIDEO_ID.mp4"
}
```

### Manual cut original

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/cut \
  -H "Content-Type: application/json" \
  -d '{"start_time":"00:01:00","duration":60}'
```

`output_format` default adalah `original`.

### Manual cut vertical 9:16

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/cut \
  -H "Content-Type: application/json" \
  -d '{"start_time":"00:01:00","duration":60,"output_format":"vertical_9_16"}'
```

Contoh response clip:

```json
{
  "clip_id": "CLIP_ID",
  "video_id": "VIDEO_ID",
  "start_time": "00:01:00",
  "start_time_seconds": 60,
  "duration": 60,
  "output_format": "vertical_9_16",
  "width": 1080,
  "height": 1920,
  "filename": "CLIP_ID.mp4",
  "file_path": "outputs/CLIP_ID.mp4",
  "download_url": "/clips/CLIP_ID/download"
}
```

### Auto split original

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/auto-split \
  -H "Content-Type: application/json" \
  -d '{"max_clips":5}'
```

Tanpa `clip_duration_seconds`, default durasi per clip adalah 60 detik.

### Auto split vertical 9:16

```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/auto-split \
  -H "Content-Type: application/json" \
  -d '{"clip_duration_seconds":60,"max_clips":5,"output_format":"vertical_9_16"}'
```

Contoh response:

```json
{
  "video_id": "VIDEO_ID",
  "clip_duration_seconds": 60,
  "max_clips": 5,
  "output_format": "vertical_9_16",
  "clips": [
    {
      "clip_id": "CLIP_ID",
      "video_id": "VIDEO_ID",
      "start_time_seconds": 0,
      "duration": 60,
      "output_format": "vertical_9_16",
      "width": 1080,
      "height": 1920,
      "filename": "CLIP_ID.mp4",
      "file_path": "outputs/CLIP_ID.mp4",
      "download_url": "/clips/CLIP_ID/download"
    }
  ]
}
```

### Download clip

```bash
curl -OJ http://localhost:8000/clips/CLIP_ID/download
```

### Database metadata

SQLite otomatis dibuat di `backend/clipper.db`.

Tabel `videos`:

- `id`
- `video_id`
- `original_filename`
- `stored_filename`
- `file_path`
- `created_at`

Tabel `clips`:

- `id`
- `clip_id`
- `video_id`
- `start_time_seconds`
- `duration`
- `output_format`
- `width`
- `height`
- `filename`
- `file_path`
- `download_url`
- `created_at`

Daftar semua video:

```bash
curl http://localhost:8000/videos
```

Detail video:

```bash
curl http://localhost:8000/videos/VIDEO_ID
```

Daftar clip untuk video:

```bash
curl http://localhost:8000/videos/VIDEO_ID/clips
```

Detail clip:

```bash
curl http://localhost:8000/clips/CLIP_ID
```

## Format vertical 9:16

Output `vertical_9_16` menggunakan FFmpeg filter:

```text
[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30[bg];[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]
```

Efeknya:

- background memenuhi canvas `1080x1920` dan diblur
- foreground diskalakan agar tetap utuh
- foreground ditempatkan di tengah
- output tetap MP4

## Testing

Backend:

```bash
cd backend
.venv/bin/python -m pytest
```

Frontend lint:

```bash
cd frontend
npm run lint
```

Frontend build:

```bash
cd frontend
npm run build
```

## Versioning dan update logs

Versi aplikasi saat ini dicatat di `VERSION`.

Setiap perubahan kode, perilaku aplikasi, atau proses proyek harus memperbarui `CHANGELOG.md`, `README.md`, dan `VERSION` dalam change set yang sama sebelum commit. Gunakan format versi semantik sederhana:

- `MAJOR` untuk perubahan besar yang tidak kompatibel
- `MINOR` untuk fitur baru
- `PATCH` untuk bug fix kecil

Rilis Tahap 7 ini dimulai dari `0.7.0`; pembaruan aturan dokumentasi ini dicatat sebagai `0.7.1`.

## Catatan batasan

- Tidak memakai PostgreSQL
- Tidak memakai Docker
- Tidak memakai AI
- Tidak memakai face tracking
- Belum memakai crop otomatis berbasis objek/wajah
