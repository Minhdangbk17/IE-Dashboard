# Phân loại mẻ nhuộm — Hướng dẫn triển khai

Trạng thái: **đã code ngày 2026-11-08**, màu badge mới (mục 4.2) vẫn chờ người dùng duyệt. Lệch so với hướng dẫn: chưa có tooltip RecipeNo/nhập tay (mục 4.3),
chưa có nút Export Excel ở tab Data Quality (mục 6), không còn ghi `is_valid_any_redye` ở bảng Trend (cột cũ giữ nguyên, mặc định 0), Rework đếm theo từng lần chạy
(không gộp theo FuyangRequest như bản nháp trước).
Phạm vi: Batch Per Day by Machine (tab Detail, Summary, Excel) và hai báo cáo dùng chung bộ phân loại là
Batch/Day Trend và Fabric/Color Matrix (kéo theo widget Trend trên Hub Nhuộm).

Tài liệu này thay thế các quy tắc Normal/Rework cũ ghi trong `memory-bank/activeContext.md` (2026-09-25,
2026-10-26). Khi code xong phải cập nhật Memory Bank và `design/UI_GUIDELINES.md` theo mục 10.

---

## 1. Định nghĩa

| Thuật ngữ | Định nghĩa |
|---|---|
| Lần chạy | Một dòng trong `batch_details` (sau chuẩn hoá của `core/batch_source.py::load_resolved_batches()`). Cùng một Dyelot có thể có nhiều lần chạy. |
| Ngày sản xuất | Ngày của đoạn cuối có giờ > 0 theo khung 07:00 → 07:00 (giữ nguyên `split_production_days()`). |
| Giờ chiếm máy | EndTime − StartTime của **mọi** lần chạy, chia theo khung 07:00. Không đổi. |
| Nhóm | Kết quả phân loại một lần chạy: CM, Sample, SC, RD, Rework, Normal, Pending. |
| Badge | Ký hiệu hiển thị trên bảng máy × ngày và trong Excel. |

Nguyên tắc chung: **mọi lần chạy đều hiện badge**, kể cả nhóm không được đếm, để bảng máy × ngày không có khoảng
trống mà không rõ máy làm gì. Giờ của mọi lần chạy vẫn vào giờ chiếm máy.

---

## 2. Quy tắc phân loại

### 2.1 Chuẩn hoá trước khi xét

- `dyelot`, `sap_lot`, `recipe_no`, `batch_type`: `strip()`; so sánh không phân biệt hoa thường.
- Nếu lần chạy có dòng nhập tay (mục 5), thay `batch_type`, `fabric_type`, `shade` bằng giá trị nhập tay
  **trước** khi phân loại.
- Nhận diện tinh luyện (`is_scouring(recipe_no)`), đúng một trong các điều kiện:
  - regex `\bDG\s*-?\s*01` trên `recipe_no.upper()` (khớp `DG01-…`, `TLDT-DG01`, `NC26E0401-DG01`);
  - `recipe_no.upper()` bỏ hết khoảng trắng chứa `TLDT` hoặc `TINHLUYEN` (khớp `TINH LUYEN-RD2`,
    `TINHLUYEN-COTTON-02`).

### 2.2 Bảng quyết định

Xét theo thứ tự, gặp điều kiện đúng đầu tiên thì dừng.

| Bước | Điều kiện | Nhóm | Badge | Đếm vào |
|---|---|---|---|---|
| 1 | Dyelot kết thúc `WA` **hoặc** bắt đầu `CL` | CM | `CM` | Cleaning MC |
| 2 | Dyelot kết thúc `DU` hoặc `KN` **hoặc** SapLot bắt đầu `4` | Sample | `S` | Không |
| 3 | `is_scouring(recipe_no)` | SC | `SC` | Không |
| 4 | BatchType = `Redye` | RD | `RD` | Không |
| 5 | BatchType = `Rework` | Rework | màu + `R` | Rework (mỗi lần chạy = 1) |
| 6 | BatchType = `Normal` | Normal | màu | Normal (mỗi lần chạy = 1) |
| 7 | Còn lại (`Unknown`, trống, giá trị lạ) | Pending | `?` | Không, cho tới khi nhập tay |

