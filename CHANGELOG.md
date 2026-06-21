# Changelog

Semua perubahan penting proyek ini dicatat di file ini.

Format mengikuti pola sederhana: versi, tanggal, lalu daftar perubahan.

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
