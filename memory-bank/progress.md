# Progress — Tiến độ & Backlog

## Đã hoàn thành (Phase 1 — Foundation Skeleton)
- [x] `config.py` — cấu hình tập trung, hỗ trợ biến môi trường.
- [x] `core/database.py` — SQLite WAL + connection pooling qua `flask.g`.
- [x] `core/auth.py` — login/logout tối giản, `@login_required`, `@role_required`.
- [x] `core/navigation.py` — Menu Registry + context_processor `NAV_MENU`.
- [x] `core/engine_base.py` — `BaseEngine` Abstract Class + `EngineMetadata`.
- [x] `core/excel_importer.py` — Schema validation, parse, bulk insert,
      export template Excel.
- [x] `app.py` — Application Factory + Auto-loader 2 cấp.
- [x] `init_db.py` — schema + seed data (users, machines, telemetry 7 ngày x
      5 máy, downtime ngẫu nhiên, import_logs mẫu).
- [x] Domain `dyeing`: Hub Aggregator + Engine `oee`, `downtime`, `excel_import`.
- [x] Domain `knitting`: scaffold tối giản (Engine `oee` stub).
- [x] UI Primer CSS + Dark Mode + Sidebar động theo role.
- [x] Modal Import Excel: Drag&Drop, Progress Bar, Preview Table, báo lỗi
      theo dòng.
- [x] `graphify/` — sơ đồ phụ thuộc Engine/Data Flow tự sinh (SVG).
- [x] `memory-bank/` — đầy đủ 6 file tài liệu ngữ cảnh cho AI Agent.

## Đã hoàn thành (bổ sung sau Phase 1 — Import Availability/Performance/Batch)
- [x] Import Availability/Performance qua `detect_and_parse_file()` +
      `save_to_db()` (`core/excel_importer.py`) — bảng `availability_logs`,
      `performance_logs`.
- [x] Import Batch Detail (`core/batch_importer.py::sync_batch_details()`) —
      bảng `batch_details`, mở rộng đủ 73 cột khớp file thật.
- [x] Engine `manual_entry` — nhập tay Availability khi không có file Excel.
- [x] Engine `reports` — Machine Scheduling Matrix / Cleaning MC Ratio, phân
      loại Batch Badge (CM/B/D/M/L/W/Rework) 5 bước dựa trên dữ liệu thật.
- [x] Bộ lọc Capacity (multi-select) cho Machine Scheduling Matrix.
- [x] Sửa root cause lỗi "Giá trị số không hợp lệ" khi import Batch (wo_qty/
      order_no chuyển String, `parse_safe_float()` không raise).
- [x] Viết lại `sync_batch_details()` theo pattern ghi `import_logs` trước/
      sau (audit trail đầy đủ, không còn "mất dữ liệu âm thầm").
- [x] Raw Data Viewer: bảng `import_log_rows`, `core/import_rows_service.py`,
      Drawer UI (`raw_data_drawer.js`) — xem/tìm/lọc/phân trang/virtual scroll
      (>1000 dòng)/Inline Edit/Xoá lần import, cho cả 3 loại import.
- [x] Nâng cấp UI Upload Data: dropzone có icon + validate 20MB client-side,
      progress bar 2 giai đoạn (upload % + đang xử lý), toast thành công đầy
      đủ thông tin + hành động nhanh.
- [x] Đổi tên schema `availability_logs` sang chuẩn `_hour`/`_kgh` (~44 cột)
      khớp đúng file Excel thật, migrate bằng `RENAME COLUMN` (không mất dữ
      liệu). Đồng bộ `downtime`, `manual_entry`, `reports`.
- [x] Sửa bug chặn hoàn toàn import Availability/Performance thật
      (`detect_file_type_from_headers()` signature cũ sai) — xem chi tiết
      `activeContext.md`.
- [x] Test bằng file mẫu thật (`tests/fixtures/sample_imports/*.xlsx`) thay
      vì suy đoán cấu trúc.
- [x] Engine `batch_matrix` — Ma trận Số mẻ/Máy theo Ngày (pivot Fabric Type
      x Color Group x Ngày sản xuất, công thức Sum/Sum thống nhất mọi cấp gộp,
      đã verify bằng số liệu thật khác trung bình cộng). Bảng cấu hình
      `batch_matrix_targets`. Widget tóm tắt trên Hub, sidebar tự động có
      mục nav (theo Auto-loader).
      **Đã đổi nguồn dữ liệu** (bản mới nhất): đếm mẻ/máy từ `availability_logs`
      thay vì `batch_details`; JOIN sang `batch_details` (khoá
      `availability_logs.batch = batch_details.dyelot`, verify 99.7% khớp)
      để lấy Shade+ColourNo phân loại Color Group (thêm quy tắc tách
      Black/White từ Dark/Light + ColourNo, thêm nhóm "Không xác định" hiển
      thị riêng thay vì bỏ qua); bộ lọc đổi Machine Group -> Capacity (Kg);
      bỏ hẳn bộ lọc ngày, cột ngày tự lấy MIN..MAX production_date thật.
- [x] Sửa bug lưu sai `start_time`/`end_time` (số serial Excel thô) trong
      `batch_details` + backfill 222 dòng dữ liệu thật.
- [x] **Daily Rollup Pattern** (xem `systemPatterns.md` mục 6.2) — áp dụng cho
      `downtime` + `batch_matrix` (OEE tạm hoãn, chỉ dùng dữ liệu demo). Bảng
      mới: `downtime_daily_summary`, `batch_matrix_daily_summary`. Hạ tầng
      mới: `core/production_time.py` (production_date 7h-cutover dùng chung),
      `core/engine_registry.py` (`discover_engines()`, gộp logic quét pkgutil
      trước đây trùng lặp với `graphify/mapper.py`), `core/rollup.py`
      (`trigger_recompute()`, CLI `flask rebuild-summaries`). Hook tự động
      sau mọi commit import (`import_raw_file()`, `do_import()`,
      `sync_batch_details()`), chỉ recompute đúng production_date bị ảnh
      hưởng. Đã viết `tests/verify_rollup_parity.py` đối chiếu kết quả
      rollup vs tính trực tiếp — **phát hiện 1 bug thật** (cộng dồn số đếm
      máy distinct theo Color Group lên cấp Fabric Type Total sẽ đếm trùng
      nếu cùng máy chạy nhiều Color Group/ngày) và đã sửa (lưu summary ở
      grain theo từng máy, dựng lại `set()` distinct lúc đọc thay vì cộng số
      đếm sẵn) — script này PASS 100% sau khi sửa, nên giữ lại chạy định kỳ
      mỗi khi sửa `recompute_daily()`/đường đọc báo cáo.
