# System Patterns — Kiến trúc & Quy ước thiết kế

## 1. Application Factory Pattern
`app.py::create_app()` khởi tạo Flask app, nạp config, đăng ký hạ tầng lõi
(Database, Navigation), auto-load Domain modules, và mount Graphify. Không có
biến `app` global nào được tạo bên ngoài factory (trừ biến `app` cuối file để
tương thích `flask run` / WSGI server).

## 2. Modular / Vertical Slice Architecture
Mỗi tính năng (Engine) được đóng gói ĐẦY ĐỦ trong một thư mục: Route (API +
View), Service (business logic), Template, Static — thay vì tách theo layer
kỹ thuật (routes/, services/, templates/ dùng chung cho cả app). Điều này
giúp thêm/xoá một Engine không ảnh hưởng tới Engine khác.

## 3. Engine-Plugin Pattern (Nested Blueprint)
```
app (Flask)
 └─ modules.dyeing (Blueprint "dyeing", url_prefix=/dyeing)
     ├─ engines.oee          (Blueprint "oee", url_prefix=/oee)      -> endpoint "dyeing.oee.view"
     ├─ engines.downtime     (Blueprint "downtime", url_prefix=/downtime)
     └─ engines.excel_import (Blueprint "excel_import", url_prefix=/excel_import)
```
- `core/engine_base.py::BaseEngine` là Abstract Base Class mọi Engine phải kế
  thừa — bắt buộc implement `metadata` (property) và `create_blueprint()`.
- Mỗi package Engine expose biến module-level `engine = XxxEngine()` — đây là
  "hợp đồng" (contract) mà Auto-loader dựa vào để phát hiện Engine hợp lệ.

## 4. Auto-Loader (2 cấp)
- **Cấp App** (`app.py::_autoload_domains`): quét `modules/` bằng `pkgutil`,
  gọi `register(app)` mà mỗi Domain package expose.
- **Cấp Domain** (`modules/<domain>/__init__.py::_autoload_engines`): quét
  `modules/<domain>/engines/`, import từng package con, lấy biến `engine`,
  gắn `engine.blueprint` vào Blueprint của Domain.

=> Thêm Domain/Engine mới = tạo thư mục đúng convention, KHÔNG sửa `app.py`
hay `__init__.py` của domain khác.

## 5. SQLite WAL Mode
`core/database.py` bật `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`
ngay khi mở connection — cho phép nhiều reader đọc đồng thời trong lúc một
writer đang ghi (quan trọng vì Import Excel có thể chạy trong lúc Hub đang
load widget). Connection được cache trong `flask.g`, đóng tự động qua
`teardown_appcontext`. **CHỈ áp dụng khi dialect là SQLite** — xem mục 5.1.

## 5.1 Dual-mode Database: SQLite (mặc định) / PostgreSQL-Supabase (khi deploy) — 2026-09-11
Bổ sung để deploy được qua Git → Supabase → Vercel: Vercel serverless có filesystem
ephemeral (mất sạch mỗi cold start), nên file SQLite cục bộ KHÔNG thể dùng làm nơi lưu dữ
liệu thật khi deploy production — phải chuyển sang Postgres (Supabase) cho môi trường đó,
NHƯNG local dev vẫn cần chạy được SQLite không phụ thuộc Postgres thật.

- **Cơ chế chọn dialect**: biến môi trường `DATABASE_URL` (mới, `config.py`). KHÔNG set
  (mặc định) -> SQLite y hệt trước đây, không đổi hành vi gì. CÓ set (vd trên Vercel trỏ
  Supabase) -> `core/database.py::get_db()` mở `psycopg2` connection thay vì `sqlite3`.
  `core/database.py::get_dialect() -> "sqlite" | "postgres"` là nguồn sự thật DUY NHẤT cho
  câu hỏi "đang chạy dialect nào" — đọc `current_app.config["DATABASE_URL"]` khi có Flask
  app context, fallback đọc thẳng `os.environ.get("DATABASE_URL")` khi KHÔNG có app context
  (vd script/test gọi thẳng `recompute_daily(day, conn)` với 1 connection tự mở, không qua
  Flask — xem `tests/test_batch_matrix_formula.py`, đây là bug thật đã gặp và sửa: `get_dialect()`
  ban đầu chỉ đọc `current_app` nên crash `RuntimeError: Working outside of application context`
  khi gọi ngoài request/CLI).
- **`_PostgresConnCompat`** (`core/database.py`) — lớp bọc 1 psycopg2 connection để mô
  phỏng đúng bề mặt API mà GẦN 20 CHỖ trong ~16 file Engine đang gọi trên
  `sqlite3.Connection`: `.execute(sql, params)` shorthand (tự tạo cursor, sqlite3.Connection
  có sẵn method này nhưng psycopg2.Connection thì KHÔNG), `.executemany()`, placeholder `?`.
  Dịch trong suốt ở tầng này (KHÔNG sửa từng câu SQL rải rác):
  - `?` -> `%s` (quy tắc placeholder của psycopg2). AN TOÀN với `IN (?, ?, ?)` động (build
    qua `",".join("?" for _ in items)`, số lượng giữ nguyên). **Cảnh báo**: `%s` khiến dấu
    `%` LITERAL (vd `LIKE '%x%'`) bị hiểu nhầm format specifier trừ khi viết `%%` — dự án
    hiện KHÔNG có `LIKE` nào, nhưng PHẢI nhớ viết `%%` nếu thêm sau này.
  - `PRAGMA table_info(x)` -> `SELECT column_name AS name FROM information_schema.columns
    WHERE table_name = 'x' ORDER BY ordinal_position` — giữ nguyên alias `name` mà mọi call
    site đang đọc (`{row["name"] for row in conn.execute(...)}`), không cần sửa call site.
  - Row factory: `psycopg2.extras.RealDictCursor` (row là dict thật, tương thích
    `dict(row)`/`row["col"]` dùng khắp nơi — codebase KHÔNG bao giờ truy cập row theo vị
    trí số `row[0]`, đã verify bằng grep).
- **`sql_datetime(expr)`** (`core/database.py`) — thay cho viết literal `datetime(...)` của
  SQLite trong câu SQL (Postgres không có hàm này). SQLite: giữ nguyên `datetime(expr)` —
  **KHÔNG được tự ý xoá hẳn wrapper rồi so sánh chuỗi thường**, vì `datetime()` còn có vai
  trò CHUẨN HOÁ (zero-pad, cắt giây lẻ/timezone) cho dữ liệu cũ/nhập tay lệch định dạng, chỉ
  bỏ đi trông "vẫn đúng" với dữ liệu mới (luôn ghi chuẩn qua `.strftime()`) nhưng mất khả
  năng chịu lỗi đó (phát hiện qua phản biện của Plan agent trước khi code, xem
  `C:\Users\cevmdtran1\.claude\plans\swift-crunching-pond.md` nếu cần đọc lại toàn bộ kế
  hoạch/lý do). Postgres: `(expr)::timestamp`.
- **`core/production_time.py::production_date_sql_expr(col)`** — bản HÀM (thay literal
  `PRODUCTION_DATE_SQL_EXPR.format(col=...)` cũ, vẫn giữ hằng số này cho tương thích ngược
  nhưng KHÔNG dùng trực tiếp ở call site mới) của biểu thức "ca sản xuất cắt 7h sáng" —
  biểu thức TRUNG TÂM nhất codebase (dùng ở downtime/batch_matrix/cleaning_matrix/rollup).
  SQLite: `date(datetime(col), '-7 hours')` (không đổi). Postgres:
  `((col)::timestamp - interval '7 hours')::date`.
