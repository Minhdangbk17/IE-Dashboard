# CLAUDE.md — Chỉ dẫn cho Claude Code trong dự án CETVN IE DASHBOARD

Đây là dự án **CETVN IE DASHBOARD** (tên cũ: MES Dashboard; Flask + SQLite, kiến trúc Modular/Engine-Plugin).
File này được Claude Code tự động đọc khi mở dự án — nó thay thế cho trí nhớ
mà Claude KHÔNG giữ được giữa các phiên làm việc.

## 1. QUAN TRỌNG NHẤT: Đọc Memory Bank trước khi làm bất kỳ việc gì

Bộ nhớ của Claude bị reset hoàn toàn giữa các phiên. Thư mục `memory-bank/`
là nguồn thông tin DUY NHẤT giúp Claude hiểu dự án đang ở đâu, tại sao mọi
thứ được thiết kế như vậy. **Ở đầu MỌI task (kể cả một câu hỏi nhỏ về kiến
trúc), Claude PHẢI đọc toàn bộ 6 file trong `memory-bank/` trước khi trả lời
hoặc sửa code** — không được giả định hoặc "đoán" lại từ đầu.

Thứ tự đọc khuyến nghị:

| File | Nội dung |
|---|---|
| `memory-bank/projectbrief.md` | Mục tiêu, phạm vi dự án, phạm vi Phase hiện tại |
| `memory-bank/productContext.md` | Luồng nghiệp vụ Nhuộm/Dệt, quy trình Import Excel chi tiết |
| `memory-bank/systemPatterns.md` | Các pattern kiến trúc: Auto-loader, Engine-Plugin, SQLite WAL, Navigation Registry, Graphify |
| `memory-bank/techContext.md` | Stack công nghệ, schema DB, biến môi trường |
| `memory-bank/activeContext.md` | Đang làm gì, quyết định gần đây, việc tiếp theo, rủi ro |
| `memory-bank/progress.md` | Checklist đã xong / backlog / known issues |

Nếu người dùng nói **"update memory bank"** hoặc **"cập nhật memory bank"**:
rà soát lại TOÀN BỘ 6 file trên (không chỉ 1-2 file), đặc biệt cập nhật
`activeContext.md` (trạng thái/quyết định mới nhất) và `progress.md`
(việc vừa hoàn thành, backlog phát sinh) để phản ánh đúng tình trạng dự án
sau khi có thay đổi đáng kể (thêm Domain/Engine mới, đổi schema DB, đổi
quyết định kiến trúc...).

## 2. `graphify/` — bản đồ kiến trúc SỐNG, không phải tài liệu tĩnh

Trước khi trả lời câu hỏi kiểu "Engine X phụ thuộc gì?" hoặc "thêm Engine
mới có ảnh hưởng gì tới OEE không?", ưu tiên tra cứu bằng cách:
1. Đọc `graphify/mapper.py` để hiểu cách graph được dựng (từ `EngineMetadata`
   của từng Engine — `data_sources`, `data_sinks`, `depends_on`).
2. Nếu ứng dụng đang chạy, gọi `GET /graphify/api/graph` (cần đăng nhập role
   `admin`) để lấy đúng trạng thái phụ thuộc hiện tại — KHÔNG suy đoán từ trí
   nhớ vì graph này tự sinh động, có thể đã đổi sau khi thêm Engine mới.
3. Khi **tạo Engine mới**, bắt buộc khai báo đúng `EngineMetadata` (trong
   `create_blueprint`/`metadata` property của Engine) — nếu khai sai
   `data_sources`/`data_sinks`/`depends_on`, sơ đồ Graphify sẽ sai và đây là
   lỗi cần tránh, không phải chi tiết tuỳ chọn.

## 3. Kiến trúc tóm tắt (chi tiết đầy đủ xem `systemPatterns.md`)

- **Application Factory**: `app.py::create_app()`, không tạo `app` global
  ngoài factory.
- **Auto-loader 2 cấp, KHÔNG hardcode**:
  - `app.py` quét `modules/<domain>/` bằng `pkgutil`, gọi `register(app)`.
  - `modules/<domain>/__init__.py` quét `engines/<engine>/`, lấy biến
    `engine = XxxEngine()`, gắn `engine.blueprint` (Nested Blueprint).
- **Mọi Engine** kế thừa `core.engine_base.BaseEngine`, phải implement
  `metadata` (property trả `EngineMetadata`) và `create_blueprint()`.
- **SQLite thuần** (`core/database.py`), WAL mode, không dùng ORM.
- **Excel Import** (`core/excel_importer.py`) là Schema-driven: khai báo
  `ImportSchema`/`ColumnSpec`, không viết lại logic parse/validate/bulk-insert.
- **Navigation**: mỗi Domain tự `register_menu(...)` khi được auto-load;
  KHÔNG sửa `templates/base.html` để thêm mục menu thủ công.

## 4. Quy tắc khi thêm Domain hoặc Engine mới

Thêm Domain/Engine mới KHÔNG được sửa `app.py` hay `__init__.py` của domain
khác. Làm theo đúng khuôn mẫu:
- Domain mới: copy cấu trúc `modules/knitting/` (scaffold tối giản) hoặc
  `modules/dyeing/` (đầy đủ) — xem README.md mục "Thêm một Domain mới".
- Engine mới trong Domain có sẵn: copy cấu trúc
  `modules/dyeing/engines/oee/` (đủ `__init__.py` + `routes.py` + `service.py`).
- Sau khi thêm, chạy lại `python app.py` — kiểm tra log Auto-loader in ra
  đúng tên Domain/Engine mới nạp được, và kiểm tra `/graphify/` để chắc
  Engine mới xuất hiện đúng trên sơ đồ.

## 5. Quy ước code

- Type hinting đầy đủ, `from __future__ import annotations` ở đầu file.
- Docstring/tên biến bằng tiếng Việt (đúng ngôn ngữ làm việc của team), tên
  hàm/class bằng tiếng Anh theo chuẩn Python (PEP8).
- Không thêm ORM/thư viện ngoài trừ khi thực sự cần — Phase 1 cố tình giữ
  dependency tối giản (`Flask`, `openpyxl`, `click`).
- Route API trả JSON qua `jsonify()`; route View trả `render_template()`.

## 6. Lệnh thường dùng

```bash
pip install -r requirements.txt
python init_db.py            # khởi tạo DB + seed data (idempotent)
python init_db.py --reset    # xoá DB cũ, tạo lại từ đầu
python app.py                # chạy dev server tại http://localhost:5000
```

Tài khoản demo: `admin/admin123` (toàn quyền), `operator/operator123` (vận hành).

## 7. Lưu ý bảo mật đã biết (không phải bug, đã ghi nhận trong progress.md)

Mật khẩu băm bằng SHA-256 + salt tĩnh (`core/auth.py`) — chỉ phù hợp demo
Phase 1. KHÔNG tự ý "sửa lỗi" phần này trừ khi người dùng yêu cầu nâng cấp
bảo mật rõ ràng, vì đây là quyết định đã ghi trong `activeContext.md` chứ
không phải sai sót.
