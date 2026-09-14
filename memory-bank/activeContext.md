# Active Context — Trạng thái hiện tại

**Cập nhật lần cuối:** 2026-09-14 — Thêm cột Target (admin-only) vào báo cáo
"Downtime by Category": bảng `downtime_targets` (khoá `category`, 2 giá trị
`target_pct`/`target_hours` độc lập), API `GET/POST /dyeing/downtime/api/
targets`, và UI inline-edit đầu tiên trong dự án cho kiểu Target (trước đó
`batch_matrix_targets` mới chỉ có API, chưa có UI — xem mục -9 bên dưới để
biết chi tiết đầy đủ. Cùng ngày, đã sửa 3 bug thật phát sinh khi test import
Batch Detail trên Postgres/Vercel: (1) `CardinalityViolation` khi
`executemany()` bị gộp thành 1 câu `INSERT...ON CONFLICT` duy nhất trên
Postgres mà file Excel có dòng trùng khoá UPSERT, và (2) `TypeError` vì
`production_date_sql_expr()` trả về `datetime.date` (Postgres) thay vì `str`
(SQLite) cho CÙNG 1 biểu thức SQL — xem `core/production_time.py::
normalize_production_date()`. Bản ghi trước đó (2026-09-12 — Sidebar thu gọn
được, Light Mode mặc định, trang Downtime chia 3 tab, sửa bug Case Notes)
vẫn giữ nguyên ở mục -8, chi tiết đầy đủ ở `systemPatterns.md` mục 6.2.

## Đang làm
- Khung Phase 1 (Application Factory, Auto-loader 2 cấp, SQLite WAL, Graphify,
  Memory Bank) đã ổn định, không đổi.
- Domain `dyeing` hiện có 7 Engine: `oee`, `downtime`, `excel_import`,
  `manual_entry`, `reports`, `batch_matrix`, `rft` (bản ghi cũ của file này
  từng chỉ liệt kê 3/6 — lưu ý cập nhật lại mỗi khi thêm Engine mới, đừng để
  lệch).
- **Engine `rft` (Right First Time) — MỚI THÊM 2026-09-13, mới ở dạng KHUNG
  SƯỜN (scaffold), CHƯA có quy tắc phân loại thật**: báo cáo 6 bảng (tab)
  phân loại mẻ nhuộm theo loại lần chạy — Lab to Lab, Lab to Bulk, Bulk to
  Bulk, 2nd Batch, Rework, Adjust Color (đúng thứ tự người dùng yêu cầu).
  Điều hướng bằng `page-tabs` ở đầu trang (click hoặc lăn chuột) — CÙNG cơ
  chế UI đã có ở trang Downtime (`activatePage()`/wheel handler copy gần như
  nguyên vẹn). Bộ lọc CÙNG Downtime: Capacity (Kg) multi-select (mặc định
  500/600/1200/2400), From/To Date, Group By Day/Week/Month (mặc định Week,
  khoảng ngày mặc định 6 tuần từ tuần hiện tại). Mỗi tab có 3 KPI (Total Valid
  Batches / <Category> Batches / Rate %) + 1 biểu đồ cột (Chart.js) + 1 bảng
  pivot 1-dòng theo period, route `GET /dyeing/rft/api/summary?category=<slug>&
  capacities=&from_date=&to_date=&group_by=` (`modules/dyeing/engines/rft/
  service.py::get_rft_pivot_data()`), gate bằng
  `permission_required("dyeing","rft","view")` (đã tự động xuất hiện đúng
  trong `/admin/accounts/<id>/permissions` nhờ `discover_engines()` động,
  KHÔNG cần sửa gì thêm ở Permission Model).
  **Nguồn dữ liệu**: `availability_logs` (capacity_kg/production_date/
  fabric_type, lọc `INVALID_FABRIC_TYPES` giống Downtime/Batch Matrix) LEFT
  JOIN `batch_details` (khoá `lower(trim(a.batch))=lower(trim(b.dyelot))`,
  cùng khoá JOIN đã verify 99.7% khớp ở `batch_matrix`). CHƯA có Daily Rollup
  (query trực tiếp mỗi request, chấp nhận được ở quy mô hiện tại) — cùng
  quyết định "tạm hoãn rollup tới khi công thức ổn định" đã áp dụng cho `oee`.
  **PHẦN CÒN THIẾU (người dùng sẽ hướng dẫn sau)**: hàm
  `classify_rft_category(row)` (`rft/service.py`) — quy tắc phân loại 1 mẻ
  vào ĐÚNG 1 trong 6 nhóm trên — hiện LUÔN trả về `None` nên mọi bảng/biểu đồ
  hiển thị đúng cấu trúc/đúng pipeline lọc nhưng số liệu category = 0 (KPI
  "Total Valid Batches" vẫn ra số thật, chứng minh pipeline lọc/JOIN/
  production_date đúng). Các cột `batch_details` có khả năng liên quan tới
  quy tắc phân loại sau này (CHƯA xác nhận ý nghĩa từng giá trị):
  `batch_type`, `formula_type`, `process_type`, `redye`, `is_rework`,
  `correction_cnt`. Khi có quy tắc cụ thể, CHỈ cần sửa hàm này (và có thể
  thêm cột chi tiết vào bảng pivot nếu người dùng muốn nhiều hơn 1 dòng) —
  routes/template/JS không cần đổi cấu trúc.
  **Verify đã làm**: dựng Flask app + DB SQLite tạm (script scratch, không
  lưu lại trong `tests/` vì logic phân loại thật chưa tồn tại để test có ý
  nghĩa) — xác nhận mẻ qua đêm (StartTime 21:00 hôm trước/EndTime 02:00 hôm
  sau) được gán đúng `production_date` hôm trước (cắt ca 7h sáng), mẻ
  FabricType "Unknow" và Capacity ngoài bộ lọc bị loại đúng, JSON trả về đúng
  cấu trúc JS cần. Full regression qua Flask test client: trang `/dyeing/rft/`
  200, xuất hiện đúng trên Hub + Sidebar + ma trận quyền admin.
- **Engine `batch_matrix`**: pivot Fabric Type x Color Group x Ngày sản xuất.
  **Nguồn dữ liệu (bản mới nhất, đã đổi so với bản đầu)**:
  - Tử số (số mẻ) đếm từ `availability_logs` — MỖI DÒNG = 1 MẺ (không còn
    đếm từ `batch_details`, không còn lọc `batch_type='Rework'` ở bước này
    vì `availability_logs` không có cột đó).
  - **Mẫu số ĐÃ ĐỔI CÔNG THỨC (2026-09-10)**: từ "số máy DISTINCT đã chạy"
    sang "tổng giờ máy chạy thực tế quy đổi máy tương đương"
    (`operating_hours/24`, bảng riêng `batch_matrix_capacity_hours_daily`)
    — xem chi tiết đầy đủ + bài học ở `systemPatterns.md` mục 6.2.
  - Fabric Type lấy trực tiếp từ `availability_logs.fabric_type` (loại rỗng/
    "Unknow(n)" như cũ).
  - Color Group: `availability_logs` KHÔNG có Shade/ColourNo -> LEFT JOIN
    `batch_details` theo **`availability_logs.batch = batch_details.dyelot`**
    (verify thật: 99.7% khớp trên toàn bộ dữ liệu, 90.7% dòng phân loại được
    màu sau khi lọc FabricType — trên ngưỡng 90%, xác nhận khoá join đúng).
    Quy tắc: Shade=Dark + ColourNo chứa "BLACK" -> "Black" (Dark còn lại giữ
    "Dark"); Shade=Light + ColourNo chứa "WHITE" -> "White" (Light còn lại
    giữ "Light"); Shade=Medium -> "Medium"; JOIN không khớp HOẶC Shade rỗng
    -> nhóm riêng **"Không xác định"** (hiển thị cuối mỗi Fabric Type, KHÔNG
    bỏ qua, KHÔNG gộp nhầm).
  - Bộ lọc: đổi từ Machine Group multi-select -> **Capacity (Kg)**
    multi-select (giá trị rời rạc từ `availability_logs.capacity_kg`).
  - **Filter Từ ngày/Đến ngày ĐÃ CÓ LẠI** (tuỳ chọn — không chọn thì cột ngày
    tự lấy MIN..MAX `production_date` thực tế trong `availability_logs`).
    Đổi filter Capacity KHÔNG làm thay đổi tập cột ngày hiển thị (chỉ đổi giá
    trị ô) — cố tình thiết kế vậy để UX ổn định khi bật/tắt filter Capacity.
  - **Chỉ tính mẻ có `batch_type='Normal'`** (đổi từ "loại Rework" sang
    whitelist "chỉ Normal" — lấy `batch_type` qua JOIN `batch_details` vì
    `availability_logs` không có cột này). Dòng JOIN không khớp (không xác
    định được BatchType) vẫn ĐƯỢC GIỮ (không đủ căn cứ để loại) — verify thật:
    loại 149/493 dòng (Rework/Unknown/Redye đã xác định), giữ 344 dòng.
  - Công thức Sum(tử theo ngày)/Sum(mẫu theo ngày) ở mọi cấp gộp (ô ngày, cột
    Total, dòng Total phụ theo Fabric Type, Grand Total) — GIỮ NGUYÊN nguyên
    tắc gộp (Sum/Sum ≠ trung bình cộng), chỉ đổi GIÁ TRỊ mẫu số bên trong
    (xem mục trên + `systemPatterns.md` mục 6.2).
  - Target (mục tiêu kinh doanh để tô màu xanh/đỏ) lưu trong bảng cấu hình
    `batch_matrix_targets(fabric_type, color_group, target_value)` — CHƯA có
    admin UI để sửa (mới có API `GET/POST /api/targets`), người dùng chủ
    động để dành cho Phase sau.
- Import dữ liệu thực tế của xưởng đã đủ 3 loại **Availability / Performance /
  Batch** (không chỉ Telemetry/Downtime như bản ghi cũ mô tả) — xem chi tiết
  kiến trúc ở `systemPatterns.md` mục 6.
- Báo cáo **Machine Scheduling Matrix** (Cleaning MC Ratio, `reports` engine)
  phân loại Batch Badge (CM/B/D/M/L/W + Rework) từ dữ liệu Availability +
  Batch Detail thật. **Nay đọc từ `cleaning_mc_daily_summary`** (Daily Rollup,
  xem quyết định -2 bên dưới) thay vì JOIN trực tiếp mỗi lần đổi filter.
- **Raw Data Viewer** (Drawer xem/sửa/xoá dữ liệu đã import, không cần
  upload lại file) đã hoàn thiện cho cả 3 loại import.
- **Permission Model** (mới, xem quyết định -6 bên dưới + `systemPatterns.md`
  mục 10): mọi route Engine (7 Engine: `dyeing.oee/downtime/batch_matrix/
  manual_entry/reports/excel_import`, `knitting.oee`) đã gate bằng
  `permission_required(domain, engine_name, action)`. admin không đổi hành
  vi gì. **Tài khoản `operator` demo hiện có 0 dòng quyền** (sidebar rỗng,
  mọi Engine bị chặn) cho tới khi chạy `flask sync-permissions --yes` (CHƯA
  chạy, chờ xác nhận) hoặc admin gán tay qua `/admin/accounts`.

## Quyết định gần đây (theo thứ tự thời gian, mới nhất trước)
-9. **Thêm cột Target (admin-only) vào báo cáo "Downtime by Category" + 2 bug
   thật phát hiện khi test import trên Postgres/Vercel** (2026-09-14, theo
   yêu cầu người dùng). **Target**: bảng `downtime_targets` mới (khoá
   `category`, 2 cột giá trị `target_pct`/`target_hours` — độc lập vì báo cáo
   có nút chuyển đổi đơn vị Hours/Percentage sẵn); API `GET /dyeing/downtime/
   api/targets` (`permission_required(..., "view")` — ai xem báo cáo cũng
   xem được target để tô màu đúng) và `POST` cùng URL (`role_required("admin")`
   — chặn CỨNG theo role, KHÔNG dùng `permission_required(..., "edit")` như
   `batch_matrix_targets` đang làm, vì yêu cầu là "chỉ admin", không phải
   "ai có quyền edit engine downtime"). `get_downtime_pivot_data()` gắn thêm
   `target_pct`/`target_hours` vào từng dòng `rows` (frontend không cần gọi
   API target riêng để vẽ bảng — chỉ dùng route GET khi cần, ví dụ debug).
   Cột Target đặt ngay sau Category, đổi giá trị hiển thị theo đúng nút
   Hours/Percentage đang chọn (theo yêu cầu người dùng, không tách 2 cột cố
   định). Ô giá trị theo kỳ VÀ ô Total vượt target của category đó được tô
   `background-color: rgba(248, 81, 73, .15)` (hồng nhạt). UI inline-edit
   (`target-cell`/`target-input` trong `downtime.js`) là LẦN ĐẦU implement
   UI sửa Target thật trong dự án — copy nguyên khuôn `case-note-cell` đã có
   sẵn cho Downtime Case Notes; `batch_matrix_targets` (tiền lệ Target đầu
   tiên trong dự án, xem mục "Đang làm" phía trên) tới nay vẫn CHƯA có UI
   sửa, chỉ có API. Schema Postgres tương ứng đã thêm vào
   `supabase/schema.sql` (kèm `enable row level security`) — **CHƯA CHẠY
   trên Supabase production**, cần áp DDL này thủ công trước khi tính năng
   hoạt động trên Vercel.
   **2 bug thật phát hiện cùng ngày** (test import Batch Detail thật trên
   Vercel/Supabase, KHÔNG liên quan tính năng Target): (1)
   `psycopg2.errors.CardinalityViolation` — `_PostgresConnCompat.executemany()`
   gộp toàn bộ dòng thành 1 câu `INSERT...ON CONFLICT DO UPDATE` duy nhất
   (tối ưu hiệu năng thêm hôm trước), Postgres từ chối nếu file Excel có 2
   dòng trùng khoá UPSERT trong CÙNG 1 lần import — sửa bằng cách khử trùng
   theo khoá UPSERT (giữ dòng CUỐI) trước khi gọi `executemany()`, ở cả
   `core/batch_importer.py::sync_batch_details()` và
   `core/excel_importer.py::save_to_db()`. (2) `TypeError:
   strptime() argument 1 must be str, not datetime.date` — CÙNG 1 biểu thức
   `production_date_sql_expr()` nhưng SQLite trả `str`, Postgres (`::date`
   cast) trả `datetime.date` qua psycopg2; không chỉ crash ở
   `core/batch_importer.py`/`core/rollup.py`, còn làm MẤT DỮ LIỆU ÂM THẦM
   (không exception) ở `batch_matrix/service.py`/`downtime/service.py` vì
   giá trị `date` object không khớp key `str` khi dùng làm dict key — đã
   thêm `core/production_time.py::normalize_production_date()` và áp dụng ở
   mọi nơi đọc production_date từ kết quả SQL computed expression (không áp
   dụng cho cột TEXT đã lưu sẵn trong bảng summary — những cột đó luôn `str`
   ở cả 2 dialect).

-8. **UI/UX polish sau redesign + sửa bug thật "Downtime Case Notes" dùng chung nhầm
   category** (2026-09-12): (1) Sidebar thu gọn được (`static/js/sidebar_toggle.js` mới,
   nút mép sidebar, trạng thái lưu `localStorage`); (2) Đổi mặc định Light Mode (trước là
   Dark) — logic áp `data-color-mode` đã lưu chuyển từ cuối `<body>` (`theme_toggle.js`)
   lên script đồng bộ ĐẦU `<head>` trong `base.html` để tránh FOUC (chớp sai theme lúc
   chuyển trang, lộ rõ ra sau khi thêm View Transitions bên dưới); (3) Trang Downtime
   chia 3 tab (Overview/Standard Achievement Breakdown/Data Quality, chuyển bằng click
   hoặc lăn chuột trên thanh tab), mỗi tab có biểu đồ riêng (biểu đồ Achievement đổi
   sang line chart theo yêu cầu), mặc định Capacity=500/600/1200/2400, Group By=Week,
   khoảng ngày mặc định 6 tuần tính từ tuần hiện tại; (4) Thêm View Transitions API
   (CSS `@view-transition`, thuần CSS không JS) để chuyển trang giữa các báo cáo có
   crossfade mượt thay vì reload cứng — khắc phục cảm giác "trôi" khi thuyết trình.
   (5) **Bug thật phát hiện + sửa**: `_empty_result()` (`downtime/service.py`) thiếu
   field `values_hours`/`datasets_hours` gây crash JS toàn bộ khi dataset rỗng (Known
   Issue cũ trong `progress.md`, nay đã sửa dứt điểm). (6) **Bug thiết kế thật phát hiện
   + sửa** (người dùng report trực tiếp): `downtime_case_notes` khoá
   `UNIQUE(availability_log_id)` khiến 1 mẻ xuất hiện ở nhiều category/field khác nhau bị
   DÙNG CHUNG 1 note — đã thêm cột `context`, đổi khoá thành
   `UNIQUE(availability_log_id, context)`, giữ tương thích ngược 27 note thật trên
   Supabase qua fallback `context=''` — chi tiết đầy đủ ở `systemPatterns.md` mục 6.2.
   **CHƯA CHẠY trên Supabase production** — xem "Việc tiếp theo".

-7. **Redesign toàn bộ giao diện web + đổi thương hiệu "MES Dashboard" ->
   "CETVN IE DASHBOARD"** (2026-09-11, theo yêu cầu người dùng, dựa trên bộ
   style reference `design/DESIGN.md`/`theme.css`/`variables.css`/`tokens.json`
   — theme "AgentQL: Aurora glow over a midnight terminal"). Đã hỏi người
   dùng 3 quyết định trước khi code (không tự suy đoán): (1) bỏ hẳn Primer CSS
   viết design system riêng (thay vì chỉ override token), (2) load font
   Figtree/Inter/IBM Plex Mono qua Google Fonts CDN (giống cách Primer đang
   load), (3) vẫn giữ Light Mode dù bản gốc chỉ định nghĩa Dark — tự suy diễn
   thêm bảng màu Light theo đúng vai trò từng lớp bề mặt của bản Dark.
   Chi tiết kỹ thuật đầy đủ (bao gồm mẹo giữ tên class Primer cũ làm hook +
   alias biến CSS `--color-canvas-default`... để không phải sửa lại từng
   template/JS) đã ghi ở `techContext.md` mục Frontend — không lặp lại ở đây.
   **Phạm vi đã sửa**: `static/css/app.css` (viết lại hoàn toàn), `templates/
   base.html` (bỏ CDN Primer, thêm Google Fonts, sidebar mới có nút toggle
   Dark/Light), `static/js/theme_toggle.js` (bắn thêm custom event
   `colormodechange` để Chart.js vẽ lại đúng màu khi đổi theme),
   `modules/dyeing/engines/downtime/static/downtime.js` (màu biểu đồ Chart.js
   đọc động từ CSS variable thay vì hardcode, tự vẽ lại khi đổi theme),
   `modules/dyeing/engines/reports/templates/cleaning_matrix_view.html` (2
   chỗ màu cảnh báo/ratio hardcode kiểu nền sáng, không hợp Dark Mode — đổi
   sang token `--warning`/`--success`/`--danger`), `graphify/templates/
   graph_view.html` (màu node/edge/legend đồng bộ theo token mới). Đổi tên
   thương hiệu ở: `templates/base.html` (title, sidebar brand), `templates/
   dashboard.html` (dòng giới thiệu), `README.md`, `.env.example`,
   `init_db.py` (mô tả CLI), `CLAUDE.md`, `memory-bank/projectbrief.md` (chỉ
   đổi dòng tiêu đề, giữ "tên cũ: MES Dashboard" để không mất ngữ cảnh lịch
   sử) — **KHÔNG đổi** identifier kỹ thuật nội bộ (đường dẫn file DB
   `data/mes_dashboard.db`, tên bảng/cột, tên biến/hàm Python, key
   `localStorage`) vì đổi những thứ này có rủi ro phá vỡ dữ liệu/triển khai
   thật đang chạy mà không nằm trong yêu cầu "redesign giao diện".
   **Verify đã làm**: dựng Flask dev server thật (không chỉ đọc code), dùng
   Playwright (cài mới qua pip vì `chromium-cli` không có sẵn trong môi
   trường này) chụp ảnh 10 trang chính ở CẢ Dark lẫn Light Mode (Overview,
   Dyeing Hub, Downtime, Batch Matrix, Manual Entry, Cleaning MC, Graphify,
   Account Management) — toàn bộ render đúng, không lỗi CSS/layout vỡ.
   **Phát hiện phụ (không phải do redesign gây ra, đã xác nhận qua Flask
   log không có lỗi 500)**: `data/mes_dashboard.db` cục bộ trên máy dev lúc
   bắt đầu verify KHÔNG có bảng `users` (chưa từng chạy `init_db.py` trên máy
   này) — đã chạy `python init_db.py` (KHÔNG `--reset`, an toàn/idempotent
   theo đúng mô tả trong CLAUDE.md) để có tài khoản demo test đăng nhập. Khi
   test với dữ liệu Batch Matrix/Downtime rỗng (đúng vì DB mới seed chỉ có
   dữ liệu demo Telemetry cũ, không có `availability_logs` thật), phát hiện
   2 lỗi JS console `Cannot read properties of undefined (reading 'map')`
   khi trang render dataset hoàn toàn rỗng — đây là edge case CÓ SẴN TỪ TRƯỚC
   ở `downtime_view.html`/`batch_matrix_view.html` (không phải do các file
   CSS/branding vừa sửa), CHƯA sửa vì ngoài phạm vi "redesign giao diện" và
   không xảy ra với dữ liệu thật (luôn có hàng nghìn dòng `availability_logs`
   trên Supabase) — ghi lại ở đây để không quên nếu sau này cần dọn.
-6. **Thêm Permission Model — phân quyền Xem/Sửa/Xoá RIÊNG CHO TỪNG ENGINE**
   (bảng `user_permissions`, decorator `permission_required()`, blueprint
   `admin/` quản lý tài khoản, lọc `NAV_MENU` theo quyền cho operator). admin
   luôn superuser cố định, không đi qua bảng phân quyền. Đã audit TOÀN BỘ
   route hiện có của 7 Engine, phân loại view/edit/delete (excel_import có
   đủ cả 3 — "import" tính là "edit"; batch_matrix/manual_entry/reports có
   view+edit; oee (2 domain)/downtime chỉ có view — không bịa gate edit/
   delete cho Engine không có chức năng đó). `flask sync-permissions [--yes]`
   backfill quyền cho operator CŨ (mặc định view=1 mọi Engine, giữ hành vi
   không đổi đột ngột) — đã chạy THỬ (không `--yes`), in đúng bảng dự kiến
   rồi dừng, KHÔNG tự ý ghi vào DB thật (đang CHỜ XÁC NHẬN của người dùng).
   Verify: `tests/test_permission_model.py` (app Flask đầy đủ trong
   subprocess riêng, 28 case) PASS 100% — sidebar operator chỉ hiện đúng
   Engine được cấp quyền, mọi URL/API khác bị chặn không lộ JSON, action edit
   bị chặn riêng biệt với view, admin không bị ảnh hưởng gì. **Quyết định có
   chủ đích**: bỏ qua tính năng "khoá tài khoản" (deactivate) — mục này được
   đánh dấu TUỲ CHỌN trong yêu cầu gốc, chưa triển khai để tập trung đúng
   phạm vi bắt buộc.
-5. **Xoá toàn bộ mockup/demo data khỏi DB thật** — đã điều tra kỹ để phân
   biệt mock/thật trước khi xoá (nhiều bảng dùng CHUNG cả 2 loại dữ liệu),
   backup DB vào `data/backups/` trước khi xoá (project không dùng git, xoá
   nhầm không khôi phục được). Đã xoá: `machine_telemetry` (845 dòng),
   `downtime_logs` (40 dòng — cả 2 đều machine_id DY-01..DY-05 giả lập,
   Downtime engine thật không đọc bảng này), `machines` (5 dòng seed, không
   khớp `machine_code` thật nào), `import_logs` id=1 (seed mẫu). GIỮ NGUYÊN
   `users` (tài khoản đăng nhập, không phải mock) và mọi dữ liệu thật khác.
   **Hệ quả**: `/dyeing/oee/` và dropdown máy ở Manual Entry giờ RỖNG cho
   tới khi có dữ liệu máy/telemetry thật. Chi tiết đầy đủ ở `progress.md`.
-4. **Sửa bug phân loại SAI Rework do cờ `redye` — `classify_batch_badge()`
   (`reports/cleaning_matrix.py`)**: người dùng xác nhận rõ ràng `redye` nghĩa
   là mẻ QUAY LẠI máy nhuộm để chạy một QUY TRÌNH KHÁC theo kế hoạch (VD
   nhuộm thêm lớp màu), KHÔNG đồng nghĩa với Rework (sửa lỗi/chạy lại do
   hỏng) — badge "LR" trên mẻ C260661030 (`batch_type='Normal'`, `redye=1`)
   ở mục -3 bên dưới là SAI, không phải hành vi đúng như tôi từng báo cáo.
   Đã bỏ `redye_number > 0` VÀ token `"RD"` trong ColourNo/RecipeNo (cùng
   ngữ nghĩa ReDye, không phải Rework) khỏi điều kiện `is_rework` — CHỈ còn
   `batch_type == 'Rework'` (nhãn khai báo) HOẶC `log_rework_minutes > 0`
   (`availability_logs.rework_hour` — số phút Rework đo THẬT trong ca chạy
   máy, khái niệm hoàn toàn khác `redye`). Đo tác động: **192/1271 mẻ
   (15.1%) trước đây bị gắn badge Rework sai** nay đã đúng lại thành màu
   bình thường (đã chạy `flask rebuild-summaries` backfill lại toàn bộ
   `cleaning_mc_daily_summary`, `tests/verify_rollup_parity.py` PASS 100% vì
   hàm test import thẳng `classify_batch_badge()` từ source, tự động đồng bộ
   theo fix). Đã kiểm tra riêng `batch_matrix` (Ma trận số mẻ/máy/ngày) theo
   yêu cầu người dùng — **xác nhận Engine này KHÔNG dùng `redye`/`is_rework`
   ở bất kỳ đâu** (chỉ lọc theo `batch_type='Normal'`, C260661030 đã đúng
   `batch_type='Normal'` nên vốn đã được tính đúng, không cần sửa code).
-3. **Sửa bug hiển thị SAI NGÀY mẻ qua đêm trên báo cáo Cleaning MC** (phát
   hiện qua báo cáo thực tế: mẻ C260638611 EndTime 2026-08-25 09:19:55 nhưng
   hiển thị dưới cột ngày 24). Rà soát kỹ TOÀN BỘ code `.py` tính
   `production_date` (mọi nơi gọi `get_production_date()`/
   `PRODUCTION_DATE_SQL_EXPR`) — xác nhận backend đã đúng 100% (đo bằng dữ
   liệu thật: 2230/5402 mẻ có production_date lệch nhau giữa Start/EndTime,
   toàn bộ đều khớp EndTime, KHÔNG mẻ nào khớp StartTime). Bug thật nằm ở
   tầng RENDER — JS inline trong `reports/templates/cleaning_matrix_view.html`
   tự suy luận cột-ngày từ `batch.start_time.slice(0,10)` thay vì dùng
   `production_date` backend đã trả đúng — đo thực tế 1004/5402 mẻ (18.6%,
   toàn bộ mẻ qua đêm) bị hiển thị sai cột dù dữ liệu gốc đúng. Bài học quy
   trình quan trọng: rà soát bug ngày/giờ PHẢI grep cả `.html` (script inline
   trong template), không chỉ `.py`/`.js` độc lập — xem chi tiết đầy đủ +
   bài học ở `systemPatterns.md` mục 6.2. Đã sửa: `get_cleaning_matrix()`
   trả thêm `production_date` trong mỗi `item["batches"]`, JS đổi điều kiện
   lọc. Tiện thể dọn 1 chỗ trùng lặp logic (không phải bug, nhưng đúng dạng
   rủi ro): `core/excel_importer.py::calculate_production_date()` refactor
   để delegate sang `get_production_date()` thay vì tự viết công thức riêng.
   Thêm `tests/test_production_date.py` (không dùng pytest) + docstring rõ
   ràng "luôn truyền EndTime" trong `get_production_date()`. Lúc này tôi từng
   báo cáo badge "LR" trên mẻ C260661030 là KHÔNG phải bug (do `redye=1` +
   thuật toán cố tình ưu tiên tín hiệu `redye` — xem giải thích ở mục -1 lúc
   đó) — **kết luận này đã bị đảo ngược ở mục -4 phía trên**: người dùng xác
   nhận `redye` không đồng nghĩa Rework, đây THỰC SỰ là 1 bug badge riêng
   (khác hẳn bug ngày ở mục này) đã được sửa sau đó.
-2. **Daily Rollup Pattern cho `reports` (Cleaning MC)** — khảo sát Bước 1
   (bắt buộc, không giả định) phát hiện Engine này CHƯA dùng rollup, tính
   trực tiếp JOIN `availability_logs x batch_details x machines` với điều
   kiện `lower(trim(...))` ở CẢ HAI vế mỗi lần đổi filter → `EXPLAIN QUERY
   PLAN` cho thấy `SCAN` (nested-loop, không dùng được PRIMARY KEY sẵn có)
   trên 5402 x 6712 dòng → đo baseline thật **~28 giây/request**. Đã báo cáo
   phát hiện 1 điểm BẤT THƯỜNG so với `downtime`/`batch_matrix` trước khi code
   tiếp (đúng yêu cầu): Cleaning MC hiển thị **chi tiết TỪNG MẺ theo trình tự**
   (chuỗi badge/máy/ngày + đầy đủ record từng mẻ trong `item["batches"]`),
   KHÔNG phải số liệu đã gộp — nên không thể rollup kiểu đếm sẵn (count) như
   downtime/batch_matrix. Người dùng chọn: **vẫn rollup, nhưng thiết kế lại để
   giữ chi tiết từng mẻ** (không chọn phương án chỉ sửa index). Giải pháp:
   `cleaning_mc_daily_summary` lưu GRAIN 1 DÒNG = 1 MẺ (khoá
   `(production_date, availability_log_id)`), đã JOIN + phân loại badge sẵn
   (`classify_batch_badge()` chạy 1 lần trong `recompute_daily()`, không chạy
   lúc đọc báo cáo) — giữ 100% cấu trúc/nội dung API cũ, chỉ đổi THỜI ĐIỂM
   tính. Đồng thời sửa root cause riêng biệt (không phải rollup): thêm 4
   expression index `CREATE INDEX ... ON table (LOWER(TRIM(col)))` cho đúng
   4 điều kiện JOIN — đo thực tế **436ms → 3ms** (145 lần) cho
   `recompute_daily()` một ngày. Response API thực đo sau khi có cả rollup +
   index: **~90ms** (từ 28 giây, ~300 lần). `tests/verify_rollup_parity.py`
   đã thêm `legacy_get_cleaning_matrix()` (dựng lại nguyên vẹn JOIN+classify
   cũ) đối chiếu 4 scenario filter khác nhau — PASS 100%. Tiện thể phát hiện +
   sửa 1 bug "mồ côi" không liên quan: `init_db.py` vẫn giữ schema CŨ (đã lỗi)
   của `batch_matrix_daily_summary` từ TRƯỚC lần sửa bug COUNT DISTINCT ở mục
   -1 — đã đồng bộ lại khớp đúng schema thật trong service.py.
-1. **Daily Rollup Pattern** cho `downtime`/`batch_matrix` (OEE tạm hoãn — theo
   yêu cầu người dùng, vì `machine_telemetry` toàn dữ liệu demo và OEE chưa có
   khái niệm "theo ngày"). Chi tiết đầy đủ + bài học kỹ thuật (COUNT DISTINCT
   không được cộng dồn số đếm sẵn qua cấp gộp) ở `systemPatterns.md` mục 6.2.
   Điểm cần nhớ khi debug sau này: `production_date` giờ CHỈ tính đúng qua
   `core/production_time.py::get_production_date()`/`PRODUCTION_DATE_SQL_EXPR`
   — đừng viết tay `-7 hours` ở chỗ mới; `downtime/service.py::operational_bounds()`
   giờ chỉ là hàm delegate (giữ lại để không phải sửa import ở `batch_matrix`/
   `reports/cleaning_matrix`) — nguồn thật là `core/production_time.py::production_bounds()`.
   Sau MỌI lần sửa `recompute_daily()` hoặc đường đọc báo cáo của 2 Engine này,
   PHẢI chạy lại `python tests/verify_rollup_parity.py` trước khi coi là xong
   — script này đã từng bắt được 1 bug thật (xem `progress.md`), không phải
   bước hình thức.
0. **Phát hiện + sửa bug lưu sai `start_time`/`end_time` trong `batch_details`**:
   file Batch thật đôi khi có cell ScheduleTime/StartTime/EndTime KHÔNG có
   number_format kiểu ngày → openpyxl trả về số serial Excel thô (VD
   `"46273.52385416667"`) thay vì `datetime`, và code cũ không có fallback
   xử lý — 100% (222/222) dòng có dữ liệu ngày trong DB thật bị lưu sai. Đã
   thêm `_parse_batch_datetime()` (`core/batch_importer.py`, tự nhận diện +
   quy đổi serial Excel, epoch 1899-12-30) cho mọi lần import sau này, VÀ đã
   chạy backfill 1 lần sửa lại 222 dòng cũ trong DB thật (xác nhận qua người
   dùng trước khi chạy). **Bug này quan trọng vì chặn hoàn toàn báo cáo
   `batch_matrix`** (phụ thuộc `production_date` tính từ `EndTime`).
1. **Availability/Performance/Batch dùng cơ chế `detect_and_parse_file()`
   signature-detect, KHÔNG dùng `ImportSchema`/`ColumnSpec`/`run_import()`**
   (cơ chế đó chỉ còn phục vụ Telemetry/Downtime — route
   `/api/import/<schema_key>` hiện không được UI nào gọi). Quyết định này
   được xác nhận lại rõ ràng sau khi có yêu cầu "redesign toàn bộ" nhưng
   người dùng chọn giữ kiến trúc hiện có thay vì viết lại.
2. **Schema `availability_logs` đã đổi tên ~44 cột sang chuẩn `_hour`/`_kgh`**
   (VD: `rework` → `rework_hour`, thêm mới toàn bộ nhóm `_kgh`) để khớp đúng
   cấu trúc file Excel thật (`Availability_20260908to09.xlsx`): 2 đơn vị tính
   song song (Giờ / Sản lượng-Giờ) cho mỗi chỉ số. Migrate bằng
   `ALTER TABLE ... RENAME COLUMN` (giữ nguyên dữ liệu cũ, không cần re-import).
   Đã cập nhật đồng bộ: `downtime/service.py` (`CATEGORY_COLUMNS`),
   `manual_entry` (form + route), `reports/cleaning_matrix.py`.
2b. **Phát hiện + sửa bug chặn hoàn toàn import Availability/Performance
   thật**: `detect_file_type_from_headers()` (signature cũ yêu cầu cột
   Dyelot/Availability/Reason cho Availability, MC/Shift/RunTime cho
   Performance) không khớp file thật hiện tại → luôn raise ValueError ngay
   từ bước đầu. Đã sửa: chỉ dùng signature này để nhận diện sớm BATCH (khớp
   đúng file thật), còn lại rơi xuống logic `_AVAILABILITY_REQUIRED`/
   `_PERFORMANCE_REQUIRED` (đã đúng từ trước, chỉ là không bao giờ được chạy
   tới do bị chặn ở bước signature). **Đây là bug quan trọng nhất phát hiện
   được — không có nó, KHÔNG file Availability/Performance thật nào import
   được**, dù code "trông có vẻ đúng".
3. **Batch Detail mở rộng từ ~34 lên 73 cột** (`models/dyeing.py::BATCH_DETAIL_FIELDS`,
   `core/batch_importer.py::BATCH_HEADER_MAP`) khớp đúng file mẫu thật
   (`tests/fixtures/sample_imports/batch_sample.xlsx`) — các cột trước đây
   *cố tình hoãn lại* vì chưa có bằng chứng file thật có (WeightPerArea,
   ReelSpeed, PumpSpeed, SapLot, CustomerCode, CustomerPO...) nay đã xác nhận
   có thật và được thêm đầy đủ.
4. Sửa 2 alias Kg-H lệch tên so với quy tắc suy luận chung: cột thật là
   `"Test Production - Sample/Bulk order (Kg-H)"`, không phải
   `"Testing Sample/Bulk order (Kg-H)"` như suy ra từ tên field.
5. **Root cause lỗi "Giá trị số không hợp lệ: 9V2607712"**: `wo_qty`/`order_no`
   từng bị ép kiểu numeric trong khi thực tế chứa mã lệnh lẫn chữ — đã chuyển
   sang String, thêm `parse_safe_float()` không bao giờ raise (một cell lỗi
   không còn làm rớt cả dòng).
6. **Raw Data Viewer**: thêm bảng `import_log_rows` lưu snapshot raw data +
   trạng thái từng dòng của MỌI lần import — trước đây không tồn tại, dữ liệu
   dòng lỗi biến mất hoàn toàn sau response. Sửa luôn lỗi minh bạch dữ liệu
   cũ: dòng thiếu field bắt buộc từng bị `continue` âm thầm không ghi lỗi.
7. Excel Import mặc định vẫn chạy chế độ "bỏ qua dòng lỗi, commit dòng hợp
   lệ" (giữ nguyên quyết định Phase 1 cũ).
8. Quality trong công thức OEE tạm giả định 100% (giữ nguyên, chưa đổi).

## Việc tiếp theo
- **CHỜ XÁC NHẬN**: chạy `supabase/migrate_case_notes_context.sql` qua Supabase SQL
  Editor trên DB production (thêm cột `context` + đổi UNIQUE constraint cho
  `downtime_case_notes`) — CHƯA chạy, cần admin tự thực hiện vì app không có quyền
  ALTER TABLE trên Postgres theo quy ước dự án (mục 5.1). Trước khi chạy, code vẫn
  hoạt động đúng với schema CŨ (fallback context an toàn ở tầng ứng dụng), nhưng bug
  "note dùng chung nhầm giữa category" CHỈ thực sự hết trên Postgres sau khi chạy script.
- **CHỜ XÁC NHẬN**: chạy `flask sync-permissions --yes` để backfill quyền
  view=1 mọi Engine cho tài khoản `operator` demo (hiện đang bị khoá hoàn
  toàn — 0 dòng quyền) — hoặc admin tự gán tay qua `/admin/accounts`.
- Cân nhắc triển khai tính năng "khoá tài khoản" (deactivate, cột `is_active`
  ở `users`) — đã đánh dấu tuỳ chọn, CHƯA làm ở lượt vừa rồi.
- Cân nhắc dọn 2 route/schema Telemetry-Downtime không còn dùng
  (`ImportSchema`/`/api/import/<schema_key>`) nếu xác nhận chắc chắn không
  còn use case nào cần — hiện đang giữ lại vì chưa có xác nhận từ người dùng.
- `detect_file_type_from_headers()`'s `AVAILABILITY_SIGNATURE`/
  `PERFORMANCE_SIGNATURE` vẫn còn giá trị cũ sai (không raise nữa nên không
  chặn luồng, nhưng vẫn là hằng số gây hiểu nhầm nếu đọc code) — nên dọn lại
  cho khớp thực tế khi có dịp.
- Bổ sung dữ liệu chất lượng (QC) để tính Quality thực tế trong OEE.
- Triển khai đầy đủ Engine cho Domain `knitting`.

## Câu hỏi mở / Rủi ro
- `batch_matrix`: 9.3% dòng (46/493, sau lọc FabricType) rơi vào nhóm "Không
  xác định" (Shade rỗng trong `batch_details` dù JOIN khớp) — dưới ngưỡng
  10% nên KHÔNG dừng lại theo yêu cầu, nhưng nếu tỷ lệ này tăng lên đáng kể
  ở dữ liệu tương lai, có thể là dấu hiệu cần bổ sung Shade khi import Batch.
- File mẫu thật đặt tại `tests/fixtures/sample_imports/*.xlsx` (availability/
  performance/batch) — dùng để test mọi thay đổi liên quan đến Import thay vì
  đoán cấu trúc; đã dùng để phát hiện toàn bộ các bug ở mục "Quyết định gần
  đây" phía trên.
- Chưa xác nhận với vận hành viên xưởng liệu Performance/Availability có thể
  có thêm biến thể header khác ngoài các file mẫu hiện có hay không.
