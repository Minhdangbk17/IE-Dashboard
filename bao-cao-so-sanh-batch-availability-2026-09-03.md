# Báo cáo so sánh dữ liệu Batch (`batch_details`) và Availability (`availability_logs`)

**Ngày phân tích (production_date):** `2026-09-03` — ngày có số mẻ nhiều nhất trong toàn bộ lịch sử dữ liệu (107 dòng), chọn làm mẫu đại diện để đối chiếu.
**Nguồn dữ liệu:** `data/mes_dashboard.db` (SQLite, dữ liệu thật của nhà máy, không phải mock).
**Phương pháp:** Query trực tiếp 2 bảng, LEFT JOIN theo khoá `LOWER(TRIM(availability_logs.batch)) = LOWER(TRIM(batch_details.dyelot))` — đúng khoá JOIN đang được dùng thật trong toàn bộ code (`batch_matrix`, `downtime`, `reports/cleaning_matrix`, `rft`).

---

## 1. Hai bảng này bản chất là gì?

| | `availability_logs` | `batch_details` |
|---|---|---|
| **Vai trò** | Nhật ký **thời gian vận hành máy** theo từng mẻ chạy (khi nào chạy, chạy máy nào, giờ nào tốn cho hạng mục gì) | Hồ sơ **kỹ thuật/công thức/tiêu hao** của mẻ nhuộm (màu, công thức, khối lượng, nước, điện, hơi...) |
| **Khoá chính** | `id` tự tăng, cho phép **NHIỀU dòng cùng 1 mã mẻ** (`UNIQUE(batch, machine, start_time)` — 1 mẻ chạy lại vẫn ghi thêm dòng mới) | `dyelot` là **PRIMARY KEY** — **CHỈ 1 dòng cho mỗi mã mẻ**, import sau **ghi đè (UPSERT)** import trước |
| **Nguồn Excel** | File Availability (theo ca/máy) | File Batch Detail (theo lô nhuộm) |
| **Khoá nối 2 bảng** | `batch` | `dyelot` (cùng giá trị mã mẻ, ví dụ `C260647150`) |

Đây là điểm khác biệt **quan trọng nhất** cần nhớ khi đọc phần so sánh bên dưới: `availability_logs` cho phép trùng mã mẻ (mẻ chạy lại), còn `batch_details` thì không — mỗi mã mẻ chỉ giữ **đúng 1 bản ghi mới nhất**.

---

## 2. Tổng quan số liệu ngày 2026-09-03

- Số dòng `availability_logs` (số lượt chạy máy): **107**
- Số mã mẻ (`batch`) duy nhất: **106** (1 mã — `C260678850` — chạy 2 lượt trong đúng ngày này)
- Số dòng nối được sang `batch_details` theo `dyelot`: **107/107 (100%)** — mọi mã mẻ đều tồn tại trong `batch_details`

→ Về mặt **khoá nối** (mã mẻ), 2 bảng khớp tuyệt đối 100%. Không có mẻ nào trong Availability mà thiếu hồ sơ Batch tương ứng.

---

## 3. So sánh các trường DÙNG CHUNG (Machine / Fabric Type / Start-End Time)

`availability_logs` và `batch_details` cùng có 3 trường trùng tên/ý nghĩa: `machine`, `fabric_type`, `start_time`/`end_time`. Đối chiếu giá trị thực tế của 107 dòng:

| Nhóm | Số dòng | Tỷ lệ | Giải thích |
|---|---:|---:|---|
| **Batch_details KHÔNG có dữ liệu Machine/FabricType/Start/End** (rỗng cả 4 trường) | 95 | 88.8% | Xem mục 3.1 |
| **Batch_details CÓ dữ liệu nhưng LỆCH** với Availability của đúng ngày này | 12 | 11.2% | Xem mục 3.2 |
| **Khớp chính xác 100%** (Machine + Fabric Type + Start + End giống hệt) | 0 | 0% | — |

