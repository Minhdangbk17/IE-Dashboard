"""
admin/
------
Blueprint "Quản lý tài khoản" — KHÔNG phải Domain nghiệp vụ (không có Engine con), nên
đăng ký trực tiếp trong `app.py::create_app()` (giống `auth`/`dashboard`/`graphify`),
KHÔNG đặt trong `modules/` để tránh Auto-loader hiểu nhầm đây là Domain sản xuất.
"""
