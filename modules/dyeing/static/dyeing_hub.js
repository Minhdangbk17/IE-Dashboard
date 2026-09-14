// dyeing_hub.js
// ---------------------------------------------------------------------------
// Điều khiển Trang Hub Tổng quan Nhuộm:
//   1. Gọi song song (Promise.all) tới các API Endpoint của từng Engine
//      (OEE, Downtime) bằng fetch() để nạp dữ liệu vào Widget mà không gây
//      nghẽn trang (mỗi Engine tự chịu trách nhiệm dữ liệu của mình).
//   2. Mở/đóng Modal Import Excel (logic chi tiết nằm trong import_modal.js).
// ---------------------------------------------------------------------------
(function () {
    "use strict";

    const widgetsEl = document.getElementById("hub-widgets");
    if (!widgetsEl) return;

    const oeeUrl = widgetsEl.dataset.oeeUrl;
    const downtimeUrl = widgetsEl.dataset.downtimeUrl;
    const batchMatrixUrl = widgetsEl.dataset.batchMatrixUrl;

    async function loadOeeWidget() {
        const tbody = document.querySelector("#oee-table tbody");
        try {
            const res = await fetch(oeeUrl);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            document.getElementById("oee-value").textContent = `${data.overall_oee_pct}%`;

            tbody.innerHTML = "";
            if (!data.machines.length) {
                tbody.innerHTML = '<tr><td colspan="2" class="color-fg-muted">No data yet.</td></tr>';
                return;
            }
            data.machines.forEach((m) => {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td>${m.machine_id}</td><td>${m.oee_pct}%</td>`;
                tbody.appendChild(tr);
            });
        } catch (err) {
            console.error("Lỗi tải widget OEE:", err);
            document.getElementById("oee-value").textContent = "Error";
            tbody.innerHTML = '<tr><td colspan="2" class="row-error">Failed to load OEE data.</td></tr>';
        }
    }

    async function loadDowntimeWidget() {
        const tbody = document.querySelector("#downtime-table tbody");
        try {
            const res = await fetch(downtimeUrl);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            document.getElementById("downtime-total").textContent = `${data.kpis.downtime_hours} hours`;

            tbody.innerHTML = "";
            const top5 = data.rows
                .map((row) => ({ name: row.category, total: row.total_pct }))
                .sort((a, b) => b.total - a.total)
                .slice(0, 5);
            if (!top5.length) {
                tbody.innerHTML = '<tr><td colspan="2" class="color-fg-muted">No data yet.</td></tr>';
                return;
            }
            top5.forEach((p) => {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td>${p.name}</td><td>${p.total.toFixed(1)}%</td>`;
                tbody.appendChild(tr);
            });
        } catch (err) {
            console.error("Lỗi tải widget Downtime:", err);
            document.getElementById("downtime-total").textContent = "Error";
            tbody.innerHTML = '<tr><td colspan="2" class="row-error">Failed to load Downtime data.</td></tr>';
        }
    }

    async function loadBatchMatrixWidget() {
        const tbody = document.querySelector("#batch-matrix-table tbody");
        try {
            const res = await fetch(batchMatrixUrl);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            document.getElementById("batch-matrix-value").textContent = data.grand_total === null || data.grand_total === undefined ? "--" : Number(data.grand_total).toFixed(2);

            tbody.innerHTML = "";
            const fabricTotals = (data.rows || []).filter((row) => row.row_type === "fabric_total");
            if (!fabricTotals.length) {
                tbody.innerHTML = '<tr><td colspan="2" class="color-fg-muted">No data yet.</td></tr>';
                return;
            }
            fabricTotals.forEach((row) => {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td>${row.fabric_type}</td><td>${row.total === null ? "-" : Number(row.total).toFixed(2)}</td>`;
                tbody.appendChild(tr);
            });
        } catch (err) {
            console.error("Lỗi tải widget Batch Matrix:", err);
            document.getElementById("batch-matrix-value").textContent = "Error";
            tbody.innerHTML = '<tr><td colspan="2" class="row-error">Failed to load Batch Matrix data.</td></tr>';
        }
    }

    // Gọi song song — KHÔNG await tuần tự — để trang không bị nghẽn chờ engine chậm nhất.
    Promise.all([loadOeeWidget(), loadDowntimeWidget(), loadBatchMatrixWidget()]);

    // Expose để import_modal.js gọi refresh lại widget sau khi import thành công.
    window.dyeingHub = {
        refreshWidgets: function refreshWidgets() {
            Promise.all([loadOeeWidget(), loadDowntimeWidget(), loadBatchMatrixWidget()]);
        },
    };

    // --- Mở/đóng modal Import ---
    const openBtn = document.getElementById("btn-open-import");
    const modal = document.getElementById("import-modal");
    const closeBtn = document.getElementById("btn-close-import");
    const cancelBtn = document.getElementById("btn-cancel-import");

    if (openBtn && modal) {
        openBtn.addEventListener("click", () => modal.classList.remove("d-none"));
    }
    [closeBtn, cancelBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => modal.classList.add("d-none"));
    });

    // --- Mở/đóng modal Export + tải file .xlsx theo Data Type/khoảng ngày đã chọn ---
    const exportOpenBtn = document.getElementById("btn-open-export");
    const exportModal = document.getElementById("export-modal");
    const exportCloseBtn = document.getElementById("btn-close-export");
    const exportCancelBtn = document.getElementById("btn-cancel-export");
    const exportConfirmBtn = document.getElementById("btn-confirm-export");
    const exportError = document.getElementById("export-error");

    function closeExportModal() {
        exportModal.classList.add("d-none");
        exportError.classList.add("d-none");
    }

    if (exportOpenBtn && exportModal) {
        exportOpenBtn.addEventListener("click", () => exportModal.classList.remove("d-none"));
    }
    [exportCloseBtn, exportCancelBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", closeExportModal);
    });
    if (exportConfirmBtn) {
        exportConfirmBtn.addEventListener("click", () => {
            const dataType = document.getElementById("export-data-type").value;
            const fromDate = document.getElementById("export-from-date").value;
            const toDate = document.getElementById("export-to-date").value;
            if (!fromDate || !toDate) {
                exportError.textContent = "Vui lòng chọn đủ Từ ngày và Đến ngày.";
                exportError.classList.remove("d-none");
                return;
            }
            exportError.classList.add("d-none");
            const params = new URLSearchParams({ data_type: dataType, from_date: fromDate, to_date: toDate });
            window.location.href = `${exportModal.dataset.exportUrl}?${params}`;
            closeExportModal();
        });
    }
})();