**Kết luận quan trọng:** với dữ liệu ngày này, **không có mẻ nào** mà `batch_details` phản ánh đúng thời gian/máy chạy thực tế theo Availability — nhưng đây **KHÔNG phải bug tính toán của ứng dụng**, vì toàn bộ Engine hiện có (`batch_matrix`, `downtime`, `reports`, `rft`) đều lấy `machine`/`start_time`/`end_time`/`fabric_type` từ **`availability_logs`** làm nguồn sự thật duy nhất, chỉ dùng `batch_details` để lấy thêm Shade/ColourNo/BatchType/Weight — đã verify bằng grep, không có chỗ nào trong `modules/` đọc `batch_details.machine/start_time/end_time`.

### 3.1. Vì sao 95/107 dòng batch_details rỗng Machine/FabricType/Time?

Kiểm tra `import_log_rows` (dữ liệu thô đã lưu lúc import) cho 1 mẻ cụ thể (`C260647150`, thuộc lần import `id=19`, file **`Batch_20260901-08.xlsx`**) cho thấy: **bản thân file Excel Batch Detail của khoảng 01/09–08/09 hoàn toàn KHÔNG có cột Machine/FabricType/ScheduleTime/StartTime/EndTime** — dòng dữ liệu thô chỉ có Customer/RecipeNo/ColourNo/Shade/Weight/Water/Power/Steam... Đây là **đặc điểm dữ liệu nguồn** (file Batch Detail có phiên bản/khổ cột khác nhau theo từng đợt xuất báo cáo từ hệ thống nhà máy), không phải lỗi parser.

Đối chiếu: file Batch Detail của khoảng cũ hơn (`Batch_2026825to31.xlsx`, `id=47`) **CÓ** đủ các cột này — xem mục 3.2.

**94/95 dòng thuộc nhóm này** đến từ import `id=19` (`Batch_20260901-08.xlsx`), phần còn lại rải rác ở các import khác cũng thiếu cột tương tự.

### 3.2. Vì sao 12/107 dòng có dữ liệu nhưng lệch ngày/máy?

12 mã mẻ này có đặc điểm chung: **đã từng chạy nhiều hơn 1 lần** (xuất hiện nhiều dòng trong `availability_logs`, ở các `production_date` khác nhau). Vì `batch_details.dyelot` là PRIMARY KEY (chỉ giữ 1 bản ghi/mã mẻ), giá trị Machine/Time đang lưu trong `batch_details` thực chất là snapshot của **lần chạy KHÁC** (thường là lần chạy trước đó), không phải lần chạy thuộc ngày 2026-09-03 đang xét.

Ví dụ minh hoạ (đã đối chiếu trực tiếp dữ liệu thô):

| Mã mẻ | Availability ngày 2026-09-03 | Batch_details đang lưu (từ lần chạy khác) |
|---|---|---|
| `C260664650` | Máy D511, 02/09 19:13 → 03/09 07:45 | Máy D511, **31/08** 06:57 → 31/08 18:24 |
| `C260685650` | Máy D058, 02/09 18:48 → 03/09 08:08 | Máy D058, **31/08** 10:48 → 31/08 16:07 |
| `C260687990` | Máy **D023**, 03/09 14:37 → 04/09 00:44 | Máy **D059** (khác!), 31/08 07:51 → 31/08 11:04 |
| `C260681060` | Máy D057, 03/09 21:14 → 04/09 01:47 | Máy D057, **29/08** 21:02 → 30/08 06:24 |

→ Với `C260687990`, Batch_details thậm chí ghi **sai cả Machine** (D059 thay vì D023) so với lần chạy đang xét — vì đó là dữ liệu của một lượt chạy hoàn toàn khác của cùng mã mẻ.

**Nguyên nhân gốc**: `core/batch_importer.py` dùng `ON CONFLICT(dyelot) DO UPDATE SET <mọi cột>=excluded.<mọi cột>` — mỗi lần mã mẻ này xuất hiện lại trong 1 file Batch mới, dòng cũ bị **ghi đè toàn bộ**, không giữ lịch sử. Đây là hành vi **có chủ đích** của thiết kế hiện tại (bảng `batch_details` được thiết kế như "hồ sơ mới nhất theo mã mẻ", không phải nhật ký nhiều lần chạy) — phù hợp vì hầu hết Engine chỉ cần Shade/ColourNo/BatchType (thường không đổi giữa các lần chạy lại của cùng mẻ), nhưng **không phù hợp** nếu có nhu cầu đối chiếu Machine/Time theo từng lần chạy cụ thể.

