"""
tests/test_rft_classification.py
------------------------------------
Verify báo cáo Right First Time (RFT) bản viết lại 2026-10-08 trên ĐÚNG 3 file mẫu người dùng
cung cấp (cùng giai đoạn 05-06/10/2026):
- `Copy of Batch_202696181325.xlsx` sheet `data`: 57 mẻ + 5 cột người dùng tự tính bằng công
  thức Excel (STAGE, MachineGroup, DyeingRFT, NewBatch, ReworkCount) = đáp án chuẩn.
- `Copy of production_report_dye_1640090610.xlsx` (sheet thô `DYE` + sheet lọc tay `DG`).
- `Copy of nc_report_1800040610.xlsx` (sheet thô `Sheet1 (2)` + sheet lọc tay `NC`).

Kịch bản: (1) công thức từng cột; (2) auto-detect + parse file thô; (3) bộ lọc tự động khớp
sheet lọc tay (trừ 2 sai lệch đã biết khi lọc tay); (4) 57/57 dòng khớp 5 cột Excel; (5) số liệu
pivot khớp pivot của người dùng; (6) import 2 lần không nhân đôi; (7) DG nạp ngày sau đổi mẻ
OK -> Rework; (8) Export Excel.

Dùng DB TẠM (file SQLite tạm + Flask app context tạm, KHÔNG đụng DB thật).
Chạy: python tests/test_rft_classification.py
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.batch_importer import _parse_batch_datetime  # noqa: E402
from core.database import close_db, get_db  # noqa: E402
from core.rft_sources_importer import (  # noqa: E402
    DYE_PRODUCTION_FILE_TYPE, NC_REPORT_FILE_TYPE, detect_rft_source_type, parse_dye_production_file,
    parse_nc_report_file, sync_dye_production_ops, sync_nc_reports,
)
from modules.dyeing.engines.rft.service import (  # noqa: E402
    classify_stage, export_rft_excel, get_rft_pivot_data, is_counted_nc, load_rft_rows,
    machine_group_label, next_batch,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_imports"
BATCH_FILE = FIXTURES / "Copy of Batch_202696181325.xlsx"
DYE_FILE = FIXTURES / "Copy of production_report_dye_1640090610.xlsx"
NC_FILE = FIXTURES / "Copy of nc_report_1800040610.xlsx"
PRODUCTION_DAY = "2026-10-05"
# Cột tính của người dùng trong sheet `data` (BW..CA) — cột MachineGroup thứ 2 trùng tên nên lấy
# theo vị trí.
COL_STAGE, COL_MACHINE_GROUP2, COL_DYEING_RFT, COL_NEW_BATCH, COL_REWORK_COUNT = 74, 75, 76, 77, 78


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _batch_sheet_rows() -> tuple[list[str], list[tuple]]:
    workbook = load_workbook(BATCH_FILE, read_only=True, data_only=True)
    try:
        rows = list(workbook["data"].iter_rows(values_only=True))
    finally:
        workbook.close()
    return [str(value) for value in rows[0]], [row for row in rows[1:] if any(value is not None for value in row)]


def _init_batch_details(db_path: str) -> int:
    """`batch_details` tối giản (đủ cột service đọc) + nạp 57 mẻ của file Batch mẫu."""
    headers, rows = _batch_sheet_rows()
    index = {name: headers.index(name) for name in (
        "Dyelot", "Machine", "MachineGroup", "FormulaCode", "TotalCorrectionCnt", "FabricType",
        "GreigeCode", "Customer", "StartTime", "EndTime",
    )}
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, machine TEXT, machine_group TEXT,
            formula_code TEXT, total_correction_cnt INTEGER NOT NULL DEFAULT 0, fabric_type TEXT,
            greige_code TEXT, customer TEXT, start_time TEXT, end_time TEXT
        )
    """)
    for row in rows:
        conn.execute(
            "INSERT INTO batch_details (dyelot, machine, machine_group, formula_code, total_correction_cnt, fabric_type, greige_code, customer, start_time, end_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                row[index["Dyelot"]], row[index["Machine"]], row[index["MachineGroup"]], row[index["FormulaCode"]],
                int(row[index["TotalCorrectionCnt"]] or 0), row[index["FabricType"]], row[index["GreigeCode"]],
                row[index["Customer"]], _parse_batch_datetime(row[index["StartTime"]]), _parse_batch_datetime(row[index["EndTime"]]),
            ),
        )
    conn.commit()
    conn.close()
    return len(rows)


