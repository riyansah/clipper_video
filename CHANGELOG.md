# Changelog

Semua perubahan penting proyek ini dicatat di file ini.

Format mengikuti pola sederhana: versi, tanggal, lalu daftar perubahan.

## [0.6.0] - 2026-06-21

### Added
- Frontend Next.js sederhana untuk upload MP4, auto split, preview clip, dan download clip.
- Input `max_clips` dengan default 5 dan pilihan `output_format` `original` atau `vertical_9_16`.
- Loading state untuk upload dan processing, serta pesan error untuk file kosong, upload gagal, auto split gagal, dan backend tidak bisa dihubungi.
- File `VERSION` sebagai penanda versi aplikasi.

### Changed
- Frontend memakai `NEXT_PUBLIC_API_URL` dengan fallback `http://127.0.0.1:8000`.
- Launcher dan konfigurasi dev disiapkan agar aplikasi bisa diakses dari host lokal atau IP server.