Màu của badge Normal/Rework (B, D, M, L, W) **giữ nguyên** bước tô màu hiện tại của `classify_batch_badge()`
(từ khoá BLACK/WHITE trong ColourNo/RecipeNo/CustomerColor, rồi Shade, rồi từ khoá sáng/tối, mặc định M), dùng
Shade đã áp nhập tay nếu có.

Những thứ **không còn** dùng để phân loại: đuôi `0` của Dyelot, SapLot `1*`/`3*`, cột `ReDye`, mã DG07/DG09/DG10,
ghi chú NG, FuyangRequest.

### 2.3 Ví dụ từ dữ liệu thật

| Dyelot | Dữ liệu | Nhóm |
|---|---|---|
| C260744040 | BatchType Normal, RecipeNo `DG08-01` | Normal |
| C260721852 | BatchType Rework | Rework |
| 11031527-WA | đuôi `WA` | CM |
| 2026110411-DU | đuôi `DU`, RecipeNo `TINHLUYEN-COTTON-02` | Sample (bước 2 trước bước 3) |
| C260736550, lần 1 | BatchType Normal, RecipeNo `TLDT-DG01` | SC |
| C260736550, lần 2 | BatchType Normal, RecipeNo `NO-T23A3105C-FY21` | Normal |
| C260744490 | BatchType Unknown, RecipeNo `TINH LUYEN-RD2` | SC |
| C260512100 (3 lần) | BatchType Redye | RD cả 3 lần |
| C260744890 | BatchType Unknown, RecipeNo `CP26J2306-C260744890` | Pending |

### 2.4 Số kỳ vọng trên file mẫu

Đếm thẳng trên dòng file (chưa qua fill-down Machine và loại dòng thiếu StartTime), dùng làm mốc đối chiếu:

| Nhóm | `batch_2026-11-01_to_2026-11-06.xlsx` (563) | `batch_2026-08-01_to_2026-08-31 (1).xlsx` sheet Batch (3.418) |
|---|---|---|
| Normal | 316 | 1.974 |
| Rework | 117 | 641 |
| CM | 79 | 436 |
| Sample | 10 | 99 |
| SC | 14 | 122 |
| RD | 5 | 16 |
| Pending | 22 | 130 |

Đối chiếu Availability tháng 8 (2.557 dòng ghép được): BatchType Rework có `rework_hour` > 0 ở 419/419 dòng,
BatchType Normal và Redye có `rework_hour` = 0 ở mọi dòng — khớp với Downtime.

---

## 3. Cách đếm

| Chỉ số | Công thức |
|---|---|
| Normal batch | Số lần chạy nhóm Normal |
| Rework batch | Số lần chạy nhóm Rework |
| No. of time Cleaning MC | Số lần chạy nhóm CM |
| Cleaning MC Ratio | Normal ÷ CM (không đổi) |
| Rework ratio (Summary) | Normal ÷ Rework (không đổi) |
| No. Dyeing machine (Summary) | Số máy distinct có ≥ 1 lần chạy Normal hoặc Rework trong tháng |
| Plan PRD time, Batch/day (Plan PRD) (Summary) | Không đổi (RunTime của mọi lần chạy) |
| Batch/Day (Trend, Matrix) | Normal × 24 ÷ giờ chiếm máy (không đổi công thức, chỉ đổi tập Normal) |
| Normal Dyeing Batches by Colour | Chỉ nhóm Normal (không đổi điều kiện, chỉ đổi tập Normal) |

- Bỏ checkbox **"ReDye = 0"** ở tab Detail, tab Summary, Batch/Day Trend và Fabric/Color Matrix; bỏ tham số
  `require_redye_zero` khỏi route, service và Excel export.
- Một Dyelot có thể có nhiều lần chạy Normal nếu dữ liệu nguồn ghi như vậy (tháng 11: 9 Dyelot, tháng 8: 70). Dashboard
  không gộp; tab Data Quality liệt kê để IT sửa nguồn.
- Dòng "No. of R&D batch" giữ nguyên logic theo `batch_type` (hiện dữ liệu không có giá trị R&D nên luôn 0).

---

## 4. Hiển thị

### 4.1 Bảng máy × ngày, chú giải