### 3.3. Máy CÓ trong Batch Detail nhưng CHƯA TỪNG xuất hiện trong Availability (phạm vi TOÀN BỘ lịch sử, không chỉ ngày 2026-09-03)

Mở rộng phạm vi kiểm tra ra toàn bộ dữ liệu (không giới hạn 1 ngày) để trả lời câu hỏi "máy nào Batch có mà Availability không có":

| | Số máy phân biệt |
|---|---:|
| Có trong `batch_details.machine` | 59 |
| Có trong `availability_logs.machine` | 47 |
| **Chỉ có ở `batch_details`, KHÔNG BAO GIỜ xuất hiện ở `availability_logs`** | **13** |
| Chỉ có ở `availability_logs`, không có ở `batch_details` | 1 (`D252`, chỉ 4 dòng đầu 05/2026 — không đáng kể) |

**13 máy chỉ có trong Batch Detail:**
`0101`, `0601`, `1203`, `1603`, `1604`, `1605`, `H101`, `H102`, `H301`, `H302`, `H501`, `H601`, `H801`

Đặc điểm đã xác nhận bằng dữ liệu thật (không suy đoán):
- **Đây KHÔNG phải dữ liệu rác/mock** — có đầy đủ Fabric Type, Customer, Start/End Time hợp lệ, trải dài **2026-06-30 → 2026-09-10** (nằm gọn trong khoảng ngày mà Availability đã có dữ liệu, 2026-05-02 → 2026-09-11 — nên KHÔNG phải do "chưa import đến kỳ này").
- Quy mô: **1.447 dòng** `batch_details` (~21% tổng số dòng có Machine) gắn với 13 máy này.
- Cơ cấu sản phẩm rất khác phần còn lại: **1.086/1.447 (75%) là Polyester** (chủ yếu "100% Recycle Polyester"), khách hàng chủ lực **PUMA (629), ADIDAS (261), UNDER ARMOUR (146)** — có vẻ là một **line nhuộm Polyester riêng** (mã máy kiểu số thuần `0101`/`0601`/`12xx`/`16xx` và `Hxxx`, khác hẳn quy ước `D0xx`/`D2xx`/`D5xx`/`DA0x`/`DO0x` đang thấy ở Availability).
- Batch Type: Normal 755, Rework 358, Unknown 318, Redye 16.
- **Đối chiếu chéo qua mã mẻ (không chỉ qua mã máy)**: trong 1.447 dyelot chạy trên 13 máy này, chỉ **13 dyelot (0.9%)** có xuất hiện ở `availability_logs` (dưới máy khác) — tức **1.434 dyelot (99.1%) hoàn toàn KHÔNG có bất kỳ bản ghi Availability nào**, không phải chỉ lệch tên máy.

**Ý nghĩa quan trọng**: toàn bộ báo cáo dựa trên `availability_logs` làm nguồn (Downtime, Batch Matrix, RFT, Cleaning MC — xem mục 5 `systemPatterns.md`) **hoàn toàn không nhìn thấy** 1.447 mẻ này, vì các Engine đó không đọc gì từ `batch_details` để tính KPI theo máy/ca. Nếu 13 máy này là dây chuyền nhuộm đang hoạt động thật (dữ liệu Batch Detail cho thấy vậy), đây là một **khoảng trống dữ liệu Availability** cần xác nhận với vận hành viên — không phải lỗi code, mà là **thiếu nguồn Excel Availability cho line máy này**.

---

## 4. So sánh các trường CHỈ CÓ Ở MỘT BẢNG (bổ sung cho nhau, không trùng lặp)