def _scenario_formulas(failures: list[str]) -> None:
    print("\n=== Kịch bản 1: công thức từng cột ===")
    for code, expected in (
        ("01-Lab to bulk", "Lab to Bulk"), ("07-Labdip", "Lab to Bulk"), ("08-So theo  QC OK<2batches", "Bulk to Bulk"),
        ("09-So theo QC-OK", "Bulk to Bulk"), ("03-Chỉnh tay không mẫu", "2nd Batch"), ("06-Khác nhóm máy", "2nd Batch"),
        (None, "2nd Batch"),
    ):
        _check(f"classify_stage({code!r})", classify_stage(code), expected, failures)
    for group, expected in (("G600", ">=500kg"), ("G500", ">=500kg"), ("C1600", ">=500kg"), ("G300", "Small Machine"), ("C100", "Small Machine"), (None, None), ("", None)):
        _check(f"machine_group_label({group!r})", machine_group_label(group), expected, failures)
    for dyelot, expected in (
        ("C260708660", "C260708661"), ("C260612221", "C260612222"), ("C260612228", "C260612229"),
        ("C260612229", "C26061222A"), ("C26061222A", "C26061222B"), ("c26061222b", "C26061222C"),
        ("C26061222Z", None), ("C26061222-", None), ("", None),
    ):
        _check(f"next_batch({dyelot!r})", next_batch(dyelot), expected, failures)


def _scenario_detect_and_parse(failures: list[str]) -> None:
    print("\n=== Kịch bản 2: auto-detect + parse file thô ===")
    dye_bytes, nc_bytes = DYE_FILE.read_bytes(), NC_FILE.read_bytes()
    _check("detect Production Report", detect_rft_source_type(dye_bytes), DYE_PRODUCTION_FILE_TYPE, failures)
    _check("detect NC Report", detect_rft_source_type(nc_bytes), NC_REPORT_FILE_TYPE, failures)
    _check("file Batch không phải nguồn RFT", detect_rft_source_type(BATCH_FILE.read_bytes()), None, failures)
    _check("file không phải Excel -> None", detect_rft_source_type(b"not an excel file"), None, failures)
    dye = parse_dye_production_file(dye_bytes)
    _check("Production Report: đọc sheet thô DYE (953 dòng)", dye["total_records"], 953, failures)
    _check("Production Report: 0 dòng lỗi", len(dye["errors"]), 0, failures)
    first = dye["rows"][0]
    _check("header 3 dòng map đúng Batch#", first["batch_no"], "C260694660", failures)
    _check("header 3 dòng map đúng Operation#", first["operation"], "PA01 - Phát thẻ-领胚", failures)
    _check("ô 'Batch Status' dính tiếng Việt vẫn map được", first["batch_status"], "Running", failures)
    _check("OP Start time -> chuỗi ngày giờ", first["op_start_time"], "2026-10-05 18:33:52", failures)
    nc = parse_nc_report_file(nc_bytes)
    _check("NC Report: đọc sheet thô đầu tiên (370 dòng)", nc["total_records"], 370, failures)
    _check("NC Report: 0 dòng lỗi", len(nc["errors"]), 0, failures)


def _scenario_auto_filter_vs_manual(failures: list[str]) -> None:
    print("\n=== Kịch bản 3: bộ lọc tự động so với sheet lọc tay ===")
    workbook = load_workbook(DYE_FILE, read_only=True, data_only=True)
    manual_dg = {str(row[7]).strip(): str(row[2]) for row in list(workbook["DG"].iter_rows(values_only=True))[1:]}
    workbook.close()
    auto_dg = {row["batch_no"] for row in parse_dye_production_file(DYE_FILE.read_bytes())["rows"] if row["operation"].upper().startswith("DG")}
    _check("DG tự lọc (công đoạn DG*) = 76 batch", len(auto_dg), 76, failures)
    _check("Sheet DG lọc tay chỉ dư 5 dòng LO02 (người dùng chốt: chỉ lấy DG*)",
           sorted({op[:4] for batch, op in manual_dg.items() if batch not in auto_dg}), ["LO02"], failures)
    _check("Mọi batch DG tự lọc đều có trong sheet lọc tay", auto_dg <= set(manual_dg), True, failures)

    workbook = load_workbook(NC_FILE, read_only=True, data_only=True)
    manual_nc = {str(row[11]).strip() for row in list(workbook["NC"].iter_rows(values_only=True))[1:]}
    workbook.close()
    auto_nc = {row["batch_ref"] for row in parse_nc_report_file(NC_FILE.read_bytes())["rows"] if is_counted_nc(row)}
    _check("NC tự lọc = 67 dòng", len(auto_nc), 67, failures)
    _check("Sheet NC lọc tay chỉ sót đúng C260709160 (người dùng xác nhận sót khi lọc tay)", sorted(auto_nc - manual_nc), ["C260709160"], failures)
    _check("Mọi NC lọc tay đều được bộ lọc tự động giữ lại", manual_nc <= auto_nc, True, failures)


