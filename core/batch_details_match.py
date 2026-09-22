"""
core/batch_details_match.py
----------------------------
`batch_details` từ nay cho phép NHIỀU dòng/1 Dyelot (mẻ gốc + mẻ redye chạy lại — xem điều tra
mẻ C260659920 trong memory-bank/activeContext.md, và `core/batch_importer.py::
_migrate_batch_details_primary_key()`). Mọi nơi JOIN `batch_details` theo `dyelot` để làm giàu
1 dòng dữ liệu khác (availability_logs/rft_dye_results/performance_logs...) trước đây ngầm giả
định "1 dyelot = 1 dòng" — nếu JOIN thẳng theo dyelot như cũ, 1 dòng nguồn sẽ bị nhân đôi (mỗi
dòng batch_details trùng dyelot tạo ra 1 dòng kết quả), gây đếm trùng ở các Engine cộng
SUM/COUNT trực tiếp trên kết quả JOIN.

`batch_details_join_sql()` cung cấp 1 LEFT JOIN luôn trả về TỐI ĐA 1 dòng batch_details cho mỗi
dòng đang JOIN vào — chọn dòng có `end_time` khớp CHÍNH XÁC với dòng nguồn (cùng 1 sự kiện thật,
vì cả 2 bảng đều xuất từ cùng hệ MES), fallback dòng `end_time` MỚI NHẤT nếu không khớp được
(giữ đúng hành vi "ghi đè bởi lần chạy mới nhất" trước đây, khi không đủ căn cứ phân biệt — VD
dòng nguồn chưa có end_time hoặc batch_details thiếu end_time).

Đây là helper hạ tầng SQL thuần (không mang logic nghiệp vụ riêng Engine nào), tương tự
`core/production_time.py` — dùng chung không vi phạm nguyên tắc Vertical Slice (xem CLAUDE.md
mục 3-4), vì nguyên tắc đó áp dụng cho LOGIC NGHIỆP VỤ riêng từng Engine, không áp dụng cho 1
đoạn SQL sửa cùng 1 lỗi kỹ thuật lặp lại ở nhiều nơi.
"""
from __future__ import annotations


def batch_details_join_sql(dyelot_exprs: str | list[str], end_time_expr: str, alias: str = "b") -> str:
    """Trả về chuỗi `LEFT JOIN batch_details {alias} ON ...` chọn ĐÚNG 1 dòng batch_details.

    `dyelot_exprs`: 1 hoặc nhiều biểu thức SQL (cột/alias) đại diện mã Dyelot của dòng đang JOIN
    vào (VD `"a.batch"`, hoặc `["a.batch_ref_no", "a.batch"]` khi cần khớp CẢ 2 cột như
    `cleaning_matrix.py`). So khớp không phân biệt hoa/thường + khoảng trắng thừa
    (`lower(trim(...))`), cùng quy ước đã dùng ở mọi JOIN dyelot khác trong dự án.
    `end_time_expr`: biểu thức SQL trỏ cột `end_time` của dòng đang JOIN vào (VD `"a.end_time"`),
    dùng để ưu tiên chọn ĐÚNG lần chạy khớp thời điểm kết thúc, khi 1 dyelot có nhiều dòng.
    `alias`: alias SQL của `batch_details` trong câu SELECT gọi hàm này (mặc định "b").
    """
    exprs = [dyelot_exprs] if isinstance(dyelot_exprs, str) else list(dyelot_exprs)
    match = " OR ".join(f"lower(trim(bb.dyelot)) = lower(trim({expr}))" for expr in exprs)
    # 2 subquery riêng biệt (thay vì 1 subquery + ORDER BY tương quan biến ngoài) vì SQLite
    # KHÔNG cho phép ORDER BY của subquery trong ON clause tham chiếu cột bảng ngoài (đã verify
    # bằng thực nghiệm: "no such column" dù WHERE tương quan y hệt lại chạy bình thường) — dùng
    # COALESCE: subquery 1 tìm dòng end_time khớp CHÍNH XÁC (tương quan trong WHERE, hợp lệ),
    # subquery 2 (KHÔNG tương quan) fallback dòng end_time mới nhất khi subquery 1 không có kết quả.
    return (
        f"LEFT JOIN batch_details {alias} ON {alias}.id = COALESCE("
        f"(SELECT bb.id FROM batch_details bb WHERE ({match}) AND bb.end_time = {end_time_expr} LIMIT 1), "
        f"(SELECT bb.id FROM batch_details bb WHERE ({match}) ORDER BY bb.end_time DESC LIMIT 1)"
        f")"
    )