- **`DatabaseError`/`DatabaseIntegrityError`** (`core/database.py`) — thay cho
  `except sqlite3.Error`/`except sqlite3.IntegrityError` trực tiếp (psycopg2 raise
  `psycopg2.Error`/`psycopg2.IntegrityError`, KHÔNG kế thừa từ lớp SQLite nên
  `except sqlite3.Error` sẽ KHÔNG bắt được lỗi Postgres — bug thật đã lường trước, không
  phải giả thuyết). **LUÔN LUÔN là tuple** (kể cả khi không có psycopg2, tuple 1 phần tử
  `(sqlite3.Error,)`) — lý do: `except (A, *DatabaseError):` (cách bắt buộc phải dùng khi
  cần kết hợp với type khác, xem `modules/dyeing/engines/{reports,excel_import}/routes.py`)
  cần `DatabaseError` LUÔN iterable được; **TUYỆT ĐỐI KHÔNG viết
  `except (A, DatabaseError):`** (tuple LỒNG bên trong tuple — Python KHÔNG tự flatten,
  `TypeError: catching classes that do not inherit from BaseException` — đã verify bug này
  bằng thực nghiệm trước khi chọn thiết kế tuple-luôn-luôn + `*` unpacking).
- **DDL (`CREATE TABLE`) trong các hàm `_ensure_*_table()` rải rác** (mỗi Engine tự đảm bảo
  bảng riêng tồn tại lúc runtime, pattern đã có từ trước — `downtime/service.py`,
  `cleaning_matrix.py`, `batch_matrix/service.py`, `excel_import/service.py`,
  `core/auth.py::ensure_user_permissions_table()`) — DDL dùng cú pháp SQLite-only
  (`INTEGER PRIMARY KEY AUTOINCREMENT`, `datetime('now')` làm DEFAULT). Ở Postgres, các
  bảng này đã được tạo trước qua `supabase/schema.sql` (áp 1 lần lúc set up dự án Supabase,
  KHÔNG lazy-create như SQLite) — mọi `_ensure_*_table()` đều gate CREATE TABLE (và
  `executescript()` — API RIÊNG của `sqlite3.Connection`, không tồn tại ở psycopg2, xem
  `core/excel_importer.py::_ensure_raw_tables()`) sau `if get_dialect() == "sqlite":`, chỉ
  `CREATE INDEX IF NOT EXISTS` chạy KHÔNG điều kiện (cú pháp giống hệt 2 dialect, vô hại nếu
  index đã có sẵn). Tương tự, `modules/dyeing/engines/manual_entry/routes.py::_ensure_columns()`
  dùng `rowid` (ngầm định riêng SQLite, KHÔNG tồn tại ở Postgres) để dọn dòng trùng lặp —
  toàn bộ hàm return sớm nếu dialect khác SQLite (Postgres không có dữ liệu cũ cần dọn).
- **`cursor.lastrowid`** không tồn tại ở psycopg2/Postgres — `core/database.py::execute_write()`
  (helper trung tâm) tự thêm `RETURNING id` vào câu INSERT khi dialect Postgres; 3 chỗ gọi
  `cursor.lastrowid` TRỰC TIẾP ngoài helper (`core/batch_importer.py`,
  `modules/dyeing/engines/excel_import/service.py` x2) đổi sang gọi
  `core/database.py::insert_returning_id(conn, sql, params)` — cùng cơ chế, dùng khi code
  đã có sẵn 1 `conn` riêng thay vì qua `execute_write()`.
- **`core/auth.py::init_app()`/`sync_permissions_command`** — 2 chỗ DUY NHẤT trong app mở
  connection kiểu "độc lập app context" (`get_raw_connection()` cũ, CHỈ SQLite) NHƯNG lại
  chạy trong luồng khởi động/CLI của app thật (không phải script rời như `init_db.py`) — đổi
  sang `core/database.py::get_raw_connection_for_app(app)` (mới), tự chọn `_PostgresConnCompat`
  hay SQLite raw connection theo `app.config["DATABASE_URL"]`. **Phân biệt rõ với
  `init_db.py`**: script đó CHỦ ĐÍCH chỉ dành cho SQLite cục bộ (seed/demo data cho local
  dev), Postgres/Supabase khởi tạo bằng `supabase/schema.sql` áp trực tiếp qua công cụ
  Supabase — KHÔNG chạy `init_db.py` nhắm vào Postgres.
- **`ON CONFLICT ... DO UPDATE SET`** — cú pháp giống hệt 2 dialect (SQLite mượn cú pháp
  này từ Postgres), KHÔNG cần sửa câu SQL — nhưng đã audit riêng cả 7 điểm dùng trong
  codebase để xác nhận từng UNIQUE constraint/index TARGET đều tồn tại đúng trong
  `supabase/schema.sql` (cú pháp giống nhau không tự động đảm bảo target tồn tại).
