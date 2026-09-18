# Spec: Reason/Detail nhập tay + tự động lưu ("Case Notes")

**Ngày viết:** 2026-09-18
**Trạng thái:** Đã triển khai và đang chạy thật (Downtime by Category + Data Quality, domain `dyeing`, Engine `downtime`) — spec này mô tả lại tính năng ĐÃ CÓ để làm tài liệu tham chiếu, đồng thời rút thành pattern có thể tái sử dụng cho báo cáo khác.
**File liên quan:** `modules/dyeing/engines/downtime/service.py` (dòng ~790-936), `modules/dyeing/engines/downtime/routes.py` (dòng ~108-123), `modules/dyeing/engines/downtime/static/downtime.js` (dòng ~273-410), `modules/dyeing/engines/downtime/templates/downtime_view.html`.

---

## 1. Mục tiêu & bối cảnh nghiệp vụ

Khi kỹ sư IE drill-down xem danh sách mẻ bất thường (bảng "Downtime by Category" hoặc "Data Quality" trên `/dyeing/downtime/`), họ cần ghi lại **lý do (Reason)** và **mô tả chi tiết (Detail)** giải thích cho từng mẻ cụ thể — thông tin này KHÔNG có sẵn trong dữ liệu import (Excel Availability/Performance/Batch không có trường ghi chú tự do phù hợp).

Yêu cầu: nhập được ngay tại chỗ trên bảng đang xem (không mở form/modal riêng), lưu tự động khi rời khỏi ô nhập, không cần bấm nút "Save".

## 2. Mô hình dữ liệu

Bảng `downtime_case_notes`:

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `availability_log_id` | INTEGER NOT NULL | FK → `availability_logs.id`, `ON DELETE CASCADE` |
| `context` | TEXT NOT NULL DEFAULT `''` | Slug ngữ cảnh — xem mục 6 |
| `reason` | TEXT (nullable) | |
| `detail` | TEXT (nullable) | |
| `updated_by` | INTEGER NOT NULL | FK → `users.id` |
| `updated_at` | TEXT NOT NULL | `datetime('now')` mặc định khi tạo, ghi tay khi upsert |

Khoá: `UNIQUE(availability_log_id, context)` — tối đa **1 note cho mỗi cặp (mẻ, ngữ cảnh)**. Sửa lại = UPSERT ghi đè đúng dòng đó, **không lưu lịch sử nhiều phiên bản**. Note **không bao giờ đụng vào `availability_logs` gốc** — đây là bảng annotation tách biệt hoàn toàn khỏi dữ liệu đã import.

## 3. Backend

- `_ensure_case_notes_table(conn)` — tạo bảng nếu chưa có (lazy, chỉ chạy DDL ở SQLite; trên Postgres bảng đã có sẵn qua `supabase/schema.sql`, vì app không có quyền tự `ALTER TABLE`/`CREATE TABLE` trên Postgres production).
- `upsert_case_note(availability_log_id, context, reason, detail, user_id) -> dict`:
  1. Validate `availability_log_id` tồn tại trong `availability_logs` (raise `ValueError` nếu không → route trả 400).
  2. `INSERT ... ON CONFLICT(availability_log_id, context) DO UPDATE SET reason=excluded.reason, detail=excluded.detail, updated_by=excluded.updated_by, updated_at=excluded.updated_at`.
  3. Đọc lại dòng vừa ghi (JOIN `users` lấy `username`) và trả về dict cho frontend cập nhật UI ngay, không cần load lại cả bảng.
- `_attach_case_notes(batches: list[dict], context: str)` — ghép note vào TOÀN BỘ danh sách batch đang hiển thị bằng **1 query duy nhất** (`WHERE availability_log_id IN (...) AND context IN (?, '')`), không phải N+1 query theo từng dòng. Ưu tiên note đúng `context`; nếu mẻ chưa có note riêng cho context đang xem, fallback về note "chung" (`context=''`, xem mục 6).
- Route ghi: `POST /dyeing/downtime/api/case-notes/<availability_log_id>`
  - Body JSON: `{context, reason, detail}` — `context` bắt buộc (400 nếu thiếu/rỗng).
  - `reason`/`detail`: `.strip()`, chuỗi rỗng chuyển thành `None`.
  - Gate: `permission_required("dyeing", "downtime", "edit")`.
  - Trả `{"status": "success", "note": {...}}` hoặc `{"error": "..."}` (400).
