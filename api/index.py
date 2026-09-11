"""
api/index.py
------------
WSGI entrypoint cho Vercel Python runtime (`@vercel/python`) — Vercel tự nhận diện
biến `app` (Flask WSGI callable) trong file này khi build theo `vercel.json` ở
thư mục gốc.

KHÔNG đặt logic gì ở đây — chỉ import lại đúng `app` đã được `create_app()` khởi
tạo trong `app.py` (nguồn duy nhất, dùng chung với `flask run`/dev server cục bộ).
"""
from app import app  # noqa: F401