- **BUG THẬT phát hiện sau khi deploy thử lên Vercel (2026-09-11, sau lần verify đầu)**:
  `config.py::Config.ensure_directories()` (gọi TRỰC TIẾP trong `app.py::create_app()`, chạy
  ngay lúc MODULE IMPORT vì `app = create_app()` ở cuối `app.py` — nghĩa là chạy lại ở MỌI
  cold start trên Vercel) gọi `DATABASE_PATH.parent.mkdir()`/`UPLOAD_FOLDER.mkdir()`
  KHÔNG ĐIỀU KIỆN — thư mục code deploy trên Vercel là READ-ONLY (trừ `/tmp`), nên lệnh
  `mkdir()` này crash NGAY (`PermissionError: Read-only file system`) TRƯỚC KHI kịp chạm tới
  Postgres/SQLite gì cả — biểu hiện ra ngoài là "Serverless Function has crashed /
  FUNCTION_INVOCATION_FAILED" không kèm traceback rõ ràng. Đã sửa: `ensure_directories()`
  return sớm nếu `DATABASE_URL` có set (coi đó là tín hiệu "đang chạy môi trường
  managed/serverless, không cần tạo thư mục cục bộ") — xác nhận qua grep:
  **`UPLOAD_FOLDER` chưa từng được ghi file thực sự ở đâu trong codebase cả** (chỉ khai báo ở
  `config.py`, Excel Import dùng `tempfile.NamedTemporaryFile` — thư mục temp hệ thống, ghi
  được cả trên `/tmp` của Vercel — KHÔNG dùng `UPLOAD_FOLDER`), nên bỏ qua an toàn 100%.
  **Bài học quy trình**: khi 1 file chạy code ở MODULE IMPORT TIME (không phải trong route
  handler), MỌI side-effect ở đó (mkdir, connect DB, ...) chạy lại ở MỌI cold start của
  serverless — phải tự hỏi "dòng này có giả định filesystem ghi được không" trước khi coi
  scaffold Vercel là xong, không chỉ kiểm tra riêng tầng DB.
- **Row Level Security (RLS) — bật cho cả 15 bảng, KHÔNG kèm policy nào** (Supabase SQL
  Editor tự cảnh báo khi thiếu, đúng lúc áp `supabase/schema.sql` lần đầu). App KHÔNG dùng
  PostgREST/Supabase client SDK — kết nối THẲNG Postgres qua `DATABASE_URL`/psycopg2
  (`core/database.py`), role đó (thường là `postgres`, chủ sở hữu bảng vì tạo qua SQL
  Editor) KHÔNG bị RLS chặn (owner/BYPASSRLS luôn bypass mặc định) — bật RLS KHÔNG ảnh
  hưởng gì tới app thật. Lý do vẫn phải bật: MỌI project Supabase tự động có REST API công
  khai (`https://<project>.supabase.co/rest/v1/...`) gọi được bằng `anon` key ngay khi
  project tồn tại — không bật RLS thì bất kỳ ai có `anon` key (rò rỉ, dùng nhầm...) đọc/ghi
  được THẲNG mọi bảng, bỏ qua hoàn toàn hệ thống đăng nhập/phân quyền của `core/auth.py`.
  Bật RLS không kèm policy = "deny all" mặc định cho mọi role không phải owner — đúng ý vì
  app này không có nhu cầu cho ai truy cập trực tiếp qua PostgREST cả. Nếu SAU NÀY thật sự
  cần (vd 1 tính năng client-side gọi thẳng Supabase), phải thêm `CREATE POLICY` rõ ràng lúc
  đó — không mở sẵn "phòng khi cần".
- **Verify đã làm** (không có Postgres thật/Docker trong môi trường phát triển, nhưng verify
  được nhiều hơn dự kiến ban đầu nhờ cài được `psycopg2-binary` qua pip mà KHÔNG cần server
  thật): (1) toàn bộ 5 test suite (`tests/test_postgres_shim_translation.py` MỚI +
  `test_batch_matrix_formula.py`/`verify_rollup_parity.py`/`test_production_date.py`/
  `test_permission_model.py` cũ) PASS 100% ở chế độ SQLite mặc định — chứng minh dual-mode
  không đổi hành vi hiện có; (2) set thử `DATABASE_URL` giả (`postgresql://fake@localhost/fake`)
  xác nhận TOÀN BỘ chuỗi wiring chạy đúng tới tận lớp mạng — `get_dialect()` trả "postgres",
  `sql_datetime()`/`production_date_sql_expr()` sinh đúng cú pháp Postgres,
  `get_raw_connection_for_app()`/`_PostgresConnCompat.__init__()` thực sự gọi
  `psycopg2.connect()` và nhận đúng lỗi mạng (`OperationalError: Connection refused` — LỖI
  MẠNG, không phải lỗi code) — CHỈ CHƯA verify được: dữ liệu THẬT trả về đúng khi có Postgres
  sống thật (cần người dùng cung cấp `DATABASE_URL` Supabase thật để làm bước cuối này).
- File liên quan: `supabase/schema.sql` (bản dịch Postgres đầy đủ của `init_db.py::SCHEMA_SQL`,
  ghi rõ "REFERENCE ONLY — chưa được app thực thi" ở đầu file — là NGUỒN DUY NHẤT định nghĩa
  schema Postgres, KHÔNG lazy-create trùng lặp ở Python), `.env.example`, `vercel.json` +
  `api/index.py` (WSGI entrypoint cho Vercel Python runtime, chỉ import lại `app.py::app`,
  route MỌI request qua Flask kể cả `/static/*` — không tách static ra CDN riêng để tránh
  cấu hình chưa kiểm chứng được trên môi trường không có Vercel thật để test).

## 6. Excel Import Pipeline — HAI nhánh kiến trúc song song (quan trọng, dễ nhầm)
`core/excel_importer.py` có **2 cơ chế import khác nhau**, đừng nhầm lẫn:

1. **Schema-driven qua `ColumnSpec`/`ImportSchema`/`run_import()`** — dùng cho
   Telemetry/Downtime (`modules/dyeing/engines/excel_import/service.py`
   `SCHEMAS` dict, route `/api/import/<schema_key>`). **Route này KHÔNG được
   UI nào gọi tới hiện tại** (Modal Import trên Hub không có option chọn
   Telemetry/Downtime) — coi như dead code còn tồn tại, không xoá vì vẫn có
   thể dùng qua API trực tiếp.
2. **Signature-detect qua `detect_and_parse_file()`** — dùng THẬT SỰ cho
   Availability/Performance (qua `AVAILABILITY_COLUMNS`/`PERFORMANCE_COLUMNS`
   + `save_to_db()`) và Batch (qua `core/batch_importer.py::parse_batch_file()`
   + `sync_batch_details()`, KHÔNG dùng `detect_and_parse_file`'s nhánh BATCH
   nội bộ — nhánh đó chỉ dùng để auto-detect loại file khi preview). Modal
   Import trên Hub Nhuộm (`dyeing_hub.html`) gọi route chung
   `/dyeing/excel_import/api/import` (`import_selected_file()`), tự nhận diện
   loại file qua header hoặc dropdown `data_type`.

Cả 2 nhánh đều ghi lịch sử vào bảng `import_logs` dùng chung. Khi thêm cột
mới cho Availability/Performance, sửa `AVAILABILITY_COLUMNS`/`PERFORMANCE_COLUMNS`
trong `core/excel_importer.py` — KHÔNG phải `ImportSchema`.

### 6.1 Raw Data Viewer — lưu snapshot per-row để xem/sửa/xoá không cần re-upload
Bảng `import_log_rows` (`import_log_id`, `row_number`, `status` valid/invalid,
`error_message`, `row_data` JSON) lưu lại RAW DATA của từng dòng ở MỌI lần
import (Availability/Performance qua `record_import_rows()`, Batch qua
`sync_batch_details()`) — trước đây không có tầng lưu trữ này, mọi thứ mất
sau khi response HTTP gửi đi. `core/import_rows_service.py` cung cấp
`list_import_rows()`/`update_import_row()` (Inline Edit — revalidate bằng
đúng hàm `_parse_raw_row()`/`_parse_batch_row()` dùng chung với luồng import
hàng loạt, nếu hợp lệ thì tự UPSERT vào bảng đích)/`delete_import()` (xoá
theo `import_log_id`, đã thêm cột này vào cả `batch_details`). UI: Drawer
trượt phải (`raw_data_drawer.js`), mở từ nút "Kiểm tra Raw Data" sau khi
import xong.

### 6.2 Daily Rollup Pattern — tính trước theo ngày, đọc báo cáo không quét lại raw data
Vấn đề: Engine tính toán (downtime, batch_matrix, reports/cleaning_matrix) trước đây
tính TRỰC TIẾP trên `availability_logs` MỖI LẦN người dùng đổi filter → chậm dần khi
dữ liệu lịch sử tăng (`reports/cleaning_matrix` đo baseline thật ~28 giây/request do
JOIN `lower(trim(...))` không dùng được index — SCAN nested-loop 5402 x 6712 dòng).
Giải pháp: tính trước theo `production_date` (xem `core/production_time.py::get_production_date()`
— ca sản xuất cắt lúc 07:00 sáng, DÙNG CHUNG cho mọi Engine, KHÔNG viết tay biểu thức
`-7 hours` rải rác), lưu vào bảng summary riêng của từng Engine, đọc báo cáo chỉ SELECT
từ bảng đã tổng hợp sẵn.

- **`core/engine_base.py::BaseEngine.recompute_daily(production_date, conn)`** — method
  OPTIONAL (mặc định no-op), Engine nào cần rollup thì override. PHẢI idempotent: DELETE
  dòng cũ của đúng `production_date` rồi INSERT lại từ raw data — an toàn gọi lại nhiều
  lần cho cùng 1 ngày.
- **`core/rollup.py::trigger_recompute(affected_dates)`** — gọi `recompute_daily()` trên
  MỌI Engine đã auto-load (qua `core/engine_registry.py::discover_engines()`, dùng CHUNG
  với `graphify/mapper.py` — tránh 2 nơi tự quét pkgutil trùng lặp) cho từng ngày trong
  `affected_dates`. Gọi NGAY sau mỗi lần import Excel commit thành công
  (`excel_import/service.py::import_raw_file()`/`do_import()`, `core/batch_importer.py::
  sync_batch_details()`) — CHỈ truyền các production_date THỰC SỰ bị ảnh hưởng bởi batch
  dữ liệu vừa import (không bao giờ quét lại toàn bộ lịch sử mỗi lần import — đây là điểm
  mấu chốt giữ tốc độ import nhanh). Chạy ĐỒNG BỘ trong cùng request (dự án chưa có
  Celery/APScheduler, cố tình không thêm dependency mới cho việc này).
- **`flask rebuild-summaries`** (CLI, đăng ký qua `core/rollup.py::init_app()`) — backfill
  toàn bộ lịch sử 1 lần khi triển khai lần đầu, hoặc chạy lại bất cứ khi nào sửa công
  thức/logic tính toán.
- **Bài học lịch sử (COUNT DISTINCT) — KHÔNG còn áp dụng cho `batch_matrix` (xem mục
  "Mẫu số batch_matrix" bên dưới, mẫu số đã đổi hẳn công thức 2026-09-10), nhưng vẫn ĐÚNG
  như một nguyên tắc chung cho Engine khác**: metric dạng **COUNT DISTINCT** (số máy
  distinct, số batch distinct...) **KHÔNG được lưu sẵn dưới dạng số đếm rồi cộng dồn lên
  cấp gộp cao hơn** — cộng 2 số đếm distinct riêng biệt có thể đếm trùng nếu 2 tập nguồn
  giao nhau (VD: cùng 1 máy chạy nhiều Color Group/ngày — cộng machine_count riêng từng
  Color Group rồi gộp lên Fabric Type Total sẽ đếm trùng máy đó). Cách đúng: lưu summary ở
  GRAIN đủ chi tiết để giữ được DANH TÍNH (machine ID, batch ID...), dựng lại `set()` distinct
  ở ĐÚNG cấp gộp đang cần lúc đọc. Ngược lại, metric SUM/COUNT thường (giờ dừng máy, số
  dòng đạt chuẩn...) cộng dồn tuyến tính an toàn, lưu sẵn số đã cộng là được (xem
  `downtime/service.py::recompute_daily()`).
- **Mẫu số `batch_matrix` — ĐÃ ĐỔI CÔNG THỨC 3 LẦN, đọc kỹ trước khi sửa lần nữa**: tử số
  (đếm mẻ theo `(production_date, fabric_type, color_group, capacity_kg)`, mỗi mẻ nguyên
  vẹn 1 ngày theo EndTime cắt 7h sáng) CHƯA BAO GIỜ đổi qua cả 3 bản. Mẫu số đã qua:
    1. **Bản 1 (gốc)**: đếm số máy DISTINCT đã chạy — bug COUNT DISTINCT kinh điển (cộng
       machine_count riêng từng Color Group rồi gộp Fabric Total sẽ đếm trùng máy).
    2. **Bản 2 (2026-09-10, sáng)**: đổi sang "tổng giờ máy chạy thực tế/24", NHƯNG dùng
       CHUNG 1 số cho CẢ BẢNG theo `(production_date, capacity_kg)` — bảng riêng
       `batch_matrix_capacity_hours_daily`, không lọc theo fabric/color khi tính giờ. Đã bị
       PHÁT HIỆN RA VẤN ĐỀ qua audit thực tế: mức "co lại" so với Target cũ không đồng đều
       giữa các dòng Color Group (dấu hiệu mẫu số không phản ánh đúng máy nào thực sự liên
       quan đến từng dòng) — KHÔNG phải bug tính toán (đã audit số liệu thô xác nhận đúng
       công thức bản 2), nhưng người dùng quyết định ĐẢO NGƯỢC vì mẫu số "dùng chung toàn
       bảng" không phản ánh đúng bản chất nghiệp vụ (1 dòng Color Group chỉ nên bị ảnh
       hưởng bởi các máy THỰC SỰ chạy màu đó, không phải mọi máy cùng Capacity).
    3. **Bản 3 (2026-09-10, chiều — HIỆN TẠI)**: mẫu số = giờ hoạt động của ĐÚNG **TẬP MÁY**
       đã chạy các mẻ được đếm ở tử số của CHÍNH Ô ĐÓ (không phải toàn bảng theo Capacity+
       ngày nữa) — nhưng vẫn tính CẢ giờ mẻ khác màu/vải mà chính các máy này chạy hôm đó
       (không giới hạn theo ColorGroup/FabricType ở bước TÍNH GIỜ, chỉ giới hạn theo TẬP
       MÁY). Gộp `operating_hours` trở lại CÙNG bảng `batch_matrix_daily_summary`
       (production_date, fabric_type, color_group, capacity_kg, batch_count,
       operating_hours) — bảng `batch_matrix_capacity_hours_daily` của bản 2 đã XOÁ.
    - **RỦI RO ĐÚNG LOẠI COUNT DISTINCT, Ở "GIỜ" THAY VÌ "ĐẾM MÁY"**: TUYỆT ĐỐI KHÔNG cộng
      thẳng `operating_hours` của các dòng ColorGroup con để ra mẫu số Total(Fabric)/Grand
      Total — 1 máy chạy nhiều màu/ngày (rất phổ biến, verify thật: 80 trường hợp máy đa
      màu/ngày trong dữ liệu) sẽ bị CỘNG GIỜ NHIỀU LẦN nếu cộng thẳng. Cách đúng: `build_matrix()`
      PHẢI truy vấn lại raw data (`_raw_fabric_and_grand_machines()`) để lấy TẬP MÁY đã khử
      trùng (union qua mọi ColorGroup con thuộc Fabric đó / qua mọi Fabric+ColorGroup cho
      Grand Total), rồi tính giờ từ đúng tập đã khử trùng (`_machine_hours_by_day_for_range()`)
      — KHÔNG được suy ra từ `operating_hours` đã lưu sẵn theo từng ColorGroup. Ví dụ thật đã
      verify: máy D051 chạy cả Polyester/Dark lẫn Polyester/Medium ngày 2026-09-03 — cộng
      thẳng cho giá trị SAI 1.63, khử trùng đúng cho 1.75.
    - **Bài học phụ về LÀM TRÒN SỚM**: lúc đầu lưu `operating_hours` đã `round(..., 4)` trước
      khi ghi DB — phát hiện qua `tests/verify_rollup_parity.py` lệch ~0.2% ở 1 ca cực đoan
      (mẫu số chỉ ~79 giây, do mẻ kết thúc 1-2 phút sau mốc 7h sáng và máy không hoạt động gì
      thêm hôm đó — mẫu số cực nhỏ khiến sai số làm tròn bị khuếch đại rất lớn khi chia). Đã
      sửa: KHÔNG làm tròn `operating_hours` lúc lưu, chỉ làm tròn ở bước hiển thị cuối cùng
      (`cell_value`/`total_value`) — cùng nguyên tắc với bài học "không cộng dồn giá trị đã
      làm tròn sẵn" đã rút ra trước đó.
    - Verify: `tests/test_batch_matrix_formula.py` (3 kịch bản: ô đơn đối chiếu ví dụ số gốc,
      mẻ qua đêm tách đúng theo ranh giới 7h, VÀ máy chạy đa màu bẫy đúng lỗi cộng trùng —
      DB tạm file SQLite + Flask app context tạm, không đụng DB thật) +
      `tests/verify_rollup_parity.py` (`direct_build_matrix()`, đối chiếu công thức bản 3
      trên dữ liệu thật, PASS tuyệt đối mọi cell/Total/Grand Total).
    - **Tác động quy mô**: `batch_matrix_targets` hiện CHƯA có Target nào cấu hình (0 dòng)
      nên chưa ảnh hưởng thực tế qua cả 3 lần đổi — Target tương lai phải tính theo đúng
      thang đo bản 3 (khác hẳn bản 1 VÀ bản 2, không chỉ khác bản 1).
