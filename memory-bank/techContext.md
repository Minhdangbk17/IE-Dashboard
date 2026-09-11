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
- **Design system riêng** (`static/css/app.css`, 2026-09-11 — thay thế hoàn
  toàn GitHub Primer CSS trước đây, xem `activeContext.md` mục redesign UI
  để biết lý do/quyết định) — không còn phụ thuộc CDN `unpkg.com/@primer/css`.
  Token màu/font/spacing/radius/shadow lấy từ `design/DESIGN.md`
  ("AgentQL — Aurora glow over a midnight terminal": nền tối Void/Abyss/Deep
  Sea/Cobalt Panel, accent Signal Blue/Aurora Purple, font Figtree (heading)
  + Inter (UI) + IBM Plex Mono (mono), bo góc pill cho nút/badge, card 12px).
  Hỗ trợ CẢ Dark (mặc định, đúng bản gốc) VÀ Light (tự suy diễn thêm, không
  có trong tài liệu gốc) qua `[data-color-mode]` + `theme_toggle.js`
  (đã thêm nút bấm toggle trong sidebar — trước đây có sẵn cơ chế JS nhưng
  chưa có UI trigger).
  **Kỹ thuật quan trọng** để tránh phải sửa lại từng template/JS-build-DOM
  đang dùng tên class kiểu Primer (`Box`, `Label`, `BtnGroup`, `blankslate`,
  `d-flex`, `f6`, `color-fg-muted`...): giữ NGUYÊN các tên class đó làm hook
  trong markup, nhưng định nghĩa lại 100% từ đầu trong `app.css` theo design
  system mới (không import/phụ thuộc gì vào Primer CSS thật). Đồng thời alias
  lại đúng tên biến CSS của Primer hay dùng trong `style="var(--color-x,
  #hex-fallback)"` rải rác nhiều template (`--color-canvas-default`,
  `--color-border-default`, `--color-fg-muted`, `--color-accent-emphasis`...)
  sang token mới trong `:root` — nhờ vậy các `style=` inline cũ tự động lên
  đúng theme mới mà không cần sửa từng chỗ.
- JavaScript thuần (Vanilla JS, ES2017+) — `fetch()` cho gọi API song song,
  `XMLHttpRequest` cho upload có Progress Bar (fetch chưa hỗ trợ tốt upload
  progress ở thời điểm viết Phase 1).
- SVG thuần (không dùng thư viện đồ thị ngoài) cho Graphify — giảm phụ thuộc
  external, dễ tuỳ biến layout. Màu node/edge đồng bộ theo token mới.
- Chart.js (CDN `cdn.jsdelivr.net`) cho biểu đồ Downtime — màu trục/lưới/chú
  giải đọc động từ CSS variable `--text-secondary` lúc vẽ (không hardcode),
  tự vẽ lại khi đổi Dark/Light qua custom event `colormodechange` (bắn từ
  `theme_toggle.js` mỗi lần `toggleColorMode()`).
- Google Fonts CDN (`fonts.googleapis.com`) nạp Figtree/Inter/IBM Plex Mono —
  cùng kiểu phụ thuộc CDN như Primer trước đây (chấp nhận theo yêu cầu người
  dùng), có `font-family` fallback về `system-ui`/`monospace` nếu mạng xưởng
  chặn CDN.

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
