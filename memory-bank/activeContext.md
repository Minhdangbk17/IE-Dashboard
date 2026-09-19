# Active Context — Trạng thái hiện tại

**Cập nhật lần cuối:** 2026-09-19 (chiều muộn) — Báo cáo RFT (cả 6 tab) đổi từ 1 dòng/tab
sang **3 dòng/3 đường cố định Cotton/CVC/Polyester + cột Target**, chart đổi từ `bar` sang
`line` — áp dụng LẠI đúng pattern đã làm cho "%Tank Loading"/"Batch/Day Trend" (mục -13/-14),
theo yêu cầu người dùng "làm hết cho cả 6 mục". Bỏ hẳn filter Fabric Type chung (không còn ý
nghĩa khi mỗi tab đã cố định lộ 3 loại). Bảng Target MỚI `rft_targets` — khoá GHÉP
**`(category, fabric_type)`** (KHÁC `tank_loading_targets` chỉ khoá `fabric_type` đơn — RFT
có 6 tab độc lập, mỗi tab cần Target riêng cho từng loại vải, không dùng chung Target giữa
các tab). KPI card đầu trang + field `chart.values`/`chart.rate_values`/`kpis.rate_pct` (dùng
bởi Dyeing Hub Dashboard) **GIỮ NGUYÊN nguyên** — vẫn gộp CẢ tab (mọi loại vải, không chỉ 3
loại chính), không cần sửa `dyeing_hub.js`; phần MỚI (`rows`/`chart.series`, 3 dòng theo
đúng `MAIN_FABRIC_TYPES`) chỉ ảnh hưởng khu vực bảng+chart chi tiết trên trang report RFT.
Route mới `POST /dyeing/rft/api/targets/<slug>/<fabric_type>`. Xem chi tiết đầy đủ ở mục -17
bên dưới. Bản ghi trước đó (2026-09-19, RFT có quy tắc phân loại thật lần đầu) giữ nguyên
ngay dưới đây.

**Cập nhật lần cuối (bản ghi cũ):** 2026-09-19 — Engine `rft` (Right First Time) có quy tắc phân loại
THẬT lần đầu tiên (trước đó là scaffold `classify_rft_category()` luôn trả `None` từ
2026-09-13). Nguồn dữ liệu mới: file "RFT report.xlsx" (QC xuất) -> bảng riêng
`rft_dye_results` (`core/rft_importer.py`, luồng import riêng cùng pattern
`batch_importer.py`). Cột `Stage` map trực tiếp sang 6 tab; Stage lạ đếm riêng qua
`other_stage_count`, không gộp vào tab nào. `production_date` suy qua JOIN Dyelot sang
`availability_logs`, dòng không khớp rơi vào cột "Unknown Date" (giữ lại khi không lọc
ngày, loại khi lọc ngày tường minh). Tab Rework/Adjust Color CHỈ tính máy MachineType
">=500kg". **Đổi hẳn công thức KPI**: `rate_pct = OK/tổng-mẻ-CỦA-CHÍNH-TAB` (trước đó là tỷ
trọng so với tổng 6 tab) — pivot cell hiển thị %. Cờ `RFT_CLASSIFICATION_READY` đổi sang
`True`, Dyeing Hub Dashboard tự động hết hiện "Awaiting classification rules". Xem chi tiết
đầy đủ (bao gồm 4 quyết định nghiệp vụ đã hỏi-đáp với người dùng trước khi code) ở mục
"Đang làm" bên dưới. Bản ghi trước đó (2026-09-19 sáng — 2 việc nhỏ Dashboard) giữ nguyên
ở mục -15/-16.

**Cập nhật lần cuối (bản ghi cũ):** 2026-09-19 (sáng) — 2 việc nhỏ trên Dyeing Hub Dashboard (mục -15/-16):
(1) Xác nhận "%Tank Loading chưa thấy biểu đồ đường" KHÔNG phải bug — người dùng chưa
upload Performance tháng 09, `performance_logs` rỗng nên không có gì để vẽ (Batch/Day vẫn
vẽ được vì dùng nguồn `availability_logs` khác). Tiện thể thêm UX: sparkline rỗng giờ hiện
"No data for this period" thay vì canvas trắng trơn im lặng (`dyeing_hub.js::
renderSparkline()`). (2) Sửa layout ô "Downtime %": trước đây `justify-content:center`
khiến cả khối (label/số/caption/link) bị dồn vào giữa ô theo chiều dọc thay vì label ở
trên cùng và "View details" ở dưới cùng như các ô khác — bỏ `align-items/justify-content:
center` khỏi `.dash-cell-downtime`, đổi `.dash-panel-link` (dùng chung mọi ô) sang
`margin-top: auto` (đẩy xuống đáy khi có khoảng trống thừa, vô hại với các ô đã có sẵn
phần tử `flex:1` — chỉ thực sự đổi hành vi ở ô Downtime, ô DUY NHẤT không có filler nào).
Bản ghi trước đó (2026-09-18 — redesign Dashboard) giữ nguyên ở mục -15/-16 bên dưới.

**Cập nhật lần cuối (bản ghi cũ):** 2026-09-18 (bản ghi mới nhất) — 3 việc riêng biệt trong
cùng 1 phiên làm việc, theo thứ tự: (1) **Bug thật + sửa**: `upsert_machine_config()`
("Batch Per Day by Machine", `reports/cleaning_matrix.py`) dùng "SELECT xem đã
có chưa rồi INSERT hoặc UPDATE" KHÔNG nguyên tử — vì bảng `machines` mặc định
RỖNG, sửa liên tiếp nhiều field trên CÙNG 1 máy chưa từng cấu hình bắn nhiều
request gần như đồng thời, có thể cùng chạy nhánh INSERT -> vi phạm
`machine_id UNIQUE` -> lỗi "lưu lúc được lúc không" đúng như người dùng report.
Đã đổi sang `INSERT ... ON CONFLICT(machine_id) DO UPDATE` nguyên tử (cùng
nguyên tắc `upsert_case_note()` bên downtime). Đồng thời sửa UX: lưu 1 field
KHÔNG còn `load()` lại toàn bảng (chỉ Capacity mới cần, các field còn lại
THUẦN mô tả) — tránh xoá mất ô khác đang gõ dở; thêm nút thu gọn/mở rộng 5 cột
cấu hình máy (state lưu localStorage). (2) **Bug thật + sửa (production
Vercel+Supabase)**: request gặp `psycopg2.OperationalError: SSL connection
has been closed unexpectedly` ở `get_current_user()` -> Flask cố render
`errors/500.html` -> `inject_nav_menu` context processor gọi
`get_current_user()` LẦN NỮA dùng lại đúng `g.db` đã hỏng -> `InterfaceError:
connection already closed` -> trang lỗi thân thiện KHÔNG BAO GIỜ render được.
Đã thêm `execute_query()`/`execute_one()` tự phát hiện connection Postgres bị
đứt, đóng + mở lại + thử lại ĐÚNG 1 LẦN (an toàn vì luôn là SELECT thuần);
`get_current_user()` coi như "chưa đăng nhập" nếu DB vẫn lỗi sau retry thay vì
crash tiếp. (3) **Tính năng mới**: thêm cột "Standard" (ngưỡng giờ) vào bảng
"Standard Achievement Breakdown" (Downtime) — xem chi tiết đầy đủ ở mục -12
bên dưới. (4) **UI nhỏ**: bỏ hẳn KPI widget "BATCH/DAY" (subtitle
"batch/day/machine", `id="valid-batches"`) khỏi tab Overview của trang
Downtime theo yêu cầu người dùng — `downtime-kpis` đổi từ 5 xuống 4 cột, KHÔNG
đụng gì tới `kpis.valid_batches` ở backend (chỉ ẩn khỏi UI, giá trị vẫn tính
và trả về trong `/api/summary` phòng khi cần lại). (5) **Tính năng mới**: báo
cáo "Batch/Day" — đổi tab mặc định sang "Batch/Day Trend" (đưa lên trước
"Fabric/Color Matrix"), báo cáo Trend giờ LUÔN cố định 3 dòng/3 đường Cotton/
CVC/Polyester (loại bỏ hoàn toàn fabric type khác + bộ lọc Fabric Type trên
tab này — không còn ý nghĩa khi báo cáo đã cố định 3 loại), thêm cột Target
(giờ/kỳ) có thể sửa qua UI cho từng loại vải + đường Target nét đứt ngang
xuyên suốt chart (bảng mới `batch_day_trend_targets`, khoá `fabric_type`) —
xem chi tiết đầy đủ ở mục -13 bên dưới. (6) **Tính năng mới**: áp dụng LẠI
đúng pattern ở mục (5) cho báo cáo "%Tank Loading" (Engine `tank_loading`) —
LUÔN cố định 3 dòng/3 đường Cotton/CVC/Polyester (bỏ filter Fabric Type), đổi
chart từ `type: "bar"` sang `type: "line"`, thêm cột Target (%) + đường nét
đứt trên chart, bảng Target mới `tank_loading_targets` (khoá `fabric_type`,
KHÔNG import cross-engine từ `batch_matrix` — định nghĩa `MAIN_FABRIC_TYPES`
riêng, đúng Vertical Slice Architecture) — xem chi tiết đầy đủ ở mục -14 bên
dưới. (7) **Tinh chỉnh UI**: đổi cả 2 báo cáo (5)+(6) từ "1 chart gộp 3 đường
màu khác nhau" sang "3 chart RIÊNG BIỆT đặt cạnh nhau" (trái=Cotton,
giữa=CVC, phải=Polyester, theo yêu cầu người dùng) — mỗi chart giờ chỉ có 1
đường số liệu + 1 đường Target của ĐÚNG loại đó, ẩn hẳn legend (không cần
phân biệt màu nữa vì đã có tiêu đề riêng từng chart). (8) **Tính năng lớn**:
viết lại HOÀN TOÀN trang "Dyeing Hub" (`/dyeing/`) từ 3 widget dạng bảng
thành 1 Dashboard 8 ô biểu đồ (Batch/Day 3 đường gộp 1 chart, gauge OEE nửa
hình tròn có kim chỉ, số % Downtime tháng hiện tại, %Tank Loading 3 đường
gộp 1 chart, 4 mini chart trend Rate% của RFT: Lab to Lab/Lab to Bulk/Bulk
to Bulk/2nd Batch) — TẤT CẢ dùng chung 1 khoảng ngày tự tính (từ ngày 15 lấy
tháng hiện tại tới hôm nay, trước ngày 15 lấy TRỌN tháng trước) + filter
Capacity >= 500Kg cố định — xem chi tiết đầy đủ ở mục -15 bên dưới. (9)
**Redesign UI/UX Dashboard theo review chuyên gia MES/Andon** (người dùng
đóng vai "nhà phê bình thiết kế" tự đánh giá bản (8), rồi cùng thống nhất 3
quyết định qua hỏi-đáp trước khi code): Batch/Day là hero DUY NHẤT (số cực
lớn, không còn là 1-trong-8-ô-bằng-nhau); gộp 4 ô RFT thành 1 card duy nhất
(lưới 2x2 nội bộ) hiện trạng thái "Đang chờ cấu hình" thay vì đường phẳng 0%
gây hiểu nhầm; và quan trọng nhất — toàn bộ Dashboard giờ là 1 "sân khấu"
(stage) kích thước cố định 1600x900 co giãn ĐỀU (transform: scale) để LUÔN
vừa khít màn hình, KHÔNG BAO GIỜ cuộn trang, chấp nhận dải trống
(letterbox) khi tỉ lệ màn hình lệch 16:9 — chuẩn bị cho mục tiêu treo TV
Andon thật trong xưởng. Phát hiện + sửa thêm 1 bug thật liên quan (sidebar
có thể ép cả trang cuộn dọc trên viewport thấp — sửa `--app-sidebar` global
trong `app.css`, ẢNH HƯỞNG MỌI TRANG, không chỉ Dyeing Hub). Xem chi tiết
đầy đủ ở mục -16 bên dưới. Bản ghi trước đó (2026-09-18 sáng — bug Batch/Day
Trend `recompute_all()`) giữ nguyên ở mục -11.