Thứ tự chú giải: `CM`, `S`, `SC`, `RD`, `?`, `B`, `D`, `M`, `L`, `W`, `BR`, `DR`, `MR`, `LR`, `WR`.

| Badge | Nhãn chú giải |
|---|---|
| `SC` | Scouring (pre-treatment) |
| `RD` | Redye (not counted) |
| `?` | Missing batch type — enter in Data Quality |

Text hiển thị trên web viết bằng tiếng Anh (quy ước dự án).

### 4.2 Màu badge mới — CHỜ DUYỆT

| Badge | Đề xuất |
|---|---|
| `SC` | Nền xanh ngọc, chữ trắng |
| `RD` | Nền xám trung tính, chữ trắng |
| `?` | Nền trắng, chữ cam, viền đứt nét cam |

Khi được duyệt: khai báo token trong `static/css/app.css` cho cả Dark và Light (theo `design/UI_GUIDELINES.md`),
thêm `.code-SC`, `.code-RD`, `.code-PENDING` (class cho `?`), và thêm 3 mã vào `BADGE_FILL_COLORS` để Excel tô
giống web.

### 4.3 Tab Detail

- 4 thẻ KPI giữ nguyên (Normal Dyeing, Cleaning MC, Cleaning MC Ratio, Rework Batch) theo cách đếm mục 3.
- Thêm thẻ thứ 5 **"Pending entry"** = số lần chạy nhóm Pending trong bộ lọc; bấm chuyển sang tab Data Quality.
- Tooltip mỗi badge hiện thêm BatchType gốc và RecipeNo, ghi rõ "(manual)" nếu đã nhập tay.

---

## 5. Nhập tay cho nhóm Pending

### 5.1 Bảng dữ liệu

Bảng mới `batch_manual_overrides` (thuộc Engine `reports`):

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | INTEGER PK | |
| `dyelot` | TEXT NOT NULL | |
| `machine` | TEXT NOT NULL | Machine **sau** fill-down |
| `start_time` | TEXT NOT NULL | Định dạng `YYYY-MM-DD HH:MM:SS` |
| `batch_type` | TEXT NOT NULL | `Normal` hoặc `Rework` |
| `fabric_type` | TEXT NOT NULL | `Cotton`, `CVC`, `Polyester` |
| `shade` | TEXT NOT NULL | `Dark`, `Medium`, `Light`, `Black`, `White` |
| `updated_by` | TEXT | username |
| `updated_at` | TEXT | |

`UNIQUE(dyelot, machine, start_time)`. Bảng riêng (không ghi vào `batch_details`) vì `sync_batch_details()` dùng
`ON CONFLICT DO UPDATE`, sẽ ghi đè giá trị nhập tay khi import lại file.

- SQLite: tạo lazy trong hàm `_ensure_*` như các bảng khác.
- Postgres: file mới `supabase/migrate_batch_manual_overrides.sql` (idempotent, bật RLS không policy) và cập nhật
  `supabase/schema.sql`.

### 5.2 Áp vào dữ liệu

Trong `load_resolved_batches()`:
1. Sau bước fill-down Machine, đọc toàn bộ `batch_manual_overrides` một lần, ghép theo
   `(lower(trim(dyelot)), lower(machine), start_time chuẩn hoá)`.
2. Với dòng khớp: ghi đè `batch_type`, `shade`, `fabric_type`; đánh dấu `_manual = True`.
3. Bước fill-up FabricType chạy **sau** bước 2, nên FabricType nhập tay cũng được các mẻ trống phía trước
   (thường là CM) dùng.

Fabric/Color Matrix: thứ tự ưu tiên Shade = Set Shade của Matrix (`batch_shade_overrides`, theo Dyelot) >
Shade nhập tay > Shade gốc.

### 5.3 Route và quyền (Engine `reports`)

| Route | Quyền | Việc |
|---|---|---|
| `GET /dyeing/reports/api/data-quality?from_date=&to_date=` | view | Trả 3 danh sách ở mục 6 |
| `POST /dyeing/reports/api/manual-overrides` | edit | Body: `batch_id`, `batch_type`, `fabric_type`, `shade`. Chỉ nhận lần chạy đang ở nhóm Pending hoặc đã có dòng nhập tay. |
| `DELETE /dyeing/reports/api/manual-overrides/<id>` | delete | Xoá giá trị nhập tay, lần chạy quay về Pending |

