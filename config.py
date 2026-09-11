"""
config.py
---------
Cấu hình tập trung cho toàn bộ ứng dụng: đường dẫn Database, thư mục Upload,
các tham số PRAGMA của SQLite và cấu hình Flask.

Toàn bộ giá trị có thể override thông qua biến môi trường (12-factor style),
giúp việc triển khai (deploy) trên nhiều môi trường (dev/staging/prod) dễ dàng hơn.
"""
from __future__ import annotations

import os
from pathlib import Path


class Config:
    """Base configuration. Đọc giá trị từ biến môi trường, có fallback mặc định."""

    # --- Đường dẫn gốc của dự án ---
    BASE_DIR: Path = Path(__file__).resolve().parent

    # --- Flask core ---
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "1") == "1"
    JSON_AS_ASCII: bool = False  # cho phép trả JSON tiếng Việt không escape unicode

    # --- Database ---
    # Dual-mode: KHÔNG set DATABASE_URL -> SQLite cục bộ (hành vi mặc định, không đổi).
    # CÓ set DATABASE_URL (vd Postgres/Supabase khi deploy Vercel) -> core/database.py
    # tự chuyển sang dùng psycopg2 qua lớp bọc tương thích. Xem core/database.py::get_dialect().
    DATABASE_URL: str | None = os.environ.get("DATABASE_URL") or None
    DATABASE_PATH: Path = Path(
        os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "mes_dashboard.db"))
    )
    # PRAGMA tối ưu cho truy vấn đồng thời (nhiều request đọc/ghi cùng lúc) — CHỈ áp dụng khi
    # chạy SQLite (DATABASE_URL rỗng); Postgres/Supabase tự quản connection pooling riêng.
    SQLITE_PRAGMAS: dict[str, str] = {
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "foreign_keys": "ON",
        "cache_size": "-64000",  # ~64MB cache
        "temp_store": "MEMORY",
    }

    # --- Upload / Excel Import ---
    UPLOAD_FOLDER: Path = Path(os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "uploads")))
    ALLOWED_IMPORT_EXTENSIONS: set[str] = {"xlsx", "xls", "csv"}
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16MB giới hạn upload
    # Nếu True: chỉ commit khi TOÀN BỘ file hợp lệ.
    # Nếu False: bỏ qua dòng lỗi, commit các dòng hợp lệ còn lại (partial import).
    IMPORT_STRICT_MODE: bool = os.environ.get("IMPORT_STRICT_MODE", "0") == "1"

    # --- Module / Engine discovery ---
    MODULES_PACKAGE: str = "modules"
    MODULES_DIR: Path = BASE_DIR / "modules"

    @classmethod
    def ensure_directories(cls) -> None:
        """Đảm bảo các thư mục cần thiết (data, uploads) tồn tại trước khi chạy — CHỈ khi
        chạy SQLite cục bộ (`DATABASE_URL` rỗng). Trên môi trường serverless (Vercel + Postgres/
        Supabase), thư mục code deploy là READ-ONLY (trừ `/tmp`) — gọi `mkdir()` ở đây sẽ
        crash ngay lúc khởi động (`PermissionError: Read-only file system`) TRƯỚC KHI kịp
        dùng tới Postgres. `DATABASE_PATH`/`UPLOAD_FOLDER` đều không cần thiết khi có
        `DATABASE_URL`: SQLite không được dùng, và Excel Import ghi file tạm qua
        `tempfile.NamedTemporaryFile` (thư mục temp hệ thống, luôn ghi được kể cả trên
        Vercel) chứ không ghi vào `UPLOAD_FOLDER`."""
        if cls.DATABASE_URL:
            return
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


CONFIG_MAP: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config(env_name: str | None = None) -> type[Config]:
    """Trả về class Config phù hợp theo tên môi trường (FLASK_ENV)."""
    env_name = env_name or os.environ.get("FLASK_ENV", "default")
    return CONFIG_MAP.get(env_name, DevelopmentConfig)