def _scenario_end_to_end(failures: list[str]) -> None:
    print("\n=== Kịch bản 4-8: import 2 nguồn + so với kết quả Excel của người dùng ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        batch_count = _init_batch_details(db_path)
        _check("nạp 57 mẻ Batch mẫu", batch_count, 57, failures)
        app = _make_temp_app(db_path)
        with app.app_context():
            for _ in range(2):  # import 2 lần — UPSERT, không nhân đôi
                dye_result = sync_dye_production_ops(DYE_FILE.read_bytes(), "tester", DYE_FILE.name)
                nc_result = sync_nc_reports(NC_FILE.read_bytes(), "tester", NC_FILE.name)
            conn = get_db()
            _check("Kịch bản 6: dye_production_ops sau 2 lần import vẫn 953 dòng",
                   conn.execute("SELECT COUNT(*) AS c FROM dye_production_ops").fetchone()["c"], 953, failures)
            _check("Kịch bản 6: dye_nc_reports sau 2 lần import vẫn 370 dòng",
                   conn.execute("SELECT COUNT(*) AS c FROM dye_nc_reports").fetchone()["c"], 370, failures)
            _check("import Production Report status", dye_result["status"], "completed", failures)
            _check("import NC Report status", nc_result["status"], "completed", failures)

            # Kịch bản 4: 57/57 dòng khớp 5 cột Excel của người dùng.
            headers, sheet_rows = _batch_sheet_rows()
            expected = {}
            for row in sheet_rows:
                key = (row[headers.index("Dyelot")], _parse_batch_datetime(row[headers.index("EndTime")]))
                expected[key] = {
                    "stage": row[COL_STAGE], "machine_group_label": row[COL_MACHINE_GROUP2],
                    "dyeing_rft": row[COL_DYEING_RFT], "new_batch": row[COL_NEW_BATCH], "rework_count": row[COL_REWORK_COUNT],
                }
            rows = load_rft_rows(PRODUCTION_DAY, PRODUCTION_DAY)
            _check("Kịch bản 4: 57 mẻ trong ngày sản xuất 05/10", len(rows), 57, failures)
            mismatches = []
            for row in rows:
                theirs = expected[(row["dyelot"], row["end_time"])]
                mine = {
                    "stage": row["stage"].lower(), "machine_group_label": row["machine_group_label"],
                    "dyeing_rft": row["dyeing_rft"], "new_batch": row["new_batch"], "rework_count": row["rework_count"],
                }
                for field, value in mine.items():
                    if value != theirs[field]:
                        mismatches.append((row["dyelot"], field, value, theirs[field]))
            _check("Kịch bản 4: số ô lệch so với Excel (5 cột x 57 dòng)", mismatches, [], failures)
            sources = {row["dyelot"]: row["rework_source"] for row in rows if row["rework_count"] == "Rework"}
            _check("Rework Source ghi rõ số NC", sources.get("C260712960"), "NC2607129600", failures)

            # Kịch bản 5: pivot khớp pivot của người dùng (sheet `pivot`).
            def tab(slug: str, **kwargs):
                return get_rft_pivot_data(slug, from_date=PRODUCTION_DAY, to_date=PRODUCTION_DAY, group_by="date", **kwargs)

            lab = tab("Lab to Bulk")
            bulk = tab("Bulk to Bulk")
            second = tab("2nd Batch")
            _check("Lab to Bulk Total (pivot 33.3%)", lab["total_row"]["total"], 33.3, failures)
            _check("Lab to Bulk Polyester (pivot 33.3%)", lab["rows"][2]["total"], 33.3, failures)
            _check("Lab to Bulk Cotton không có mẻ -> '-'", lab["rows"][0]["total"], None, failures)
            _check("Bulk to Bulk Total (pivot 100%)", bulk["total_row"]["total"], 100.0, failures)
            _check("2nd Batch Total (pivot 91.2%)", second["total_row"]["total"], 91.2, failures)
            _check("2nd Batch Cotton/CVC/Polyester (pivot 93.3/92.9/80.0%)", [row["total"] for row in second["rows"]], [93.3, 92.9, 80.0], failures)
            _check("2nd Batch KPI = 31/34 mẻ", (second["kpis"]["hit_batches"], second["kpis"]["total_batches"]), (31, 34), failures)
            _check("Target RFT là mức tối thiểu", lab["target_direction"], "min", failures)

            rework = tab("Rework")
            adjustment = tab("Adjustment")
            _check("Rework: mẫu số chỉ máy >=500kg (pivot 47 mẻ)", rework["kpis"]["total_batches"], 47, failures)
            _check("Rework rate tổng = 3/47 (pivot 6.4%)", rework["kpis"]["rate_pct"], 6.4, failures)
            _check("Adjustment rate tổng = 1/47 (pivot 2.1%)", adjustment["kpis"]["rate_pct"], 2.1, failures)
            _check("Rework theo vải: Cotton 0/19, CVC 1/17, Polyester 2/11",
                   [row["total"] for row in rework["rows"]], [0.0, 5.9, 18.2], failures)
            _check("Target Rework là mức tối đa", rework["target_direction"], "max", failures)

            small_only = tab("Rework", machine_groups="Small Machine")
            _check("Lọc Small Machine -> tab Rework không còn mẻ", small_only["kpis"]["total_batches"], 0, failures)
            _check("Lọc Capacity 600 -> 2nd Batch chỉ còn máy G600",
                   {row["machine_group"] for row in load_rft_rows(PRODUCTION_DAY, PRODUCTION_DAY) if row["capacity"] == 600.0} == {"G600"}
                   and tab("2nd Batch", capacities="600")["kpis"]["total_batches"] > 0, True, failures)
            _check("available_capacities lấy từ MachineGroup", lab["available_capacities"],
                   ["25", "50", "100", "300", "500", "600", "800", "1200", "1600", "2400"], failures)

            # Kịch bản 7: Production Report của ngày sau có mẻ làm lại -> mẻ gốc chuyển Rework.
            target = next(row for row in rows if row["rework_count"] == "OK")
            conn.execute(
                "INSERT INTO dye_production_ops (batch_no, operation, op_start_time) VALUES (?, ?, ?)",
                (target["new_batch"], "DG09 - Nhuộm lại màu-染缸修色", "2026-10-07 10:00:00"),
            )
            conn.commit()
            later = {row["dyelot"]: row for row in load_rft_rows(PRODUCTION_DAY, PRODUCTION_DAY)}
            _check(f"Kịch bản 7: {target['dyelot']} chuyển OK -> Rework khi DG ngày sau có {target['new_batch']}",
                   (later[target["dyelot"]]["rework_count"], later[target["dyelot"]]["rework_source"]), ("Rework", "DG"), failures)
            _check("DG không làm đổi DyeingRFT (chỉ NC/TotalCorrectionCnt)", later[target["dyelot"]]["dyeing_rft"], target["dyeing_rft"], failures)
            conn.execute("DELETE FROM dye_production_ops WHERE op_start_time = '2026-10-07 10:00:00'")
            conn.commit()

            # Kịch bản 8: Export Excel.
            content, filename = export_rft_excel(from_date=PRODUCTION_DAY, to_date=PRODUCTION_DAY)
            workbook = load_workbook(io.BytesIO(content), read_only=True)
            _check("Export: 4 sheet", workbook.sheetnames, ["Dyeing RFT", "Rework Count", "Data", "Filters"], failures)
            _check("Export: sheet Data có 57 mẻ", workbook["Data"].max_row - 1, 57, failures)
            rework_sheet = list(workbook["Rework Count"].iter_rows(values_only=True))
            grand = next(row for row in rework_sheet if row and row[0] == "Grand Total")
            _check("Export: Grand Total Rework Count OK/Adjustment/Rework/Total", grand[1:5], (43, 1, 3, 47), failures)
            workbook.close()
            _check("Export: tên file", filename, f"rft_{PRODUCTION_DAY}_to_{PRODUCTION_DAY}.xlsx", failures)
            close_db()
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_formulas(failures)
    _scenario_detect_and_parse(failures)
    _scenario_auto_filter_vs_manual(failures)
    _scenario_end_to_end(failures)
    print(f"\n{'=' * 60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'=' * 60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
