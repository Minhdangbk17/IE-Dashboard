"""
graphify/
---------
Graphify Engine / Module — phục vụ việc lập bản đồ đồ thị (Graph Mapping)
theo dõi mối quan hệ phụ thuộc giữa các Engine và Data Flow từ File Excel /
máy IoT đến Dashboard.

Khác với các Engine trong `modules/<domain>/engines/`, Graphify là một
module CẤP ỨNG DỤNG (application-level) — nó quét (introspect) TOÀN BỘ hệ
thống (mọi Domain, mọi Engine) để vẽ sơ đồ tổng thể, nên được mount trực
tiếp bởi `app.py` (xem `_register_graphify`) thay vì nằm trong `modules/`.
"""