- Không phải mọi phép tính đều đáng để rollup: phần NÀO gây chậm thật sự (vòng lặp Python
  qua từng dòng raw, VD 9-category downtime hoặc JOIN+phân loại màu batch_matrix) mới cần
  bảng summary riêng; phần đã là SQL aggregate rẻ sẵn (SUM/COUNT DISTINCT có index, VD
  `valid_batches`/achievement của downtime) có thể giữ nguyên query trực tiếp trên raw data
  — không bắt buộc rollup 100% mọi chỉ số.
- **Ví dụ thêm: bảng "Data Quality" (đổi tên từ "Abnormal Point" 2026-09-11 — code/hàm
  vẫn giữ tên nội bộ `abnormal_point`/`ABNORMAL_POINT_*`, CHỈ label hiển thị UI đổi tên,
  xem `downtime/service.py::get_abnormal_point_pivot()`/`get_abnormal_point_batches()`)**
  — bảng pivot Day/Week/Month đếm mẻ có
  `load_hour`/`unload_hour` = 0 trên trang Downtime (cùng cấu trúc bảng "Downtime by
  category": cột ngoài cùng = tên chỉ số, cột phải = period). Đây là truy vấn ĐẾM theo
  filter+group_by (không phải số liệu gộp cố định theo ngày để tái dùng nhiều lần) nên
  KHÔNG áp Daily Rollup — query TRỰC TIẾP `availability_logs`, GROUP BY ngày ở SQL
  (SUM CASE WHEN = 0, an toàn cộng dồn tuyến tính vì là SUM không phải COUNT DISTINCT) rồi
  gộp lại Day/Week/Month ở Python — cùng kỹ thuật `_daily_planned_and_achievement()` đã
  dùng cho `planned_hours`/achievement. Ghi chú tên cột thật (đỡ phải dò lại):
  **`load_hour`** = giờ Loading, **`unload_hour`** = giờ Unloading trong
  `availability_logs` — CHÍNH LÀ 2 cột đã dùng cho category "Fabric loading"/"Fabric
  unloading" ở `CATEGORY_COLUMNS` (mục đầu file `downtime/service.py`), không viết
  tắt/không gộp lý do khác. **Loại mẻ FabricType không hợp lệ** (rỗng/"Unknow"/
  "Unknown"/"All", dùng CHUNG `INVALID_FABRIC_TYPES` đã áp dụng cho `valid_batches` —
  không định nghĩa tiêu chí riêng cho tính năng mới) theo yêu cầu người dùng: phần lớn mẻ
  "-WA"/cleaning có FabricType rỗng/"Unknow" và Loading/Unloading=0 mặc định, KHÔNG phải
  bất thường thật — loại ra làm số liệu giảm mạnh 923/1063 -> 49/189 (đúng ý nghĩa
  nghiệp vụ hơn). Danh sách chi tiết (khi bấm vào 1 ô) nhận thêm `period`+`group_by` để
  giới hạn đúng cột đã bấm (dùng lại `_period_date_range()` đã có sẵn cho Top-10-batch
  drill-down) và KHÔNG giới hạn LIMIT — nguyên tắc chung cho tính năng "double-check":
  con số đếm hiển thị PHẢI khớp tuyệt đối số dòng trả về ở API chi tiết, người dùng cần
  đối chiếu tay được.
- **Tái dùng modal đã có thay vì viết mới**: khi 1 trang đã có sẵn 1 overlay/modal cho
  tính năng drill-down (VD `#top-batches-overlay` của Downtime, dùng cho Top 10 batch
  theo category), tính năng drill-down MỚI THÊM trên CHÍNH trang đó nên tái dùng ĐÚNG DOM
  overlay/title/body sẵn có (chỉ thêm 1 hàm JS render nội dung khác), KHÔNG tạo thêm
  overlay/CSS/JS riêng — giữ trang gọn, tránh trùng lặp pattern (đã áp dụng cho
  "Abnormal Point").
- **Downtime Case Notes — annotation thủ công DÙNG CHUNG cho CẢ 2 danh sách drill-down
  của Engine `downtime`: "Downtime by Category" VÀ "Data Quality" (2026-09-11, đổi tên
  từ "Abnormal Point")**: bảng `downtime_case_notes` (`reason`, `detail`, `updated_by`,
  `updated_at`, `UNIQUE(availability_log_id)` — tối đa 1 note/mẻ, sửa lại thì UPSERT,
  KHÔNG lưu lịch sử nhiều phiên bản). **Khoá FK đã ĐỔI so với đề xuất ban đầu của người
  dùng** (`downtime_logs.id`) **sang `availability_logs.id`** — kiểm tra thực tế cả
  `get_top_batches_for_category()` LẪN `get_abnormal_point_batches()` đều lấy dữ liệu
  TRỰC TIẾP từ `availability_logs`, KHÔNG hề đụng `downtime_logs` (bảng đó rỗng, chưa
  nối vào pipeline thật). Route ghi (`POST /api/case-notes/<id>`) gate bằng
  `permission_required("dyeing", "downtime", "edit")` — xem ví dụ đầy đủ ở mục 10.
  **Lịch sử thiết kế quan trọng**: bản ĐẦU (khi mới làm xong "Downtime by Category")
  CỐ TÌNH tách riêng annotation này khỏi Reason/Detail của "Abnormal Point" (lúc đó vẫn
  đang auto-match TỪ `downtime_logs` qua điều kiện overlap thời gian, xem lịch sử ở
  `progress.md`) — nhưng auto-match đó gần như luôn "No log found" vì `downtime_logs`
  rỗng/chưa có dữ liệu thật. Người dùng dùng thử bản Case Notes trên "Downtime by
  Category", thấy ổn, rồi yêu cầu áp dụng "tương tự" cho Abnormal Point (đổi tên thành
  "Data Quality" luôn) — quyết định đúng lúc này là **XOÁ HẲN cơ chế auto-match
  `downtime_logs`** (`_attach_downtime_log_reasons()`, `_ensure_downtime_logs_detail_column()`,
  badge "No log found") và **DÙNG CHUNG** `_attach_case_notes()`/`downtime_case_notes`
  cho cả 2 danh sách — vì cả 2 đều khoá theo CÙNG `availability_logs.id`, 1 mẻ có thể
  xuất hiện ở CẢ 2 báo cáo (VD vừa Rework vừa Loading=0) nên annotation PHẢI là 1 nguồn
  duy nhất, không tách 2 bảng song song (sẽ lệch nhau nếu sửa từ 1 trong 2 chỗ). Cột
  `downtime_logs.detail` đã thêm trước đó (migration + `DOWNTIME_SCHEMA`) được GIỮ
  NGUYÊN dù không còn code nào đọc — vô hại, để dành nếu sau này `downtime_logs` được
  nối vào pipeline import thật. Verify: dựng app Flask ĐẦY ĐỦ trong SUBPROCESS trỏ DB
  TẠM (copy từ DB thật) — tạo note qua context "Data Quality", xác nhận note đó cũng đọc
  được y hệt qua `get_top_batches_for_category()` (chứng minh dùng chung 1 bảng, không
  phải 2 bảng đồng bộ ngầm).
