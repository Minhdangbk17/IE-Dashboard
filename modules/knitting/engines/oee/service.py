"""
modules/knitting/engines/oee/service.py
-------------------------------------------
Stub tối giản cho Phase 1 — Domain "knitting" hiện dùng chung bảng
`machine_telemetry`/`downtime_logs` với "dyeing" (cột `domain` trong bảng
`machines` phân biệt xưởng). Logic tính toán chi tiết cho Dệt sẽ được triển
khai đầy đủ ở Phase 2 khi có schema dữ liệu riêng cho xưởng Dệt.
"""
from __future__ import annotations

from typing import Any


def calculate_oee_placeholder() -> dict[str, Any]:
    return {
        "status": "not_implemented",
        "message": "Engine OEE cho Domain Dệt sẽ được triển khai đầy đủ ở Phase 2.",
        "machines": [],
    }
