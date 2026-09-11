// raw_data_drawer.js
// ---------------------------------------------------------------------------
// Raw Data Viewer: Drawer trượt từ phải hiển thị toàn bộ dòng (valid + invalid)
// của một lần import — tìm kiếm/lọc/phân trang phía client, sửa nhanh (Inline
// Edit) dòng lỗi mà không cần upload lại file, xoá cả lần import nếu nạp nhầm.
//
// Khi số dòng sau lọc > 1000: chuyển sang chế độ Virtual Scroll (chỉ render
// các dòng đang nằm trong viewport + buffer) để không bị giật/lag DOM.
// ---------------------------------------------------------------------------
(function () {
    "use strict";

    const overlay = document.getElementById("raw-data-drawer");
    if (!overlay) return;

    const ROW_HEIGHT = 28;
    const VIRTUAL_SCROLL_THRESHOLD = 1000;
    const BUFFER_ROWS = 8;

    const rowsUrlTemplate = overlay.dataset.rowsUrlTemplate;
    const rowUpdateUrlTemplate = overlay.dataset.rowUpdateUrlTemplate;
    const deleteUrlTemplate = overlay.dataset.deleteUrlTemplate;

    const fileNameEl = document.getElementById("drawer-file-name");
    const fileMetaEl = document.getElementById("drawer-file-meta");
    const searchInput = document.getElementById("drawer-search");
    const statusFilterEl = document.getElementById("drawer-status-filter");
    const pageSizeSelect = document.getElementById("drawer-page-size");
    const summaryEl = document.getElementById("drawer-summary");
    const bodyEl = document.getElementById("drawer-body");
    const paginationEl = document.getElementById("drawer-pagination");
    const deleteBtn = document.getElementById("btn-delete-import");
    const reuploadBtn = document.getElementById("btn-reupload");
    const closeBtn = document.getElementById("btn-close-drawer");

    let currentLogId = null;
    let columns = [];
    let allRows = []; // {id, row_number, status, error, data}
    let statusFilter = "all";
    let searchQuery = "";
    let pageSize = 25;
    let currentPage = 1;

    function rowsUrl(logId) { return rowsUrlTemplate.replace("/0/rows", `/${logId}/rows`); }
    function rowUpdateUrl(logId, rowId) { return rowUpdateUrlTemplate.replace("/0/rows/0", `/${logId}/rows/${rowId}`); }
    function deleteUrl(logId) { return deleteUrlTemplate.replace(/\/0$/, `/${logId}`); }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }

    function open(logId) {
        currentLogId = logId;
        statusFilter = "all";
        searchQuery = "";
        searchInput.value = "";
        currentPage = 1;
        statusFilterEl.querySelectorAll(".BtnGroup-item").forEach((btn) => btn.classList.toggle("is-active", btn.dataset.status === "all"));
        overlay.classList.add("is-open");
        bodyEl.innerHTML = '<div class="drawer-empty">Loading data...</div>';
        fileNameEl.textContent = "Raw Data";
        fileMetaEl.textContent = "";
        fetch(rowsUrl(logId))
            .then((res) => res.json())
            .then((data) => {
                if (data.error) throw new Error(data.error);
                columns = data.columns;
                allRows = data.rows;
                fileNameEl.textContent = data.file_name;
                fileMetaEl.textContent = `${data.file_type} · ${data.total} rows`;
                render();
            })
            .catch((err) => {
                bodyEl.innerHTML = `<div class="drawer-empty">Failed to load data: ${escapeHtml(err.message)}</div>`;
            });
    }

    function close() {
        overlay.classList.remove("is-open");
    }

    function filteredRows() {
        let rows = allRows;
        if (statusFilter !== "all") {
            rows = rows.filter((row) => row.status === statusFilter);
        }
        if (searchQuery) {
            const query = searchQuery.toLowerCase();
            rows = rows.filter((row) => Object.values(row.data).some((value) => String(value ?? "").toLowerCase().includes(query)));
        }
        return rows;
    }

    function render() {
        const rows = filteredRows();
        summaryEl.textContent = `Showing ${rows.length}/${allRows.length} rows`;
        if (!rows.length) {
            bodyEl.innerHTML = '<div class="drawer-empty">No rows match the filters.</div>';
            paginationEl.innerHTML = "";
            return;
        }
        if (rows.length > VIRTUAL_SCROLL_THRESHOLD) {
            paginationEl.innerHTML = `<span class="f6 color-fg-muted">Scroll to see all ${rows.length} rows (virtual scroll)</span>`;
            renderVirtualScroll(rows);
        } else {
            const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
            currentPage = Math.min(currentPage, totalPages);
            const start = (currentPage - 1) * pageSize;
            const pageRows = rows.slice(start, start + pageSize);
            renderTable(pageRows, 0, 0);
            renderPagination(totalPages);
        }
    }

    function renderPagination(totalPages) {
        if (totalPages <= 1) {
            paginationEl.innerHTML = "";
            return;
        }
        paginationEl.innerHTML = `
            <div class="d-flex flex-items-center" style="gap:6px;">
                <button type="button" class="btn btn-sm" id="pg-prev" ${currentPage <= 1 ? "disabled" : ""}>&larr;</button>
                <span class="f6">Page ${currentPage}/${totalPages}</span>
                <button type="button" class="btn btn-sm" id="pg-next" ${currentPage >= totalPages ? "disabled" : ""}>&rarr;</button>
            </div>`;
        document.getElementById("pg-prev")?.addEventListener("click", () => { currentPage -= 1; render(); });
        document.getElementById("pg-next")?.addEventListener("click", () => { currentPage += 1; render(); });
    }

    function tableHead() {
        return `<thead><tr><th>#</th><th>Status</th>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>`;
    }

    function rowHtml(row) {
        const invalidClass = row.status === "invalid" ? "raw-row-invalid" : "";
        const title = row.status === "invalid" ? ` title="${escapeHtml(row.error || "")}"` : "";
        const badge = row.status === "invalid"
            ? `<span class="status-badge status-invalid">Invalid</span>`
            : `<span class="status-badge status-valid">Valid</span>`;
        const cells = columns.map((col) => `<td class="raw-cell-editable" data-row-id="${row.id}" data-field="${escapeHtml(col)}">${escapeHtml(row.data[col])}</td>`).join("");
        return `<tr class="${invalidClass}"${title}><td>${row.row_number}</td><td>${badge}</td>${cells}</tr>`;
    }

    function renderTable(rows, topSpacerPx, bottomSpacerRows) {
        const bottomSpacerPx = bottomSpacerRows > 0 ? bottomSpacerRows * ROW_HEIGHT : 0;
        const body = rows.map(rowHtml).join("");
        bodyEl.innerHTML = `<table class="raw-table">${tableHead()}<tbody>` +
            (topSpacerPx > 0 ? `<tr><td colspan="${columns.length + 2}" style="height:${topSpacerPx}px;padding:0;border:none;"></td></tr>` : "") +
            body +
            (bottomSpacerPx > 0 ? `<tr><td colspan="${columns.length + 2}" style="height:${bottomSpacerPx}px;padding:0;border:none;"></td></tr>` : "") +
            `</tbody></table>`;
        bindEditableCells();
    }

    function renderVirtualScroll(rows) {
        function renderVisible() {
            const scrollTop = bodyEl.scrollTop;
            const viewportHeight = bodyEl.clientHeight || 400;
            const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER_ROWS);
            const endIndex = Math.min(rows.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + BUFFER_ROWS);
            renderTable(rows.slice(startIndex, endIndex), startIndex * ROW_HEIGHT, rows.length - endIndex);
        }
        bodyEl.onscroll = renderVisible;
        renderVisible();
    }

    function bindEditableCells() {
        bodyEl.querySelectorAll(".raw-cell-editable").forEach((cell) => {
            cell.addEventListener("click", () => startEdit(cell), { once: true });
        });
    }

    function startEdit(cell) {
        const rowId = Number(cell.dataset.rowId);
        const field = cell.dataset.field;
        const row = allRows.find((r) => r.id === rowId);
        if (!row) return;
        const currentValue = row.data[field] ?? "";
        cell.innerHTML = `<input type="text" class="raw-cell-input" value="${escapeHtml(currentValue)}">`;
        const input = cell.querySelector("input");
        input.focus();
        input.select();
        let committed = false;
        const commit = () => {
            if (committed) return;
            committed = true;
            const newValue = input.value;
            if (newValue === currentValue) {
                render();
                return;
            }
            saveEdit(row, field, newValue);
        };
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") { event.preventDefault(); input.blur(); }
            if (event.key === "Escape") { committed = true; render(); }
        });
    }

    function saveEdit(row, field, newValue) {
        const updatedData = { ...row.data, [field]: newValue };
        fetch(rowUpdateUrl(currentLogId, row.id), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data: updatedData }),
        })
            .then(async (res) => {
                const payload = await res.json();
                if (!res.ok && !payload.status) {
                    // Lỗi cấp request (VD: dòng/log không còn tồn tại) — payload chỉ có {error},
                    // không phải kết quả revalidate — không ghi đè state trong bộ nhớ.
                    flashMessage(payload.error || "Failed to save changes.", "error");
                    render();
                    return;
                }
                row.data = payload.data || updatedData;
                row.status = payload.status;
                row.error = payload.error;
                render();
                if (window.dyeingHub) window.dyeingHub.refreshWidgets();
                if (payload.status === "valid") {
                    flashMessage(`Row #${row.row_number} saved.`, "success");
                } else {
                    flashMessage(`Row #${row.row_number} still has an error: ${payload.error}`, "warn");
                }
            })
            .catch(() => {
                flashMessage("Failed to save changes — check your connection.", "error");
                render();
            });
    }

    function flashMessage(message, kind) {
        const el = document.createElement("div");
        el.className = `flash flash-${kind} import-toast`;
        el.textContent = message;
        let container = document.querySelector(".toast-container");
        if (!container) {
            container = document.createElement("div");
            container.className = "toast-container";
            document.body.appendChild(container);
        }
        container.appendChild(el);
        window.setTimeout(() => el.remove(), 3500);
    }

    searchInput.addEventListener("input", () => {
        searchQuery = searchInput.value.trim();
        currentPage = 1;
        render();
    });

    statusFilterEl.addEventListener("click", (event) => {
        const btn = event.target.closest(".BtnGroup-item");
        if (!btn) return;
        statusFilterEl.querySelectorAll(".BtnGroup-item").forEach((el) => el.classList.remove("is-active"));
        btn.classList.add("is-active");
        statusFilter = btn.dataset.status;
        currentPage = 1;
        render();
    });

    pageSizeSelect.addEventListener("change", () => {
        pageSize = Number(pageSizeSelect.value);
        currentPage = 1;
        render();
    });

    deleteBtn.addEventListener("click", () => {
        if (!currentLogId) return;
        if (!window.confirm("Delete all data from this import? This action cannot be undone.")) return;
        fetch(deleteUrl(currentLogId), { method: "DELETE" })
            .then((res) => res.json())
            .then(() => {
                close();
                flashMessage("Import data deleted.", "success");
                if (window.dyeingHub) window.dyeingHub.refreshWidgets();
            })
            .catch(() => flashMessage("Delete failed — check your connection.", "error"));
    });

    reuploadBtn.addEventListener("click", () => {
        close();
        const importModal = document.getElementById("import-modal");
        if (importModal) importModal.classList.remove("d-none");
    });

    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });

    window.rawDataDrawer = { open, close };
}());