- **BUG THẬT phát hiện + sửa (2026-09-12): note bị "dùng chung nhầm" giữa các category/
  field khác nhau của CÙNG 1 mẻ.** Thiết kế ban đầu ở trên (`UNIQUE(availability_log_id)`)
  có lỗ hổng: 1 mẻ (`availability_log_id`) thường xuất hiện ở NHIỀU category khác nhau
  trong "Downtime by Category" (vd 1 mẻ vừa có giờ Rework vừa có giờ Color Adjustment)
  hoặc cả 2 field của "Data Quality" (loading/unloading) — vì chỉ khoá theo
  `availability_log_id`, sửa Reason/Detail ở 1 category làm lộ/đổi luôn note đó ở MỌI
  category/field khác của cùng mẻ (người dùng report: "bấm vào category này lại xuất
  hiện reason/detail của category kia"). Đã sửa bằng cách thêm cột `context` (giá trị =
  tên category trong `CATEGORIES` khi ghi từ "Downtime by Category", hoặc "loading"/
  "unloading" khi ghi từ "Data Quality") và đổi khoá thành
  `UNIQUE(availability_log_id, context)` — mỗi (mẻ, category/field) giờ có note ĐỘC LẬP.
  - **Tương thích ngược với 27 note thật đã có trên Supabase production**: note CŨ (tạo
    trước khi có `context`) được gán `context=''` và dùng làm FALLBACK hiển thị cho MỌI
    category/field CHƯA có note riêng của đúng mẻ đó (`_attach_case_notes()` query
    `WHERE context IN (?, '')` rồi ưu tiên đúng context nếu có) — KHÔNG mất dữ liệu, chỉ
    "tách dần" khi người dùng sửa lại theo từng category cụ thể (lần sửa đó ghi thành 1
    dòng MỚI với context riêng, KHÔNG ghi đè dòng context='').
  - **SQLite** (`_migrate_case_notes_context_column()`, gọi lazy trong
    `_ensure_case_notes_table()`): không thể ALTER đổi UNIQUE constraint tại chỗ -> dựng
    lại bảng (RENAME bảng cũ, CREATE bảng mới đúng schema, INSERT copy dữ liệu với
    context='', DROP bảng cũ) — **BUG PHỤ đã bắt được lúc viết test**: thiếu
    `conn.commit()` sau bước copy khiến transaction treo, dữ liệu cũ "biến mất" với mọi
    connection khác cho tới khi có commit tình cờ khác — đã thêm `conn.commit()` tường
    minh cuối hàm migrate.
  - **Postgres (production)**: app KHÔNG có quyền tự ALTER TABLE theo quy ước dự án (mục
    5.1) — đã viết `supabase/migrate_case_notes_context.sql` (idempotent, có `begin`/
    `commit`) để người dùng tự chạy 1 lần qua Supabase SQL Editor trên DB thật (thêm cột
    `context` default `''`, drop constraint `UNIQUE(availability_log_id)` cũ, tạo lại
    `UNIQUE(availability_log_id, context)`) — **CHƯA CHẠY**, xem `activeContext.md` mục
    "Việc tiếp theo". `supabase/schema.sql` đã cập nhật định nghĩa bảng cho lần cài mới
    (không tự áp dụng ngược cho DB production đã tồn tại).
  - Route `POST /api/case-notes/<id>` giờ BẮT BUỘC nhận thêm `context` trong JSON body
    (400 nếu thiếu) — `upsert_case_note(availability_log_id, context, reason, detail,
    user_id)`. Frontend (`downtime.js`): biến `activeCaseContext` set = category lúc mở
    modal Top-10-by-category (`openTopBatches()`), hoặc = field lúc mở modal Data Quality
    (`openAbnormalPointBatches()`), gửi kèm mỗi lần `saveCaseNote()`.
  - Verify: `tests/test_downtime_case_notes_context.py` (DB tạm SQLite mô phỏng ĐÚNG
    schema cũ có sẵn 1 note thật, để code tự lazy-migrate — không giả định) — 7 case PASS:
    migrate giữ nguyên note cũ, fallback đúng, ghi note category A không đụng category B
    (cả note cũ context='' lẫn note context khác đã ghi trước), tổng số dòng đúng (không
    ghi đè nhầm qua sai `ON CONFLICT` target).
