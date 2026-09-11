"""
graphify/mapper.py
-------------------
Utility quét (introspect) toàn bộ Domain/Engine đã được cài đặt trong
`modules/` và xây dựng một Đồ thị (Graph) mô tả luồng dữ liệu:

    File Excel/CSV --(upload)--> Engine Import --(write)--> Bảng SQLite
                                                                  |
                                                              (read)
                                                                  v
                                                          Engine Tính toán (OEE, Downtime, ...)

Đồ thị được biểu diễn dưới dạng đơn giản (list Node + list Edge), dễ
JSON-serialize để trả về cho Frontend vẽ bằng SVG (xem `graph_view.html`).

Việc quét này KHÔNG cần Flask app context — chỉ dùng `pkgutil` + `importlib`
để import các package Python thuần, sau đó đọc thuộc tính `engine.metadata`
(một `EngineMetadata`, xem `core/engine_base.py`) mà mỗi Engine tự khai báo.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.engine_base import EngineMetadata
from core.engine_registry import discover_engines

# Từ khoá nhận diện một "data_source" thực chất là File Excel/CSV do người
# dùng upload (khác với tên một bảng SQLite thật sự).
_FILE_SOURCE_HINTS = ("excel", "csv", "file")


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str  # "source" | "engine" | "table"
    domain: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str  # "upload" | "write" | "read" | "depends_on"


@dataclass
class Graph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [asdict(n) for n in self.nodes], "edges": [asdict(e) for e in self.edges]}


def discover_engine_metadata() -> list[EngineMetadata]:
    """Trả về EngineMetadata của mọi Engine đã cài đặt trong hệ thống (bất kể Domain nào).

    Logic quét pkgutil thực tế nằm ở `core/engine_registry.py::discover_engines()` —
    dùng chung với `core/rollup.py` (cần giữ lại instance Engine để gọi `.recompute_daily()`,
    không chỉ đọc metadata), tránh 2 nơi tự quét trùng lặp.
    """
    return [engine.metadata for engine in discover_engines()]


def build_graph() -> Graph:
    """Xây dựng Graph hoàn chỉnh từ metadata của mọi Engine đã phát hiện."""
    graph = Graph()
    node_ids: set[str] = set()

    def ensure_node(node_id: str, label: str, kind: str, domain: str = "") -> None:
        if node_id not in node_ids:
            graph.nodes.append(GraphNode(id=node_id, label=label, kind=kind, domain=domain))
            node_ids.add(node_id)

    ensure_node("source:excel_file", "File Excel / CSV\n(user-uploaded)", "source")

    for meta in discover_engine_metadata():
        engine_id = f"engine:{meta.domain}.{meta.name}"
        ensure_node(engine_id, f"{meta.domain}.{meta.name}", "engine", domain=meta.domain)

        for source in meta.data_sources:
            if any(hint in source.lower() for hint in _FILE_SOURCE_HINTS):
                graph.edges.append(GraphEdge(source="source:excel_file", target=engine_id, relation="upload"))
            else:
                table_id = f"table:{source}"
                ensure_node(table_id, source, "table")
                graph.edges.append(GraphEdge(source=table_id, target=engine_id, relation="read"))

        for sink in meta.data_sinks:
            table_id = f"table:{sink}"
            ensure_node(table_id, sink, "table")
            graph.edges.append(GraphEdge(source=engine_id, target=table_id, relation="write"))

        for dependency in meta.depends_on:
            dep_id = f"engine:{meta.domain}.{dependency}"
            ensure_node(dep_id, f"{meta.domain}.{dependency}", "engine", domain=meta.domain)
            graph.edges.append(GraphEdge(source=dep_id, target=engine_id, relation="depends_on"))

    return graph