Sau mỗi lần lưu hoặc xoá: gọi `core/rollup.py::trigger_recompute()` cho ngày sản xuất của lần chạy đó **và**
ngày của các lần chạy phía trước cùng máy đang lấy FabricType từ lần chạy này (chuỗi mẻ trống liền trước).

Cập nhật `EngineMetadata`: `reports.data_sinks` thêm `batch_manual_overrides`; `batch_matrix.data_sources`
thêm `batch_manual_overrides`.

---

## 6. Tab Data Quality (mới, trong trang Batch Per Day by Machine)

Dùng chung bộ lọc From/To với tab Detail. Ba bảng, mỗi bảng có số dòng ở tiêu đề:

| Bảng | Điều kiện | Cột | Thao tác |
|---|---|---|---|
| Missing batch type | Nhóm Pending | Production Date, Machine, Dyelot, Start, End, RecipeNo, ColourNo, SapLot, Note | Chọn BatchType / Fabric Type / Shade, nút Save; người có quyền delete thấy nút Clear |
| Scouring marked Normal | Nhóm SC và BatchType gốc = Normal | Production Date, Machine, Dyelot, RecipeNo, Start, End | Chỉ xem (IT sửa nguồn) |
| Dyelot with several Normal runs | Dyelot có ≥ 2 lần chạy nhóm Normal (xét toàn lịch sử, hiện nếu ít nhất 1 lần nằm trong bộ lọc) | Dyelot, từng lần: Machine, Start, RecipeNo, ReDye | Chỉ xem |

Nút "Export Excel" của tab xuất 3 bảng thành 3 sheet. Bảng Data Quality **không** làm thay đổi con số nào.

---

## 7. Excel

- Sheet Detail: tô màu thêm `SC`, `RD`, `?` theo `BADGE_FILL_COLORS`.
- Sheet mới **"Data"** (một dòng = một lần chạy trong bộ lọc): Production Date, Machine, Dyelot, BatchType gốc,
  BatchType nhập tay, RecipeNo, Fabric Type, Shade, Group, Badge, `Normal_Cnt` (0/1), `RW_Cnt` (0/1), `CM_Cnt` (0/1),
  Start, End, Hours. Pivot Sum các cột `_Cnt` phải ra đúng KPI trên web.

---

## 8. Thay đổi code theo file

| File | Thay đổi |
|---|---|
| `modules/dyeing/engines/reports/cleaning_matrix.py` | Viết lại `classify_batch_badge()` theo mục 2 (nhận thêm `batch_type`, `recipe_no`); thêm `is_scouring()`; xoá `_is_normal_dyeing()`, `_effective_badge_is_rework()` và tham số `require_redye_zero` ở `get_cleaning_matrix()`, `get_batch_summary()`, các hàm export; `recompute_all()` truyền đủ trường; `is_rework` = nhóm Rework; KPI/Summary theo mục 3; hàm Data Quality + nhập tay (mục 5–6); `BADGE_FILL_COLORS`, `ALL_BADGE_CODES` thêm 3 mã. |
| `modules/dyeing/engines/reports/routes.py` | Bỏ tham số `require_redye_zero`; thêm 3 route mục 5.3. |
| `modules/dyeing/engines/reports/templates/cleaning_matrix_view.html` | Chú giải + CSS badge mới, bỏ checkbox ReDye (2 tab), thẻ KPI Pending, tab Data Quality. |
| `modules/dyeing/engines/reports/__init__.py` | `EngineMetadata.data_sinks`. |
| `core/batch_source.py` | Áp nhập tay (mục 5.2); `batch_type`, `recipe_no` đã có trong `_OPTIONAL_COLUMNS`; giữ nguyên các bước khác. |
| `modules/dyeing/engines/batch_matrix/batch_day_trend.py` | `_is_normal_batch()` và `_classification_label()` truyền `batch_type`, `recipe_no`; bỏ `require_redye_zero`; nhãn Classification thêm SC/RD/Pending; `is_valid_any_redye` ghi bằng `is_valid` (giữ cột để không phải migration). |
| `modules/dyeing/engines/batch_matrix/service.py` | `_load_matrix_source()` và `_assign_color_groups()` dùng bộ phân loại mới, bỏ `require_redye_zero`, áp thứ tự Shade mục 5.2. |
| `modules/dyeing/engines/batch_matrix/templates/batch_matrix_view.html` | Bỏ checkbox ReDye (Trend + Matrix), sửa câu ghi chú "Normal dyeing batches only (Dyelot…)". File đang có thay đổi chưa commit: commit trước khi sửa. |
| `modules/dyeing/engines/batch_matrix/__init__.py` | `EngineMetadata.data_sources`. |
| `static/css/app.css` | Token màu 3 badge mới, cả 2 theme. |
| `supabase/migrate_batch_manual_overrides.sql`, `supabase/schema.sql` | Mục 5.1. |