- **Biến thể "cache chi tiết từng dòng" (`reports/cleaning_matrix.py`) — KHÁC
  downtime/batch_matrix**: Cleaning MC hiển thị CHI TIẾT TỪNG MẺ theo trình tự
  (chuỗi badge/máy/ngày + đầy đủ record từng mẻ), không phải số liệu đã gộp —
  nên KHÔNG áp dụng được kiểu rollup đếm sẵn (count) như downtime/batch_matrix.
  Bài học rút ra qua khảo sát thật trước khi code (đúng quy trình "phát hiện bất
  thường thì hỏi trước khi tự quyết định cấu trúc bảng"): khi Engine cần giữ
  DANH SÁCH chi tiết (không chỉ con số tổng hợp), thiết kế `<engine>_daily_summary`
  ở GRAIN 1 DÒNG = 1 BẢN GHI NGUỒN (khoá `(production_date, <raw_row_id>)`, ở đây
  là `availability_logs.id`), lưu sẵn KẾT QUẢ đã tính tốn kém (ở đây là
  `classify_batch_badge()` 5 bước + JOIN 3 bảng) ngay trong `recompute_daily()`,
  đọc báo cáo chỉ SELECT + dựng lại cấu trúc Python y hệt bản cũ — tức là
  "cache kết quả tính toán tốn kém", không phải "gộp số liệu". Đồng thời, nếu
  nguyên nhân chậm thật sự là JOIN thiếu index (không phải chỉ do tính lại mỗi
  lần đọc), PHẢI sửa cả 2: thêm expression index
  `CREATE INDEX ... ON table (LOWER(TRIM(col)))` cho đúng điều kiện JOIN đang
  dùng (đo thực tế `reports/cleaning_matrix`: 436ms → 3ms, 145 lần cho
  `recompute_daily()` một ngày) — rollup và index không loại trừ nhau, đây là
  2 fix bổ sung cho 2 nguyên nhân khác nhau.
- **Bài học quan trọng: `get_production_date()`/`PRODUCTION_DATE_SQL_EXPR` PHẢI
  luôn nhận EndTime cho dữ liệu dạng batch (có cả StartTime lẫn EndTime), KHÔNG
  bao giờ nhận StartTime làm nguồn chính** — một mẻ được tính vào "ngày sản
  xuất" theo lúc nó KẾT THÚC, không phải lúc bắt đầu (StartTime chỉ dùng làm
  fallback khi EndTime NULL/mẻ chưa xong). Bug thật đã phát hiện (2026-09-10,
  báo cáo Cleaning MC hiển thị nhầm ngày mẻ C260638611): rà soát kỹ TOÀN BỘ
  backend (mọi nơi gọi `get_production_date()`/`PRODUCTION_DATE_SQL_EXPR` trong
  `.py`, gồm `core/rollup.py`, `core/batch_importer.py`, `downtime/service.py`,
  `batch_matrix/service.py`, `reports/cleaning_matrix.py`, `excel_import/
  service.py`) đều ĐÃ ưu tiên EndTime đúng — dữ liệu lưu trong
  `cleaning_mc_daily_summary`/cột `availability_logs.production_date` hoàn
  toàn đúng. **Bug thật nằm ở tầng KHÁC hẳn mà lần rà soát `.py` đầu tiên bỏ
  sót: JS inline trong `<script>` của template** (`reports/templates/
  cleaning_matrix_view.html`) — dòng render bảng lấy lại
  `batch.start_time.slice(0, 10) === day` để quyết định mẻ thuộc cột-ngày nào,
  BỎ QUA hoàn toàn `production_date` đã tính đúng ở backend. Đo thực tế:
  1004/5402 mẻ (18.6%) — mọi mẻ chạy qua đêm — bị hiển thị sai cột ngày dù
  dữ liệu gốc đã đúng. **Bài học quy trình**: khi rà soát bug "tính sai theo
  ngày/giờ", PHẢI grep CẢ file `.html` (script inline trong template, không
  chỉ `.py`/`.js` độc lập) — 1 Engine có thể tính đúng 100% ở backend nhưng
  vẫn hiển thị sai nếu tầng render tự suy luận lại ngày từ trường thô
  (`start_time`) thay vì dùng field `production_date` server đã trả sẵn. Đã
  sửa: `get_cleaning_matrix()` giờ trả thêm field `production_date` trong mỗi
  phần tử `item["batches"]`, JS đổi điều kiện lọc sang `batch.production_date
  === day`. Đồng thời tiện thể dọn 1 chỗ trùng lặp logic phát hiện được khi
  rà soát (không phải bug, nhưng đúng rủi ro tương tự): `core/excel_importer.py::
  calculate_production_date()` từng tự viết lại công thức cắt ca 07:00 riêng
  thay vì gọi `get_production_date()` — đã refactor để chỉ ép kiểu rồi
  delegate, tránh 2 nơi lệch nhau nếu sau này chỉ sửa 1 chỗ. Unit test:
  `tests/test_production_date.py` (chạy `python tests/test_production_date.py`,
  không dùng pytest theo đúng chủ trương dependency tối giản) — assert mẻ qua
  đêm PHẢI lấy production_date theo EndTime.

