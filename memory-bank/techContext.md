# Tech Context — Công nghệ sử dụng

## Backend
- **Python** 3.11+ (type hinting đầy đủ, `from __future__ import annotations`).
- **Flask** 3.x — Application Factory Pattern, Blueprint (bao gồm Nested Blueprint).
- **sqlite3** (module built-in) — KHÔNG dùng ORM (SQLAlchemy...) ở Phase 1 để
  giữ tối giản, dễ debug trực tiếp bằng công cụ SQLite thông thường.
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
- **openpyxl** — đọc/ghi file `.xlsx` (Excel Import Pipeline + Template Export).
- Module `csv` built-in — hỗ trợ import file `.csv`.

## Frontend
- **GitHub Primer CSS** (qua CDN `unpkg.com/@primer/css`) — design system
  chuẩn GitHub, hỗ trợ `data-color-mode="dark"`.
- JavaScript thuần (Vanilla JS, ES2017+) — `fetch()` cho gọi API song song,
  `XMLHttpRequest` cho upload có Progress Bar (fetch chưa hỗ trợ tốt upload
  progress ở thời điểm viết Phase 1).
- SVG thuần (không dùng thư viện đồ thị ngoài) cho Graphify — giảm phụ thuộc
  external, dễ tuỳ biến layout.

## Cấu trúc dữ liệu (SQLite Schema chính)
- `users` — tài khoản đăng nhập (role: admin/operator).
- `user_permissions` — phân quyền Xem/Sửa/Xoá RIÊNG CHO TỪNG ENGINE của user
  role='operator' (`user_id, domain, engine_name, can_view, can_edit,
  can_delete`, FK CASCADE khi xoá user). admin luôn superuser cố định, KHÔNG
  đi qua bảng này — xem `systemPatterns.md` mục 10 (Permission Model).
- `machines` — danh mục máy theo domain.
- `machine_telemetry` — dữ liệu vận hành máy theo thời gian.
- `downtime_logs` — lịch sử dừng máy.
- `import_logs` — lịch sử các lần import Excel/CSV.

(Danh sách trên chỉ liệt kê nhóm bảng CỐT LÕI/hạ tầng — mỗi Engine còn tự sở
hữu thêm bảng riêng, vd `*_daily_summary` của Daily Rollup Pattern — xem
`systemPatterns.md` mục 6.2 để tra cứu đầy đủ, đừng coi danh sách này là
schema hoàn chỉnh.)

## Công cụ phát triển
- `init_db.py` — script CLI khởi tạo schema + seed data mẫu.
- `flask init-db` — CLI command tương đương (đăng ký qua `core/database.py`).
- Không cần Docker/Redis/Celery ở Phase 1 — ứng dụng chạy single-process,
  phù hợp triển khai tại chỗ (on-premise) ở xưởng có hạ tầng hạn chế.

## Biến môi trường (config.py)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `SECRET_KEY` | dev-secret-key-change-in-production | Khoá ký session |
| `FLASK_DEBUG` | 1 | Bật debug mode |
| `DATABASE_PATH` | data/mes_dashboard.db | Đường dẫn file SQLite |
| `UPLOAD_FOLDER` | uploads/ | Thư mục lưu file tạm khi import |
| `IMPORT_STRICT_MODE` | 0 | 1 = chỉ commit khi 100% dòng hợp lệ |
