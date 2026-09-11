"""
tests/test_permission_model.py
---------------------------------
Kiểm thử end-to-end tính năng Phân quyền theo Engine (bảng `user_permissions`) — dựng app
Flask ĐẦY ĐỦ (`create_app()`, mọi Blueprint/Engine thật) trỏ vào DB TẠM (file SQLite riêng,
KHÔNG đụng DB thật), verify:
  1. Operator được admin cấp CHỈ can_view=1 cho `dyeing.oee`: sidebar CHỈ hiện đúng 1 mục,
     mọi URL Engine khác (cả trang View lẫn API) đều bị chặn (redirect 302 về Hub đúng
     domain, KHÔNG trả JSON lộ dữ liệu).
  2. Action 'edit' bị chặn RIÊNG (không chỉ 'view') khi chưa được cấp `can_edit`.
  3. admin KHÔNG bị ảnh hưởng gì — vẫn thấy/thao tác được mọi Engine + trang Quản lý tài
     khoản như trước khi có tính năng phân quyền.

LƯU Ý KỸ THUẬT: `app.py` tạo Blueprint ở cấp MODULE (vd `dyeing_bp`) — gọi `create_app()`
2 LẦN trong CÙNG 1 process sẽ crash ("blueprint đã được đăng ký"). Vì vậy script này CHỈ
gọi `create_app()` ĐÚNG 1 LẦN, trong 1 SUBPROCESS riêng (biến môi trường `DATABASE_PATH`
trỏ vào DB tạm TRƯỚC khi `app.py` được import) — tách biệt hoàn toàn khỏi process gọi
`python tests/test_permission_model.py` ban đầu.

Chạy: python tests/test_permission_model.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_ENV_MARKER = "PERMISSION_TEST_DB_PATH"


def _check(label: str, actual: object, expected: object, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _run_inner_test() -> int:
    """Chạy TRONG subprocess con — DATABASE_PATH đã trỏ vào DB tạm qua biến môi trường
    TRƯỚC khi import app.py, nên `create_app()` (chạy 1 lần duy nhất ở cuối app.py) sẽ mở
    đúng DB tạm này."""
    failures: list[str] = []
    import app as app_module  # noqa: PLC0415 — import trong hàm để trì hoãn tới khi env đã set

    client = app_module.app.test_client()

    # --- Admin tạo tài khoản operator test + gán quyền CHỈ view=1 cho dyeing.oee ---
    client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    r = client.post(
        "/admin/accounts/new",
        data={"username": "perm_test_op", "full_name": "Permission Test", "password": "test123456", "role": "operator"},
    )
    match = re.search(r"/admin/accounts/(\d+)/permissions", r.headers.get("Location", ""))
    _check("Tạo operator -> redirect sang trang gán quyền", bool(match), True, failures)
    user_id = int(match.group(1)) if match else None

    client.post(f"/admin/accounts/{user_id}/permissions", data={"view__dyeing__oee": "on"})
    client.get("/logout")

    # --- Đăng nhập bằng operator test, kiểm tra sidebar + chặn URL ---
    client.post("/login", data={"username": "perm_test_op", "password": "test123456"}, follow_redirects=True)

    r = client.get("/")
    html = r.get_data(as_text=True)
    links = re.findall(r'sidebar-link-child[^>]*>\s*<a href="([^"]+)"', html)
    _check("Sidebar operator CHỈ hiện đúng 1 mục dyeing.oee", links, ["/dyeing/oee/"], failures)

    r = client.get("/dyeing/oee/")
    _check("dyeing.oee (CÓ quyền view) -> 200", r.status_code, 200, failures)
    r = client.get("/dyeing/oee/api/calculate")
    _check("dyeing.oee API (CÓ quyền view) -> 200", r.status_code, 200, failures)

    blocked_pages = (
        "/dyeing/downtime/", "/dyeing/batch_matrix/", "/dyeing/reports/cleaning-matrix",
        "/dyeing/manual_entry/", "/knitting/oee/",
    )
    for path in blocked_pages:
        r = client.get(path, follow_redirects=False)
        _check(f"{path} (KHÔNG có quyền) -> 302 (chặn)", r.status_code, 302, failures)

    blocked_apis = (
        "/dyeing/downtime/api/summary", "/dyeing/batch_matrix/api/matrix",
        "/dyeing/reports/api/cleaning-matrix", "/dyeing/excel_import/api/history",
    )
    for path in blocked_apis:
        r = client.get(path, follow_redirects=False)
        _check(f"{path} (API, KHÔNG có quyền) -> 302, KHÔNG lộ JSON", r.status_code, 302, failures)
        leaks_json = bool(r.content_type and "json" in r.content_type)
        _check(f"{path} -> content_type KHÔNG phải JSON (không lộ dữ liệu)", leaks_json, False, failures)

    r = client.post(
        "/dyeing/batch_matrix/api/targets",
        json={"fabric_type": "CVC", "color_group": "Black", "target_value": 5},
        follow_redirects=False,
    )
    _check("POST batch_matrix/api/targets (chưa có quyền edit) -> 302 (chặn action edit riêng)", r.status_code, 302, failures)

    client.get("/logout")

    # --- Đăng nhập lại admin — xác nhận KHÔNG bị ảnh hưởng ---
    client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    admin_pages = (
        "/dyeing/", "/dyeing/oee/", "/dyeing/downtime/", "/dyeing/batch_matrix/",
        "/dyeing/reports/cleaning-matrix", "/dyeing/manual_entry/", "/knitting/oee/",
        "/graphify/", "/admin/accounts",
    )
    for path in admin_pages:
        r = client.get(path)
        _check(f"admin: {path} -> 200 (không đổi so với trước)", r.status_code, 200, failures)

    r = client.get("/")
    html = r.get_data(as_text=True)
    links = re.findall(r'sidebar-link-child[^>]*>\s*<a href="([^"]+)"', html)
    _check("admin: sidebar vẫn thấy ĐẦY ĐỦ mọi Engine (>=6 mục)", len(links) >= 6, True, failures)
    _check("admin: có mục 'Account Management'", "Account Management" in html, True, failures)

    print(f"\n{'=' * 60}\nKẾT QUẢ (subprocess): {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'=' * 60}")
    return 1 if failures else 0


def main() -> int:
    if os.environ.get(_ENV_MARKER):
        # Đang chạy TRONG subprocess con (DATABASE_PATH đã được set trước khi import app).
        return _run_inner_test()

    # --- Process cha: dựng DB tạm rồi gọi lại chính script này trong 1 subprocess riêng ---
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import Config  # noqa: E402
    import init_db  # noqa: E402

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = init_db.get_raw_connection(Path(db_path), Config.SQLITE_PRAGMAS)
        init_db.create_schema(conn)
        init_db.seed_users(conn)
        conn.close()

        env = dict(os.environ)
        env["DATABASE_PATH"] = db_path
        env[_ENV_MARKER] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            env=env, capture_output=True, text=True, encoding="utf-8",
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