### 6.3 Downtime "Total Valid Batches" vs Cleaning MC "Normal Dyeing" — KHÁC số theo THIẾT KẾ, không phải bug (2026-09-11)
Người dùng phát hiện cùng filter (capacity 500/600/1200/2400, 1 khoảng ngày) ra 2 số khác
nhau: Downtime 389 mẻ, Cleaning MC "Normal Dyeing" 308 mẻ, và ĐÃ xác nhận 389 đúng (dùng
Downtime làm ground truth). Điều tra đầy đủ (đối chiếu batch ID thật, không suy đoán) kết
luận: **KHÔNG có bug** — 2 số đo 2 khái niệm khác nhau, chênh lệch 81 mẻ giải thích ĐỦ
100% bằng 2 nguyên nhân cộng dồn:

1. **Cleaning MC "Normal Dyeing" cố ý loại Rework khỏi số đếm** (+88 mẻ): trong dữ liệu
   mẫu, 397 dòng có FabricType hợp lệ tách thành 308 NORMAL-badge + 89 REWORK-badge.
   Downtime "Total Valid Batches" tính CẢ HAI (không phân biệt rework), Cleaning MC tách
   riêng 3 nhóm KPI (Normal/Cleaning/Rework) — "Normal Dyeing" CHỈ là 1 trong 3 nhóm đó,
   không phải "tổng số mẻ".
2. **Cleaning MC đếm theo DÒNG lịch máy (schedule slot), Downtime đếm DISTINCT batch
   code** (−7 mẻ): 1 mã batch chạy lại trong CHÍNH khoảng ngày filter (VD máy chạy lại
   ngay batch đó, hoặc mẻ qua đêm rơi vào 2 production_date liên tiếp) — Cleaning MC ĐÚNG
   khi đếm cả 2 lần (đây là 2 slot lịch máy thật, ma trận scheduling cần hiển thị cả 2),
   Downtime đếm distinct để không tính 1 mẻ thành "2 mẻ hợp lệ" khi ước lượng sản lượng.
   Dữ liệu mẫu: 7 mã batch bị đếm dư kiểu này trong nhóm Normal (308 dòng -> 301 mã
   distinct).
   
   `389 (Downtime) − 308 (Cleaning MC Normal) = 81 = 88 (Rework bị loại) − 7 (dedup theo
   dòng khác biệt)` — khớp CHÍNH XÁC, không còn phần nào chưa rõ nguyên nhân.

**Đã loại trừ hoàn toàn (verify bằng số liệu thật, không phải chỉ đọc code):**
- Production-date (StartTime/EndTime, cắt 7h sáng): CẢ HAI dùng chung
  `COALESCE(end_time, start_time)` + `PRODUCTION_DATE_SQL_EXPR` — population thô chỉ lọc
  capacity+ngày (426 dòng) khớp CHÍNH XÁC tổng `normal+cleaning+rework` của Cleaning MC.
- Capacity mapping qua bảng `machines`: bảng này hiện **RỖNG HOÀN TOÀN 0 dòng** (hệ quả
  đợt xoá mockup DY-01..05 trước đó) — `configured_capacity_kg` ở Cleaning MC LUÔN
  fallback về `a.capacity_kg` (giống Downtime) cho MỌI dòng, không có máy nào bị mất
  mapping riêng lẻ. **Cảnh báo cho tương lai**: nếu sau này nạp lại `machines` với dữ
  liệu capacity thật (khác `availability_logs.capacity_kg` cho vài máy), 2 báo cáo CÓ
  THỂ lệch nhau vì lý do này — hiện tại thì không, vì bảng đang rỗng.
- FabricType không hợp lệ ("Unknow"/rỗng): 2 CƠ CHẾ loại khác nhau (Downtime lọc trực
  tiếp theo cột `fabric_type`; Cleaning MC loại gián tiếp qua badge "CM" khi dyelot chứa
  "-WA") nhưng **verify thật cho thấy 2 cơ chế trùng khớp 100%** trong dữ liệu hiện có —
  toàn bộ 29 dòng FabricType không hợp lệ ĐỀU là mẻ CM ("-WA"), không có dòng CM nào có
  FabricType hợp lệ và ngược lại. Đây là sự trùng khớp dữ liệu thực tế, KHÔNG phải ràng
  buộc code đảm bảo — nếu sau này có mẻ CM với FabricType hợp lệ (hoặc mẻ dyeing thật bị
  thiếu FabricType), 2 số MỚI bắt đầu lệch vì lý do khác ngoài Rework/dedup.
- Biên ngày lọc (>= vs >, string vs date) và multi-select Capacity `IN (...)`: verify ở
  cả tầng service VÀ tầng route (`test_client` gọi trực tiếp `/api/summary` và
  `/api/cleaning-matrix` với 4 capacity) — số liệu khớp tuyệt đối, không có lỗi cắt biên
  hay lỗi chỉ lọc được 1 giá trị.

**Nguyên tắc rút ra cho Engine mới sau này**: khi 2 báo cáo cùng dùng `availability_logs`
làm nguồn nhưng hiển thị số "batch" khác nhau, KHÔNG vội cho là bug — kiểm tra trước:
(1) 1 bên có đang lọc bớt theo business rule riêng không (rework/cleaning/badge...)? (2) 1
bên đếm DISTINCT, 1 bên đếm ROW không? Nếu có, đó là 2 KPI khác nhau về ĐỊNH NGHĨA, không
phải lỗi tính toán — cần làm rõ với người dùng tên/ý nghĩa từng KPI thay vì tự sửa để "ép"
2 số khớp nhau.

## 7. Navigation Registry + Context Processor
`core/navigation.py::nav_registry` là registry toàn cục. Mỗi Domain tự
`register_menu(...)` khi được auto-load. `app.context_processor` bơm biến
`NAV_MENU` vào MỌI template — View không cần tự truyền. Lọc menu qua 2 TẦNG:
(1) `NavigationRegistry.for_role(role)` — lọc theo `NavItem.roles` (vd Graphify/
"Quản lý tài khoản" chỉ `roles=("admin",)`); (2) với `role='operator'`, lọc
THÊM lần nữa theo Permission Model (mục 10) — xem `_filter_by_permission()`.
admin KHÔNG bị lọc ở tầng (2), luôn thấy toàn bộ menu đã qua tầng (1).

## 8. Graphify — Introspection Pattern
`graphify/mapper.py` KHÔNG lưu trữ graph tĩnh — nó quét động (dynamic
introspection) `EngineMetadata` của mọi Engine đã cài đặt mỗi khi API
`/graphify/api/graph` được gọi. Vì vậy sơ đồ luôn phản ánh đúng trạng thái
hệ thống hiện tại, kể cả sau khi thêm Engine mới. Logic quét pkgutil thực tế
nằm ở `core/engine_registry.py::discover_engines()` (trả về instance
`BaseEngine`, không chỉ metadata) — dùng CHUNG với `core/rollup.py` (mục 6.2),
tránh 2 nơi tự quét trùng lặp.

## 9. Quy ước đặt tên Blueprint & Endpoint
- Tên Blueprint = tên thư mục Engine (vd `oee`, `downtime`).
- Endpoint đầy đủ = `<domain>.<engine>.<view_func>` (vd `dyeing.oee.view`,
  `dyeing.oee.api_calculate`) nhờ cơ chế Nested Blueprint của Flask.

## 10. Permission Model — phân quyền Xem/Sửa/Xoá theo TỪNG ENGINE (2026-09-10)
Bổ sung tầng phân quyền chi tiết hơn role nhị phân cũ (admin/operator) — operator giờ
được cấp quyền RIÊNG CHO TỪNG ENGINE (không phải cả domain gộp), admin luôn superuser
cố định.