**Cập nhật lần cuối (bản ghi cũ):** 2026-09-17 — Thêm 2 filter mới (Fabric Type, Brand
Program) vào TẤT CẢ 5 báo cáo của Dyeing Hub (Downtime, Batch/Day — cả 2 tab,
Batch Per Day by Machine, Right First Time, %Tank Loading) + chuẩn hoá cách
trình bày mọi filter dropdown giống hệt Downtime (dropdown "N selected"/"All
..." + checkbox "Select All" — trước đó "Batch Per Day by Machine" hiển thị
kiểu liệt kê ngang "300kg, 500kg, 600kg, 1200kg, 2400kg" trong nút bấm, khác
hẳn Downtime). Chi tiết đầy đủ ở mục -10 bên dưới (rủi ro kỹ thuật quan trọng
nhất: bug COUNT-DISTINCT-dạng-giờ suýt tái diễn ở `batch_matrix`, đã tránh
bằng đường tính riêng). Bản ghi trước đó (2026-09-14 — cột Target Downtime by
Category + 2 bug Postgres/Vercel) vẫn giữ nguyên ở mục -9.

**Cập nhật lần cuối (bản ghi cũ):** 2026-09-14 — Thêm cột Target (admin-only) vào báo cáo
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
- Domain `dyeing` hiện có 8 Engine: `oee`, `downtime`, `excel_import`,
  `manual_entry`, `reports`, `batch_matrix`, `rft`, `tank_loading` (bản ghi cũ
  của file này từng chỉ liệt kê 3/6 rồi 7/7 — lưu ý cập nhật lại mỗi khi thêm
  Engine mới, đừng để lệch).
