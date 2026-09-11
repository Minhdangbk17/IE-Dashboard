"""
modules/dyeing/engines/oee/service.py
---------------------------------------
Logic tính toán chỉ số OEE (Overall Equipment Effectiveness) cho các máy Nhuộm.

Công thức chuẩn:
    OEE = Availability x Performance x Quality

    - Availability (Tính sẵn sàng) = Thời gian chạy thực tế / Thời gian kế hoạch
    - Performance  (Hiệu suất)     = Tốc độ thực tế / Tốc độ tiêu chuẩn
    - Quality      (Chất lượng)    = Sản lượng đạt / Tổng sản lượng

Ghi chú Phase 1: bảng `machine_telemetry` hiện chưa có cột phế phẩm/lỗi
(reject/defect), vì vậy Quality tạm thời được giả định = 100%. Đây là điểm
mở rộng rõ ràng cho Phase 2 khi tích hợp dữ liệu chất lượng (QC).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.database import execute_query

QUALITY_ASSUMPTION = 1.0  # 100% — xem ghi chú ở trên (chưa có dữ liệu QC ở Phase 1)


def calculate_oee(machine_id: str | None = None, days: int = 7) -> dict[str, Any]:
    """Tính OEE tổng hợp theo từng máy trong `days` ngày gần nhất.

    Trả về dict JSON-serializable, sẵn sàng cho `jsonify()`.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    sql = (
        "SELECT machine_id, status, actual_speed, standard_speed, output_meters "
        "FROM machine_telemetry WHERE timestamp >= ?"
    )
    params: list[Any] = [since]
    if machine_id:
        sql += " AND machine_id = ?"
        params.append(machine_id)

    rows = execute_query(sql, params)

    aggregates: dict[str, dict[str, float]] = {}
    for row in rows:
        agg = aggregates.setdefault(
            row["machine_id"],
            {"total_samples": 0, "running_samples": 0, "speed_ratio_sum": 0.0, "speed_samples": 0, "output_sum": 0.0},
        )
        agg["total_samples"] += 1
        if row["status"] == "RUNNING":
            agg["running_samples"] += 1
            agg["output_sum"] += row["output_meters"] or 0.0
            if row["standard_speed"]:
                ratio = min((row["actual_speed"] or 0.0) / row["standard_speed"], 1.5)
                agg["speed_ratio_sum"] += ratio
                agg["speed_samples"] += 1

    machine_results = []
    for mid, agg in sorted(aggregates.items()):
        availability = agg["running_samples"] / agg["total_samples"] if agg["total_samples"] else 0.0
        performance = (agg["speed_ratio_sum"] / agg["speed_samples"]) if agg["speed_samples"] else 0.0
        quality = QUALITY_ASSUMPTION
        oee = availability * performance * quality

        machine_results.append(
            {
                "machine_id": mid,
                "availability_pct": round(availability * 100, 1),
                "performance_pct": round(performance * 100, 1),
                "quality_pct": round(quality * 100, 1),
                "oee_pct": round(oee * 100, 1),
                "output_meters": round(agg["output_sum"], 1),
                "sample_count": agg["total_samples"],
            }
        )

    overall_oee = round(
        sum(m["oee_pct"] for m in machine_results) / len(machine_results), 1
    ) if machine_results else 0.0

    return {
        "period_days": days,
        "overall_oee_pct": overall_oee,
        "quality_note": "Quality is temporarily assumed at 100% (no QC data in Phase 1).",
        "machines": machine_results,
    }
