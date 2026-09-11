"""
seed_supabase_users.py
-----------------------
Seed tài khoản admin/operator đầu tiên vào Postgres/Supabase — CHẠY THỦ CÔNG 1 LẦN
sau khi đã áp `supabase/schema.sql`, TRƯỚC lần deploy Vercel đầu tiên (hoặc bất cứ
lúc nào cần thêm tài khoản gốc). `supabase/schema.sql` CHỈ tạo bảng (DDL), KHÔNG seed
dữ liệu mẫu như `init_db.py` làm cho SQLite — nếu không chạy script này, bảng `users`
trên Supabase sẽ trống và KHÔNG ai đăng nhập được.

Dùng lại ĐÚNG `core/auth.py::hash_password()` (SHA-256 + salt = SECRET_KEY) để hash
mật khẩu khớp CHÍNH XÁC với logic app dùng lúc verify lúc đăng nhập — vì vậy PHẢI
chạy script này với CÙNG SECRET_KEY sẽ dùng trên Vercel (nếu SECRET_KEY khác, mật khẩu
tạo ở đây sẽ không khớp khi app thật verify).

Cách chạy (từ máy local, KHÔNG chạy trên Vercel):
    export DATABASE_URL="postgresql://...supabase connection string thật..."
    export SECRET_KEY="...giá trị SECRET_KEY bạn sẽ set trên Vercel..."
    pip install psycopg2-binary   # nếu chưa cài
    python seed_supabase_users.py

Mặc định tạo 2 tài khoản demo giống `init_db.py` (admin/admin123, operator/operator123)
— ĐỔI MẬT KHẨU NGAY sau khi đăng nhập lần đầu, đừng để mặc định trên môi trường thật.
An toàn chạy lại nhiều lần (UPSERT theo username, không tạo trùng).
"""
from __future__ import annotations

import hashlib
import os
import sys

try:
    import psycopg2
except ImportError:
    print("Chưa cài psycopg2-binary. Chạy: pip install psycopg2-binary")
    sys.exit(1)


def hash_password(raw_password: str, secret_key: str) -> str:
    """Y HỆT core/auth.py::hash_password() — không import trực tiếp module đó vì file này
    chạy độc lập, không có Flask app context/`current_app`."""
    return hashlib.sha256(f"{secret_key}:{raw_password}".encode("utf-8")).hexdigest()


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    secret_key = os.environ.get("SECRET_KEY")
    if not database_url:
        print("Thiếu biến môi trường DATABASE_URL (connection string Supabase thật).")
        return 1
    if not secret_key:
        print(
            "Thiếu biến môi trường SECRET_KEY — PHẢI dùng ĐÚNG giá trị bạn sẽ set trên "
            "Vercel, nếu không mật khẩu tạo ở đây sẽ không khớp lúc app thật verify."
        )
        return 1

    accounts = [
        ("admin", "admin123", "Administrator", "admin"),
        ("operator", "operator123", "Operator", "operator"),
    ]

    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        for username, password, full_name, role in accounts:
            password_hash = hash_password(password, secret_key)
            cur.execute(
                """
                INSERT INTO users (username, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    full_name = excluded.full_name,
                    role = excluded.role
                """,
                (username, password_hash, full_name, role),
            )
            print(f"  - Seeded '{username}' (role={role})")
        conn.commit()
        cur.close()
    finally:
        conn.close()

    print()
    print("Xong. Đăng nhập bằng admin/admin123 hoặc operator/operator123 rồi ĐỔI MẬT KHẨU NGAY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
