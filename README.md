# CETVN IE DASHBOARD — Phase 1: Foundation Skeleton

Web Dashboard phân tích dữ liệu sản xuất (MES) cho xưởng Nhuộm (Dyeing) và
Dệt (Knitting), xây dựng trên Flask + SQLite (WAL mode), theo kiến trúc
**Modular / Vertical Slice + Engine-Plugin Pattern**.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Khởi tạo Database (bắt buộc chạy trước)

```bash
python init_db.py            # tạo DB + seed data mẫu (idempotent)
python init_db.py --reset    # xoá DB cũ và tạo lại từ đầu
```

Tài khoản demo:
- `admin` / `admin123` (toàn quyền, bao gồm Graphify)
- `operator` / `operator123` (vận hành, import dữ liệu)

## Chạy ứng dụng

```bash
python app.py
```

Mở trình duyệt tại `http://localhost:5000`.

## Cấu trúc chính

```
app.py                # Application Factory + Auto-loader Domain
init_db.py             # Khởi tạo schema + seed data
config.py              # Cấu hình tập trung (env-driven)
core/                  # Hạ tầng dùng chung (DB, Auth, Nav, Engine base, Excel Importer)
graphify/               # Sơ đồ phụ thuộc Engine / Data Flow (tự sinh)
memory-bank/            # Tài liệu ngữ cảnh dự án cho AI Agent
modules/
  dyeing/               # Domain Nhuộm — đầy đủ 3 Engine
    engines/
      oee/               # Chỉ số OEE
      downtime/          # Phân tích dừng máy (Pareto)
      excel_import/      # Import Excel/CSV -> SQLite
  knitting/             # Domain Dệt — scaffold tối giản (Phase 2 sẽ mở rộng)
```

## Thêm một Domain mới (vd `finishing`)

1. Tạo `modules/finishing/__init__.py` với hàm `register(app)` (copy khuôn
   mẫu từ `modules/knitting/__init__.py`).
2. Tạo `modules/finishing/routes.py` với `finishing_bp` + route Hub.
3. Tạo `modules/finishing/engines/<ten_engine>/` theo khuôn mẫu
   `modules/dyeing/engines/oee/`.
4. Chạy lại `python app.py` — Auto-loader sẽ tự phát hiện Domain mới,
   KHÔNG cần sửa `app.py`.

## Thêm một Engine mới trong Domain có sẵn (vd `quality` trong `dyeing`)

1. Tạo thư mục `modules/dyeing/engines/quality/` với `__init__.py` (expose
   biến `engine = QualityEngine()`), `routes.py`, `service.py`.
2. `QualityEngine` phải kế thừa `core.engine_base.BaseEngine` và implement
   `metadata` + `create_blueprint()`.
3. Chạy lại ứng dụng — Engine mới tự động xuất hiện trên Hub Nhuộm **và**
   trên sơ đồ Graphify (`/graphify/`), không cần đăng ký thủ công.

## Ghi chú bảo mật (Phase 1)

Mật khẩu băm bằng SHA-256 + salt tĩnh — chỉ phù hợp demo nội bộ. Trước khi
triển khai production với nhiều người dùng, thay bằng
`werkzeug.security.generate_password_hash` hoặc bcrypt (xem `core/auth.py`).