| Chỉ có ở `availability_logs` | Chỉ có ở `batch_details` |
|---|---|
| Toàn bộ breakdown giờ vận hành: `running_time_hour`, `total_downtime_hour`, `rework_hour`, `load_hour`, `unload_hour`, `cleaning_hour`, `maintenance_hour`... (44 cột `_hour`/`_kgh`) | Thông tin công thức/tiêu hao: `recipe_no`, `formula_type`, `process_type`, `liquor_ratio`, `soft_water`/`hot_water`/`sum_water`, `power`, `steam_per_kg`, `dye_cost`, `chemical_cost` |
| `availability_pct` (chỉ số Availability %) | `shade`, `colour_no`, `customer_color` — dùng để phân nhóm Color Group ở `batch_matrix` |
| `ach_load`, `ach_unload`, `ach_ph`... (cờ đạt/không đạt tiêu chuẩn) | `batch_type` (Normal/Rework/Unknown), `is_rework`, `correction_cnt` — dùng phân loại RFT/Cleaning MC |
| `capacity_kg` (dung tích thiết kế của máy) | `weight` (khối lượng vải THỰC TẾ nạp vào mẻ) |

→ 2 bảng **bổ sung cho nhau** theo đúng thiết kế: Availability trả lời "máy chạy bao lâu, mất giờ vào việc gì", Batch Detail trả lời "mẻ đó nhuộm màu gì, công thức nào, tiêu hao ra sao". Không có sự trùng lặp dữ liệu ở nhóm trường này.

### 4.1. Đối chiếu `weight` (Batch) và `capacity_kg` (Availability) — kiểm tra hợp lý

Không phải trường trùng nhau nhưng có quan hệ logic (khối lượng nạp không nên vượt dung tích máy):

- 105/107 mẻ: `weight ≤ capacity_kg` (hợp lý).
- **2/107 mẻ vượt nhẹ dung tích** (đáng chú ý nhưng trong ngưỡng chấp nhận được, không phải bất thường lớn):
  - `C260619260`: weight = 1219 kg / capacity = 1200 kg (vượt 1.6%)
  - `C260653010`: weight = 505.5 kg / capacity = 500 kg (vượt 1.1%)

### 4.2. Đối chiếu tín hiệu Rework: `batch_details.batch_type` vs `availability_logs.rework_hour`

Phân bố `batch_type` ngày 2026-09-03: **Normal 63, Rework 30, Unknown 14**.

Phát hiện đáng chú ý: **4 mẻ có `rework_hour > 0` (giờ Rework đo thật trên máy) nhưng `batch_type = 'Unknown'`** (không phải "Normal" cũng không phải "Rework" khai báo) — tức là Availability đã ghi nhận có phát sinh giờ sửa lỗi thật, nhưng Batch Detail không phân loại được mẻ đó (do JOIN theo dyelot không khớp Shade/BatchType, hoặc file Batch thiếu dòng tương ứng).

| Mã mẻ | rework_hour (Availability) | batch_type (Batch Detail) |
|---|---:|---|
| `C260674832` | 11.6 giờ | Unknown |
| `C260681060` | 3.8 giờ | Unknown |
| `C260690350` | 2.88 giờ | Unknown |
| `C260690360` | 1.43 giờ | Unknown |

→ Đây là các mẻ nên được rà soát thủ công nếu cần độ chính xác cao cho KPI Rework theo Batch Type.

---

## 5. Tóm tắt "giống" và "khác"

**Giống nhau (đáng tin cậy 100%):**
- Mã mẻ (`batch` ↔ `dyelot`) — khớp tuyệt đối 107/107, đây là khoá liên kết đúng và ổn định.
- Ý nghĩa nghiệp vụ: cả 2 đều mô tả cùng 1 mẻ nhuộm, không phải 2 nguồn độc lập nhau.

**Khác nhau (theo THIẾT KẾ, không phải lỗi):**
- Phạm vi dữ liệu: Availability = *thời gian vận hành*; Batch Detail = *công thức/tiêu hao/chất lượng*. Không trường nào bị tính trùng 2 lần trong các báo cáo hiện có.
- Số dòng/mẻ: Availability cho phép nhiều dòng/mã mẻ (mỗi lần chạy 1 dòng); Batch Detail luôn đúng 1 dòng/mã mẻ (bản mới nhất).

