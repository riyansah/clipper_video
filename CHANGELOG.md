# Changelog

Semua perubahan penting proyek ini dicatat di file ini.

Format mengikuti pola sederhana: versi, tanggal, lalu daftar perubahan.

## [0.13.0] - 2026-06-22

### Added
- Endpoint `POST /clips/{clip_id}/transcribe` untuk extract audio clip dengan FFmpeg lalu membuat transcript memakai arsitektur provider.
- Tabel SQLite `transcripts` dengan kolom status, provider, transcript_text, segments_json, error_message, dan timestamp.
- `DummyTranscriptionProvider` default melalui `TRANSCRIPTION_PROVIDER=dummy` agar transcript bisa dites tanpa biaya API.
- Endpoint `GET /clips/{clip_id}/transcript` untuk mengambil transcript terbaru per clip.
- Endpoint placeholder `POST /clips/{clip_id}/auto-subtitle-from-transcript` yang saat ini mengembalikan `501 TODO`.
- Tombol `Generate Transcript` dan `View Transcript` di halaman `/history` beserta loading state dan tampilan hasil transcript.
- Tes backend untuk alur transcript sukses, gagal, 404, transcript terbaru, dan pembuatan tabel.

## [0.12.1] - 2026-06-21

### Fixed
- Memperbaiki layout frontend yang bertumpuk di layar laptop dengan membatasi style badge absolut hanya ke `.subtitle-badge`.

## [0.12.0] - 2026-06-21

### Added
- Endpoint `POST /clips/{clip_id}/subtitle` untuk membuat SRT dan burn subtitle manual dengan FFmpeg.
- Metadata clip subtitle `parent_clip_id`, `has_subtitle`, dan `subtitle_text` dengan migrasi SQLite otomatis.
- Form subtitle sederhana di `/history` dengan waktu default dari durasi clip, loading, error, preview, dan download hasil.
- Tes backend untuk SRT, FFmpeg, validasi, migrasi, 404, dan kegagalan output.

## [0.11.0] - 2026-06-21

### Added
- Endpoint `DELETE /clips/{clip_id}` untuk menghapus file clip dan metadata.
- Endpoint `DELETE /videos/{video_id}` untuk menghapus video, semua clip, job, dan file terkait.
- Validasi path storage, pelaporan file yang tidak ditemukan, serta error handling file dan database.
- Tombol delete clip dan video di `/history` dengan konfirmasi, loading state, dan pesan error.
- Tes backend untuk delete, missing file, 404, permission error, dan path di luar storage.

## [0.10.0] - 2026-06-21

### Added
- Frontend auto split sekarang menyediakan input durasi per clip dan mengirim `clip_duration_seconds` ke backend.

## [0.9.0] - 2026-06-21

### Added
- Halaman frontend `/history` untuk melihat daftar video tersimpan dan clip per video.
- Link navigasi dari halaman utama ke history dan dari history kembali ke halaman utama.
- Dokumentasi endpoint dan langkah test browser untuk halaman history.
- README diringkas menjadi panduan setup, endpoint utama, testing, dan versioning.
- Versi proyek dan metadata frontend diselaraskan ke `0.9.0`.

## [0.7.1] - 2026-06-21

### Changed
- Menetapkan aturan proyek bahwa setiap perubahan harus memperbarui `CHANGELOG.md`, `README.md`, dan `VERSION` dalam change set yang sama.

## [0.7.0] - 2026-06-21

### Added
- Metadata video dan clip disimpan ke SQLite `backend/clipper.db` memakai SQLAlchemy.
- Endpoint untuk daftar/detail video dan clip: `GET /videos`, `GET /videos/{video_id}`, `GET /videos/{video_id}/clips`, dan `GET /clips/{clip_id}`.
- Frontend bisa mengambil ulang daftar clip dari backend berdasarkan `video_id`.

## [0.6.1] - 2026-06-21

### Added
- Manual cut dikembalikan ke frontend dengan input `start_time`, `duration`, dan `output_format`.
- Hasil manual cut ditampilkan di daftar clip yang sama untuk preview dan download.

## [0.6.0] - 2026-06-21

### Added
- Frontend Next.js sederhana untuk upload MP4, auto split, preview clip, dan download clip.
- Input `max_clips` dengan default 5 dan pilihan `output_format` `original` atau `vertical_9_16`.
- Loading state untuk upload dan processing, serta pesan error untuk file kosong, upload gagal, auto split gagal, dan backend tidak bisa dihubungi.
- File `VERSION` sebagai penanda versi aplikasi.

### Changed
- Frontend memakai `NEXT_PUBLIC_API_URL` dengan fallback `http://127.0.0.1:8000`.
- Launcher dan konfigurasi dev disiapkan agar aplikasi bisa diakses dari host lokal atau IP server.
