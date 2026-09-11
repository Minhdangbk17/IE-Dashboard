# Project Brief — CETVN IE DASHBOARD (tên cũ: MES Dashboard)

## Tổng quan
Xây dựng một Web Dashboard phân tích dữ liệu sản xuất (MES) nội bộ cho các
nhà máy Nhuộm (Dyeing) và Dệt (Knitting) thuộc hệ thống CETVN / Crystal CET
(và các nhà máy liên kết CETBD, RTVL, EG ở các giai đoạn sau).

## Mục tiêu Phase 1 (Foundation Skeleton)
1. Dựng khung kiến trúc **Modular / Vertical Slice + Engine-Plugin Pattern**
   trên nền Flask, có thể mở rộng thêm Domain (xưởng) và Engine (chỉ số tính
   toán) mà không cần sửa code lõi (`app.py`).
2. Chuẩn hoá tầng dữ liệu bằng **SQLite thuần** (WAL mode) — không dùng ORM,
   giữ hiệu năng cao và dễ triển khai offline tại xưởng.
3. Xây dựng **Excel Import Pipeline** đáng tin cậy: validate schema, báo lỗi
   chi tiết theo dòng, bulk insert trong transaction — vì nguồn dữ liệu chính
   ở giai đoạn đầu là file Excel do vận hành viên nhập tay hoặc export từ máy.
4. Cung cấp **Hub Dashboard** cho từng xưởng, tổng hợp các chỉ số vận hành cốt
   lõi: OEE (Overall Equipment Effectiveness) và Downtime (dừng máy).
5. Trực quan hoá kiến trúc hệ thống qua **Graphify** — sơ đồ phụ thuộc
   Engine/Data Flow tự sinh, hỗ trợ Agent AI và kỹ sư mới hiểu hệ thống nhanh.

## Phạm vi Phase 1
- Domain: `dyeing` (đầy đủ 3 Engine: oee, downtime, excel_import).
- Domain: `knitting` (scaffold tối giản, chứng minh Auto-loader đa-domain).
- Auth tối giản (session-based, 2 role: admin/operator).
- UI: GitHub Primer CSS, Dark Mode mặc định, Sidebar + Main Content.

## Ngoài phạm vi Phase 1 (Backlog cho Phase sau)
- Kết nối trực tiếp PLC/IoT (hiện tại giả lập bằng Excel Import + seed data).
- Dữ liệu chất lượng (QC/reject) để tính chính xác chỉ số Quality trong OEE.
- Engine đầy đủ cho Domain "knitting".
- Multi-factory sync (CETVN, CETBD, RTVL, EG).
- Authentication nâng cao (JWT/SSO), audit log chi tiết.

## Bên liên quan (Stakeholders)
- Vận hành viên xưởng Nhuộm/Dệt: nhập liệu qua Excel Import.
- Kỹ sư công nghiệp (Industrial Engineering): theo dõi OEE, phân tích Downtime.
- Quản trị hệ thống: theo dõi log import, sơ đồ kiến trúc qua Graphify.
