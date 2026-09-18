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
    const stageToggle = document.getElementById("stage-toggle");
    const stageMenu = document.getElementById("stage-menu");
    const stageCheckboxes = [...document.querySelectorAll(".stage-checkbox")];
    const MAX_STAGE_LINES = 4; // Quy tắc line chart: tối đa 3-4 đường để tránh "spaghetti chart".
    let chartData = null;
    let achievementChart = null;
    let dataQualityChart = null;
    let latestAbnormalData = null;
    let unitMode = "hour";
    const globalUnitFilter = document.getElementById("globalUnitFilter");

    // Dropdown multi-select DATA-DRIVEN (option list lấy từ response API, khác Capacity ở
    // trên vốn là danh sách cố định render sẵn qua Jinja) — dùng chung cho Fabric Type và
    // Brand Program. "All" = bỏ chọn hết (selected rỗng, KHÔNG lọc), khác hẳn cơ chế
    // "check từng ô" của Capacity vì option list ở đây có thể đổi theo filter ngày/capacity.
    function makeMultiSelectDropdown(toggleId, menuId, defaultLabel) {
        const toggle = document.getElementById(toggleId);
        const menu = document.getElementById(menuId);
        let selected = new Set();
        let options = [];
        function updateLabel() {
            if (selected.size === 0) toggle.textContent = defaultLabel;
            else if (selected.size === 1) toggle.textContent = [...selected][0];
            else toggle.textContent = `${selected.size} selected`;
        }
        function render() {
            menu.innerHTML = options.length
                ? `<label class="capacity-option"><input type="checkbox" class="ms-all-option" ${selected.size === 0 ? "checked" : ""}> All</label><div class="border-top my-1"></div>` +
                  options.map((value) => `<label class="capacity-option"><input type="checkbox" class="ms-option" value="${escAttr(value)}" ${selected.has(value) ? "checked" : ""}> ${escHtml(value)}</label>`).join("")
                : `<span class="f6 color-fg-muted" style="padding:6px 8px;display:block;">No data</span>`;
            const allBox = menu.querySelector(".ms-all-option");
            if (allBox) allBox.addEventListener("change", () => {
                if (allBox.checked) { selected.clear(); render(); updateLabel(); load(); }
                else { allBox.checked = true; }
            });
            menu.querySelectorAll(".ms-option").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) selected.add(box.value); else selected.delete(box.value);
                render();
                updateLabel();
                load();
            }));
        }
        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            menu.hidden = !menu.hidden;
            toggle.setAttribute("aria-expanded", String(!menu.hidden));
        });
        document.addEventListener("click", (event) => {
            if (!toggle.parentElement.contains(event.target)) {
                menu.hidden = true;
                toggle.setAttribute("aria-expanded", "false");
            }
        });
        updateLabel();
        return {
            selected: () => [...selected],
            setOptions(newOptions) {
                options = newOptions || [];
                // Loại lựa chọn cũ không còn xuất hiện trong option list mới (VD đổi khoảng
                // ngày khiến Fabric Type/Brand Program cũ không còn dữ liệu nào).
                selected = new Set([...selected].filter((value) => options.includes(value)));
                render();
                updateLabel();
            },
        };
    }
    const fabricTypeFilter = makeMultiSelectDropdown("fabric-type-toggle", "fabric-type-menu", "All fabric types");
    const brandProgramFilter = makeMultiSelectDropdown("brand-program-toggle", "brand-program-menu", "All brand programs");

    function pad2(value) { return String(value).padStart(2, "0"); }
    function formatDate(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
    function mondayOf(d) {
        const date = new Date(d);
        const isoDay = (date.getDay() + 6) % 7; // Monday=0 ... Sunday=6
        date.setDate(date.getDate() - isoDay);
        date.setHours(0, 0, 0, 0);
        return date;
    }
    function defaultDateRange() {
        // Mặc định 6 tuần tính từ tuần hiện tại (5 tuần trước + tuần hiện tại, Mon-Sun).
        const currentWeekStart = mondayOf(new Date());
        const from = new Date(currentWeekStart);
        from.setDate(from.getDate() - 5 * 7);
        const to = new Date(currentWeekStart);
        to.setDate(to.getDate() + 6);
        return { from: formatDate(from), to: formatDate(to) };
    }

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
            fabric_types: fabricTypeFilter.selected().join(","),
            brand_programs: brandProgramFilter.selected().join(","),
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

    function targetValueOf(row, useHours) {
        const value = useHours ? row.target_hours : row.target_pct;
        return value === null || value === undefined ? null : Number(value);
    }

    function formatTargetText(target, useHours) {
        return target === null ? "-" : (useHours ? target.toFixed(2) : `${target.toFixed(1)}%`);
    }

    function renderTargetCell(row, useHours) {
        const target = targetValueOf(row, useHours);
        const text = formatTargetText(target, useHours);
        if (!window.DOWNTIME_IS_ADMIN) return `<td>${text}</td>`;
        return `<td><span class="target-cell" data-category="${escAttr(row.category)}">${text}</span></td>`;
    }

    function renderTable(data) {
        const head = document.getElementById("pivot-head");
        head.innerHTML = "<th>Category</th><th>Target</th>" + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        const useHours = unitMode === "hour";
        const periodKeys = data.period_keys || [];
        document.querySelector("#pivot-table tbody").innerHTML = data.rows.map((row) => {
            const target = targetValueOf(row, useHours);
            const values = useHours ? row.values_hours : row.values;
            const cells = values.map((value, index) => {
                if (value === null) return `<td>-</td>`;
                const over = target !== null && Number(value) > target;
                const text = useHours ? Number(value).toFixed(2) : `${Number(value).toFixed(1)}%`;
                const periodKey = periodKeys[index];
                const cls = ["cell-clickable", over ? "cell-over-target" : ""].filter(Boolean).join(" ");
                if (!periodKey) return `<td class="${over ? "cell-over-target" : ""}">${text}</td>`;
                return `<td class="${cls}" data-period="${escAttr(periodKey)}" data-category="${escAttr(row.category)}">${text}</td>`;
            }).join("");
            const totalValue = useHours ? row.total_hours : row.total_pct;
            const totalOver = target !== null && Number(totalValue) > target;
            return `<tr><th>${row.category}</th>${renderTargetCell(row, useHours)}${cells}<td class="${totalOver ? "cell-over-target" : ""}"><strong>${useHours ? Number(row.total_hours).toFixed(2) : `${Number(row.total_pct).toFixed(1)}%`}</strong></td></tr>`;
        }).join("") + `<tr class="total-row"><th>Total</th><td>-</td>${(useHours ? data.total_row_hours : data.total_row).map((value) => `<td><strong>${useHours ? (value === null ? "-" : Number(value).toFixed(2)) : `${Number(value).toFixed(1)}%`}</strong></td>`).join("")}<td><strong>${useHours ? Number(data.kpis.downtime_hours_per_batch).toFixed(2) : `${data.kpis.downtime_rate_pct.toFixed(1)}%`}</strong></td></tr>`;
    }

    function startEditingTarget(cell) {
        const category = cell.dataset.category;
        const row = (chartData && chartData.rows || []).find((item) => item.category === category);
        if (!row) return;
        const useHours = unitMode === "hour";
        const currentValue = targetValueOf(row, useHours);
        const input = document.createElement("input");
        input.type = "number";
        input.step = "0.1";
        input.className = "target-input";
        input.value = currentValue === null ? "" : currentValue;
        cell.replaceWith(input);
        input.focus();
        input.select();

        let settled = false;
        function commit() {
            if (settled) return;
            settled = true;
            saveTarget(input, row, useHours, input.value.trim());
        }
        function cancel() {
            if (settled) return;
            settled = true;
            input.replaceWith(buildTargetCellSpan(row, useHours));
        }
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") { event.preventDefault(); input.blur(); }
            if (event.key === "Escape") { event.preventDefault(); cancel(); }
        });
    }

    function buildTargetCellSpan(row, useHours) {
        const span = document.createElement("span");
        span.className = "target-cell";
        span.dataset.category = row.category;
        span.textContent = formatTargetText(targetValueOf(row, useHours), useHours);
        return span;
    }

    function saveTarget(inputEl, row, useHours, newValueText) {
        const parsed = newValueText === "" ? 0 : Number(newValueText);
        if (Number.isNaN(parsed)) {
            inputEl.replaceWith(buildTargetCellSpan(row, useHours));
            showToast("Target must be a number.", "error");
            return;
        }
        const targetPct = useHours ? (row.target_pct ?? 0) : parsed;
        const targetHours = useHours ? parsed : (row.target_hours ?? 0);
        fetch(window.DOWNTIME_TARGETS_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category: row.category, target_pct: targetPct, target_hours: targetHours }),
        }).then((response) => {
            if (!response.ok) throw new Error("save failed");
            return response.json();
        }).then(() => {
            row.target_pct = targetPct;
            row.target_hours = targetHours;
            renderTable(chartData);
            showToast("Target saved.", "success");
        }).catch(() => {
            inputEl.replaceWith(buildTargetCellSpan(row, useHours));
            showToast("Failed to save target.", "error");
        });
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
    // Category ("Downtime by Category") hoặc field ("loading"/"unloading" của Data
    // Quality) đang xem trong modal — PHẢI gửi kèm khi lưu note để note lưu ĐÚNG
    // context, không bị dùng chung cho mọi category của cùng 1 mẻ (bug đã sửa).
    let activeCaseContext = "";

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
        activeCaseContext = category;
        const params = new URLSearchParams({
            period: periodKey,
            group_by: document.getElementById("group-by").value,
            category: category,
            capacities: selectedCapacities().join(","),
            fabric_types: fabricTypeFilter.selected().join(","),
            brand_programs: brandProgramFilter.selected().join(","),
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
            body: JSON.stringify({ context: activeCaseContext, reason, detail }),
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
        const targetCell = event.target.closest(".target-cell");
        if (targetCell) { startEditingTarget(targetCell); return; }
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
        activeCaseContext = field;
        const params = new URLSearchParams({
            field,
            capacities: selectedCapacities().join(","),
            fabric_types: fabricTypeFilter.selected().join(","),
            brand_programs: brandProgramFilter.selected().join(","),
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

    let abnormalPointSeq = 0;
    async function loadAbnormalPoint() {
        // Bấm đổi filter (VD Group By Day <-> Week) liên tiếp bắn ra nhiều fetch() chồng
        // nhau — request CHẬM hơn (VD Day, nhiều kỳ hơn) có thể resolve SAU request nhanh
        // hơn (VD Week) dù được bắn TRƯỚC, khiến DOM bị response CŨ ghi đè sau response MỚI
        // -> bảng hiển thị dữ liệu không khớp filter đang chọn. Đánh số thứ tự mỗi lần gọi,
        // chỉ áp dụng response nếu vẫn là lần gọi MỚI NHẤT tại thời điểm resolve.
        const seq = ++abnormalPointSeq;
        const response = await fetch(`${window.DOWNTIME_ABNORMAL_POINT_API_URL}?${filters()}`);
        if (seq !== abnormalPointSeq || !response.ok) return;
        const data = await response.json();
        if (seq !== abnormalPointSeq) return;
        latestAbnormalData = data;
        renderAbnormalPointTable(data);
        updateDataQualityChart(data);
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

    function selectedStages() {
        return stageCheckboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
    }

    function updateStageLabel() {
        const count = selectedStages().length;
        stageToggle.textContent = count ? `${count} selected` : "Select stage";
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

    function chartTextColors() {
        const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
        const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#abaebb";
        const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
        return { textColor, gridColor };
    }

    function updateAchievementChart(data) {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById("achievementChart");
        if (!canvas) return;
        const periods = data.achievement.periods;
        const selected = selectedStages();
        // Quy tắc line chart: tối đa MAX_STAGE_LINES đường/biểu đồ — lọc theo stage đã chọn
        // (mặc định 4/6 stage) để tránh "spaghetti chart" thay vì luôn vẽ cả 6.
        const breakdown = data.achievement.breakdown.filter((row) => selected.includes(row.stage));
        const colors = ["#2862d7", "#625fff", "#3fb950", "#d29922", "#db61a2", "#f778ba"];
        const allStages = data.achievement.breakdown.map((row) => row.stage);
        const datasets = breakdown.map((row) => {
            const index = allStages.indexOf(row.stage);
            return {
                label: row.stage,
                data: row.values,
                borderColor: colors[index % colors.length],
                backgroundColor: colors[index % colors.length],
                borderWidth: 2,
                tension: 0.35,
                fill: false,
                spanGaps: true,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: colors[index % colors.length],
            };
        });
        if (achievementChart) achievementChart.destroy();
        const { textColor, gridColor } = chartTextColors();
        achievementChart = new Chart(canvas, {
            type: "line",
            data: { labels: periods, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, max: 100, ticks: { color: textColor }, grid: { color: gridColor }, title: { display: true, text: "Achievement (%)", color: textColor } },
                },
                plugins: { legend: { position: "bottom", labels: { color: textColor, usePointStyle: true } } },
            },
        });
    }

    function updateDataQualityChart(data) {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById("dataQualityChart");
        if (!canvas) return;
        const fieldColors = { loading: "#d29922", unloading: "#db61a2" };
        const datasets = (data.rows || []).map((row) => ({
            label: row.label,
            data: row.values,
            backgroundColor: fieldColors[row.field] || "#2862d7",
            borderColor: fieldColors[row.field] || "#2862d7",
            borderWidth: 1,
        }));
        if (dataQualityChart) dataQualityChart.destroy();
        const { textColor, gridColor } = chartTextColors();
        dataQualityChart = new Chart(canvas, {
            type: "bar",
            data: { labels: data.periods || [], datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: textColor, precision: 0 }, grid: { color: gridColor }, title: { display: true, text: "Number of batches", color: textColor } },
                },
                plugins: { legend: { position: "bottom", labels: { color: textColor, usePointStyle: true } } },
            },
        });
    }

    const pageTabsNav = document.getElementById("downtime-tabs");
    const pageTabs = pageTabsNav ? [...pageTabsNav.querySelectorAll(".page-tab")] : [];
    const downtimePages = [...document.querySelectorAll(".downtime-page")];
    let activePageIndex = 0;

    function activatePage(index) {
        index = Math.max(0, Math.min(downtimePages.length - 1, index));
        activePageIndex = index;
        pageTabs.forEach((tab, i) => tab.classList.toggle("is-active", i === index));
        downtimePages.forEach((page, i) => { page.hidden = i !== index; });
        // Chart.js đo kích thước container lúc vẽ — canvas ở trang vừa hiện lại
        // trước đó có thể 0x0 (bị "hidden"), phải resize lại sau khi hiện ra.
        requestAnimationFrame(() => {
            if (index === 0 && chart) chart.resize();
            if (index === 1 && achievementChart) achievementChart.resize();
            if (index === 2 && dataQualityChart) dataQualityChart.resize();
        });
    }

    if (pageTabsNav) {
        pageTabs.forEach((tab, index) => tab.addEventListener("click", () => activatePage(index)));

        let wheelLocked = false;
        pageTabsNav.addEventListener("wheel", (event) => {
            if (Math.abs(event.deltaY) < 2) return;
            event.preventDefault();
            if (wheelLocked) return;
            wheelLocked = true;
            activatePage(activePageIndex + (event.deltaY > 0 ? 1 : -1));
            window.setTimeout(() => { wheelLocked = false; }, 450);
        }, { passive: false });
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

    let loadSeq = 0;
    async function load() {
        // Cùng lý do với loadAbnormalPoint(): bấm đổi Group By/Date/Capacity liên tiếp bắn
        // nhiều fetch() chồng nhau, response CHẬM hơn có thể resolve SAU và ghi đè DOM bằng
        // dữ liệu của filter đã cũ. Đánh số thứ tự, bỏ qua response không còn là lần gọi mới nhất.
        const seq = ++loadSeq;
        const response = await fetch(`${window.DOWNTIME_API_URL}?${filters()}`);
        if (seq !== loadSeq || !response.ok) return;
        const data = await response.json();
        if (seq !== loadSeq) return;
        fabricTypeFilter.setOptions(data.available_fabric_types || []);
        brandProgramFilter.setOptions(data.available_brand_programs || []);
        document.getElementById("planned-hours").textContent = data.kpis.planned_hours.toFixed(1);
        document.getElementById("downtime-hours").textContent = data.kpis.downtime_hours.toFixed(1);
        document.getElementById("downtime-rate").textContent = `${data.kpis.downtime_rate_pct.toFixed(1)}%`;
        document.getElementById("valid-batches").textContent = data.kpis.valid_batches.toLocaleString();
        document.getElementById("achievement-rate").textContent = `${data.kpis.achievement_rate_pct.toFixed(1)}%`;
        renderTable(data);
        renderAchievement(data);
        chartData = data;
        updateChart(selectedCategories());
        updateAchievementChart(data);
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
    stageToggle.addEventListener("click", () => {
        stageMenu.hidden = !stageMenu.hidden;
        stageToggle.setAttribute("aria-expanded", String(!stageMenu.hidden));
    });
    stageCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
        if (checkbox.checked && selectedStages().length > MAX_STAGE_LINES) {
            checkbox.checked = false;
            showToast(`Line chart is limited to ${MAX_STAGE_LINES} stages at once — deselect one first.`, "error");
            return;
        }
        updateStageLabel();
        if (chartData) updateAchievementChart(chartData);
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
            stageMenu.hidden = true;
            stageToggle.setAttribute("aria-expanded", "false");
        }
    });
    ["from-date", "to-date", "group-by"].forEach((id) => document.getElementById(id).addEventListener("change", load));
    document.addEventListener("colormodechange", () => {
        updateChart(selectedCategories());
        if (chartData) updateAchievementChart(chartData);
        if (latestAbnormalData) updateDataQualityChart(latestAbnormalData);
    });
    updateCapacityLabel();
    updateCategoryLabel();
    updateStageLabel();
    const defaultRange = defaultDateRange();
    document.getElementById("from-date").value = defaultRange.from;
    document.getElementById("to-date").value = defaultRange.to;
    load();
}());