Không đổi: `dca_cost` (chỉ sao chép bước tô màu), RFT, Downtime, Idle Time (chỉ dùng giờ).

---

## 9. Kiểm thử

1. Unit test `classify_batch_badge()`: mỗi bước của bảng 2.2 + các ví dụ mục 2.3 + thứ tự ưu tiên (đuôi `DU` có
   RecipeNo tinh luyện vẫn là Sample; Rework có Shade Dark ra `DR`).
2. Import 2 file mẫu vào DB tạm qua `sync_batch_details()`, `recompute_all()`, so số nhóm với bảng 2.4 (chênh lệch
   chỉ được phép do dòng thiếu StartTime/Machine bị loại — in rõ số dòng bị loại).
3. Parity: tổng Normal của tab Detail == Trend (dòng Total) == Matrix (Grand Total) trên cùng bộ lọc.
4. Nhập tay: lưu một dòng Pending → nhóm đổi đúng, FabricType lan sang mẻ CM trống liền trước, ngày liên quan được
   tính lại; import lại file không làm mất giá trị nhập tay; xoá → quay về Pending; operator chỉ có quyền view bị chặn ghi.
5. Excel: Sum `Normal_Cnt`/`RW_Cnt`/`CM_Cnt` sheet Data == KPI web.
6. Cập nhật các test đang dựa trên quy tắc cũ: `test_rework_classification.py`, `test_batch_summary_formula.py`,
   `test_batch_day_trend_recompute_all.py`, `test_batch_source_consistency.py`, `test_color_summary_by_fabric.py`,
   `test_cleaning_matrix_tank_filter.py`, `test_batch_matrix_*`.
7. Kiểm tra UI theo checklist Mục 12 của `design/UI_GUIDELINES.md` (2 theme, mobile).

---

## 10. Triển khai và tài liệu

1. Chạy `supabase/migrate_batch_manual_overrides.sql` trên Supabase.
2. Deploy code.
3. Chạy `flask rebuild-summaries` (hoặc `/admin/data-tools`) để tính lại `cleaning_mc_daily_summary` và
   `batch_day_trend_daily_summary` theo quy tắc mới.
4. Cấp quyền `reports` edit cho người nhập tay.
5. Cập nhật `memory-bank/activeContext.md`, `progress.md`, `systemPatterns.md` (mục 6.2.1) và
   `design/UI_GUIDELINES.md` (token, component, nhật ký quyết định, bảng màu nghiệp vụ 6.2).

Số liệu các kỳ đã báo cáo sẽ thay đổi sau bước 3 (ví dụ tháng 8: Normal 1.956 → 1.974, Rework 927 → 641).

---

## 11. Ngoài phạm vi (việc của IT ở nguồn)

Tài liệu gửi IT: https://claude.ai/artifact/Gfoex3EX5r6Xc9QV9PLV3M (cần cập nhật theo quyết định 2026-11-08:
Rework đếm theo lần chạy, Redye loại ra và vẫn hiển thị, Unknown phải được nhập đủ BatchType/FabricType/Shade,
tinh luyện tách riêng).

- BatchType bắt buộc, không để `Unknown`; tinh luyện ghi `Pre-treatment` (khi có, bước 3 vẫn giữ nguyên kết quả).
- Mỗi Dyelot chỉ một lần chạy Normal.
- Mã công đoạn là cột riêng thay vì nằm trong RecipeNo.
