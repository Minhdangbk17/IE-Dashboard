# Product Context — Luồng nghiệp vụ & Quy trình Import

## Luồng nghiệp vụ xưởng Nhuộm (Dyeing)
1. Máy nhuộm vận hành theo ca; vận hành viên (hoặc hệ thống IoT ở Phase sau)
   ghi nhận trạng thái máy (RUNNING/STOPPED/MAINTENANCE), tốc độ thực tế,
   tốc độ tiêu chuẩn, sản lượng (mét vải) theo từng mốc thời gian.
2. Khi máy dừng, vận hành viên ghi nhận **lý do dừng máy** (reason_code/
   reason_name) và thời lượng dừng — dữ liệu này phục vụ phân tích Pareto để
   xác định nguyên nhân gây tổn thất sản lượng lớn nhất.
3. Cuối ca/ngày, dữ liệu trên được tổng hợp vào file Excel (do thiếu kết nối
   IoT trực tiếp ở Phase 1) và import vào hệ thống qua **Hub Nhuộm**.
4. Sau khi import, các Engine `oee` và `downtime` tự động tính toán lại chỉ
   số dựa trên dữ liệu mới nhất — Hub hiển thị widget realtime (fetch async).

## Luồng nghiệp vụ xưởng Dệt (Knitting)
Phase 1 mới scaffold tối giản. Nghiệp vụ tương tự Nhuộm nhưng chỉ số đặc thù
khác (hiệu suất dệt theo mũi/phút, định mức tiêu hao sợi...) — sẽ triển khai
đầy đủ ở Phase 2 theo đúng khuôn mẫu kiến trúc của Nhuộm.

## Quy trình Import Excel (chi tiết)
1. Người dùng vào Hub xưởng, bấm nút **"Import Data"** → mở Modal.
2. Chọn loại dữ liệu (Telemetry hoặc Downtime) → có thể tải **file mẫu**
   (Template) để biết đúng cấu trúc cột.
3. Kéo-thả hoặc chọn file `.xlsx`/`.xls`/`.csv` → hệ thống gọi API
   `/api/preview` để xem trước 5 dòng đầu + liệt kê lỗi (nếu có) mà KHÔNG ghi
   vào Database.
4. Người dùng xem preview, sửa lại file nếu cần, rồi bấm **"Xác nhận Import"**.
5. Hệ thống upload file thật (có Progress Bar) tới `/api/import/<loại>`:
   - Validate lại toàn bộ (parse ngày tháng, kiểu số, enum trạng thái...).
   - Bỏ qua dòng trống tự động.
   - Dòng lỗi được thu thập chi tiết (số dòng + mô tả lỗi cụ thể) — KHÔNG
     làm crash tiến trình.
   - Theo cấu hình `IMPORT_STRICT_MODE`: hoặc yêu cầu file 100% hợp lệ mới
     commit, hoặc commit các dòng hợp lệ và bỏ qua dòng lỗi (mặc định).
   - Toàn bộ dòng hợp lệ được ghi vào SQLite bằng MỘT transaction
     (`executemany`) để tối ưu hiệu năng và đảm bảo tính toàn vẹn.
6. Kết quả import (số dòng thành công/lỗi) được lưu vào bảng `import_logs`
   để tra cứu lịch sử, đồng thời trả JSON cho Frontend hiển thị + tự động
   làm mới (refresh) các widget trên Hub.

## Vai trò người dùng (Roles)
- **admin**: superuser cố định — toàn quyền mọi Engine, xem sơ đồ Graphify,
  quản lý tài khoản (`/admin/accounts`).
- **operator**: quyền Xem/Sửa/Xoá RIÊNG CHO TỪNG ENGINE (2026-09-10, thay cho
  quyền cố định "xem Hub/OEE/Downtime" trước đây) — admin gán qua
  `/admin/accounts/<id>/permissions`, mặc định tài khoản operator mới KHÔNG
  có quyền gì cho tới khi được gán. Không xem Graphify/Quản lý tài khoản (2
  mục này chỉ dành riêng admin qua `roles=("admin",)`, không đi qua bảng
  phân quyền theo Engine). Chi tiết đầy đủ ở `systemPatterns.md` mục 10.