- Route đọc (`.../api/top-batches`, `.../api/abnormal-point-batches`) gate bằng quyền `"view"`, gọi `_attach_case_notes()` trước khi trả JSON — client không cần gọi API riêng để lấy note.

## 4. Frontend (UX)

- Trong modal drill-down (`#top-batches-overlay`, DOM dùng chung cho cả 2 báo cáo), mỗi ô Reason/Detail render qua `renderCaseNoteCell()`:
  - Có quyền edit (`window.DOWNTIME_CAN_EDIT_NOTES === true`, bơm từ `current_user_can('dyeing','downtime','edit')`): render `<span class="case-note-cell" data-log-id data-field>` — click vào để sửa.
  - Không có quyền edit: render plain text, không có control nào (route ghi vẫn chặn ở server dù cố gọi thẳng API).
- Click vào ô → `startEditingCaseNote()` thay `<span>` bằng `<input>` (Reason) hoặc `<textarea>` (Detail), focus + select toàn bộ text cũ.
- Lưu (`saveCaseNote()`):
  - **Reason**: lưu khi `blur` HOẶC nhấn `Enter`.
  - **Detail**: CHỈ lưu khi `blur` (giữ `Enter` để xuống dòng trong ghi chú dài).
  - `Escape`: huỷ, không lưu, revert về giá trị cũ.
- Gọi `POST .../api/case-notes/<id>` với `{context: activeCaseContext, reason, detail}` — `activeCaseContext` được set khi mở modal (= tên category khi mở từ "Downtime by Category", = field `loading`/`unloading` khi mở từ "Data Quality").
- Thành công: cập nhật lại `row.case_reason/case_detail/case_updated_by/case_updated_at` từ response, render lại `<span>`, toast "Note saved." (dùng chung `.toast-container`/`.import-toast` có sẵn trong `app.css`, không viết CSS/JS toast riêng).
- Thất bại: revert `<span>` về giá trị cũ, toast "Failed to save note.".
- Ô đã có note: `title="Edited by {username} at {updated_at}"` khi hover.
- Ô Detail dài: hiển thị cắt 45 ký tự + "..." (`truncateText()`), full text qua `title=` — **API luôn trả full text không cắt**, cắt chỉ xảy ra ở tầng hiển thị.
- Ô trống + có quyền edit: placeholder `<span class="case-note-empty">Click to add</span>`.

## 5. Phân quyền

| Hành động | Quyền yêu cầu |
|---|---|
| Xem note (qua API đọc batch chi tiết) | `permission_required("dyeing", "downtime", "view")` |
| Ghi/sửa note | `permission_required("dyeing", "downtime", "edit")` |

`admin` là superuser cố định, luôn ghi được, không đi qua bảng `user_permissions`.

## 6. Quyết định thiết kế quan trọng (kèm lý do)

- **Vì sao có cột `context` thay vì chỉ khoá `UNIQUE(availability_log_id)`**: bản đầu chỉ khoá theo mẻ → 1 mẻ xuất hiện ở nhiều category khác nhau (VD vừa có giờ Rework vừa có giờ Color Adjustment) hoặc cả 2 field của Data Quality (loading/unloading) bị **dùng chung nhầm 1 note** — sửa Reason ở category này làm lộ/đổi luôn note ở category khác của cùng mẻ. Đây là bug thật người dùng report trực tiếp, đã sửa bằng cách thêm `context` + đổi khoá thành `UNIQUE(availability_log_id, context)`.
- **Vì sao note CŨ (trước khi có `context`) không bị mất**: gán `context=''`, dùng làm giá trị fallback hiển thị cho MỌI context chưa có note riêng — tách dần khi người dùng sửa lại theo từng category cụ thể (lần sửa ghi thành dòng MỚI với context riêng, không ghi đè dòng `context=''`).
- **Vì sao dùng CHUNG 1 bảng cho cả 2 báo cáo (Downtime by Category + Data Quality) thay vì 2 bảng annotation riêng**: cả 2 đều khoá theo cùng `availability_logs.id`, 1 mẻ có thể xuất hiện ở CẢ HAI — annotation phải là 1 nguồn duy nhất để không lệch nhau khi sửa từ 1 trong 2 nơi.
- **Vì sao inline-edit thay vì form/modal riêng**: tái dùng đúng pattern UI đã có (`case-note-cell`, copy từ `target-cell` đã dùng cho tính năng Target trước đó) — giảm số thao tác khi kỹ sư cần ghi chú nhiều dòng liên tiếp lúc rà soát bảng.
- **Vì sao auto-save khi blur/Enter thay vì nút "Save" riêng**: giảm ma sát thao tác, khớp quy trình thực tế "xem batch bất thường → ghi lý do ngay" thay vì phải nhớ bấm lưu.
- **Vì sao KHÔNG lưu lịch sử nhiều phiên bản**: yêu cầu ban đầu chỉ cần annotation hiện tại, không cần audit trail — UPSERT ghi đè là đủ, tránh phình bảng không cần thiết (có thể bổ sung sau nếu có yêu cầu truy vết).