- **Bảng `user_permissions`** (`user_id, domain, engine_name, can_view, can_edit,
  can_delete`, UNIQUE(user_id, domain, engine_name), FK `user_id -> users.id ON DELETE
  CASCADE` — CASCADE chỉ thực sự chạy trên connection có `PRAGMA foreign_keys=ON`, ứng
  dụng đã bật qua `config.SQLITE_PRAGMAS`, nhưng script dọn dữ liệu thủ công bằng
  `sqlite3.connect()` trần PHẢI tự bật lại pragma này nếu muốn cascade hoạt động). Tạo tự
  động lúc app khởi động qua `core/auth.py::ensure_user_permissions_table()` (gọi từ
  `auth.init_app(app)`) — AN TOÀN trên DB thật đã có dữ liệu, không cần `init_db.py --reset`.
- **admin luôn superuser cố định, KHÔNG đi qua bảng này** — `has_permission()` không được
  gọi cho admin; `permission_required()`/`current_user_can()` return True ngay khi
  `role=='admin'`, tránh 1) tự khoá nhầm chính mình qua UI quản lý tài khoản, 2) query DB
  không cần thiết.
- **`core/auth.py::permission_required(domain, engine_name, action)`** — decorator gate
  route theo đúng 1 (domain, engine_name, action∈{'view','edit','delete'}); chưa đăng
  nhập -> redirect login; operator không đủ quyền -> flash lỗi + redirect Hub ĐÚNG domain
  đó (KHÔNG phải dashboard chung, để user biết đang ở đâu) — route KHÔNG BAO GIỜ trả JSON
  dữ liệu thật khi bị chặn (verify bằng `tests/test_permission_model.py`: content-type
  redirect, không phải JSON).
- **Danh sách (domain, engine_name) lấy ĐỘNG từ `core/engine_registry.py::
  discover_engines()`** ở MỌI nơi cần (route gate, form phân quyền, `sync-permissions`)
  — KHÔNG hardcode danh sách Engine ở bất kỳ đâu, đúng nguyên tắc Auto-loader.
- **Phân loại action theo route hiện có** (đã audit toàn bộ, không suy đoán; cập nhật
  2026-09-11 sau khi `dyeing.downtime` có route ghi thật đầu tiên):
  - CHỈ có `view` (không có chức năng sửa/xoá thật để gate): `dyeing.oee`, `knitting.oee`.
  - Có `view` + `edit` (không có route xoá): `dyeing.batch_matrix` (POST `/api/targets`
    = edit), `dyeing.manual_entry` (lưu mẻ nhập tay = edit), `dyeing.reports` (import
    Batch Detail = edit), **`dyeing.downtime`** (POST `/api/case-notes/<id>` — lưu
    annotation Reason/Detail thủ công cho 1 mẻ trong danh sách drill-down "Downtime by
    Category" = edit; mọi route đọc khác của Engine này vẫn chỉ `view`, xem mục 6.2 phần
    "Downtime Case Notes").
  - Có đủ `view`+`edit`+`delete`: `dyeing.excel_import` — "import" (ghi dữ liệu mới) tính
    là `edit` (không phải delete); `PATCH .../rows/<id>` (sửa 1 dòng) = edit; `DELETE
    .../import-logs/<id>` = delete; template/preview/history = view.
- **Ví dụ áp dụng `permission_required` cho 1 route GHI DỮ LIỆU THẬT mới thêm sau khi
  Permission Model đã tồn tại** (`downtime/routes.py::api_upsert_case_note`, xem mục 6.2):
  chỉ cần gắn `@permission_required("dyeing", "downtime", "edit")` — KHÔNG viết decorator/
  kiểm tra quyền riêng. Với UI: ẩn hẳn control chỉnh sửa (không chỉ chặn backend) bằng
  cách bơm `current_user_can('dyeing', 'downtime', 'edit')` (đã có sẵn trong MỌI template
  qua `context_processor` ở `core/navigation.py::inject_nav_menu()`, không cần import gì
  thêm) vào 1 biến JS (`window.DOWNTIME_CAN_EDIT_NOTES`) rồi kiểm tra ở tầng render —
  user KHÔNG có quyền edit vẫn ĐỌC được dữ liệu qua API (route đó vẫn chỉ gate ở "view"),
  chỉ route GHI mới cần "edit". Verify đầy đủ 2 chiều (không chỉ ẩn UI): dựng app Flask
  ĐẦY ĐỦ trong SUBPROCESS trỏ DB TẠM (copy từ DB thật, cùng pattern
  `tests/test_permission_model.py`) — operator CHỈ có `view` gọi thẳng route ghi qua API
  vẫn bị chặn (302 redirect, KHÔNG trả JSON, dữ liệu trong DB KHÔNG đổi); operator có
  thêm `edit` thì ghi được, `updated_by` phản ánh đúng username người sửa.
- **`NavItem.domain`/`NavItem.engine_name`** (mới, optional) — CHỈ set cho mục con ứng
  đúng 1 Engine (gán tại nơi mỗi Domain `__init__.py::register()` build `children` từ
  `engines_loaded`, vốn đã có sẵn `e.domain`/`e.name`). Mục cha Domain/mục không gắn
  Engine nào (vd "Quản lý tài khoản") để `None` — không bị lọc theo Permission Model, chỉ
  lọc theo `roles` như trước. `core/navigation.py::_filter_by_permission()` (chỉ chạy cho
  role='operator'): ẩn mục cha Domain nếu KHÔNG còn Engine con nào hiển thị sau lọc.
- **Blueprint `admin/`** (KHÔNG dưới `modules/` — không phải Domain nghiệp vụ, không có
  Engine con, đăng ký trực tiếp trong `app.py::create_app()` như `auth`/`dashboard`/
  `graphify`) — `/admin/accounts` (danh sách), `/admin/accounts/new` (tạo, redirect sang
  trang gán quyền ngay nếu role=operator — UX 1 luồng), `/admin/accounts/<id>/permissions`
  (ma trận quyền, liệt kê ĐỘNG qua `discover_engines()`; nếu account đang xem role=admin
  chỉ hiện thông báo, KHÔNG cho sửa).
- **`flask sync-permissions [--yes]`** (`core/auth.py::sync_permissions_command`) — backfill
  quyền cho user operator ĐÃ TỒN TẠI TỪ TRƯỚC khi tính năng này ra đời (mặc định
  `can_view=1` cho MỌI Engine, giữ hành vi không đổi đột ngột so với role nhị phân cũ);
  user operator TẠO MỚI sau khi có tính năng không cần lệnh này (mặc định KHÔNG có quyền
  gì, an toàn hơn — admin phải chủ động gán). **CHECKPOINT BẮT BUỘC**: luôn in bảng dự
  kiến rồi DỪNG, KHÔNG ghi gì vào DB nếu thiếu `--yes` — đã verify hành vi này, KHÔNG tự
  chạy `--yes` lên DB thật khi chưa có xác nhận rõ ràng của người dùng (tài khoản
  `operator` demo hiện có 0 dòng quyền — sidebar rỗng, mọi Engine bị chặn — cho tới khi
  admin chạy lệnh này hoặc gán tay qua UI).
- Verify: `tests/test_permission_model.py` (dựng app Flask ĐẦY ĐỦ qua `create_app()`
  trong SUBPROCESS riêng trỏ DB tạm — app.py có Blueprint cấp module nên gọi `create_app()`
  2 lần trong CÙNG process sẽ crash, phải tách subprocess) — 28 case: sidebar operator chỉ
  hiện đúng Engine được cấp quyền, mọi URL/API khác bị chặn không lộ JSON, action edit bị
  chặn riêng biệt với view, admin hoàn toàn không bị ảnh hưởng.