- **Engine `rft` (Right First Time) — CÓ QUY TẮC PHÂN LOẠI THẬT (2026-09-19,
  trước đó chỉ là scaffold `classify_rft_category()` luôn trả `None` từ
  2026-09-13)**: báo cáo 6 tab phân loại mẻ nhuộm theo loại lần chạy — Lab to
  Lab, Lab to Bulk, Bulk to Bulk, 2nd Batch, Rework, Adjust Color. Nguồn dữ
  liệu phân loại là file **"RFT report.xlsx"** (QC xuất, 13 cột: Customer,
  Color, OrderNo, GreigeCode, Dyelot, MachineType, NC-DG, ResultDYE,
  NewBatch2, Rework Count, Stage, recipe, body/rib) — người dùng cung cấp file
  mẫu (`tests/fixtures/sample_imports/RFT report.xlsx`) và xác nhận rõ 4
  quyết định nghiệp vụ qua hỏi-đáp trước khi code (không tự đoán):
  1. **Nguồn nạp dữ liệu**: bảng RIÊNG `rft_dye_results` (khoá `dyelot`,
     `core/rft_importer.py`) — KHÔNG mở rộng `batch_details` (tránh 2 luồng
     import khác nhau cùng ghi 1 bảng). Import qua luồng signature-detect
     CHUNG với Availability/Performance/Batch (`core/excel_importer.py::
     detect_file_type_from_headers()` thêm `RFT_SIGNATURE =
     {"dyelot","resultdye","stage"}`), nhưng ghi dữ liệu THẬT qua module riêng
     `core/rft_importer.py::sync_rft_results()` (CÙNG pattern
     `core/batch_importer.py::sync_batch_details()` — KHÔNG dùng
     `detect_and_parse_file()`'s nhánh RFT nội bộ cho import thật, nhánh đó
     CHỈ phục vụ preview/auto-detect, giống nguyên tắc đã áp dụng cho BATCH).
     Modal Import trên Dyeing Hub có thêm option "RFT Report"
     (`value="rft"`), auto-detect cũng nhận diện được.
  2. **Quy tắc map Stage -> tab**: cột `Stage` (chuẩn hoá `.strip().lower()`)
     map TRỰC TIẾP qua `STAGE_TO_CATEGORY` (`rft/service.py`) sang 1 trong 6
     tab — người dùng xác nhận Stage trong dữ liệu đầy đủ THẬT sẽ tự có đủ 6
     giá trị (file mẫu 32 dòng chỉ là 1 phần nhỏ, không có `lab to lab`/
     `rework`/`adjust color` là bình thường). Giá trị Stage KHÔNG khớp 6 tên
     trên **KHÔNG bị gộp vào tab nào** (không bịa nhóm "Unclassified" như
     Color Group ở `batch_matrix`) — đếm riêng qua field `other_stage_count`
     trả về cùng response, UI hiển thị dòng cảnh báo nhỏ trên mỗi tab khi > 0
     (chỉ báo dữ liệu nguồn cần rà soát, không phải lỗi tính toán).
  3. **Nguồn `production_date`** (file RFT report không có cột ngày): LEFT
     JOIN `availability_logs` theo `lower(trim(a.batch))=lower(trim(r.dyelot))`
     (cùng khoá JOIN đã verify 99.7% khớp ở `batch_matrix`/`downtime`) lấy
     StartTime/EndTime. Dòng KHÔNG khớp (thường là MachineType "Small
     Machine", chưa theo dõi Availability) **vẫn được GIỮ LẠI** khi KHÔNG có
     filter ngày (rơi vào 1 cột pivot riêng **"Unknown Date"**, luôn xếp CUỐI
     bảng — không sort theo alphabet chung vì chữ 'u' có thể chen giữa key
     ngày/tuần/tháng dạng số), nhưng bị LOẠI khi người dùng chủ động lọc
     From/To Date (không đủ căn cứ xác nhận nằm trong khoảng).
  4. **Công thức KPI ĐỔI HẲN** so với thiết kế scaffold ban đầu: `rate_pct =
     số mẻ ResultDYE='OK' trong CHÍNH tab đó / tổng số mẻ CỦA CHÍNH tab đó`
     (đo "tỷ lệ đạt ngay lần đầu" của loại lần chạy đó) — KHÔNG còn là tỷ
     trọng so với tổng 6 tab như bản cũ. Cell/Total trên bảng pivot hiển thị
     **dạng %** (không phải số mẻ thô). KPI card đổi tên: "TOTAL BATCHES" (mẻ
     của tab này)/"OK (RIGHT FIRST TIME)" (thay "category_batches")/"RATE".
  **Business rule riêng cho 2 tab "Rework"/"Adjust Color"**: CHỈ tính mẻ có
  `MachineType = ">=500kg"` (loại "Small Machine") — `RESTRICTED_TO_LARGE_MACHINE`
  trong `rft/service.py`, áp dụng SAU khi đã phân loại theo Stage (không ảnh
  hưởng 4 tab còn lại). Filter Machine Type (>=500kg / Small Machine) là filter
  MỚI, độc lập với Capacity (Kg) cũ — lấy trực tiếp từ `rft_dye_results.machine_type`
  (không phụ thuộc JOIN `availability_logs`, nên "Small Machine" — vốn thường
  không khớp Availability — vẫn lọc được đầy đủ, theo đúng yêu cầu "đây là dữ
  liệu thật, không được mất").
  Bộ lọc đầy đủ: Capacity (Kg), Machine Type (mới), Fabric Type, Brand
  Program, From/To Date, Group By Day/Week/Month — `available_fabric_types`/
  `available_brand_programs`/`available_machine_types` đều tính từ CÙNG 1 lần
  query (sau lọc Capacity+Date, TRƯỚC khi áp 3 filter kia), độc lập với chính
  3 filter đó (cùng nguyên tắc downtime/batch_matrix).
  Cờ `RFT_CLASSIFICATION_READY` (`rft/service.py`) đã đổi từ `False` sang
  **`True`** — Dyeing Hub Dashboard (4 mini chart Lab to Lab/Lab to Bulk/Bulk
  to Bulk/2nd Batch, thêm ở bản ghi 2026-09-18 mục -16) tự động hết hiện
  "Awaiting classification rules", hiện đúng % thật (KHÔNG cần sửa gì ở
  `dyeing_hub.js` — response `kpis.rate_pct`/`chart.rate_values`/
  `chart.categories` giữ NGUYÊN tên field, chỉ đổi Ý NGHĨA công thức).
  **File mới**: `core/rft_importer.py` (`RFT_HEADER_MAP`, `parse_rft_file()`,
  `sync_rft_results()` — UPSERT theo `dyelot`, cùng kỹ thuật khử trùng trước
  `executemany()` để tránh `CardinalityViolation` trên Postgres đã áp dụng ở
  Batch). `supabase/schema.sql` đã thêm bảng `rft_dye_results` + bật RLS —
  **CHƯA CHẠY trên Supabase production** (xem "Việc tiếp theo").
  **Verify đã làm**: `tests/test_rft_classification.py` (MỚI, `python
  tests/test_rft_classification.py`, không dùng pytest) — 5 kịch bản: (1) map
  đúng 6 Stage + Stage lạ trả `None`; (2) `parse_rft_file()` +
  `detect_file_type_from_headers()` trên CHÍNH file mẫu thật (31 dòng, 21
  OK/10 NG, 0 lỗi); (3) công thức KPI OK/tổng-trong-tab ĐÚNG số tay tính +
  giới hạn >=500kg cho Rework loại đúng mẻ Small Machine + `other_stage_count`
  đếm đúng; (4) mẻ không khớp `availability_logs` rơi đúng bucket "Unknown
  Date" khi không lọc ngày, bị loại khi lọc ngày tường minh; (5)
  `sync_rft_results()` end-to-end trên file mẫu thật, import 2 LẦN xác nhận
  UPSERT idempotent (không nhân đôi dòng, `import_logs` vẫn ghi đủ audit
  trail 2 lần). Full regression: `test_permission_model.py` (28 case,
  `/dyeing/rft/` vẫn gate đúng permission, không đổi hành vi Engine khác) +
  `test_batch_matrix_formula.py`/`test_production_date.py`/
  `test_postgres_shim_translation.py`/`test_downtime_brand_fabric_filters.py`/
  `test_batch_matrix_brand_fabric_filters.py`/
  `test_downtime_case_notes_context.py`/`test_batch_day_trend_recompute_all.py`
  đều PASS 100% (không regression). **Lưu ý phát hiện phụ, KHÔNG phải do thay
  đổi lần này**: `verify_rollup_parity.py` đang lệch 3 scenario trên DB dev cục
  bộ — đã cô lập bằng `git stash` (chạy lại đúng script trên code CHƯA có thay
  đổi RFT vẫn lệch y hệt) — nguyên nhân là `cleaning_mc_daily_summary` cục bộ
  chưa được `flask rebuild-summaries` lại sau đợt pull code mới nhất (mục -11
  bên dưới), không liên quan gì tới RFT.
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
-17. **Báo cáo RFT (cả 6 tab) — áp dụng lại pattern "3 loại vải cố định + Target + đường nét
   đứt" đã làm cho "%Tank Loading"/"Batch/Day Trend"** (2026-09-19, theo yêu cầu người dùng
   "mỗi báo cáo phân làm 3 loại cotton cvc polyester ... chuyển thành biểu đồ đường và có
   thêm cột target ... làm hết cho cả 6 mục").

   **Khác biệt so với %Tank Loading (mục -14)**:
   - RFT có **6 tab độc lập** (Lab to Lab/Lab to Bulk/Bulk to Bulk/2nd Batch/Rework/Adjust
     Color), mỗi tab cần Target RIÊNG theo từng loại vải — bảng `rft_targets` khoá GHÉP
     **`(category, fabric_type)`** (KHÁC `tank_loading_targets`/`batch_day_trend_targets`
     chỉ khoá `fabric_type` đơn, vì 2 báo cáo đó chỉ có 1 "trang" duy nhất).
   - KPI card đầu trang (TOTAL BATCHES/OK/RATE) và `chart.values`/`chart.rate_values`/
     `kpis.rate_pct` **GIỮ NGUYÊN Ý NGHĨA CŨ** — vẫn gộp CẢ tab (mọi loại vải, kể cả loại
     ngoài Cotton/CVC/Polyester), KHÔNG thu hẹp phạm vi toàn báo cáo về 3 loại chính như
     %Tank Loading đã làm (Tank Loading loại HẲN fabric khác 3 loại chính khỏi KPI tổng).
     Lý do: field này được Dyeing Hub Dashboard đọc trực tiếp (4 mini-chart RFT) — quyết
     định GIỮ NGUYÊN hành vi cũ để KHÔNG phải sửa `dyeing_hub.js` (đúng nguyên tắc đã áp
     dụng khi thêm `rate_values` trước đó: "bổ sung THUẦN TUÝ, không đổi/xoá field cũ").
     Phần chia-3-dòng-theo-vải là hoàn toàn MỚI (`rows`/`chart.series`), chỉ phục vụ khu vực
     bảng+chart chi tiết bên dưới KPI card trên trang report RFT.
   - Bỏ hẳn dropdown filter "Fabric Type" chung (trước đó cho phép lọc theo BẤT KỲ giá trị
     Fabric Type nào xuất hiện trong dữ liệu) — không còn ý nghĩa khi mỗi tab đã LUÔN hiển
     thị cố định đúng 3 loại. Filter Machine Type (>=500kg/Small Machine, dùng cho business
     rule Rework/Adjust Color) và Brand Program GIỮ NGUYÊN, không liên quan tới thay đổi này.
   - Route mới `POST /dyeing/rft/api/targets/<slug>/<fabric_type>` (`<slug>` là khoá URL 6
     tab, VD `lab_to_lab` — route tự map sang tên hiển thị qua `RFT_CATEGORY_SLUGS`, cùng
     cách `api_summary` đã làm).
   - `MAIN_FABRIC_TYPES`/`_normalize_main_fabric_type()` định nghĩa RIÊNG trong
     `rft/service.py` (KHÔNG import từ `tank_loading`) — giữ đúng Vertical Slice
     Architecture, cùng quyết định trùng lặp có kiểm soát đã áp dụng ở mục -14.

   Layout: mỗi tab đổi từ 1 chart `bar` + bảng 1-dòng sang **3 chart `line` cạnh nhau**
   (trái=Cotton, giữa=CVC, phải=Polyester, dùng CHUNG class CSS `.trend-charts-row`/
   `.trend-chart-col` đã có sẵn từ %Tank Loading) + bảng 3 dòng có cột Target editable
   (`.case-note-cell`/`.case-note-input` tái dùng CSS có sẵn, không viết mới). JS
   (`rft.js`) đổi cấu trúc `charts` từ 1-instance/category sang khoá ghép
   `"${category}::${fabricType}"` (18 Chart instance tối đa, 6 tab x 3 vải) — `activatePage()`
   resize TẤT CẢ chart thuộc đúng category đang active (lọc theo tiền tố khoá) thay vì 1
   instance như bản cũ.

   **Verify đầy đủ**: `tests/test_rft_classification.py` (5 kịch bản cũ, KHÔNG đổi assertion
   nào — vì `kpis`/`other_stage_count`/`periods` giữ nguyên hành vi) — PASS 100% sau khi sửa.
   `tests/test_permission_model.py` — PASS 100%, không regression Engine khác. Smoke test
   thêm (ad-hoc, KHÔNG lưu vào `tests/`) dựng app Flask ĐẦY ĐỦ + DB tạm qua `init_db.py`:
   trang `/dyeing/rft/` render 200, KHÔNG còn `fabric-type-toggle` trong HTML; API trả đúng
   3 `rows` theo thứ tự Cotton/CVC/Polyester, `target=null` khi chưa cấu hình; POST target
   lưu/đọc lại đúng giá trị; `/dyeing/` (Hub) vẫn render 200 với field cũ
   (`kpis`/`chart.categories`/`chart.rate_values`/`classification_ready`) không đổi.

   **Supabase production**: đã thêm bảng `rft_targets` vào `supabase/schema.sql` (kèm RLS) —
   CHƯA CHẠY trên Supabase thật, cần admin áp DDL thủ công (bảng hoàn toàn mới).

-16. **Redesign lại Dashboard Dyeing Hub (mục -15) theo review UI/UX chuyên gia MES/Andon**
   (2026-09-18, người dùng yêu cầu tôi đóng vai "nhà phê bình thiết kế" tự chấm bản (8) đầu
   tiên theo 4 tiêu chí: Hero Metric / Tinh giản / Exception-based / Quy tắc 3 giây — review
   KHÔNG viết code, chỉ phân tích, rồi hỏi lại người dùng 3 câu trước khi thống nhất hướng).

   **Tự phê bình bản đầu (mục -15) phát hiện**: Batch/Day tuy đúng vị trí góc trên-trái
   nhưng cùng kích thước/trọng số thị giác với 7 ô khác — không phải "hero" thật; 4 ô RFT
   (đang luôn 0% vì `classify_rft_category()` chưa xong) chiếm nguyên 50% diện tích cho dữ
   liệu chưa sẵn sàng; Downtime%/Batch/Day không có tô màu theo ngưỡng (exception-based
   yếu, trừ gauge OEE); biểu đồ 3 đường + chú giải đòi hỏi bước tra cứu, không đạt "3 giây".

   **3 quyết định người dùng chốt qua hỏi-đáp** (không đoán, hỏi rõ từng cái):
   1. Batch/Day là hero **DUY NHẤT** (không chia sẻ vị trí nổi bật với %Tank Loading).
   2. Giữ nguyên 4 ô RFT (không ẩn) để không phải bố trí lại layout sau này khi có dữ liệu
      thật — nhưng cần tránh trông "như lỗi hệ thống" trong lúc chờ.
   3. Dashboard sẽ treo TV lớn trong xưởng (Andon thật) — nhưng người dùng CHỦ ĐỘNG đơn
      giản hoá yêu cầu: bỏ qua các chi tiết "khoảng cách xem/chế độ kiosk", chỉ cần ĐÚNG 1
      ràng buộc kỹ thuật: **toàn bộ Dashboard luôn vừa khít màn hình, không bao giờ cuộn,
      dù tỉ lệ khung hình nào** — "gom tất cả widget vào 1 widget tổng, cân tỉ lệ ngầm".
      Khi được hỏi về đánh đổi dải trống (letterbox) ở màn hình lệch tỉ lệ, người dùng chọn
      **chấp nhận dải trống, đổi lại mọi widget luôn đúng tỉ lệ tuyệt đối** (không co kéo méo).

   **Thiết kế lại** (`modules/dyeing/templates/dyeing_hub.html`,
   `modules/dyeing/static/dyeing_hub.js`):
   - **Cơ chế "sân khấu co giãn"**: `#dash-stage` (chứa toàn bộ 5 khối) có kích thước CỐ
     ĐỊNH 1600x900 (16:9) khai báo bằng CSS thường (không phải %), rồi `dyeing_hub.js::
     rescaleStage()` đo kích thước thật của `#dash-stage-outer` (vùng còn trống sau khi trừ
     sidebar + tiêu đề trang), tính `scale = min(availW/1600, availH/900)`, áp
     `transform: scale(...)` lên `#dash-stage` — CHÍNH XÁC kỹ thuật "canvas cố định + co
     giãn đều" dùng phổ biến cho màn hình kiosk/digital signage, khác hẳn responsive web
     thông thường (chỉ phản ứng theo chiều rộng, cho phép cuộn dọc tự do). Dùng
     `ResizeObserver` quan sát `#dash-stage-outer` (không cần biết RIÊNG lý do đổi kích
     thước — window resize hay sidebar thu/phóng đều tự kích hoạt tính lại).
   - **Bố cục 5 khối** (không còn 8 ô bằng nhau): cột trái (640px, cao suốt 900px) = Hero
     Batch/Day; cột phải (960px) chia lưới 2x2 = OEE / Downtime% / %Tank Loading / RFT
     (RFT giờ là 1 card DUY NHẤT chứa lưới 2x2 nội bộ cho 4 category, không phải 4 ô cấp
     cao ngang hàng như bản -15 — vừa đúng yêu cầu "giữ 4 ô" vừa gọn không gian hơn).
   - **Hero Batch/Day**: số lớn 168px (tổng gộp 3 loại vải, lấy từ `kpis.batch_per_day` có
     sẵn) thay vì biểu đồ 3 đường làm trọng tâm; 3 số phụ Cotton/CVC/Polyester (kèm chấm
     màu, không cần chú giải riêng vì màu đặt cạnh ngay tên) lấy từ `rows[i].total`; sparkline
     mờ (ẩn hẳn trục/lưới/chú giải/tooltip — chỉ giữ HÌNH DẠNG đường, đúng tinh thần "giảm
     chart chrome cho màn hình đọc từ xa") lấy từ `rows[i].values`. %Tank Loading dùng lại
     ĐÚNG pattern này nhưng ở quy mô nhỏ hơn (ô phụ, không phải hero).
   - **RFT gộp 1 card, dùng cờ `classification_ready`** (thêm ở mục -15's tiếp theo — xem
     `rft/service.py::RFT_CLASSIFICATION_READY`, hằng số MỚI đặt ngay cạnh
     `classify_rft_category()`, comment nhắc rõ "đổi thành True khi thay xong hàm này"): khi
     `false` (hiện tại), card nhận class `is-pending` (làm mờ màu số liệu) + 1 dòng chú
     thích "Đang chờ cấu hình quy tắc phân loại" — THAY THẾ hoàn toàn cách hiển thị "0%"
     trần trụi dễ hiểu nhầm là dữ liệu thật xấu. Khi cờ chuyển `true` (sau khi có quy tắc
     phân loại thật), card tự động hiện đúng số liệu — không cần sửa gì thêm ở
     template/JS.
   - **Downtime% tô màu theo ngưỡng tạm** (`downtimeColorFor()`: <=8% xanh `--success`,
     <=15% vàng `--warning`, >15% đỏ `--danger`) — **CHƯA có ngưỡng chính thức từ người
     dùng** (câu hỏi này đã hỏi nhưng chưa được trả lời trong phiên — để mặc định hợp lý,
     dễ chỉnh sửa lại 1 chỗ duy nhất khi có số thật).

   **BUG THẬT phát hiện + sửa khi verify Playwright ở NHIỀU tỉ lệ màn hình** (không phải
   người dùng report — bắt được TRƯỚC khi báo hoàn thành, đúng quy trình bắt buộc): viewport
   1366x768 (laptop phổ biến) vẫn PHÁT SINH CUỘN DỌC dù `.app-main` đã ép `height:100vh`
   cho riêng trang này. Nguyên nhân: `.app-sidebar` (`static/css/app.css`, DÙNG CHUNG MỌI
   TRANG) khai báo `min-height: 100vh` (không phải `height`) — khi danh sách menu dài hơn
   viewport (846px menu vs 768px màn hình ở test case này), sidebar tự do cao HƠN 100vh để
   chứa hết menu, kéo theo `.app-shell` (flex row cha) và cả trang bị cuộn theo, BẤT KỂ
   `.app-main` đã bị ép cao đúng 100vh hay chưa. Đã có SẴN `.sidebar-body{flex:1;
   min-height:0; overflow-y:auto;}` để cuộn nội bộ menu khi cần, nhưng KHÔNG BAO GIỜ được
   kích hoạt vì `.app-sidebar` không hề bị ép trần chiều cao. Sửa: đổi `.app-sidebar` sang
   `height: 100vh` (giữ cả `min-height:100vh` cho an toàn) — **ảnh hưởng MỌI TRANG** (không
   chỉ Dyeing Hub) nhưng là sửa ĐÚNG bug tiềm ẩn từ trước (đã kiểm tra trang Downtime/Admin
   Accounts sau khi sửa — sidebar hiển thị bình thường, không bị cắt/vỡ, trang nào có nội
   dung dài hơn viewport vẫn cuộn ĐÚNG như thiết kế, chỉ riêng sidebar giờ tự cuộn nội bộ
   khi menu dài hơn màn hình thay vì kéo cả trang cuộn theo).

   **Thêm block mới cho base.html**: `{% block body_class %}{% endblock %}` (mặc định
   rỗng, KHÔNG đổi hành vi trang nào khác) — `dyeing_hub.html` dùng để gắn class
   `page-dyeing-hub` lên `<body>`, cho phép CSS ép `.app-main` cao 100vh CHỈ RIÊNG trang
   này (scope bằng `body.page-dyeing-hub .app-main {...}`) mà không đụng hành vi cuộn bình
   thường của mọi trang khác trong app.

   **Verify đầy đủ**: seed dữ liệu mẫu vào bản sao TẠM của DB dev (không đụng file thật —
   đã xác nhận `availability_logs`/`performance_logs` DB dev thật vẫn 0 dòng sau khi xong),
   chạy Playwright ở 4 tỉ lệ màn hình khác nhau (1600x900 chuẩn 16:9, 2400x900 ultrawide,
   1366x768 laptop phổ biến, 1200x1200 vuông — trường hợp lệch tỉ lệ cực đoan nhất) + đo
   `document.documentElement.scrollHeight` so với `clientHeight` bằng JS thật (không đoán
   qua ảnh chụp) — xác nhận CẢ 4 tỉ lệ đều KHÔNG có cuộn dọc/ngang sau khi sửa bug sidebar.
   Chụp ảnh xác nhận bằng mắt: dải letterbox xuất hiện đúng ở 2 tỉ lệ lệch (ultrawide letterbox
   trái-phải, vuông letterbox trên-dưới), tỉ lệ chuẩn/gần chuẩn (16:9, laptop) lấp đầy gần
   như toàn bộ. Xác nhận cờ `is-pending`/ghi chú RFT hiện đúng qua `classList.contains()`.
   Test cả Light/Dark Mode. Re-run `tests/test_permission_model.py` — PASS 100%, không
   regression trên các trang khác sau khi sửa `.app-sidebar` toàn cục.

-15. **Viết lại Dyeing Hub thành Dashboard tổng 8 widget biểu đồ** (2026-09-18, theo yêu
   cầu người dùng — hỏi rõ 1 câu về kiểu chart cho 4 widget RFT trước khi code: line chart
   trend theo ngày, giống Batch/Day/Tank Loading, thay vì gauge như OEE).

   **Bố cục** (`modules/dyeing/templates/dyeing_hub.html`, CSS Grid `.dash-grid`
   3 cột, `grid-auto-rows: minmax(320px, auto)` — xem bài học ở mục "Bug thật" bên dưới):
   Hàng 1 = Batch/Day (trái) / OEE gauge (giữa) / Downtime % (phải). Hàng 2 = %Tank
   Loading + 4 mini-chart RFT (Lab to Lab, Lab to Bulk, Bulk to Bulk, 2nd Batch — ĐÚNG
   thứ tự người dùng nêu, bỏ qua Rework/Adjust Color).

   **KHÔNG thêm route mới nào** (trừ 1 field bổ sung) — Dashboard hoàn toàn tái dùng các
   API JSON đã có sẵn của từng Engine (`batch_matrix.api_batch_day_trend`,
   `oee.api_calculate`, `downtime.api_summary`, `tank_loading.api_summary`,
   `rft.api_summary`), gọi song song bằng `Promise.all()` từ `dyeing_hub.js` — ĐÚNG kiến
   trúc widget cũ (fetch async độc lập từng Engine), chỉ đổi CÁCH RENDER (chart thay vì
   bảng) và THÊM tham số ngày/capacity dùng chung.

   **Quy tắc khoảng ngày** (tính ở `dyeing_hub.js::dashboardWindow()`, client-side, không
   cần route mới): `today.getDate() >= 15` → từ ngày 1 tháng hiện tại tới hôm nay
   (month-to-date); ngược lại → TRỌN tháng trước (`new Date(year, month, 0)` = ngày cuối
   tháng trước, cách lấy "ngày 0" kinh điển trong JS Date). Filter Capacity CỐ ĐỊNH
   `"500,600,1200,2400"` — CHÍNH LÀ tập giá trị Capacity >= 500Kg thật có trong dữ liệu
   (7 mức toàn hệ thống: 25/50/300/500/600/1200/2400), TRÙNG với default đã dùng sẵn ở
   Downtime/Batch Matrix/RFT/Tank Loading — không phải danh sách suy đoán riêng.

   **Batch/Day + %Tank Loading trên Dashboard**: GỘP LẠI thành 1 chart/3 đường màu khác
   nhau (KHÁC trang report riêng của 2 báo cáo này — đã tách thành 3 chart cạnh nhau ở
   mục -13/-14 theo yêu cầu TRƯỚC — ở đây là widget tóm tắt trên Hub nên gộp lại cho gọn
   không gian, đúng yêu cầu người dùng lần này "biểu đồ gồm 3 đường").

   **RFT — thêm field mới `chart.rate_values`** (`modules/dyeing/engines/rft/service.py::
   get_rft_pivot_data()`): API cũ chỉ có `chart.values` (SỐ ĐẾM mẻ đã phân loại/kỳ, không
   phải %) và `kpis.rate_pct` (1 số % duy nhất cho CẢ khoảng ngày, không theo từng kỳ) —
   không đủ để vẽ 1 đường trend Rate% theo ngày. Thêm `rate_values` = tính riêng
   `count/len(batches)*100` cho TỪNG kỳ (không dùng `total_batches` toàn khoảng, tránh
   lệch nếu số mẻ/kỳ không đều) — bổ sung THUẦN TUÝ (field mới, không đổi/xoá field cũ),
   trang report RFT gốc (`rft_view.html`/`rft.js`) không bị ảnh hưởng gì. **Lưu ý quan
   trọng đã biết trước**: `classify_rft_category()` LUÔN trả `None` (chưa có quy tắc phân
   loại thật, xem mục "Đang làm" phần RFT phía trên) — 4 chart RFT trên Dashboard sẽ HIỆN
   ĐƯỜNG PHẲNG 0% cho tới khi có quy tắc, đây là HÀNH VI ĐÚNG chứ không phải bug Dashboard.

   **OEE gauge — nửa hình tròn + kim chỉ, tự viết bằng Chart.js (KHÔNG thêm thư viện
   ngoài)**: dùng chart `type: "doughnut"` với `rotation: -90, circumference: 180,
   cutout: "72%"` (công thức "rainbow gauge" kinh điển — tâm vòng cung rơi vào CẠNH DƯỚI
   `chartArea`, không phải giữa). Kim chỉ vẽ bằng 1 Chart.js plugin tự viết
   (`gaugeNeedlePlugin`, đăng ký namespace riêng `options.plugins.gaugeNeedle` — ĐÚNG API
   plugin chuẩn Chart.js v4, không đụng state nội bộ của Chart instance). Góc kim quét
   TUYẾN TÍNH 180°(trái,0%) -> 270°(thẳng đứng,50%) -> 360°/0°(phải,100%). Giá trị lấy từ
   `oee.api_calculate?days=<độ dài khoảng ngày Dashboard>` — **CHÚ THÍCH RÕ "Definition
   pending"** dưới gauge vì người dùng xác nhận "OEE sẽ định nghĩa sau"; giá trị hiện tại
   chỉ là kết quả công thức CŨ (`Availability x Performance x Quality`, Quality giả định
   100%) đọc từ `machine_telemetry` — bảng này KHÔNG có khái niệm Capacity nên KHÔNG áp
   được filter Capacity >= 500Kg của Dashboard (giữ nguyên hạn chế đã biết, chờ định nghĩa
   OEE mới).

   **BUG THẬT tự phát hiện + sửa qua Playwright TRƯỚC KHI báo hoàn thành** (không phải
   người dùng report — quy trình bắt buộc "test UI trong browser trước khi báo xong" đã
   bắt được 2 lỗi): (1) **Quên thêm `<script src=".../chart.js@4.4.4/...">` vào
   `dyeing_hub.html`** — trang Hub trước giờ CHƯA BAO GIỜ dùng Chart.js (chỉ có bảng), nên
   không có sẵn thẻ script như các trang report khác — mọi hàm vẽ chart return sớm ở
   `typeof Chart === "undefined"`, khiến TOÀN BỘ 6 canvas trống trơn và gauge OEE không
   bao giờ cập nhật giá trị (kẹt ở "--%") — im lặng, KHÔNG lỗi console. (2) **CSS Grid +
   flex:1 trong container auto-height = canvas cao 0px**: `.dash-grid` (CSS Grid) không
   có `grid-auto-rows` cố định, nên chiều cao mỗi hàng grid = "auto" (theo nội dung) —
   `.dash-chart-wrap{flex:1}` bên trong `.widget-card{display:flex;flex-direction:column}`
   không có "khoảng trống còn lại" nào để giãn ra (vòng lặp phụ thuộc kinh điển của
   flexbox trong container auto-height), canvas render với chiều cao 0. Sửa bằng thêm
   `grid-auto-rows: minmax(320px, auto)` vào `.dash-grid` — cho mỗi hàng 1 chiều cao TỐI
   THIỂU cụ thể, phá vòng lặp phụ thuộc. **Bài học quy trình**: cả 2 lỗi này hoàn toàn IM
   LẶNG (không throw exception, không lỗi console) — chỉ phát hiện được nhờ chụp ảnh
   THẬT qua Playwright rồi NHÌN vào ảnh, không thể phát hiện chỉ bằng cách đọc code hay
   kiểm tra response API trả JSON đúng (JSON data hoàn toàn đúng, lỗi nằm 100% ở tầng
   render phía trình duyệt).

   **Verify đầy đủ**: sau khi sửa 2 bug trên, dựng lại DB SQLite tạm (copy từ DB dev,
   KHÔNG đụng file thật — đã xác nhận `availability_logs`/`performance_logs` DB dev thật
   vẫn nguyên 0 dòng sau khi verify xong) và chèn dữ liệu mẫu Cotton/CVC/Polyester trải
   14 ngày, chạy `flask rebuild-summaries`, khởi động server THẬT (port riêng, tránh đúng
   1 sự cố môi trường Windows đã gặp: nhiều tiến trình `python app.py` cũ từ các lần verify
   trước ĐỀU bind thành công vào cùng port 5000 — khác POSIX, Windows cho phép nhiều
   socket cùng LISTEN 1 port do ngữ nghĩa `SO_REUSEADDR` lỏng hơn — khiến request bị route
   nhầm vào server cũ trỏ DB rỗng, dễ nhầm tưởng là bug code; đã dọn sạch toàn bộ tiến
   trình `python.exe` cũ trước khi verify lại). Chụp ảnh Playwright CẢ Light lẫn Dark Mode
   (đúng nút toggle `.theme-toggle-btn` thật, không phải suy đoán) — xác nhận: 2 chart 3
   đường Cotton/CVC/Polyester vẽ đúng, gauge OEE vẽ đúng vị trí kim + đổi màu theo ngưỡng
   (67.4% ra màu vàng), 4 chart RFT hiện đúng đường phẳng 0% (đúng hành vi đã biết trước),
   không có lỗi console nào, cả 2 theme đều đọc đúng token màu (`--text-primary` cho kim
   chỉ, `--text-secondary` cho trục). Re-run `tests/test_permission_model.py` — PASS
   100%, không regression.

-14. **Báo cáo "%Tank Loading" — áp dụng LẠI đúng pattern "3 loại vải cố định + Target +
   đường nét đứt" vừa làm cho Batch/Day Trend (mục -13)** (2026-09-18, theo yêu cầu người
   dùng).

   **Khác biệt DUY NHẤT so với mục -13** (còn lại giống hệt về mặt kỹ thuật):
   - Đổi loại chart từ `type: "bar"` sang `type: "line"` (yêu cầu rõ "chuyển biểu đồ thành
     biểu đồ đường tương tự batch/day") — trước đó Tank Loading là bar chart 1 cột/kỳ,
     Batch/Day Trend vốn ĐÃ là line chart từ đầu nên mục -13 không cần đổi type.
   - `MAIN_FABRIC_TYPES`/`_normalize_main_fabric_type()` được **định nghĩa RIÊNG** trong
     `tank_loading/service.py` (KHÔNG import từ `batch_matrix/batch_day_trend.py`) — dù
     giá trị giống hệt (`("Cotton", "CVC", "Polyester")`), cố tình KHÔNG dùng chung 1 nguồn
     giữa 2 Engine để giữ đúng Vertical Slice Architecture (mỗi Engine tự đóng gói đầy đủ,
     không phụ thuộc Engine khác — CLAUDE.md mục 3-4). Đây là 1 trong những chỗ dự án CHỦ
     ĐÍCH chấp nhận trùng lặp có kiểm soát (kèm comment chéo tham chiếu) thay vì tạo phụ
     thuộc chéo giữa 2 Engine — cùng tinh thần `INVALID_FABRIC_TYPES` đã lệch nhau có chủ
     đích giữa `batch_matrix`/`downtime`/`rft` từ trước.
   - Bảng Target mới `tank_loading_targets` (khoá `fabric_type`) — tách riêng khỏi
     `batch_day_trend_targets` dù cùng khoá `fabric_type` giống hệt, vì 2 báo cáo đo 2 chỉ
     số khác nhau (Batch/Day vs %Tank Loading) trên 2 nguồn dữ liệu khác nhau
     (`availability_logs`+`batch_details` vs `performance_logs`).
   - Nguồn dữ liệu `performance_logs.fabric_type` (khác `availability_logs.fabric_type`
     dùng ở Batch/Day Trend) — 2 bảng import độc lập nhau nên KHÔNG có gì đảm bảo cùng quy
     ước viết hoa/thường, nhưng so khớp không phân biệt hoa/thường nên không thành vấn đề.

   Công thức MỖI loại vải: Sum(OutputKgH)/Sum(MaxOutputKgH) của ĐÚNG loại đó (tính độc
   lập, không dùng chung mẫu số) — giữ nguyên nguyên tắc Sum/Sum đã có từ bản 1-đường cũ.
   KPI tổng ở đầu trang (`tank_loading_pct`/`total_output_kgh`/`total_max_load_kgh`) giờ
   CHỈ tính trên 3 loại chính (loại khác bị loại khỏi TOÀN BỘ báo cáo, không chỉ khỏi
   chart/bảng) — đã verify riêng để xác nhận KPI tổng không bị lệch bởi dữ liệu loại vải
   khác (ví dụ Nylon).

   Verify: script DB tạm (bẫy đúng: 1 dòng Nylon với output=999 để xác nhận KHÔNG làm
   lệch KPI tổng của 3 loại chính) xác nhận công thức tách đúng theo từng loại vải, Target
   lưu/đọc đúng, từ chối đúng fabric_type ngoài danh sách. Verify end-to-end Flask test
   client (subprocess, DB tạm): trang đã gỡ filter Fabric Type, file JS tĩnh xác nhận
   `type: "line"` (không còn `"bar"`) + có `isTargetLine`, API luôn trả đủ 3 dòng, ghi
   Target qua API phản ánh đúng, operator chỉ-view bị chặn ghi (302). Re-run
   `tests/test_permission_model.py` — PASS 100%, không regression (chưa có test suite
   riêng cho `tank_loading` từ trước).

   **Postgres production**: đã thêm bảng `tank_loading_targets` vào `supabase/schema.sql`
   (kèm RLS) — CHƯA CHẠY trên Supabase thật, cần admin áp DDL thủ công (bảng hoàn toàn
   mới, không cần migration script riêng).

   **Cập nhật ngay sau đó (cùng ngày)**: người dùng yêu cầu đổi cách trình bày — thay vì 1
   chart gộp 3 đường màu khác nhau (Cotton/CVC/Polyester chồng lên nhau cùng 1 biểu đồ),
   tách thành **3 chart RIÊNG BIỆT đặt cạnh nhau** (trái=Cotton, giữa=CVC, phải=Polyester,
   đúng thứ tự `MAIN_FABRIC_TYPES`). Áp dụng CÙNG lúc cho CẢ Batch/Day Trend (mục -13) lẫn
   %Tank Loading. Mỗi chart giờ chỉ nhận đúng 1 dòng dữ liệu (`row`) + vẽ 1 đường số liệu +
   1 đường Target (nếu có) của ĐÚNG loại đó — không cần lọc legend theo hậu tố " Target"
   nữa (đơn giản hơn hẳn), chỉ cần ẩn hẳn legend (`display:false`) vì tiêu đề `<h4>` phía
   trên mỗi canvas đã đủ để phân biệt. JS đổi từ biến `let trendChart`/`let chart` (1 Chart
   instance) sang object `{fabric_type: Chart instance}`, `updateTrendChart()`/
   `updateChart()` giờ `forEach` qua `data.rows` để vẽ từng canvas riêng
   (`trend-chart-cotton`/`trend-chart-cvc`/`trend-chart-polyester` và tương tự
   `tank-loading-chart-*`). CSS mới `.trend-charts-row`/`.trend-chart-col` (flex 3 cột, dùng
   CHUNG class ở cả 2 file template) tự chuyển sang xếp dọc dưới 900px màn hình. Verify:
   Flask test client xác nhận cả 6 canvas ID (3 mỗi trang) tồn tại đúng trong HTML, trích
   xuất + `node -c` script JS đã render (thay xong Jinja) xác nhận cú pháp hợp lệ, re-run
   `test_permission_model.py`/`test_batch_day_trend_recompute_all.py` — PASS 100%.

-13. **Báo cáo "Batch/Day Trend" — đưa lên trước Matrix làm tab mặc định, LUÔN cố định
   3 dòng/3 đường Cotton/CVC/Polyester, thêm Target có thể sửa + đường nét đứt trên
   chart** (2026-09-18, theo yêu cầu người dùng).

   **Trước khi code — điều tra qua agent** để tránh lặp lại đúng sai lầm đã xảy ra ở
   Downtime: đọc lại commit `e198720` ("Remove per-category Target dashed lines from
   Downtime by Category chart") — lý do gỡ KHÔNG phải bản thân ý tưởng "đường Target nét
   đứt" bị coi là dở, mà vì áp dụng lên 1 chart STACKED BAR có tới 9 category chọn tự do
   (`selected.forEach` nhân số đường Target lên tới 9, chồng lên bar+line đã dày sẵn ->
   rối mắt). Chart Batch/Day Trend ngược lại: LUÔN cố định đúng 3 đường (không phụ thuộc
   lựa chọn người dùng), không phải bar chart — kết luận: áp dụng lại đúng kỹ thuật cũ
   (đường nét đứt + ẩn khỏi legend/tooltip qua `legend.labels.filter`/`tooltip.filter`)
   là AN TOÀN ở đây, không tái diễn lý do bị gỡ trước đó.

   **Thiết kế**:
   - `batch_day_trend.py::MAIN_FABRIC_TYPES = ("Cotton", "CVC", "Polyester")` (so khớp
     không phân biệt hoa/thường qua `_normalize_main_fabric_type()`) — mọi `fabric_type`
     KHÁC 3 loại này bị loại HOÀN TOÀN khỏi báo cáo Trend (khác mọi báo cáo khác trong dự
     án vốn hiển thị ĐỘNG theo `available_fabric_types` tìm thấy trong dữ liệu thật).
     **CHƯA xác nhận** dữ liệu thật có biến thể viết khác (VD viết tắt "PES" cho
     Polyester) — nếu người dùng phát hiện thiếu dữ liệu do sai chính tả/viết tắt, chỉ cần
     bổ sung alias vào `_MAIN_FABRIC_TYPE_BY_NORM`.
   - `get_batch_day_trend()` viết lại: MỖI loại vải có tử số/mẫu số RIÊNG, tính ĐỘC LẬP
     theo ĐÚNG công thức gốc (đếm mẻ Rework=0 * 24 / tổng giờ TẤT CẢ mẻ CỦA ĐÚNG loại đó)
     — KHÔNG dùng chung mẫu số như bản 1-đường-gộp cũ. Xoá hẳn filter "Fabric Type" khỏi
     UI/API tab Trend (không còn ý nghĩa khi báo cáo đã cố định đúng 3 loại — người dùng
     không thể "lọc xuống còn 1 trong 3" vì mục đích là LUÔN thấy cả 3).
   - Bảng Target mới `batch_day_trend_targets` (khoá `fabric_type`, CHỈ 3 giá trị hợp lệ)
     — CỐ TÌNH KHÔNG tái dùng `batch_matrix_targets` (khoá `(fabric_type, color_group)`)
     dù cùng khái niệm "target" bề ngoài: 2 bảng trả lời 2 câu hỏi khác nhau (target cho 1
     ô fabric+color của Matrix vs. target cho TỔNG Batch/Day của 1 loại vải ở Trend, khác
     quy mô số dù cùng công thức gốc) — tái dùng sẽ cần sentinel `color_group` giả, dễ gây
     hiểu nhầm là dữ liệu lỗi. Theo đúng pattern đã có trong dự án ("mỗi báo cáo 1 bảng
     Target riêng, khoá theo đơn vị hàng của chính báo cáo đó" — `downtime_targets` khoá
     `category`, `batch_matrix_targets` khoá `(fabric_type, color_group)`).
   - Quyền ghi Target: `permission_required("dyeing", "batch_matrix", "edit")` — theo
     ĐÚNG quy ước sẵn có của `batch_matrix_targets` (KHÔNG phải `role_required("admin")`
     như Target bên Downtime — 2 quyết định độc lập, xem mục -9).
   - UI: tái dùng ĐÚNG class `case-note-cell`/`case-note-input` (global trong `app.css`)
     cho ô Target — trang `batch_matrix_view.html` trước đây CHƯA có `showToast()`, đã
     thêm mới copy nguyên mẫu từ `cleaning_matrix_view.html`.
   - Đường Target trên chart: nét đứt (`borderDash:[6,4]`) CÙNG MÀU với đường số liệu
     tương ứng (Cotton=`#3fb950`, CVC=`#2862d7`, Polyester=`#f778ba`), ẩn khỏi legend
     (filter theo hậu tố " Target") và tooltip (filter theo cờ `isTargetLine`) — chỉ vẽ
     khi loại vải đó ĐÃ có Target cấu hình (`row.target !== null`).
   - Tab mặc định đổi từ "Fabric/Color Matrix" sang "Batch/Day Trend" — chỉ cần đổi thứ tự
     DOM của nav button + `<section>` (cả 2 cùng lúc, giữ nhất quán), JS `tabs`/`pages`
     dựng từ `querySelectorAll` theo thứ tự DOM nên `activePageIndex = 0` tự động trỏ đúng
     tab mới mà không cần sửa logic chuyển tab.

   Verify: script DB tạm xác nhận công thức tách đúng theo từng loại vải (đối chiếu tay:
   Cotton 2 mẻ hợp lệ/20h → 2.4, CVC 1 mẻ/8h → 3.0, Polyester 0 mẻ hợp lệ/8h → 0.0, 1 mẻ
   Nylon bị loại hoàn toàn không ảnh hưởng 3 loại kia), Target lưu/đọc đúng, từ chối đúng
   fabric_type ngoài danh sách 3 loại. Verify end-to-end Flask test client (subprocess, DB
   tạm): thứ tự tab đúng trong markup, tab Trend là mặc định (không `hidden`), filter
   Fabric Type đã bị gỡ khỏi HTML, API luôn trả đủ 3 dòng kể cả khi rỗng dữ liệu, ghi Target
   qua API phản ánh đúng ở lần đọc sau, operator chỉ-view bị chặn ghi (302). Re-run
   `tests/test_batch_day_trend_recompute_all.py`, `tests/test_batch_matrix_formula.py`,
   `tests/test_batch_matrix_brand_fabric_filters.py`, `tests/verify_rollup_parity.py` —
   PASS 100%, không regression.

   **Postgres production**: đã thêm bảng `batch_day_trend_targets` vào
   `supabase/schema.sql` (kèm RLS) — CHƯA CHẠY trên Supabase thật, cần admin áp DDL thủ
   công (bảng hoàn toàn mới, không phải ALTER, không cần migration script riêng — cùng
   cách đã làm cho `downtime_achievement_standards` ở mục -12 và `downtime_targets` ở mục
   -9).

-12. **Thêm cột "Standard" (ngưỡng giờ) vào bảng "Standard Achievement Breakdown"
   + cho phép sửa qua UI, sửa 2 bug thật riêng biệt phát sinh cùng phiên**
   (2026-09-18, theo yêu cầu người dùng: "giá trị so sánh đã có nhưng phải xuất
   ra trên UI và người dùng có quyền có thể sửa chúng").

   **Phát hiện trước khi code**: ngưỡng "Standard" (giờ) đã tồn tại từ trước
   dưới dạng hằng số Python `STANDARD_HOURS` (`core/excel_importer.py`) — dùng
   để tính cờ `ach_load`/`ach_unload`/`ach_sample_check`/`ach_ph`/`ach_chemical`/
   `ach_color` (0/1/NULL) NGAY LÚC IMPORT (`_add_availability_business_fields()`),
   lưu thẳng vào `availability_logs`. Báo cáo Achievement
   (`downtime/service.py::_daily_planned_and_achievement()`) SUM/COUNT thẳng
   các cột `ach_*` này (KHÔNG tính lại từ giờ thô mỗi lần đọc) — nghĩa là đổi
   hằng số Python không hề ảnh hưởng gì tới dữ liệu ĐÃ import trước đó, và
   không có UI nào để sửa cả.

   **Thiết kế**: bảng mới `downtime_achievement_standards` (khoá `stage` —
   "Load"/"Unload"/"Sample Check"/"pH Check"/"Chemical"/"Color", cùng bộ khoá
   với `ACHIEVEMENT_COLUMNS` ở `downtime/service.py`; cột `standard_hours`),
   seed mặc định từ `STANDARD_HOURS` khi đọc lần đầu. Đặt các hàm CRUD
   (`get_achievement_standards()`, `get_achievement_standard_hours_by_field()`,
   `set_achievement_standard()`) trong `core/excel_importer.py` — CÙNG chỗ với
   `STANDARD_HOURS`/`ACH_FIELDS`/`_add_availability_business_fields()` đã có
   sẵn (Engine downtime import từ đây, đúng hướng phụ thuộc Engine -> core).
   Thêm 2 dict mới `ACHIEVEMENT_STAGES` (stage -> cột giờ thô) và
   `ACHIEVEMENT_STAGE_ACH_FIELDS` (stage -> cột `ach_*`) — PHẢI giữ đồng bộ
   bộ khoá "stage" với `ACHIEVEMENT_COLUMNS` (downtime/service.py) và danh sách
   stage hardcode trong `downtime_view.html` (bộ lọc stage của biểu đồ) — 3 nơi
   định nghĩa CÙNG 1 khái niệm "stage", chưa gộp thành 1 nguồn vì mỗi nơi cần
   value khác nhau (cột giờ thô / cột ach_* / chỉ cần tên hiển thị).

   **Điểm mấu chốt khác hẳn Target (Downtime by Category)**: sửa Target chỉ đổi
   ngưỡng TÔ MÀU hiển thị, KHÔNG đụng số liệu gốc. Sửa Standard THẬT SỰ đổi kết
   quả tính toán — `set_achievement_standard()` phải UPDATE lại cột `ach_*`
   tương ứng cho TOÀN BỘ `availability_logs` (không chỉ dữ liệu import sau này),
   RỒI tính lại `ach_evaluated`/`ach_passed`/`ach_all_items` (tổng hợp của CẢ 6
   cờ `ach_*`, phải tính lại dù chỉ 1 stage đổi). Vì vậy JS (`saveStandard()`)
   PHẢI `load()` lại toàn trang sau khi lưu (khác `saveTarget()` chỉ
   `renderTable()` lại từ dữ liệu cache, không gọi `load()`).
   `_add_availability_business_fields()` cũng đổi để nhận `standard_hours`
   (dict tuỳ chọn, khoá theo cột giờ thô) — mọi lần IMPORT SAU (Excel hàng loạt
   `detect_and_parse_file()`, Manual Entry, revalidate Raw Data Viewer) đều
   dùng Standard MỚI NHẤT từ DB thay vì hằng số cũ; vòng lặp hàng loạt fetch
   Standard đúng 1 LẦN trước khi lặp qua từng dòng (không query DB mỗi dòng).

   **Quyền**: route ghi `POST /dyeing/downtime/api/achievement-standards/<stage>`
   gate bằng `permission_required("dyeing", "downtime", "edit")` — CỐ Ý khác
   Target (Target dùng `role_required("admin")`, quyết định riêng đã ghi ở mục
   -9) vì người dùng yêu cầu rõ "người dùng có quyền [edit]" chứ không phải
   "chỉ admin". UI: tái dùng ĐÚNG class `case-note-cell`/`case-note-input` +
   flag `window.DOWNTIME_CAN_EDIT_NOTES` đã có sẵn (không tạo permission
   flag/CSS riêng), giống hệt cách vừa làm cho machine config ở mục dưới đây.

   **Postgres production**: đã thêm bảng vào `supabase/schema.sql` (kèm RLS) —
   **CHƯA CHẠY trên Supabase thật**, cần admin áp DDL này thủ công (không có
   migration script riêng vì đây là bảng HOÀN TOÀN MỚI, không phải ALTER bảng
   đã có dữ liệu — cùng cách đã làm cho `downtime_targets` ở mục -9).

   Verify: script tạm dựng DB SQLite tạm (không đụng DB thật) xác nhận
   `get_achievement_standards()` trả đủ 6 stage với giá trị mặc định,
   `set_achievement_standard()` recompute ĐÚNG `ach_load` + 3 cột tổng hợp cho
   TOÀN BỘ dữ liệu cũ (đối chiếu tay: máy có `load_hour` nằm giữa Standard cũ
   và Standard mới đổi đúng từ "không đạt" sang "đạt"), từ chối đúng standard
   âm/stage không hợp lệ. Verify end-to-end qua Flask test client đầy đủ
   (subprocess riêng, DB tạm): trang render 200 kèm cột Standard, `/api/summary`
   trả đúng `standard_hours` từng stage, ghi qua API phản ánh đúng ở lần đọc
   sau, operator chỉ có `view` bị chặn ghi (302, không lộ JSON). Re-run
   `tests/test_downtime_brand_fabric_filters.py`,
   `tests/test_downtime_case_notes_context.py`, `tests/test_permission_model.py`,
   `tests/verify_rollup_parity.py` — PASS 100%, không regression.

-11a. **2 bug thật phát hiện + sửa cùng phiên với mục -12 ở trên, KHÔNG liên
   quan tính năng Standard** (2026-09-18): (1) **"Batch Per Day by Machine" lưu
   cấu hình máy "lúc được lúc không"** — `upsert_machine_config()`
   (`reports/cleaning_matrix.py`) dùng "SELECT xem đã có chưa rồi
   INSERT/UPDATE" 2 câu SQL riêng biệt, KHÔNG nguyên tử. Vì bảng `machines`
   mặc định RỖNG, mọi máy CHƯA sửa lần nào rơi vào nhánh INSERT ở LẦN ĐẦU —
   sửa liên tiếp nhiều field trên CÙNG 1 máy (Tab qua nhiều ô) bắn nhiều
   request gần đồng thời, có thể CÙNG thấy "chưa có dòng" ở bước SELECT rồi
   CÙNG INSERT, request thua vi phạm `machine_id UNIQUE` -> lỗi 400. Đã đổi
   sang `INSERT ... ON CONFLICT(machine_id) DO UPDATE` nguyên tử (cùng nguyên
   tắc `upsert_case_note()`). Đồng thời JS hiện đúng lỗi thật từ server thay vì
   thông báo chung chung. UX: lưu 1 field (MC brand/Tank/MC quantity/Tube no)
   KHÔNG còn `load()` lại toàn bảng nữa — các field này THUẦN mô tả, không ảnh
   hưởng phép tính nào khác (đã xác nhận qua code); CHỈ Capacity mới `load()`
   lại (ảnh hưởng Cleaning MC Ratio + filter Capacity), và khi đó chụp lại +
   mở lại đúng các ô đang gõ dở ở nơi khác sau khi render xong (tránh mất nội
   dung, bug đã report trực tiếp). Thêm nút thu gọn/mở rộng 5 cột cấu hình máy
   (MC brand/Tank/MC quantity/Tube no/Capacity), state lưu `localStorage`.
   Verify: script tạm DB SQLite (mô phỏng race, xác nhận UPSERT không còn lỗi
   UNIQUE + không tạo dòng trùng), Flask test client thật lưu 2 lần liên tiếp
   trên 1 mã máy test (dọn sạch sau khi xong, không để lại dữ liệu test trong
   DB dev). (2) **Cascading crash khi Postgres mất kết nối giữa chừng
   (production Vercel+Supabase)** — log thật cho thấy request gặp
   `psycopg2.OperationalError: SSL connection has been closed unexpectedly` ở
   `get_current_user()` (decorator phân quyền), Flask cố render
   `errors/500.html`, nhưng `inject_nav_menu` (context processor chạy cho MỌI
   template) lại gọi `get_current_user()` LẦN NỮA dùng lại đúng `g.db` đã hỏng
   -> `psycopg2.InterfaceError: connection already closed` -> trang lỗi thân
   thiện KHÔNG BAO GIỜ render được, người dùng thấy lỗi thô. Đã thêm
   `execute_query()`/`execute_one()` (`core/database.py`) tự phát hiện lỗi kết
   nối Postgres, đóng + mở lại + thử lại ĐÚNG 1 LẦN (an toàn vì luôn là SELECT
   thuần); `get_current_user()` (`core/auth.py`) coi như "chưa đăng nhập" nếu
   DB vẫn lỗi sau retry, KHÔNG crash tiếp (lỗi vẫn log đầy đủ qua
   `current_app.logger.exception`). Đường SQLite không đổi hành vi. Verify:
   mock `_PostgresConnCompat` (không có Postgres thật trong môi trường dev) xác
   nhận đứt kết nối 1 lần tự phục hồi, mất kết nối kéo dài vẫn trả `None` sạch
   sẽ thay vì crash, đường SQLite không bị ảnh hưởng. Re-run
   `tests/test_postgres_shim_translation.py`, `tests/test_production_date.py`,
   `tests/test_permission_model.py` — PASS 100%.

-11. **BUG THẬT phát hiện + sửa trên production: "Batch/Day Trend" không tính ra
   số liệu dù dữ liệu đã upload đủ tới ngày hiện tại** (2026-09-18, người dùng
   report trực tiếp sau khi dùng thử tính năng filter mới ở mục -10).

   **Quy trình điều tra** (không đoán, xác nhận từng bước qua người dùng):
   (1) Nghi ngờ đầu tiên — bảng rollup `batch_day_trend_daily_summary` chưa
   được tạo/backfill trên Postgres (Engine này MỚI thêm, có sẵn
   `supabase/migrate_batch_day_trend.sql` cảnh báo đúng tình huống này) — ĐÃ
   LOẠI TRỪ sau khi người dùng chạy migration + `flask rebuild-summaries`
   nhưng vẫn rỗng. (2) Yêu cầu người dùng chạy SQL đếm trực tiếp trên
   Supabase: `trend_rows=652, matrix_rows=3151, avail_rows=9839` — xác nhận
   bảng KHÔNG rỗng (652 dòng có thật), nên không phải lỗi "chưa tính". (3)
   Yêu cầu mở rộng khoảng ngày filter trên UI — người dùng xác nhận 652 dòng
   đó CHỈ nằm trong 6 ngày ĐẦU TIÊN của tháng 6/2026, dù `availability_logs`
   (9839 dòng) có dữ liệu tới ngày hiện tại (giữa tháng 9/2026).

   **Nguyên nhân gốc**: `core/rollup.py::trigger_recompute()` (dùng bởi CẢ
   `flask rebuild-summaries` LẪN hook sau mỗi import) lặp
   `for production_date in sorted(affected_dates): for engine in engines:
   engine.recompute_daily(production_date, conn)`. Với HẦU HẾT Engine (downtime,
   batch_matrix's Fabric/Color Matrix, cleaning_matrix), việc tính 1 ngày là
   độc lập/rẻ (SQL aggregate có WHERE theo đúng ngày đó). NHƯNG thuật toán
   carry-forward của `batch_day_trend.py` (mẻ FabricType không hợp lệ cộng
   dồn giờ sang mẻ THẬT kế tiếp CÙNG MÁY, xem module docstring) về bản chất
   PHỤ THUỘC THỨ TỰ THỜI GIAN xuyên suốt lịch sử — để tính ĐÚNG 1 ngày D,
   `recompute_daily(D)` phải fetch + sort lại TOÀN BỘ lịch sử của MỌI máy có
   liên quan (`_machine_records()`, không giới hạn theo ngày). Gọi hàm này
   LẶP LẠI cho hàng trăm ngày (dữ liệu nhiều tháng) khiến CÙNG 1 lịch sử máy
   bị fetch + sort lại hàng trăm lần — mỗi lần là 2 round-trip mạng khi DB là
   Postgres remote (Supabase) — đủ chậm để CLI/tiến trình có vẻ "treo" và bị
   ngắt (timeout/đóng terminal) giữa chừng, chỉ kịp xử lý xong vài ngày ĐẦU
   TIÊN theo thứ tự `sorted()` (tăng dần — khớp CHÍNH XÁC triệu chứng "chỉ có
   6 ngày đầu tháng 6", đây là những ngày CŨ NHẤT trong tập `affected_dates`
   khi backfill toàn bộ lịch sử).

   **Giải pháp**: thêm method MỚI, TUỲ CHỌN vào `core/engine_base.py::
   BaseEngine`: `recompute_all(dates: Iterable[date], conn)` — mặc định lặp
   `recompute_daily()` cho từng ngày (GIỮ NGUYÊN hành vi cũ cho mọi Engine
   không override, không rủi ro regression). `core/rollup.py::
   trigger_recompute()` đổi từ lặp lồng nhau (ngày ngoài, Engine trong) sang
   gọi `engine.recompute_all(affected_dates, conn)` MỘT LẦN cho mỗi Engine
   (Engine tự quyết định cách xử lý hiệu quả cho CẢ tập ngày). `batch_matrix`
   Engine (`__init__.py`) override `recompute_all()`: `service.recompute_daily()`
   (Fabric/Color Matrix) vẫn lặp theo ngày như cũ (rẻ, không cần đổi), nhưng
   gọi `batch_day_trend.recompute_all()` MỚI — hàm này (1) hợp TẬP MÁY liên
   quan tới BẤT KỲ ngày nào trong `dates` (union qua `_find_candidate_machines()`
   cho từng ngày), (2) với MỖI máy, fetch + sort lịch sử ĐÚNG 1 LẦN (thay vì N
   lần), chạy carry-forward 1 lần xuyên suốt, giữ lại mọi bản ghi resolve vào
   ĐÚNG 1 ngày nằm trong `dates`, (3) DELETE + INSERT 1 LẦN cho toàn bộ `dates`
   liên quan thay vì lặp theo từng ngày. Về mặt TOÁN HỌC cho kết quả GIỐNG HỆT
   gọi `recompute_daily()` lặp từng ngày (cùng thứ tự sort, cùng state
   `carry_hours` xuyên suốt lịch sử máy — chỉ khác là quyết định "ngày nào
   được INSERT" dựa trên tập `dates` thay vì so sánh với 1 `day_str` duy nhất),
   chỉ khác ở SỐ LẦN fetch+sort (đúng 1 lần/máy thay vì N lần/máy).

   Verify: `tests/test_batch_day_trend_recompute_all.py` (MỚI) — 3 kịch bản:
   (1) `recompute_all({3 ngày})` cho kết quả GIỐNG HỆT (từng field) với
   `recompute_daily()` gọi lặp 3 lần trên 1 DB riêng biệt, dữ liệu có carry-
   forward XUYÊN NGÀY (máy M1: Unknown 2h -> Real A ngày 1 hấp thụ carry ->
   Unknown 3h -> Real B ngày 2 hấp thụ carry -> Real C ngày 3 không carry);
   (2) xác nhận giá trị cụ thể đúng theo tay tính (6h/7h/5h); (3) gọi
   `recompute_all()` với SUBSET ngày (bỏ ngày 2 giữa) — xác nhận chỉ ngày
   được yêu cầu mới xuất hiện trong kết quả, không "rò rỉ" ngày khác. PASS
   100%, cùng toàn bộ 8 test suite cũ (bao gồm `verify_rollup_parity.py`,
   `test_permission_model.py`) không regression sau khi đổi
   `core/rollup.py::trigger_recompute()`.

   **Việc tiếp theo cho người dùng**: chạy lại `flask rebuild-summaries` trên
   production (đường mới sẽ nhanh hơn NHIỀU — không còn re-fetch lịch sử máy
   lặp lại theo từng ngày) để backfill đầy đủ Batch/Day Trend từ đầu lịch sử
   dữ liệu tới hiện tại — 652 dòng hiện có (chỉ 6 ngày đầu 06/2026) sẽ bị xoá
   và tính lại đúng cho TOÀN BỘ khoảng ngày.

-10. **Thêm filter Fabric Type + Brand Program vào TẤT CẢ 5 báo cáo Dyeing +
   chuẩn hoá UI filter dropdown theo mẫu Downtime** (2026-09-17, theo yêu cầu
   người dùng — đã hỏi rõ phạm vi trước khi code: "tất cả 5 báo cáo" thay vì
   chỉ 3 báo cáo được nhắc tên, và "mở rộng bảng rollup" thay vì "tính trực
   tiếp khi có filter" cho riêng Downtime).

   **UI**: mọi Capacity/Fabric Type/Brand Program filter giờ dùng CHUNG 1 mẫu
   dropdown (nút hiện nhãn gọn "All ..."/"N selected" + panel xổ xuống có
   checkbox "Select All" ở đầu) — factory JS `makeMultiSelectDropdown()` viết
   riêng cho từng file JS của từng Engine (dự án không có module JS dùng
   chung giữa các Engine, đúng Vertical Slice Architecture, nên copy-paste có
   chủ đích, không phải trùng lặp ngoài ý muốn). Trước đây "Batch Per Day by
   Machine" (`cleaning_matrix.py`) hiển thị SAI kiểu — nút bấm liệt kê NGANG
   toàn bộ giá trị đã chọn (VD "300kg, 500kg, 600kg, 1200kg, 2400kg") thay vì
   nhãn gọn — đây CHÍNH LÀ điều người dùng mô tả là "xổ ngang" khác "xổ
   xuống" của Downtime, đã xác nhận bằng screenshot Playwright trước khi sửa.

   **Rủi ro kỹ thuật quan trọng nhất (đã lường trước, không phải bug phát
   sinh)**: `batch_matrix_daily_summary` (rollup của tab "Fabric/Color
   Matrix") lưu `operating_hours` = giờ hoạt động CẢ NGÀY của 1 máy — khác
   hẳn `downtime_daily_summary`/`cleaning_mc_daily_summary`/
   `batch_day_trend_daily_summary` (SUM giá trị ĐO ĐƯỢC theo từng dòng/mẻ, có
   thể chia nhỏ theo bất kỳ chiều nào an toàn). Ban đầu định thêm
   `brand_program` vào PRIMARY KEY của bảng này giống `capacity_kg` — SAI:
   1 máy có thể chạy NHIỀU brand_program trong CÙNG 1 ngày (khác capacity_kg,
   đã verify 0 máy có >1 capacity_kg cố định), nên bucket theo brand_program
   rồi SUM operating_hours qua các bucket sẽ tái diễn ĐÚNG bug COUNT DISTINCT
   đã tốn 3 lần sửa ở "Mẫu số" (xem `systemPatterns.md` mục 6.2) — chỉ khác
   "giờ" thay vì "đếm máy", và khác machine-hours thay vì brand_program. Đã
   PHÁT HIỆN RA trước khi merge (không phải sau khi có bug thật) nhờ tự đặt
   câu hỏi "tính chất SUM theo dòng hay theo tài nguyên dùng chung" cho từng
   bảng rollup trước khi copy pattern `capacity_kg` sang `brand_program`. Đã
   REVERT lại schema gốc, viết đường tính RIÊNG: `_raw_matrix_rows()` +
   `_aggregate_raw_rows()` (`batch_matrix/service.py`) — khi có Brand Program
   filter, TOÀN BỘ ma trận (cả dòng "data" lẫn Total(Fabric)/Grand Total)
   tính TRỰC TIẾP từ raw data với tập máy khử trùng đúng cấp, TÁI DÙNG đúng
   `cell_value_dedup()`/`total_value_dedup()` đã có sẵn cho Total/Grand Total
   — khi KHÔNG lọc Brand Program (mặc định), code path CŨ giữ NGUYÊN 100%
   (đọc từ rollup, không query raw data thêm), không đổi hiệu năng đường mặc
   định. Verify bằng `tests/test_batch_matrix_brand_fabric_filters.py`
   (kịch bản bẫy đúng: máy M1 chạy 2 mẻ CÙNG ngày/Fabric/Color/Capacity
   nhưng khác Brand Program — xác nhận lọc theo 1 brand vẫn tính ĐỦ giờ CẢ
   NGÀY của M1, không chỉ giờ phần mẻ khớp brand đó) — PASS toàn bộ, cùng
   `tests/test_batch_matrix_formula.py` (regression 3 kịch bản cũ) vẫn PASS
   100% sau khi sửa.

   **Các rollup AN TOÀN mở rộng trực tiếp** (grain = 1 dòng/1 bản ghi đo
   được, không phải machine-hours dùng chung): `downtime_daily_summary` (thêm
   `fabric_type`+`brand_program` vào PRIMARY KEY — mỗi dòng là SUM giờ CỦA
   CHÍNH mẻ đó, cộng dồn theo bất kỳ chiều nào cũng an toàn),
   `cleaning_mc_daily_summary` (thêm cột `fabric_type`, PK không đổi — grain
   sẵn là 1 dòng/1 mẻ), `batch_day_trend_daily_summary` (thêm cột
   `brand_program`, PK không đổi — grain sẵn là 1 dòng/1 mẻ đã resolve).
   `rft`/`tank_loading` chưa có rollup (query trực tiếp) nên thêm filter chỉ
   là JOIN + WHERE/lọc Python thông thường, không có rủi ro gì.

   **Migration Postgres production** (CHƯA CHẠY, cần admin tự áp qua Supabase
   SQL Editor rồi chạy `flask rebuild-summaries` — xem "Việc tiếp theo"):
   `supabase/migrate_downtime_summary_brand_fabric.sql` (đổi PRIMARY KEY),
   `supabase/migrate_cleaning_matrix_fabric_type.sql`,
   `supabase/migrate_batch_day_trend_brand_program.sql` (2 file sau chỉ ADD
   COLUMN, không đổi PK). `supabase/schema.sql` đã cập nhật cho lần cài mới.

   **Brand Program suy từ đâu**: mọi Engine đều JOIN
   `batch_details.greige_code -> brand_program_mapping.greige_code` (khác
   nhau ở cách nối tới `greige_code`: `downtime`/`batch_matrix`/`rft` qua
   `availability_logs.batch = batch_details.dyelot`;
   `tank_loading` qua `performance_logs.dyelot = batch_details.dyelot` trực
   tiếp, không qua alias `batch`/`batch_ref_no` như availability_logs).

   Test mới: `tests/test_downtime_brand_fabric_filters.py`,
   `tests/test_batch_matrix_brand_fabric_filters.py`. Đã re-run toàn bộ test
   suite cũ (`test_batch_matrix_formula.py`, `verify_rollup_parity.py`,
   `test_permission_model.py`, `test_production_date.py`,
   `test_postgres_shim_translation.py`, `test_downtime_case_notes_context.py`)
   — PASS 100%, không có regression.

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
- **CHỜ XÁC NHẬN**: tạo bảng MỚI `rft_dye_results` trên Supabase production (áp DDL trong
  `supabase/schema.sql`, bảng hoàn toàn mới nên không cần migration script) — trước khi
  chạy, Engine `rft` vẫn hoạt động (trả empty state đúng, không lỗi 500) trên CẢ SQLite lẫn
  Postgres vì `_rft_rows()` bắt `DatabaseError` khi bảng chưa tồn tại, nhưng trên
  Postgres/Vercel sẽ KHÔNG import/hiển thị được dữ liệu RFT thật cho tới khi bảng tồn tại.
  Cũng cần import file "RFT report.xlsx" thật (qua Modal Import trên Dyeing Hub, chọn "RFT
  Report" hoặc để Auto-detect) sau khi có bảng — DB dev cục bộ hiện CHƯA có dữ liệu
  `rft_dye_results` nào (chỉ mới verify bằng test tạm + file mẫu).
- **ĐÃ XÁC NHẬN** (2026-09-19): người dùng report "%Tank Loading chưa thấy biểu đồ đường"
  — điều tra xác nhận KHÔNG phải bug code (đối chiếu công thức/filter Tank Loading giống
  hệt Batch/Day, đã hoạt động đúng khi có dữ liệu). Nguyên nhân THẬT: **người dùng CHƯA
  upload file Excel "Performance" của tháng 09** — `performance_logs` rỗng nên %Tank
  Loading không có gì để vẽ, trong khi Batch/Day (nguồn `availability_logs`) đã có dữ liệu
  nên vẫn vẽ được. Không cần sửa gì thêm — chỉ cần người dùng import Performance của tháng
  09 qua "Import Data" trên Hub. Đã tiện thể thêm UX nhỏ: `renderSparkline()`
  (`dyeing_hub.js`) giờ hiện rõ "No data for this period" thay vì để canvas trắng trơn im
  lặng khi `labels` rỗng — tránh hiểu nhầm "trống trơn" là lỗi ở lần sau. Áp dụng cho CẢ
  Hero Batch/Day lẫn %Tank Loading (RFT không qua đường này, đã có cơ chế "Đang chờ cấu
  hình" riêng từ mục -16).
- **CHỜ XÁC NHẬN**: ngưỡng tô màu chính thức cho Downtime% trên Dashboard (hiện đang tạm
  đặt <=8% xanh / <=15% vàng / >15% đỏ trong `dyeing_hub.js::downtimeColorFor()` — người
  dùng chưa xác nhận số cụ thể, đã hỏi nhưng chưa có câu trả lời trong phiên làm việc này).
- **CHỜ XÁC NHẬN**: tạo bảng MỚI `tank_loading_targets` trên Supabase production (áp lại
  DDL tương ứng trong `supabase/schema.sql`, không cần migration script vì là bảng hoàn
  toàn mới) — trước khi chạy, tính năng Target trên trang %Tank Loading vẫn hoạt động nếu
  app chạy SQLite, nhưng trên Postgres/Vercel sẽ lỗi 500 cho tới khi bảng tồn tại.
- **CHỜ XÁC NHẬN**: tạo bảng MỚI `batch_day_trend_targets` trên Supabase production
  (áp lại DDL tương ứng trong `supabase/schema.sql`, không cần migration script vì
  là bảng hoàn toàn mới) — trước khi chạy, tính năng Target trên tab Batch/Day Trend
  vẫn hoạt động nếu app chạy SQLite (tự lazy-create), nhưng trên Postgres/Vercel sẽ
  lỗi 500 khi gọi `get_trend_targets()`/`set_trend_target()` cho tới khi bảng tồn tại.
- **CHỜ XÁC NHẬN**: tạo bảng MỚI `downtime_achievement_standards` trên Supabase
  production (áp lại đoạn DDL tương ứng trong `supabase/schema.sql`, không có
  migration script riêng vì đây là bảng hoàn toàn mới) — trước khi chạy, tính
  năng "Standard" trên UI vẫn hiển thị/sửa được nếu app đang chạy SQLite (tự
  lazy-create), nhưng trên Postgres/Vercel sẽ lỗi 500 khi gọi
  `get_achievement_standards()`/`set_achievement_standard()` cho tới khi bảng
  này tồn tại.
- **CHỜ XÁC NHẬN**: chạy 3 migration mới cho filter Fabric Type/Brand Program
  (2026-09-17) qua Supabase SQL Editor trên DB production, rồi chạy lại
  `flask rebuild-summaries` để backfill dữ liệu lịch sử theo đúng 2 chiều mới:
  `supabase/migrate_downtime_summary_brand_fabric.sql`,
  `supabase/migrate_cleaning_matrix_fabric_type.sql`,
  `supabase/migrate_batch_day_trend_brand_program.sql`. Trước khi chạy, app
  vẫn hoạt động đúng (2 filter mới trả "All" cho dữ liệu cũ, không lỗi) vì
  code đã tự gate theo `get_dialect()`/cột tồn tại — chỉ là CHƯA lọc được
  đúng theo Fabric Type/Brand Program cho dữ liệu lịch sử trên Postgres cho
  tới khi áp migration.
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