- [x] **Daily Rollup Pattern cho `reports` (Cleaning MC Ratio)** — khảo sát bắt
      buộc trước khi code phát hiện Engine này CHƯA dùng rollup, tính trực tiếp
      JOIN `availability_logs x batch_details x machines` (điều kiện
      `lower(trim(...))` không dùng được index) mỗi lần đổi filter, baseline đo
      thật **~28 giây/request**. Phát hiện điểm khác biệt so với downtime/
      batch_matrix (hiển thị chi tiết TỪNG MẺ theo trình tự, không phải số liệu
      gộp) → đã hỏi người dùng trước khi tự quyết định cấu trúc bảng (theo đúng
      yêu cầu), người dùng chọn vẫn rollup nhưng thiết kế lại để giữ chi tiết
      từng mẻ. Bảng mới `cleaning_mc_daily_summary` ở GRAIN 1 dòng = 1 mẻ
      (khoá `production_date, availability_log_id`), lưu sẵn badge đã phân
      loại (`classify_batch_badge()` chạy 1 lần trong `recompute_daily()`).
      Sửa thêm root cause riêng: thêm 4 expression index
      `LOWER(TRIM(...))` cho đúng điều kiện JOIN — đo thực tế 436ms → 3ms
      (145 lần) cho 1 ngày. Response API sau khi có cả 2 fix: **~90ms** (từ
      28 giây, ~300 lần). Mở rộng `tests/verify_rollup_parity.py` với
      `legacy_get_cleaning_matrix()` (dựng lại nguyên vẹn JOIN+classify cũ),
      4 scenario filter khác nhau — PASS 100%. Tiện thể phát hiện + sửa 1 bug
      "mồ côi": `init_db.py` vẫn giữ schema CŨ (đã lỗi, có cột `machine_count`)
      của `batch_matrix_daily_summary` từ TRƯỚC lần sửa bug COUNT DISTINCT ở
      mục trên — đồng bộ lại khớp đúng schema thật trong service.py.
- [x] **Sửa bug hiển thị sai ngày mẻ qua đêm trên báo cáo Cleaning MC** — rà
      soát toàn bộ code `.py` tính production_date xác nhận backend đúng 100%
      (đo thật: 2230/5402 mẻ lệch ngày giữa Start/EndTime, 100% khớp EndTime).
      Bug thật ở JS inline trong template `cleaning_matrix_view.html` (dùng
      `start_time.slice(0,10)` thay vì `production_date`) — đo được 1004/5402
      mẻ (18.6%, toàn bộ mẻ qua đêm) từng hiển thị sai cột ngày. Đã sửa +
      thêm `tests/test_production_date.py` + dọn trùng lặp logic ở
      `core/excel_importer.py::calculate_production_date()`. Chi tiết đầy đủ
      ở `activeContext.md`/`systemPatterns.md` mục 6.2.
- [x] **Sửa bug phân loại SAI Rework do cờ `redye`** — `classify_batch_badge()`
      (`reports/cleaning_matrix.py`) từng coi `redye>0` (hoặc token "RD" trong
      ColourNo/RecipeNo) là dấu hiệu Rework; người dùng xác nhận `redye` nghĩa
      là mẻ quay lại máy chạy QUY TRÌNH KHÁC theo kế hoạch, KHÔNG phải Rework.
      Đã bỏ 2 tín hiệu này khỏi `is_rework`, chỉ còn `batch_type='Rework'`
      hoặc `log_rework_minutes>0` (số phút Rework đo thật trên ca máy). Đo
      tác động: 192/1271 mẻ (15.1%) từng bị gắn badge Rework sai, đã sửa +
      `flask rebuild-summaries` backfill lại toàn bộ. Đã kiểm tra riêng
      `batch_matrix` theo yêu cầu — xác nhận Engine này không dùng
      `redye`/`is_rework` ở đâu cả nên không cần sửa.
- [x] **Xác nhận công thức Ma trận Số mẻ/Máy theo Ngày đúng như mong đợi**
      (Sum số mẻ/Sum số máy distinct theo ngày, lọc Color/Capacity — người
      dùng xác nhận qua ví dụ số liệu thật, không đổi code) + **thêm tính
      năng drill-down "double-check"**: bấm vào 1 ô ngày trên
      `/dyeing/batch_matrix/` mở modal hiển thị danh sách mẻ thật (machine,
      batch, dyelot, shade, colour_no, capacity, start/end time) đã được
      tính vào đúng ô đó. Route mới `GET .../api/day-batches?date=&
      fabric_type=&color_group=&capacity=...` (`batch_matrix/service.py::
      get_day_batches()`) — query TRỰC TIẾP raw data (không qua
      `batch_matrix_daily_summary`) vì đây là truy vấn hẹp/hiếm (1 ngày, 1 ô,
      chỉ chạy khi bấm xem), dùng lại đúng điều kiện lọc JOIN như
      `recompute_daily()` để đảm bảo khớp 100% số liệu đã hiển thị.
- [x] **Xoá toàn bộ mockup/demo data khỏi DB thật** (theo yêu cầu người dùng,
      đã xác nhận đúng phạm vi trước khi xoá + backup DB vào
      `data/backups/` trước khi thực hiện vì project không dùng git):
      `machine_telemetry` (845 dòng, machine_id DY-01..DY-05 giả lập),
      `downtime_logs` (40 dòng, cùng DY-01..DY-05 giả lập — Downtime engine
      thật KHÔNG đọc bảng này, đọc từ `availability_logs`), `machines` (5
      dòng seed DY-01..DY-05, không khớp `machine_code` thật nào nên vốn đã
      không phục vụ báo cáo thật), và 1 dòng `import_logs` id=1
      ('telemetry_template_demo.xlsx', seed mẫu). ĐÃ GIỮ NGUYÊN toàn bộ dữ
      liệu thật (`availability_logs` 5402, `batch_details` 6712,
      `import_log_rows` 13892, 42 `import_logs` thật, mọi bảng
      `*_daily_summary`) và tài khoản `users` (admin/operator — không phải
      mock, là hạ tầng đăng nhập). Verify: KPI Cleaning MC không đổi trước/
      sau xoá (đúng như kỳ vọng — `machines` seed vốn không khớp dữ liệu
      thật), toàn bộ trang vẫn 200, `tests/verify_rollup_parity.py` +
      `tests/test_production_date.py` vẫn PASS 100%. **Hệ quả cần lưu ý**:
      trang OEE (`/dyeing/oee/`) và dropdown máy ở Manual Entry
      (`/dyeing/manual_entry/`) giờ hiển thị RỖNG (không còn máy demo nào)
      — đây là kỳ vọng đúng cho tới khi có nguồn `machine_telemetry` thật
      hoặc `machines` được nạp lại bằng dữ liệu máy thật (xem mục Backlog
      "Daily Rollup cho OEE").
- [x] **Drill-down "double-check" cho báo cáo Downtime** (tương tự tính năng
      vừa thêm ở Batch Matrix): bấm vào 1 ô số trên bảng pivot Downtime
      (`/dyeing/downtime/`) mở modal hiển thị Top 10 batch có giờ Downtime
      CATEGORY lớn nhất trong đúng kỳ (Day/Week/Month) đó, sắp xếp giảm dần.
      Route mới `GET .../api/top-batches?period=&group_by=&category=&
      capacities=` (`downtime/service.py::get_top_batches_for_category()`)
      — query TRỰC TIẾP `availability_logs` (không qua
      `downtime_daily_summary`, bảng đó chỉ lưu TỔNG giờ/ngày/category chứ
      không giữ chi tiết từng mẻ) vì đây là truy vấn hẹp/hiếm, chỉ chạy khi
      bấm xem. Thêm `_period_date_range()` quy đổi ngược nhãn kỳ (VD
      "2026-W27", "2026-09") sang khoảng ngày để lọc đúng — dùng lại
      `operational_bounds()` có sẵn. **Đổi API** `get_downtime_pivot_data()`:
      trả thêm `period_keys` (khoá kỳ thô, VD "2026-07") song song với
      `periods` (nhãn hiển thị, VD "Jul-26") — frontend cần khoá thô để gọi
      API drill-down đúng, không suy ngược được từ nhãn hiển thị.