**Khác nhau do ĐẶC ĐIỂM FILE NGUỒN (cần lưu ý khi làm việc với dữ liệu):**
- 88.8% mẻ ngày 2026-09-03 có `batch_details` thiếu hẳn Machine/FabricType/Time vì file `Batch_20260901-08.xlsx` không có các cột này (khác với file `Batch_2026825to31.xlsx` cũ hơn — có đủ cột).
- 11.2% mẻ có Machine/Time trong `batch_details` nhưng là dữ liệu "tồn dư" từ lần chạy trước đó của cùng mã mẻ (do cơ chế UPSERT ghi đè theo `dyelot`), không đại diện cho lần chạy ngày 2026-09-03.
- 4 mẻ có tín hiệu Rework thật (giờ máy) nhưng chưa được phân loại `batch_type` tương ứng.

**Khác nhau ở PHẠM VI MÁY (phát hiện qua rà soát toàn bộ lịch sử, không chỉ ngày 2026-09-03):**
- **13 mã máy** (`0101`, `0601`, `1203`, `1603`, `1604`, `1605`, `H101`, `H102`, `H301`, `H302`, `H501`, `H601`, `H801`) có dữ liệu thật trong `batch_details` (1.447 dòng, chủ yếu Polyester cho PUMA/ADIDAS/UNDER ARMOUR, khoảng 06/2026–09/2026) nhưng **CHƯA TỪNG được import qua Availability** — 99.1% mã mẻ chạy trên các máy này không hề có bản ghi Availability nào. Nhiều khả năng đây là một dây chuyền/line nhuộm riêng chưa có nguồn dữ liệu Availability.
- Chiều ngược lại gần như không có: chỉ 1 máy (`D252`, 4 dòng đầu tháng 05/2026) có trong Availability mà không có trong Batch Detail — không đáng kể.

**Không phát hiện lỗi tính toán trong ứng dụng** — vì mọi Engine báo cáo (`batch_matrix`, `downtime`, `reports/cleaning_matrix`, `rft`) đều lấy Machine/Time/FabricType từ `availability_logs`, chỉ lấy Shade/ColourNo/BatchType/Weight từ `batch_details` — 2 nhóm trường không bị lẫn lộn giữa 2 nguồn.

---

## 6. Khuyến nghị

1. Nếu sau này cần đối chiếu Machine/Time theo TỪNG lần chạy cụ thể của 1 mã mẻ (không chỉ bản mới nhất), cần đổi khoá `batch_details` từ `dyelot` (PK) sang khoá kết hợp có thêm mốc thời gian, hoặc giữ lịch sử thay vì UPSERT ghi đè — đây là thay đổi lớn về schema, chỉ nên làm khi có nhu cầu nghiệp vụ rõ ràng.
2. Rà soát 4 mẻ ở mục 4.2 (`rework_hour > 0` nhưng `batch_type = Unknown`) để xác nhận có cần bổ sung dữ liệu Batch cho đúng phân loại.
3. Xác nhận với vận hành viên: liệu file Batch Detail dạng "không có cột Machine/Time" (như `Batch_20260901-08.xlsx`) có phải là chuẩn xuất báo cáo MỚI từ nay hay là thiếu sót một lần — nếu là chuẩn mới, không cần xử lý gì thêm (ứng dụng không phụ thuộc các cột này từ `batch_details`); nếu là thiếu sót, cần yêu cầu xuất lại file đầy đủ cột.
4. **Ưu tiên xác nhận với vận hành viên về 13 máy chỉ có ở Batch Detail** (mục 3.3): nếu đây là dây chuyền nhuộm Polyester đang hoạt động thật (dữ liệu cho thấy rõ ràng có), cần bổ sung nguồn Excel Availability cho line này — hiện tại toàn bộ KPI Downtime/Batch Matrix/RFT/Cleaning MC (đều tính từ `availability_logs`) đang **bỏ sót hoàn toàn ~1.447 mẻ** của line này.

---

*Báo cáo tạo tự động bằng truy vấn trực tiếp trên `data/mes_dashboard.db` ngày phân tích được tạo: 2026-09-17. Toàn bộ số liệu trong báo cáo đã được đối chiếu bằng dữ liệu thật (không suy đoán), có thể tái tạo lại bằng script SQL/Python tương đương truy vấn ở mục 2–4.*
