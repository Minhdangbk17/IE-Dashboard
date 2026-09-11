(function () {
    "use strict";

    const categories = ["Rework", "Color Adjustment", "Sample checking", "Fabric loading", "Fabric unloading", "Bleaching/Washing", "PH checking", "Chemical load", "Others"];
    const ABNORMAL_POINT_LABELS = { loading: "Cases Loading = 0", unloading: "Cases Unloading = 0" };
    let chart;
    const capacityToggle = document.getElementById("capacity-toggle");
    const capacityMenu = document.getElementById("capacity-menu");
    const capacityAll = document.getElementById("capacity-all");
    const capacityCheckboxes = [...document.querySelectorAll(".capacity-checkbox")];
    const categoryToggle = document.getElementById("category-toggle");
    const categoryMenu = document.getElementById("category-menu");
    const categoryAll = document.getElementById("category-all");
    const categoryCheckboxes = [...document.querySelectorAll(".category-checkbox")];
    let chartData = null;
    let unitMode = "hour";
    const globalUnitFilter = document.getElementById("globalUnitFilter");

    function selectedCapacities() {
        return capacityCheckboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
    }

    function updateCapacityLabel() {
        const selected = selectedCapacities();
        capacityAll.checked = selected.length === capacityCheckboxes.length;
        if (selected.length === 0) capacityToggle.textContent = "Select capacity";
        else if (selected.length === capacityCheckboxes.length) capacityToggle.textContent = "All capacities";
        else if (selected.length <= 2) capacityToggle.textContent = `${selected.join(", ")} Kg`;
        else capacityToggle.textContent = `${selected.length} selected`;
    }

    function filters() {
        return new URLSearchParams({
            capacities: selectedCapacities().join(","),
            from_date: document.getElementById("from-date").value,
            to_date: document.getElementById("to-date").value,
            group_by: document.getElementById("group-by").value
        });
    }

    function escAttr(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }

    function escHtml(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function truncateText(value, maxLength) {
        const text = String(value ?? "");
        return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
    }

    function renderTable(data) {
        const head = document.getElementById("pivot-head");
        head.innerHTML = "<th>Category</th>" + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        const useHours = unitMode === "hour";
        const periodKeys = data.period_keys || [];
        document.querySelector("#pivot-table tbody").innerHTML = data.rows.map((row) => {
            const values = useHours ? row.values_hours : row.values;
            const cells = values.map((value, index) => {
                if (value === null) return `<td>-</td>`;
                const text = useHours ? Number(value).toFixed(2) : `${Number(value).toFixed(1)}%`;
                const periodKey = periodKeys[index];
                if (!periodKey) return `<td>${text}</td>`;
                return `<td class="cell-clickable" data-period="${escAttr(periodKey)}" data-category="${escAttr(row.category)}">${text}</td>`;
            }).join("");
            return `<tr><th>${row.category}</th>${cells}<td><strong>${useHours ? Number(row.total_hours).toFixed(2) : `${Number(row.total_pct).toFixed(1)}%`}</strong></td></tr>`;
        }).join("") + `<tr class="total-row"><th>Total</th>${(useHours ? data.total_row_hours : data.total_row).map((value) => `<td><strong>${useHours ? (value === null ? "-" : Number(value).toFixed(2)) : `${Number(value).toFixed(1)}%`}</strong></td>`).join("")}<td><strong>${useHours ? Number(data.total_row_hours.reduce((sum, value) => sum + (value || 0), 0)).toFixed(2) : `${data.kpis.downtime_rate_pct.toFixed(1)}%`}</strong></td></tr>`;
    }

    const topBatchesOverlay = document.getElementById("top-batches-overlay");
    const topBatchesTitle = document.getElementById("top-batches-title");
    const topBatchesBody = document.getElementById("top-batches-body");
    function closeTopBatches() { topBatchesOverlay.hidden = true; }
    document.getElementById("top-batches-close").addEventListener("click", closeTopBatches);
    topBatchesOverlay.addEventListener("click", (event) => { if (event.target === topBatchesOverlay) closeTopBatches(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !topBatchesOverlay.hidden) closeTopBatches(); });

    function toastContainer() {
        let el = document.querySelector(".toast-container");
        if (!el) {
            el = document.createElement("div");
            el.className = "toast-container";
            document.body.appendChild(el);
        }
        return el;
    }

    function showToast(message, kind) {
        const element = document.createElement("div");
        element.className = `flash flash-${kind || "success"} import-toast`;
        element.textContent = message;
        toastContainer().appendChild(element);
        window.setTimeout(() => element.remove(), 4000);
    }

    let topBatchesCategory = "";
    let activeCaseRows = [];

    function caseNoteUrl(logId) {
        return window.DOWNTIME_CASE_NOTE_URL_TEMPLATE.replace(/\/0$/, `/${logId}`);
    }

    function renderCaseNoteCell(batch, field) {
        const value = field === "reason" ? (batch.case_reason || "") : (batch.case_detail || "");
        const displayText = field === "detail" ? truncateText(value, 45) : value;
        const tooltip = batch.case_updated_by
            ? ` title="Edited by ${escAttr(batch.case_updated_by)} at ${escAttr(batch.case_updated_at)}"`
            : (field === "detail" && value ? ` title="${escAttr(value)}"` : "");
        if (!window.DOWNTIME_CAN_EDIT_NOTES) {
            return `<td${tooltip}>${escHtml(displayText)}</td>`;
        }
        const placeholder = value ? "" : `<span class="case-note-empty">Click to add</span>`;
        return `<td${tooltip}><span class="case-note-cell" data-log-id="${batch.availability_log_id}" data-field="${field}">${escHtml(displayText) || placeholder}</span></td>`;
    }

    function renderTopBatchesTable() {
        topBatchesBody.innerHTML = `<p class="f6 color-fg-muted">${activeCaseRows.length} batches (cross-checked directly against raw data).</p>` +
            `<table class="preview-table"><thead><tr><th>#</th><th>Batch</th><th>Machine</th><th>Capacity (Kg)</th><th>${escHtml(topBatchesCategory)} Hours</th><th>Reason</th><th>Detail</th><th>Start</th><th>End</th></tr></thead><tbody>` +
            activeCaseRows.map((batch, index) => `<tr><td>${index + 1}</td><td>${escHtml(batch.batch) || "-"}</td><td>${escHtml(batch.machine) || "-"}</td><td>${batch.capacity_kg ?? "-"}</td><td>${Number(batch.category_hours).toFixed(2)}</td>${renderCaseNoteCell(batch, "reason")}${renderCaseNoteCell(batch, "detail")}<td>${escHtml(batch.start_time) || "-"}</td><td>${escHtml(batch.end_time) || "-"}</td></tr>`).join("") +
            `</tbody></table>`;
    }

    function openTopBatches(periodKey, category) {
        const idx = chartData && chartData.period_keys ? chartData.period_keys.indexOf(periodKey) : -1;
        const label = idx >= 0 ? chartData.periods[idx] : periodKey;
        topBatchesTitle.textContent = `Top 10 — ${category} — ${label}`;
        topBatchesBody.innerHTML = `<p class="color-fg-muted">Loading...</p>`;
        topBatchesOverlay.hidden = false;
        const params = new URLSearchParams({
            period: periodKey,
            group_by: document.getElementById("group-by").value,
            category: category,
            capacities: selectedCapacities().join(","),
        });
        fetch(`${window.DOWNTIME_TOP_BATCHES_API_URL}?${params}`).then((response) => response.json()).then((batches) => {
            if (!Array.isArray(batches) || !batches.length) {
                activeCaseRows = [];
                topBatchesBody.innerHTML = `<p class="color-fg-muted">No batches match the current filters.</p>`;
                return;
            }
            topBatchesCategory = category;
            activeCaseRows = batches;
            renderTopBatchesTable();
        }).catch(() => { topBatchesBody.innerHTML = `<p class="color-fg-muted">Failed to load batches.</p>`; });
    }

    function startEditingCaseNote(cell) {
        const field = cell.dataset.field;
        const logId = cell.dataset.logId;
        const row = activeCaseRows.find((batch) => String(batch.availability_log_id) === String(logId));
        if (!row) return;
        const currentValue = (field === "reason" ? row.case_reason : row.case_detail) || "";
        const isDetail = field === "detail";
        const input = document.createElement(isDetail ? "textarea" : "input");
        if (!isDetail) input.type = "text";
        input.className = "case-note-input";
        input.value = currentValue;
        cell.parentElement.classList.add("case-note-editing");
        cell.replaceWith(input);
        input.focus();
        input.select();

        let settled = false;
        function commit() {
            if (settled) return;
            settled = true;
            saveCaseNote(input, row, field, input.value.trim());
        }
        function cancel() {
            if (settled) return;
            settled = true;
            input.parentElement.classList.remove("case-note-editing");
            input.replaceWith(buildCaseNoteCellSpan(row, field));
        }
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !isDetail) { event.preventDefault(); input.blur(); }
            if (event.key === "Escape") { event.preventDefault(); cancel(); }
        });
    }

    function buildCaseNoteCellSpan(row, field) {
        const value = (field === "reason" ? row.case_reason : row.case_detail) || "";
        const displayText = field === "detail" ? truncateText(value, 45) : value;
        const span = document.createElement("span");
        span.className = "case-note-cell";
        span.dataset.logId = row.availability_log_id;
        span.dataset.field = field;
        if (value) {
            span.textContent = displayText;
        } else {
            span.innerHTML = `<span class="case-note-empty">Click to add</span>`;
        }
        return span;
    }

    function saveCaseNote(inputEl, row, field, newValue) {
        const reason = field === "reason" ? newValue : (row.case_reason || "");
        const detail = field === "detail" ? newValue : (row.case_detail || "");
        fetch(caseNoteUrl(row.availability_log_id), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason, detail }),
        }).then((response) => {
            if (!response.ok) throw new Error("save failed");
            return response.json();
        }).then((data) => {
            row.case_reason = data.note.reason;
            row.case_detail = data.note.detail;
            row.case_updated_by = data.note.updated_by;
            row.case_updated_at = data.note.updated_at;
            inputEl.parentElement.classList.remove("case-note-editing");
            inputEl.replaceWith(buildCaseNoteCellSpan(row, field));
            showToast("Note saved.", "success");
        }).catch(() => {
            inputEl.parentElement.classList.remove("case-note-editing");
            inputEl.replaceWith(buildCaseNoteCellSpan(row, field));
            showToast("Failed to save note.", "error");
        });
    }

    topBatchesBody.addEventListener("click", (event) => {
        const cell = event.target.closest(".case-note-cell");
        if (!cell) return;
        startEditingCaseNote(cell);
    });

    document.querySelector("#pivot-table tbody").addEventListener("click", (event) => {
        const cell = event.target.closest("td.cell-clickable");
        if (!cell) return;
        openTopBatches(cell.dataset.period, cell.dataset.category);
    });

    function renderDataQualityDrilldownTable() {
        topBatchesBody.innerHTML = `<p class="f6 color-fg-muted">${activeCaseRows.length} batches (cross-checked directly against raw data).</p>` +
            `<table class="preview-table"><thead><tr><th>Machine</th><th>Production Date</th><th>Fabric Type</th><th>Batch</th><th>Customer</th><th>ColourNo</th><th>Loading (h)</th><th>Unloading (h)</th><th>Reason</th><th>Detail</th><th>Start</th><th>End</th></tr></thead><tbody>` +
            activeCaseRows.map((batch) => `<tr><td>${escHtml(batch.machine) || "-"}</td><td>${escHtml(batch.production_date) || "-"}</td><td>${escHtml(batch.fabric_type) || "-"}</td><td>${escHtml(batch.batch_ref_no || batch.batch) || "-"}</td><td>${escHtml(batch.customer) || "-"}</td><td>${escHtml(batch.colour_no) || "-"}</td><td>${Number(batch.load_hour).toFixed(2)}</td><td>${Number(batch.unload_hour).toFixed(2)}</td>${renderCaseNoteCell(batch, "reason")}${renderCaseNoteCell(batch, "detail")}<td>${escHtml(batch.start_time) || "-"}</td><td>${escHtml(batch.end_time) || "-"}</td></tr>`).join("") +
            `</tbody></table>`;
    }

    function openAbnormalPointBatches(field, label, periodKey) {
        topBatchesTitle.textContent = `Data Quality — ${label}`;
        topBatchesBody.innerHTML = `<p class="color-fg-muted">Loading...</p>`;
        topBatchesOverlay.hidden = false;
        const params = new URLSearchParams({
            field,
            capacities: selectedCapacities().join(","),
            group_by: document.getElementById("group-by").value,
        });
        if (periodKey) {
            params.set("period", periodKey);
        } else {
            params.set("from_date", document.getElementById("from-date").value);
            params.set("to_date", document.getElementById("to-date").value);
        }
        fetch(`${window.DOWNTIME_ABNORMAL_POINT_BATCHES_API_URL}?${params}`).then((response) => response.json()).then((batches) => {
            if (!Array.isArray(batches) || !batches.length) {
                activeCaseRows = [];
                topBatchesBody.innerHTML = `<p class="color-fg-muted">No batches match the current filters.</p>`;
                return;
            }
            activeCaseRows = batches;
            renderDataQualityDrilldownTable();
        }).catch(() => { topBatchesBody.innerHTML = `<p class="color-fg-muted">Failed to load batches.</p>`; });
    }

    function renderAbnormalPointTable(data) {
        const head = document.getElementById("abnormal-point-head");
        head.innerHTML = "<th>Data Quality</th>" + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        const periodKeys = data.period_keys || [];
        document.querySelector("#abnormal-point-table tbody").innerHTML = data.rows.map((row) => {
            const cells = row.values.map((value, index) => {
                const periodKey = periodKeys[index];
                if (!periodKey || !value) return `<td>${value || 0}</td>`;
                return `<td class="cell-clickable" data-period="${escAttr(periodKey)}" data-field="${escAttr(row.field)}">${value}</td>`;
            }).join("");
            return `<tr><th>${row.label}</th>${cells}<td><strong>${row.total}</strong></td></tr>`;
        }).join("") + `<tr class="total-row"><th>Total</th>${data.total_row.map((value) => `<td><strong>${value}</strong></td>`).join("")}<td><strong>${data.total_row.reduce((sum, value) => sum + (value || 0), 0)}</strong></td></tr>`;
    }

    async function loadAbnormalPoint() {
        const response = await fetch(`${window.DOWNTIME_ABNORMAL_POINT_API_URL}?${filters()}`);
        if (!response.ok) return;
        renderAbnormalPointTable(await response.json());
    }

    document.querySelector("#abnormal-point-table tbody").addEventListener("click", (event) => {
        const cell = event.target.closest("td.cell-clickable");
        if (!cell) return;
        openAbnormalPointBatches(cell.dataset.field, ABNORMAL_POINT_LABELS[cell.dataset.field], cell.dataset.period);
    });

    function selectedCategories() {
        return categoryCheckboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
    }

    function updateCategoryLabel() {
        const selected = selectedCategories();
        categoryAll.checked = selected.length === categoryCheckboxes.length;
        categoryToggle.textContent = categoryAll.checked ? "All Categories" : selected.length ? `${selected.length} selected` : "Select category";
    }

    function updateChart(selected) {
        if (!chartData || typeof Chart === "undefined") return;
        const colors = { "Total Rate": "#ff7dda", "Rework": "#2862d7", "Color Adjustment": "#625fff", "Sample checking": "#3fb950", "Fabric loading": "#d29922", "Fabric unloading": "#db61a2", "Bleaching/Washing": "#85a6e9", "PH checking": "#f778ba", "Chemical load": "#79c0ff", "Others": "#abaebb" };
        const datasets = selected.map((name) => ({
            label: name === "Total Rate" ? "Total Downtime Rate" : name,
            data: (unitMode === "hour" ? chartData.datasets_hours : chartData.datasets)[name] || [],
            type: name === "Total Rate" ? "line" : "bar",
            backgroundColor: colors[name],
            borderColor: colors[name],
            borderWidth: name === "Total Rate" ? 2 : 1,
            pointRadius: name === "Total Rate" ? 3 : 0,
            yAxisID: "y",
        }));
        if (chart) chart.destroy();
        const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
        const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#abaebb";
        const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
        chart = new Chart(document.getElementById("downtimeChart"), {
            type: "bar",
            data: { labels: chartData.labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { stacked: true, ticks: { color: textColor }, grid: { color: gridColor } },
                            y: { stacked: true, beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor }, title: { display: true, text: unitMode === "hour" ? "Downtime hours / batch" : "Downtime rate (%)", color: textColor } },
                },
                plugins: { legend: { position: "bottom", labels: { color: textColor, usePointStyle: true } } },
            },
        });
    }

    function renderAchievement(data) {
        const head = document.getElementById("achievement-head");
        head.innerHTML = "<th>Stage</th>" + data.achievement.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        document.querySelector("#achievement-table tbody").innerHTML = data.achievement.breakdown.map((row) => {
            const cells = row.values.map((value) => `<td>${value === null ? "N/A" : `${value.toFixed(1)}%`}</td>`).join("");
            const total = row.rate_pct === null ? "N/A" : `${row.rate_pct.toFixed(1)}%`;
            return `<tr><th>${row.stage}</th>${cells}<td><strong>${total}</strong></td></tr>`;
        }).join("");
    }

    async function load() {
        const response = await fetch(`${window.DOWNTIME_API_URL}?${filters()}`);
        if (!response.ok) return;
        const data = await response.json();
        document.getElementById("planned-hours").textContent = data.kpis.planned_hours.toFixed(1);
        document.getElementById("downtime-hours").textContent = data.kpis.downtime_hours.toFixed(1);
        document.getElementById("downtime-rate").textContent = `${data.kpis.downtime_rate_pct.toFixed(1)}%`;
        document.getElementById("valid-batches").textContent = data.kpis.valid_batches.toLocaleString();
        document.getElementById("achievement-rate").textContent = `${data.kpis.achievement_rate_pct.toFixed(1)}%`;
        renderTable(data);
        renderAchievement(data);
        chartData = data;
        updateChart(selectedCategories());
        loadAbnormalPoint();
    }

    capacityToggle.addEventListener("click", () => {
        capacityMenu.hidden = !capacityMenu.hidden;
        capacityToggle.setAttribute("aria-expanded", String(!capacityMenu.hidden));
    });
    capacityAll.addEventListener("change", () => {
        capacityCheckboxes.forEach((checkbox) => { checkbox.checked = capacityAll.checked; });
        updateCapacityLabel();
        load();
    });
    capacityCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
        updateCapacityLabel();
        load();
    }));
    categoryToggle.addEventListener("click", () => {
        categoryMenu.hidden = !categoryMenu.hidden;
        categoryToggle.setAttribute("aria-expanded", String(!categoryMenu.hidden));
    });
    categoryAll.addEventListener("change", () => {
        categoryCheckboxes.forEach((checkbox) => { checkbox.checked = categoryAll.checked; });
        updateCategoryLabel();
        updateChart(selectedCategories());
    });
    categoryCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
        updateCategoryLabel();
        updateChart(selectedCategories());
    }));
    globalUnitFilter.querySelectorAll("[data-unit]").forEach((button) => button.addEventListener("click", () => {
        unitMode = button.dataset.unit;
        globalUnitFilter.querySelectorAll("[data-unit]").forEach((item) => {
            const active = item.dataset.unit === unitMode;
            item.classList.toggle("selected", active);
            item.setAttribute("aria-pressed", String(active));
        });
        if (chartData) {
            renderTable(chartData);
            updateChart(selectedCategories());
        }
    }));
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".capacity-dropdown")) {
            capacityMenu.hidden = true;
            capacityToggle.setAttribute("aria-expanded", "false");
        }
        if (!event.target.closest(".category-selector")) {
            categoryMenu.hidden = true;
            categoryToggle.setAttribute("aria-expanded", "false");
        }
    });
    ["from-date", "to-date", "group-by"].forEach((id) => document.getElementById(id).addEventListener("change", load));
    document.addEventListener("colormodechange", () => updateChart(selectedCategories()));
    updateCapacityLabel();
    updateCategoryLabel();
    load();
}());