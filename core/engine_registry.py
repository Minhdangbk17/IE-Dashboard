"""
core/engine_registry.py
------------------------
Quét (introspect) `modules/<domain>/engines/<engine>/` để lấy TẤT CẢ instance
Engine đã cài đặt trong hệ thống — dùng `pkgutil` + `importlib`, không hardcode
tên Domain/Engine nào (đúng convention Auto-loader của dự án).

Trước đây logic quét này chỉ tồn tại trong `graphify/mapper.py::discover_engine_metadata()`
(chỉ trả về `EngineMetadata`, không giữ lại instance Engine để gọi method) — module
này tách ra thành nguồn DUY NHẤT trả về chính instance `BaseEngine`, để cả
`graphify/mapper.py` (đọc `.metadata`) LẪN `core/rollup.py` (gọi `.recompute_daily()`)
dùng chung, tránh 2 nơi quét pkgutil trùng lặp.
"""
from __future__ import annotations

import importlib
import pkgutil

from core.engine_base import BaseEngine


def discover_engines() -> list[BaseEngine]:
    """Quét mọi Domain trong `modules/`, trả về instance Engine (`engine = XxxEngine()`)
    mà mỗi package Engine tự expose — bất kể Domain nào, không cần Flask app context."""
    import modules

    engines: list[BaseEngine] = []
    for _finder, domain_name, is_pkg in pkgutil.iter_modules(modules.__path__):
        if not is_pkg:
            continue
        try:
            engines_pkg = importlib.import_module(f"modules.{domain_name}.engines")
        except ModuleNotFoundError:
            continue  # Domain không có sub-package engines/ -> bỏ qua

        engines_path = getattr(engines_pkg, "__path__", None)
        if engines_path is None:
            continue

        for _finder2, engine_name, is_pkg2 in pkgutil.iter_modules(engines_path):
            if not is_pkg2:
                continue
            engine_module = importlib.import_module(f"modules.{domain_name}.engines.{engine_name}")
            engine = getattr(engine_module, "engine", None)
            if isinstance(engine, BaseEngine):
                engines.append(engine)

    return engines