- [x] **Dọn 3 dòng mockup còn sót lẫn trong dữ liệu thật, lộ ra ở báo cáo
      Cleaning MC** (phát hiện qua rà soát `DISTINCT machine` — 3 mã máy
      "DY-01"/"DY-API"/"DY-FIX" lẫn giữa các mã máy thật): batch "B-API"/máy
      "DY-API" (từ file test `Availability_api.csv`, import_logs id=2),
      batch "B-FIX"/máy "DY-FIX" (từ file test `Availability_fix.csv`,
      import_logs id=5), batch "MANUAL-TEST-3"/máy "DY-01" (nhập tay lúc
      test tính năng Manual Entry) — cả 3 đều từ các phiên debug/test SỚM
      (trước khi có dữ liệu thật), không khớp máy/mẻ thật nào. Đã backup DB
      trước khi xoá (`data/backups/`), xoá `availability_logs` id=1,2,3 +
      `batch_details` dyelot='MANUAL-TEST-3' + `import_logs` id=2,5, sau đó
      `trigger_recompute({2026-09-08})` để đồng bộ lại
      `cleaning_mc_daily_summary`/`downtime_daily_summary`/
      `batch_matrix_daily_summary`. Verify: KPI Cleaning MC giảm đúng 2
      normal + 1 rework (khớp 3 dòng đã xoá), mọi trang vẫn 200, 2 bộ test
      vẫn PASS 100%. **PHÂN BIỆT QUAN TRỌNG đã xác nhận với người dùng**:
      các dyelot có chữ "Test"/"Autotest" khác (VD "Test_001", "TEST
      Brine1", "Autotest0002") trong `batch_details` là MẺ TEST THẬT của
      nhà máy (test dung dịch/hoá chất, nằm trong file Batch Excel thật đã
      import) — KHÔNG phải mockup, đã GIỮ NGUYÊN, không đụng vào.
- [x] **Đổi công thức mẫu số Ma trận Số mẻ/Máy theo Ngày** (`batch_matrix`):
      từ "số máy DISTINCT đã chạy" sang "tổng giờ máy chạy thực tế quy đổi
      máy tương đương" (`operating_hours/24`), loại trừ thời gian máy idle.
      Tử số (số mẻ) giữ nguyên. Tách thành bảng RIÊNG
      `batch_matrix_capacity_hours_daily` (production_date, capacity_kg,
      operating_hours, machine_equivalent) vì mẫu số không còn có
      fabric_type/color_group. Mỗi dòng availability được cắt theo ranh
      giới 7h sáng để phân bổ đúng giờ chạy vào từng ngày (KHÁC tử số — tử
      số gán nguyên mẻ vào 1 ngày theo EndTime, mẫu số chia nhỏ theo giờ
      thực tế). Verify bằng đúng ví dụ số trong yêu cầu gốc
      (`tests/test_batch_matrix_formula.py`, DB tạm in-memory) — ra đúng
      operating_hours=16, machine_equivalent=0.667, cell_value=6.0 + case
      mẻ qua đêm tách đúng 9h/3h. Cập nhật `tests/verify_rollup_parity.py`
      (`direct_build_matrix()` viết lại theo công thức mới, PASS trên dữ
      liệu thật). Đã `flask rebuild-summaries` backfill lại toàn bộ. Tác
      động quy mô: giá trị ô giảm ~8-25 lần so với công thức cũ (mẫu số giờ
      là quy mô toàn nhà máy, không chỉ vài máy chạy đúng 1 màu) —
      `batch_matrix_targets` hiện chưa có Target nào cấu hình (0 dòng) nên
      chưa ảnh hưởng thực tế. Chi tiết đầy đủ ở `systemPatterns.md` mục 6.2.
- [x] **Audit số liệu thô batch_matrix (theo yêu cầu người dùng, nghi ngờ số
      "co lại" không đều giữa các dòng Color Group là bug)** — audit đầy đủ
      1 ô cụ thể (CVC/Black/02-09, Capacity 500+600+1200+2400): tử số=3, mẫu
      số=283.30h (giờ máy dùng chung toàn bảng theo Capacity+ngày, đúng bản
      2), giá trị=0.25 — KHỚP tuyệt đối, không phải bug tính toán. Đã kiểm
      tra 4 lỗi nghi ngờ (đơn vị phút/giờ, lẫn capacity, đếm trùng JOIN,
      logic cắt 7h) — không phát hiện lỗi nào ở bản 2.
- [x] **ĐẢO NGƯỢC thiết kế mẫu số sang bản 3** (theo quyết định người dùng
      sau audit trên — bản 2 "giờ dùng chung toàn bảng" tuy tính đúng nhưng
      không phản ánh đúng nghiệp vụ): mẫu số giờ = giờ hoạt động của ĐÚNG
      TẬP MÁY đã chạy các mẻ trong CHÍNH ô đó (không phải toàn Capacity+
      ngày). Gộp `operating_hours` trở lại `batch_matrix_daily_summary`,
      xoá bảng `batch_matrix_capacity_hours_daily`. Total(Fabric)/Grand
      Total PHẢI truy vấn lại raw data để khử trùng máy (tránh đúng bug
      COUNT DISTINCT dạng "giờ" — verify bằng ví dụ thật: máy D051 chạy đa
      màu ngày 2026-09-03, cộng thẳng sai 1.63, khử trùng đúng 1.75). Phát
      hiện + sửa thêm 1 bug phụ: làm tròn `operating_hours` quá sớm (4 chữ
      số) trước khi lưu DB gây lệch ~0.2% ở ca cực đoan mẫu số ~79 giây —
      đã bỏ làm tròn sớm. Audit lại 3 cấp (ô/Total Fabric/Grand Total) cho
      đúng ô CVC/Black/02-09 — ra 2.04/2.05/2.49 (khác hẳn 0.25 của bản 2).
      Viết lại hoàn toàn `tests/test_batch_matrix_formula.py` (3 kịch bản,
      thêm kịch bản máy đa màu bẫy lỗi cộng trùng) +
      `tests/verify_rollup_parity.py` (`direct_build_matrix()`) — PASS
      tuyệt đối. Chi tiết đầy đủ lịch sử 3 lần đổi công thức ở
      `systemPatterns.md` mục 6.2.
- [x] **Permission Model — phân quyền Xem/Sửa/Xoá RIÊNG CHO TỪNG ENGINE**:
      bảng `user_permissions` (tạo tự động khi app khởi động, an toàn cho DB
      thật đã có dữ liệu), `core/auth.py::permission_required()`/
      `has_permission()`/`current_user_can()`, blueprint `admin/` quản lý
      tài khoản (`/admin/accounts`, tạo tài khoản, ma trận quyền theo Engine
      liệt kê ĐỘNG qua `engine_registry`), `NAV_MENU` lọc thêm theo quyền
      cho operator. admin superuser cố định, không đổi hành vi. Đã audit +
      gate toàn bộ route của 7 Engine (`dyeing.oee/downtime/batch_matrix/
      manual_entry/reports/excel_import`, `knitting.oee`) theo đúng phân
      loại view/edit/delete thực tế (không bịa gate cho chức năng không tồn
      tại). `flask sync-permissions [--yes]` backfill quyền cho operator cũ
      — đã chạy thử KHÔNG `--yes`, in đúng bảng dự kiến rồi dừng, CHƯA ghi
      vào DB thật (chờ xác nhận người dùng). Verify:
      `tests/test_permission_model.py` (app Flask đầy đủ, subprocess riêng
      để tránh lỗi đăng ký Blueprint 2 lần) — 28 case PASS 100%. Tuỳ chọn
      "khoá tài khoản" (deactivate) CHƯA triển khai (đánh dấu tuỳ chọn trong
      yêu cầu gốc). Chi tiết đầy đủ ở `systemPatterns.md` mục 10.

- [x] **Chuẩn hoá 100% text giao diện web sang tiếng Anh** (không đụng
      docstring/comment code, giữ nguyên tiếng Việt theo quy ước mục 5
      CLAUDE.md): rà soát toàn bộ `.html`/`.js`/`routes.py` bằng regex diacritic
      tiếng Việt trước khi sửa, dịch thủ công theo từng nhóm (template →
      JS hiển thị DOM → `flash()` → `jsonify()` error → `register_menu(label=...)`
      → `EngineMetadata.description` → nhãn node Graphify), cắt bớt mô tả dài
      dòng/tính từ thừa, CHỈ giữ 3 hint ngắn đã có từ trước (drag-drop Import
      modal, độ dài mật khẩu tối thiểu ở form tạo tài khoản, ghi chú "Admin
      full access" ở ma trận quyền) — không thêm hint mới ở chỗ khác. Phát
      hiện thêm 3 điểm text tiếng Việt "lọt lưới" ngoài phạm vi file ban đầu
      (đã hỏi người dùng trước khi sửa, không tự đoán): `quality_note` trong
      `oee/service.py` (dict trả JSON hiển thị UI), hằng số
      `UNCLASSIFIED_COLOR_GROUP` trong `batch_matrix/service.py` (vừa là giá
      trị hiển thị UI vừa dùng trong `color_group_sort_key()` — đổi
      "Không xác định" -> "Unclassified", đồng bộ `tests/verify_rollup_parity.py`
      + JS so sánh trong `batch_matrix_view.html`, sau đó `flask
      rebuild-summaries` để backfill giá trị mới vào `batch_matrix_daily_summary`
      đã lưu sẵn trong DB — 2 bộ test `test_batch_matrix_formula.py` +
      `verify_rollup_parity.py` PASS 100% sau khi đổi), và `full_name` seed
      trong `init_db.py::seed_users()` ("Quản trị viên"/"Nhân viên vận hành" ->
      "Administrator"/"Operator" — sửa script KHÔNG tự áp dụng cho DB thật đã
      seed do hàm idempotent, đã UPDATE trực tiếp DB thật sau khi backup).
      Verify cuối bằng Flask test client dựng HTML thật (không chỉ grep mã
      nguồn) cho 13 trang: `/`, `/dyeing/`, `/dyeing/oee/`, `/dyeing/downtime/`,
      `/dyeing/batch_matrix/`, `/dyeing/reports/cleaning-matrix`,
      `/dyeing/manual_entry/`, `/knitting/`, `/knitting/oee/`, `/graphify/`,
      `/admin/accounts`, `/admin/accounts/new`, `/admin/accounts/<id>/permissions`
      — toàn bộ 200, không còn ký tự có dấu tiếng Việt nào ngoài comment HTML/JS
      (đã loại trừ đúng phạm vi). **Quy ước áp dụng từ nay cho mọi Engine/trang
      mới**: mọi text hiển thị trên trình duyệt (label, title, flash, jsonify
      message hiển thị, EngineMetadata.description, nhãn node Graphify) viết
      bằng tiếng Anh ngắn gọn ngay từ đầu; docstring/comment `.py` vẫn viết
      tiếng Việt theo đúng mục 5 CLAUDE.md — không cần dọn lại lần nữa.

- [x] **"Abnormal Point" trên trang Downtime** — bảng pivot Day/Week/Month
      (CÙNG cấu trúc bảng "Downtime by category": cột ngoài cùng là tên chỉ
      số, cột bên phải là period theo `group_by` đang chọn, có cột/dòng
      Total), đặt Ở DƯỚI CÙNG trang `/dyeing/downtime/` (dưới bảng "Standard
      Achievement Breakdown"). **Lịch sử thiết kế**: bản đầu (2026-09-11 sáng)
      là 2 ô số KPI đơn giản "Cases Loading = 0"/"Cases Unloading = 0" không
      chia theo period — người dùng yêu cầu đổi thành bảng pivot theo period
      (giống "Downtime by category") NGAY SAU ĐÓ, đã XOÁ HẲN 2 ô số cũ (không
      giữ song song) + thêm điều kiện lọc FabricType không hợp lệ (loại mẻ
      "Unknow", số liệu giảm mạnh từ 923/1063 xuống 49/189 — phần lớn
      "-WA"/cleaning batch có FabricType rỗng/"Unknow" vốn không nên tính).
      2 chỉ số KHÔNG loại trừ lẫn nhau (verify thật: batch C260634180 chỉ ở
      Loading=0 vì unload_hour=0.11≠0). Cột thật đã xác nhận (không đoán):
      `load_hour`/`unload_hour` trong `availability_logs` — CHÍNH LÀ 2 cột
      dùng cho category "Fabric loading"/"Fabric unloading" trong
      `CATEGORY_COLUMNS` (`downtime/service.py`). Loại FabricType không hợp lệ
      dùng CHUNG `INVALID_FABRIC_TYPES` (rỗng/"Unknow"/"Unknown"/"All") đã áp
      dụng cho `valid_batches` — không định nghĩa lại tiêu chí riêng.
      Query TRỰC TIẾP `availability_logs` (cấp MẺ, KHÔNG qua
      `downtime_daily_summary`) — SUM(CASE WHEN...=0) group theo ngày ở SQL
      rồi gộp Day/Week/Month ở Python (cùng cách `_daily_planned_and_
      achievement()` làm, an toàn cộng dồn tuyến tính vì là SUM không phải
      COUNT DISTINCT). 3 hàm ở `downtime/service.py`: `get_abnormal_point_pivot()`
      (bảng), `get_abnormal_point_batches()` (drill-down chi tiết, nhận thêm
      `period`+`group_by` để giới hạn đúng 1 cột đã bấm — quy đổi bằng
      `_period_date_range()` dùng CHUNG với Top-10-batch drill-down có sẵn),
      `_abnormal_point_fabric_filter()` (helper loại FabricType, dùng chung
      cho cả 2 hàm trên để số đếm luôn khớp số dòng chi tiết). Route:
      `GET /dyeing/downtime/api/abnormal-point?capacities=&from_date=&to_date=&
      group_by=` (bảng) + `GET .../api/abnormal-point-batches?field=loading|
      unloading&period=&group_by=&capacities=...` (chi tiết 1 ô). Danh sách
      chi tiết KHÔNG giới hạn LIMIT — số dòng luôn khớp đúng con số hiển thị
      để đối chiếu tay được. UI: tái sử dụng ĐÚNG modal `#top-batches-overlay`
      đã có sẵn (dùng cho drill-down Top 10 batch/category) — không viết
      CSS/JS modal mới. Verify bằng dữ liệu thật (đối chiếu tay SQL thô +
      qua Flask test client): pivot `group_by=month` không filter → Loading
      35/6/8 (Jul/Aug/Sep, tổng 49), Unloading 167/21/1 (tổng 189); click ô
      "Jul-26" Loading → đúng 35 dòng, tất cả `load_hour=0` VÀ `fabric_type`
      không phải Unknow/rỗng; click ô "Sep-26" Unloading → đúng 1 dòng.
- [x] **Thêm cột Reason/Detail vào danh sách chi tiết Abnormal Point** (ghép từ
      `downtime_logs` — log vận hành nhập tay theo Machine + thời điểm dừng
      máy + thời lượng). **Phát hiện quan trọng trước khi code (đã hỏi người
      dùng, không tự đoán)**: `downtime_logs` là bảng CÒN SÓT từ Phase 1 demo,
      CHƯA TỪNG được nối vào pipeline báo cáo thật (Downtime/Cleaning MC đều
      tính từ `availability_logs`, không đọc bảng này) — đang RỖNG 0 dòng
      (dữ liệu mock DY-01..05 đã bị xoá ở lần dọn mockup trước), VÀ schema gốc
      KHÔNG có cột ghi chú tự do nào (`timestamp, machine_id, reason_code,
      reason_name, duration_minutes` — chỉ có Reason phân loại, không có
      Detail). Người dùng xác nhận vẫn triển khai + thêm cột `detail TEXT`
      mới. Đã thêm cột `detail` vào `init_db.py` (schema + seed demo) và vào
      `DOWNTIME_SCHEMA` (`excel_import/service.py`, route Import chưa từng
      được UI gọi tới — cập nhật cho nhất quán, không phải đường dẫn thật).
      Bảng `downtime_logs` LÀ BẢNG CÓ SẴN TỪ TRƯỚC nên cần migrate an toàn
      trên DB thật đã tồn tại — `downtime/service.py::
      _ensure_downtime_logs_detail_column()` (ALTER TABLE ADD COLUMN, lazy,
      chạy khi cần, cùng pattern `_ensure_batch_details_columns()` của
      `cleaning_matrix.py`).
      **Logic ghép**: `_attach_downtime_log_reasons()` — với MỖI mẻ trong
      danh sách Abnormal Point (đã có Machine/StartTime/EndTime), tìm
      `downtime_logs` CÙNG Machine mà khoảng `[timestamp, timestamp+
      duration_minutes]` CHỒNG LẤN [StartTime, EndTime] của mẻ (điều kiện
      overlap kinh điển `log_start < batch_end AND log_end > batch_start`,
      không so bằng chính xác). Nhiều log khớp → nối Reason bằng "; ", nối
      Detail bằng " | ", theo đúng thứ tự thời gian log. Không log nào khớp →
      `downtime_log_matched=0`, frontend hiện badge cam/đỏ "No log found"
      (`.downtime-log-missing`) THAY VÌ để trống — vì đây là dấu hiệu mẻ bất
      thường không có lý do ghi nhận, cần nổi bật.
      **Hiệu năng**: JOIN 1 LẦN cho CẢ danh sách (không query riêng từng mẻ)
      — lấy hết `downtime_logs` của ĐÚNG tập Machine liên quan trong khoảng
      [MIN(start_time)..MAX(end_time)] của toàn danh sách bằng 1 câu SQL, rồi
      lọc/ghép overlap ở tầng Python. Đo thật: danh sách 1007 mẻ (Unloading=0,
      không filter) → 93ms; 175 mẻ (Loading=0) → 52ms — không đáng kể.
      **Cột Detail**: cắt hiển thị ~45 ký tự + "..." (`truncateText()` trong
      `downtime.js`), giữ nguyên full text qua `title="..."` để hover xem đầy
      đủ — API luôn trả full text KHÔNG cắt, chỉ cắt ở tầng hiển thị.
      **KHÔNG thêm sort cột** — đã kiểm tra toàn bộ `.js` trong app, KHÔNG có
      bảng nào khác đã có cơ chế sort-by-click để tái sử dụng (theo đúng yêu
      cầu "tái sử dụng, không viết mới nếu chưa có").
      Verify bằng dữ liệu thật (insert 4 dòng test tạm vào `downtime_logs`,
      backup DB trước, xoá sạch sau khi xong — KHÔNG để lại dữ liệu giả):
      case 1 log khớp (batch C260634180/D512 → Reason="Waiting Material"),
      case 2 log khớp cùng 1 mẻ (batch C260625020/DA04 → Reason="Breakdown;
      Power Outage", đúng thứ tự thời gian), case Detail dài 128 ký tự (batch
      C260626520/D026 → API trả full, client cắt còn 45+"..."), và case
      KHÔNG log nào khớp (batch C260583110/DA02 → `downtime_log_matched=0`).
      **Quy ước rút ra cho báo cáo tương tự sau này cần đối chiếu
      `downtime_logs`**: bảng này CHỈ có Reason phân loại + KHÔNG có Detail
      gốc, KHÔNG có dữ liệu thật (0 dòng), và `machine_id` là mock — PHẢI
      hỏi lại người dùng về nguồn dữ liệu trước khi giả định bảng này "đã có
      sẵn dữ liệu operator nhập tay" như tên gọi gợi ý.
- [x] **Cho phép nhập/sửa Reason/Detail trực tiếp (inline edit) trên danh sách
      drill-down "Downtime by Category"** — annotation thủ công RIÊNG, bảng
      mới `downtime_case_notes` (`reason`, `detail`, `updated_by`,
      `updated_at`, `UNIQUE(availability_log_id)` — tối đa 1 note/mẻ, sửa lại
      = UPSERT, KHÔNG lưu lịch sử nhiều phiên bản), KHÔNG ghi đè
      `availability_logs` gốc (verify: snapshot đầy đủ dòng `availability_logs`
      trước/sau khi tạo VÀ sau khi sửa note — giống hệt 100%, không đổi field
      nào). **Đã đổi khoá FK so với đề xuất ban đầu** (`downtime_logs.id` ->
      `availability_logs.id`) sau khi xác nhận danh sách drill-down thật sự
      lấy dữ liệu từ đâu — chi tiết đầy đủ ở `systemPatterns.md` mục 6.2. Bổ
      sung `id AS availability_log_id` vào SELECT của
      `get_top_batches_for_category()` (trước đây không trả field này) làm
      khoá ghép note — join 1 LẦN cho cả danh sách (`_attach_case_notes()`,
      cùng kỹ thuật với `_attach_downtime_log_reasons()` của Abnormal Point).
      **Quyền**: route ghi `POST /dyeing/downtime/api/case-notes/<id>` gate
      bằng ĐÚNG `permission_required("dyeing", "downtime", "edit")` có sẵn từ
      Permission Model — KHÔNG viết cơ chế quyền riêng; admin luôn ghi được
      (superuser cố định); operator cần `can_edit=1` mới ghi được, chỉ
      `can_view=1` vẫn ĐỌC được note qua API (route đọc chỉ gate "view")
      nhưng UI ẩn hẳn control chỉnh sửa (`window.DOWNTIME_CAN_EDIT_NOTES`,
      bơm từ `current_user_can('dyeing','downtime','edit')` đã có sẵn trong
      mọi template qua context_processor). UI: click vào ô Reason (input)
      hoặc Detail (textarea, hỗ trợ nhiều dòng) → sửa tại chỗ → lưu khi blur
      hoặc Enter (Reason) — Detail CHỈ lưu khi blur (giữ Enter để xuống dòng
      trong ghi chú dài); phản hồi rõ ràng qua toast tái dùng ĐÚNG
      `.toast-container`/`.import-toast` đã có sẵn trong `app.css`/
      `import_handler.js`, không viết CSS/JS toast mới; tooltip nhỏ
      "Edited by {updated_by} at {updated_at}" trên ô đã có note.
      **Verify đầy đủ** (dựng app Flask ĐẦY ĐỦ trong SUBPROCESS trỏ DB TẠM —
      copy từ DB thật, KHÔNG đụng DB thật, cùng pattern
      `tests/test_permission_model.py` — 17 case, PASS 100%): admin tạo note
      → lưu đúng, `availability_logs` không đổi, đúng 1 dòng trong
      `downtime_case_notes`; admin sửa lại → vẫn đúng 1 dòng (upsert, không
      trùng), `updated_at` đổi; operator CHỈ có `view`: thấy được Reason/
      Detail đã lưu qua API, trang có `DOWNTIME_CAN_EDIT_NOTES=false`, gọi
      thẳng route ghi qua API bị chặn (302 redirect, KHÔNG trả JSON, dữ liệu
      trong DB KHÔNG đổi); operator được cấp thêm `edit`: ghi thành công,
      `updated_by` đúng username người vừa sửa.
- [x] **Đổi tên bảng "Abnormal Point" thành "Data Quality" + áp dụng CÙNG cơ chế
      Case Notes (inline edit Reason/Detail) vừa làm cho "Downtime by
      Category"** — người dùng đã dùng thử tính năng Case Notes trên Downtime
      by Category (27 note thật đã nhập qua UI, VD "Discipline"/"Lack of HC
      in peak time"/"Process not optimized"...) và xác nhận ổn, yêu cầu áp
      dụng tương tự cho bảng còn lại. **Quyết định thiết kế quan trọng**: XOÁ
      HẲN cơ chế cũ (auto-match Reason/Detail từ `downtime_logs` qua overlap
      thời gian + badge "No log found", vốn gần như luôn rỗng vì
      `downtime_logs` chưa có dữ liệu thật) — thay bằng DÙNG CHUNG
      `downtime_case_notes`/`_attach_case_notes()` với Downtime by Category
      (KHÔNG tạo bảng annotation thứ 2 riêng cho Data Quality), vì 2 danh
      sách cùng khoá theo `availability_logs.id` và 1 mẻ có thể xuất hiện ở
      CẢ 2 báo cáo — annotation phải là 1 nguồn duy nhất để tránh lệch nhau
      khi sửa từ 1 trong 2 nơi. Đã thêm `availability_log_id` vào SELECT của
      `get_abnormal_point_batches()` (trước đây không có field này). Cột
      `downtime_logs.detail` (migration ở task trước) giữ nguyên, không dùng
      tới nhưng vô hại. UI: đổi toàn bộ text hiển thị "Abnormal Point" ->
      "Data Quality" (heading, cột đầu bảng pivot, tiêu đề modal drill-down)
      — tên hàm/biến nội bộ Python/JS (`abnormal_point`, `ABNORMAL_POINT_*`)
      GIỮ NGUYÊN, chỉ đổi label hiển thị. Xoá CSS `.downtime-log-missing`
      (không còn dùng). Verify (subprocess + DB tạm copy từ DB thật, không
      đụng 27 note thật trên DB thật): trang hiện đúng heading "Data
      Quality", không còn text "Abnormal Point" nào; note tạo qua context
      Data Quality đọc lại được y hệt qua `get_top_batches_for_category()`
      (chứng minh dùng CHUNG 1 bảng); operator view-only vẫn đọc được note
      nhưng bị chặn ghi (302); admin/editor ghi được bình thường. Full
      regression 11 trang vẫn 200 trên DB thật với dữ liệu note thật đang có.
- [x] **Chuẩn bị deploy Git -> Supabase -> Vercel: dual-mode DB SQLite/Postgres +
      scaffold Vercel** — người dùng muốn deploy, phát hiện chặn đường thật sự:
      app đọc/ghi trực tiếp 1 file SQLite cục bộ, Vercel serverless filesystem
      ephemeral (mất dữ liệu mỗi cold start). Đã lập kế hoạch qua Plan Mode +
      1 vòng phản biện bằng Plan agent (bắt được 2 lỗi thiết kế trước khi code:
      không được xoá hẳn wrapper `datetime()` khi dịch — mất khả năng chuẩn hoá
      dữ liệu cũ/lệch định dạng; và số liệu khảo sát `PRAGMA table_info` ban đầu
      đếm thiếu do phạm vi grep hẹp). **Kiến trúc**: dual-mode qua biến môi
      trường `DATABASE_URL` — không set (mặc định) chạy SQLite y hệt trước,
      set (vd Vercel trỏ Supabase) chuyển sang psycopg2 qua lớp bọc
      `_PostgresConnCompat` (`core/database.py`) dịch trong suốt `?`->`%s` và
      `PRAGMA table_info`->`information_schema.columns`, để ~16 file Engine
      HẦU NHƯ không cần sửa câu SQL nào. Đã tự sửa tay các phần KHÔNG dịch được
      trong suốt: hàm `datetime()`/`datetime('now')` literal (thêm
      `sql_datetime()`/`production_date_sql_expr()` dialect-aware, xem chi tiết
      đầy đủ ở systemPatterns.md mục 5.1), `cursor.lastrowid` (3 chỗ, đổi sang
      `insert_returning_id()`), `except sqlite3.Error` (đổi sang
      `DatabaseError` — tuple LUÔN LUÔN, tránh bug tuple-lồng-tuple đã verify
      bằng thực nghiệm), DDL `CREATE TABLE`/`executescript()` trong các hàm
      `_ensure_*_table()` rải rác (gate sau `if get_dialect()=="sqlite"`, vì
      Postgres đã có bảng qua `supabase/schema.sql` từ trước), 1 chỗ dùng
      `rowid` (ngầm định SQLite-only) để dọn dữ liệu trùng. Phát hiện + sửa 1
      bug thật giữa chừng: `get_dialect()` ban đầu chỉ đọc được
      `current_app.config` nên crash `RuntimeError: Working outside of
      application context` khi `tests/test_batch_matrix_formula.py` gọi
      `recompute_daily(day, conn)` trực tiếp không qua Flask — đã thêm fallback
      đọc `os.environ.get("DATABASE_URL")` khi không có app context.
      **File mới**: `supabase/schema.sql` (dịch Postgres đầy đủ 15 bảng từ
      `init_db.py::SCHEMA_SQL`), `.env.example`, `.gitignore` (viết lại — phát
      hiện root dự án trùng root venv Python, `.gitignore` cũ chỉ có `*`),
      `vercel.json` + `api/index.py` (WSGI entrypoint), `tests/
      test_postgres_shim_translation.py` (test riêng logic dịch SQL của shim,
      không cần Postgres thật). `requirements.txt` thêm `psycopg2-binary`.
      **Verify**: cài được `psycopg2-binary` qua pip (không cần server Postgres
      thật) nên verify được NHIỀU hơn dự kiến ban đầu — toàn bộ 5 test suite
      PASS ở chế độ SQLite mặc định (chứng minh không đổi hành vi cũ), VÀ set
      thử `DATABASE_URL` giả xác nhận toàn bộ chuỗi wiring chạy đúng tới tận
      lớp mạng (`psycopg2.connect()` nhận đúng lỗi `Connection refused` — lỗi
      mạng vì server giả, KHÔNG phải lỗi code). Full regression 13 trang vẫn
      200. **Chưa verify được** (cần người dùng cung cấp `DATABASE_URL`
      Supabase thật): dữ liệu trả về đúng khi chạy với Postgres sống thật.
      Đã audit riêng cả 7 điểm dùng `ON CONFLICT` — xác nhận mọi UNIQUE
      constraint/index target đều có trong `supabase/schema.sql`. Xác nhận
      Excel Import xử lý file tải lên bằng `tempfile.NamedTemporaryFile`
      (thư mục temp hệ thống, `/tmp` ghi được trên Vercel) chứ KHÔNG dùng
      `UPLOAD_FOLDER` lưu lâu dài — đã sẵn sàng cho filesystem ephemeral, độc
      lập với phần migrate DB.
- [x] **Bug thật phát hiện sau khi người dùng deploy thử lên Vercel** (function
      crash, `FUNCTION_INVOCATION_FAILED`) — `config.py::Config.
      ensure_directories()` gọi `mkdir()` KHÔNG điều kiện lên `data/`/`uploads/`
      ngay lúc MODULE IMPORT (`app = create_app()` cuối `app.py`, chạy lại ở
      MỌI cold start) — thư mục code deploy Vercel READ-ONLY nên crash trước
      cả khi chạm tới DB. Đã sửa: return sớm nếu có `DATABASE_URL` (đã verify
      `UPLOAD_FOLDER` chưa từng được ghi file thật ở đâu — an toàn bỏ qua).
      Đồng thời xác nhận với người dùng: **CHƯA set `DATABASE_URL` trên
      Vercel** — nghĩa là kể cả sau fix này, app vẫn sẽ crash cho tới khi có
      Supabase project thật + set biến môi trường, vì SQLite không thể chạy
      trên Vercel dù có sửa mkdir hay không (không có nơi nào ghi được file DB
      lâu dài). Đã tạo thêm `seed_supabase_users.py` (script gốc, chạy 1 lần
      từ máy local SAU khi áp `supabase/schema.sql`) — `supabase/schema.sql`
      CHỈ tạo bảng (DDL), KHÔNG seed dữ liệu như `init_db.py` làm cho SQLite,
      nên bảng `users` trên Supabase mới sẽ RỖNG nếu không chạy script này —
      không ai đăng nhập được. Script dùng lại ĐÚNG công thức hash
      (SHA-256 + SECRET_KEY) của `core/auth.py::hash_password()` — đã verify
      bằng thực nghiệm cho ra CÙNG hash byte-for-byte — PHẢI chạy với đúng
      `SECRET_KEY` sẽ dùng trên Vercel, không thì mật khẩu tạo ra không khớp
      lúc app thật verify đăng nhập.
- [x] **Deploy thật lên Vercel + Supabase (Pooler) — đã verify với server
      THẬT** (không còn là backlog "chờ dữ liệu thật" nữa). Chuỗi lỗi thật đã
      gặp và fix theo thứ tự: (1) Direct connection
      `db.<ref>.supabase.co:5432` chỉ có IPv6, Vercel Functions không có
      outbound IPv6 → `Cannot assign requested address` — chuyển sang
      connection string qua **Pooler** (`aws-0-<region>.pooler.supabase.com:
      6543`, username dạng `postgres.<project-ref>` — KHÁC Direct connection,
      dễ gõ sai/sót phần `.<project-ref>`); (2) `AVAILABILITY_COLUMNS`
      (`core/excel_importer.py`) có 2 header khác nhau cùng map vào 1 field DB
      (`testing_sample_order_kgh`, `testing_bulk_order_kgh` — alias thủ công
      trùng field tự sinh từ vòng lặp) → field bị liệt kê 2 lần trong cột
      INSERT của `save_to_db()`; SQLite bỏ qua lỗi này (cột trùng, giá trị sau
      ghi đè) nhưng Postgres từ chối thẳng (`DuplicateColumn`) — sửa bằng
      `dict.fromkeys()` khử trùng lặp khi build `AVAILABILITY_DB_FIELDS`,
      giữ thứ tự xuất hiện đầu; (3) Excel Import qua UI rất chậm/timeout khi
      file nhiều dòng — nguyên nhân: `psycopg2.Cursor.executemany()` KHÔNG tự
      batch, gửi 1 round-trip mạng RIÊNG cho MỖI DÒNG (khác SQLite chạy cục
      bộ) — sửa `_PostgresConnCompat.executemany()`
      (`core/database.py`) tự nhận diện hình dạng `INSERT ... VALUES (%s,
      %s, ...) [ON CONFLICT ...]` chuẩn (mọi call site executemany hiện có
      đều vậy) và gộp thành `psycopg2.extras.execute_values()` (1000
      dòng/round-trip) — `cursor.rowcount` sau đó không đáng tin (chỉ phản
      ánh page cuối) nên bọc qua `_StaticRowCountCursor` gán cứng
      `len(seq)` (an toàn vì mọi INSERT executemany trong dự án hoặc có
      `ON CONFLICT DO UPDATE` — mọi dòng đều tính affected — hoặc là INSERT
      thường không thể âm thầm bỏ dòng). Đã verify bằng mock cursor (không
      cần Postgres thật): `?`→`%s`, gộp `VALUES` đúng, `execute_values` được
      gọi đúng tham số, `.rowcount`/`.close()` forward đúng.
- [x] **`migrate_sqlite_to_supabase.py`** (script gốc, chạy 1 lần từ máy
      local, KHÔNG qua UI/Vercel vì Serverless Function giới hạn 300s không
      đủ cho khối lượng dữ liệu lịch sử lớn) — copy toàn bộ dữ liệu THẬT đang
      có trong `data/mes_dashboard.db` (9302 `availability_logs`, 6804
      `batch_details`, 9302 `cleaning_mc_daily_summary`, 6686
      `downtime_daily_summary`, 2720 `batch_matrix_daily_summary`, 43
      `import_logs`, 17901 `import_log_rows`, 31 `downtime_case_notes`) sang
      Supabase. Điểm mấu chốt: KHÔNG giữ nguyên `id` gốc từ SQLite khi insert
      (Postgres tự sinh `id` mới — tránh đụng độ với id do chính app đã tạo
      qua lần test-upload file nhỏ trước đó), thay vào đó đọc lại
      {khoá tự nhiên: id mới} từ Postgres sau mỗi bảng cha để tự tra đúng id
      cho bảng con (vd `cleaning_mc_daily_summary`/`downtime_case_notes`
      remap `availability_log_id` qua bộ ba `batch_ref_no+machine+
      start_time`, KHÔNG qua id); `user_permissions`/`downtime_case_notes.
      updated_by` remap theo **username** (không theo id) vì bảng `users` cố
      tình KHÔNG được copy (Supabase đã seed sẵn qua `seed_supabase_users.py`
      với hash theo `SECRET_KEY` của Vercel — copy đè sẽ hỏng đăng nhập). Bảng
      không có khoá tự nhiên (`import_logs`, `import_log_rows`) dùng guard
      theo số dòng đã có (bỏ qua nếu đích đã có dữ liệu, trừ khi `--force`) để
      chạy lại nhiều lần không bị nhân đôi; các bảng còn lại dùng
      `ON CONFLICT ... DO UPDATE` (idempotent thật sự). Toàn bộ chạy trong 1
      transaction (`--dry-run` để xem trước rồi rollback).
      **Phát hiện thật khi xây bộ test bằng mock** (dựng "shadow Postgres"
      bằng 1 SQLite phụ + monkeypatch `psycopg2`, chạy full script với dữ
      liệu thật 53k+ dòng, cố tình cho id lệch giữa 2 "DB" để bắt lỗi giả
      định id trùng): `supabase/schema.sql` THIẾU cột `import_logs.created_at`
      so với schema thật của SQLite local (sót khi dịch ban đầu) — sửa
      `bulk_upsert()` tự dò cột thật qua `information_schema.columns` và chỉ
      insert phần giao (tự chịu được lệch schema thay vì phải sửa tay + chạy
      `ALTER TABLE` thủ công trên Supabase trước); đã bổ sung lại cột này vào
      `supabase/schema.sql` cho khớp (không bắt buộc phải `ALTER TABLE` trên
      Supabase thật vì script đã tự chịu được, cột này dư thừa với
      `imported_at` sẵn có). Test PASS toàn bộ: remap đúng, dòng "giả lập
      user đã test-upload trước đó" không bị đụng, chạy lại lần 2 không nhân
      đôi dữ liệu.

- [x] **Redesign toàn bộ giao diện web + đổi thương hiệu "MES Dashboard" ->
      "CETVN IE DASHBOARD"** (2026-09-11) — bỏ hẳn GitHub Primer CSS, viết
      design system riêng (`static/css/app.css`) theo `design/DESIGN.md`
      ("AgentQL: Aurora glow over a midnight terminal"), hỗ trợ cả Dark
      (mặc định) và Light Mode (tự suy diễn thêm, có nút toggle trong
      sidebar). Chi tiết đầy đủ + lý do quyết định ở `activeContext.md`
      mục -7 và `techContext.md` mục Frontend. Verify bằng Flask dev server
      thật + Playwright chụp ảnh 10 trang ở cả 2 theme — không lỗi
      layout/CSS. Phát hiện phụ 2 lỗi JS console tiền-tồn (không phải do
      redesign) khi dataset rỗng — xem Known Issues bên dưới.

- [x] **UI/UX polish sau redesign + sửa 2 bug thật** (2026-09-12): Sidebar thu gọn được
      (`static/js/sidebar_toggle.js`); đổi mặc định Light Mode (logic áp theme đã lưu
      chuyển lên script đồng bộ đầu `<head>` để tránh FOUC); trang Downtime chia 3 tab
      (Overview/Standard Achievement Breakdown/Data Quality, chuyển bằng click hoặc lăn
      chuột), mỗi tab có biểu đồ riêng (Achievement dùng line chart), mặc định
      Capacity=500/600/1200/2400, Group By=Week, khoảng ngày 6 tuần tính từ tuần hiện
      tại; thêm View Transitions API (CSS thuần) cho crossfade mượt giữa các trang.
      **Bug thật #1**: `_empty_result()` (`downtime/service.py`) thiếu
      `values_hours`/`datasets_hours` gây crash JS toàn bộ khi dataset rỗng — đã sửa,
      xem Known Issues bên dưới (đã gỡ mục cũ). **Bug thật #2** (người dùng report):
      `downtime_case_notes` khoá `UNIQUE(availability_log_id)` khiến 1 mẻ xuất hiện ở
      nhiều category/field khác nhau (Downtime by Category / Data Quality) bị DÙNG
      CHUNG 1 note — thêm cột `context`, đổi khoá thành
      `UNIQUE(availability_log_id, context)`, giữ tương thích ngược 27 note thật trên
      Supabase qua fallback `context=''`. Chi tiết đầy đủ + lý do thiết kế ở
      `systemPatterns.md` mục 6.2, `activeContext.md` mục -8. Verify: 6 test suite cũ
      (`test_batch_matrix_formula`, `test_permission_model`, `test_postgres_shim_translation`,
      `test_production_date`, `verify_rollup_parity`) vẫn PASS 100% (không regression) +
      test mới `tests/test_downtime_case_notes_context.py` (7 case, dựng DB tạm mô phỏng
      ĐÚNG schema cũ có sẵn note thật để code tự lazy-migrate) PASS 100%.
      **CHỜ XÁC NHẬN**: `supabase/migrate_case_notes_context.sql` chưa chạy trên Supabase
      production (app không có quyền tự ALTER TABLE Postgres) — xem `activeContext.md`
      mục "Việc tiếp theo".

## Backlog (Phase 2+)
- [ ] "Khoá tài khoản" (deactivate, cột `is_active` ở `users`) — tuỳ chọn
      trong yêu cầu gốc của Permission Model, chưa triển khai để tập trung
      đúng phạm vi bắt buộc.
- [ ] Daily Rollup cho OEE (`oee_daily_summary`) — tạm hoãn vì `machine_telemetry`
      hiện toàn dữ liệu demo (chưa có nguồn telemetry thật) và OEE hiện không
      có khái niệm "theo ngày" nào cả (rolling N-day window). Nếu triển khai:
      lưu SỐ LIỆU THÔ (running_samples, total_samples, speed_ratio_sum,
      speed_samples, output_sum) chứ KHÔNG lưu sẵn % — tránh bug trung bình
      cộng % ≠ % thật khi gộp nhiều ngày (bài học đã rút ra khi làm batch_matrix).
- [ ] Admin UI sửa `batch_matrix_targets` qua giao diện (hiện chỉ có API
      `GET/POST /dyeing/batch_matrix/api/targets`, phải gọi trực tiếp) — do
      người dùng chủ động để dành, chưa yêu cầu làm ngay.
- [ ] Bổ sung cột/ bảng dữ liệu chất lượng (QC/reject) để tính Quality thực
      trong công thức OEE (hiện giả định 100%).
- [ ] Triển khai đầy đủ Engine cho Domain `knitting` (hiệu suất dệt, định
      mức tiêu hao sợi...).
- [ ] Kết nối trực tiếp PLC/IoT thay vì phụ thuộc hoàn toàn vào Excel Import.
- [ ] Multi-factory sync: đồng bộ dữ liệu giữa CETVN, CETBD, RTVL, EG.
- [ ] Nâng cấp Authentication: JWT/SSO, phân quyền chi tiết hơn theo xưởng.
- [ ] Audit log chi tiết cho mọi thao tác ghi dữ liệu (không chỉ Import).
- [ ] Viết test tự động (pytest) cho `core/excel_importer.py` và các Service.
- [ ] Thêm phân trang (pagination) cho bảng Downtime Logs khi dữ liệu lớn.
- [ ] Cân nhắc chuyển Graphify sang thư viện vẽ đồ thị chuyên dụng (vd
      Cytoscape.js) nếu số lượng Engine tăng nhiều, layout tự chế hiện tại
      (`graph_view.html`) chỉ phù hợp quy mô nhỏ/vừa.

## Known Issues
- `batch_matrix_view.html` (JS): khi dataset hoàn toàn rỗng (VD DB mới seed
  chưa có `availability_logs`), một vài hàm render gọi `.map()` trên field
  mà backend không trả về khi không có dữ liệu -> `Cannot read properties of
  undefined (reading 'map')` ở console (phát hiện 2026-09-11 lúc verify
  redesign UI trên DB dev mới seed, KHÔNG phải bug do redesign gây ra, KHÔNG
  xảy ra với dữ liệu thật vì luôn có hàng nghìn dòng — chưa sửa vì ngoài
  phạm vi công việc lúc phát hiện). **`downtime_view.html` đã sửa dứt điểm
  2026-09-12** (`_empty_result()` thiếu `values_hours`/`datasets_hours`,
  xem mục "Đã hoàn thành" phía trên) — mục Known Issues này giờ CHỈ còn áp
  dụng cho `batch_matrix_view.html`.
- Sơ đồ Graphify dùng thuật toán xếp tầng (leveling) đơn giản — có thể chồng
  chéo cạnh (edge) nếu đồ thị nhiều nhánh phức tạp; chấp nhận được ở quy mô
  Phase 1 (dưới ~10 Engine).
- Mật khẩu người dùng băm bằng SHA-256 + salt tĩnh — CHỈ phù hợp demo/Phase 1,
  cần thay bằng `werkzeug.security` hoặc bcrypt trước khi đưa vào production
  thật với nhiều người dùng.
- `detect_file_type_from_headers()` (`core/excel_importer.py`) còn giữ
  `AVAILABILITY_SIGNATURE`/`PERFORMANCE_SIGNATURE` với giá trị không khớp
  file thật (không còn gây lỗi vì không raise nữa, nhưng đọc code dễ hiểu
  nhầm) — nên dọn lại cho khớp thực tế.
- Route `/api/import/<schema_key>` (Telemetry/Downtime, `ImportSchema`-based)
  không được UI nào gọi tới hiện tại — giữ lại vì chưa xác nhận có còn cần
  không, không phải bug nhưng là code "mồ côi" cần lưu ý khi audit.