## 7. Cách tái sử dụng pattern này cho 1 báo cáo/Engine khác

Checklist khi muốn áp lại "Reason/Detail auto-save" cho 1 danh sách drill-down mới:

1. **Xác định entity gốc** danh sách đang khoá theo cái gì (VD `availability_logs.id`, `batch_details.dyelot`...). Nếu đã có bảng annotation khoá đúng entity đó rồi (như `downtime_case_notes` khoá theo `availability_logs.id`) — **dùng chung bảng đó**, chỉ thêm 1 giá trị `context` mới, KHÔNG tạo bảng annotation thứ 2 cho cùng entity.
2. Nếu entity gốc khác hẳn (VD theo máy, theo lô nhuộm...) — tạo bảng riêng theo đúng schema mẫu ở mục 2, đặt tên theo Engine sở hữu.
3. Hàm SELECT danh sách chi tiết phải trả thêm khoá entity gốc (`id`) trong response — frontend cần khoá này để gửi kèm khi lưu note.
4. Ghép note vào danh sách bằng **1 query JOIN duy nhất** cho cả danh sách — không N+1 theo từng dòng.
5. Route ghi **luôn bắt buộc `context`** nếu entity có thể xuất hiện ở nhiều màn hình/ngữ cảnh hiển thị khác nhau — quyết định `context` slug là gì (tên category, tên field...) do bối cảnh cụ thể quyết định.
6. Gate quyền: đọc theo `"view"`, ghi theo `"edit"` của đúng Engine sở hữu dữ liệu — dùng `permission_required()` có sẵn, không viết cơ chế phân quyền riêng.
7. UI: tái dùng class `case-note-cell`/`.case-note-empty`/`.case-note-editing` và `.toast-container` đã có trong `app.css`/`downtime.js` thay vì viết CSS/JS annotation mới — chỉ cần 1 hàm render nội dung khác cho đúng field của báo cáo mới.
8. Nếu danh sách đã có modal/overlay drill-down sẵn (VD `#top-batches-overlay`), tái dùng luôn DOM đó — không tạo overlay mới.

## 8. Trạng thái hiện tại & rủi ro còn mở

- Đã dùng thật trên production: 27 note thật trên Supabase (tính tới 2026-09-17), qua cả 2 màn hình Downtime by Category và Data Quality.
- Cột `downtime_logs.detail` (từ 1 thiết kế cũ đã bị thay thế — auto-match theo `downtime_logs`, xem lịch sử ở `memory-bank/systemPatterns.md` mục 6.2) không còn liên quan tới cơ chế này, giữ lại vô hại.
- **Chưa có**: lịch sử chỉnh sửa nhiều phiên bản (hiện tại UPSERT ghi đè, mất giá trị note cũ khi sửa lại) — nếu sau này cần audit trail đầy đủ ai-sửa-gì-lúc-nào qua từng lần, cần thiết kế thêm bảng lịch sử riêng (ngoài phạm vi spec này).
- **Chưa có**: giới hạn độ dài `reason`/`detail` ở tầng validate backend (hiện chỉ `.strip()`) — chấp nhận được ở quy mô hiện tại, cân nhắc nếu phát sinh input bất thường.
