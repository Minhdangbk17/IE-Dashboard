(function () {
    "use strict";

    const capacityToggle = document.getElementById("capacity-toggle");
    const capacityMenu = document.getElementById("capacity-menu");
    const capacityAll = document.getElementById("capacity-all");
    const capacityCheckboxes = [...document.querySelectorAll(".capacity-checkbox")];
    let charts = {}; // fabric_type -> Chart instance (1 biểu đồ riêng/loại vải)

    function escAttr(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }
    function escHtml(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function showToast(message, kind) {
        let container = document.querySelector(".toast-container");
        if (!container) { container = document.createElement("div"); container.className = "toast-container"; document.body.appendChild(container); }
        const el = document.createElement("div");
        el.className = `flash flash-${kind || "success"} import-toast`;
        el.textContent = message;
        container.appendChild(el);
        window.setTimeout(() => el.remove(), 4000);
    }

    // Dropdown multi-select DATA-DRIVEN (cùng cách trình bày với Capacity ở trên, nhưng
    // option list lấy từ response API) — dùng cho Fabric Type/Brand Program.
    function makeMultiSelectDropdown(toggleId, menuId, defaultLabel, onChange) {
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
                if (allBox.checked) { selected.clear(); render(); updateLabel(); onChange(); }
                else { allBox.checked = true; }
            });
            menu.querySelectorAll(".ms-option").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) selected.add(box.value); else selected.delete(box.value);
                render();
                updateLabel();
                onChange();
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
                selected = new Set([...selected].filter((value) => options.includes(value)));
                render();
                updateLabel();
            },
        };
    }
    const brandProgramFilter = makeMultiSelectDropdown("brand-program-toggle", "brand-program-menu", "All brand programs", load);

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
        // Mặc định 6 tuần tính từ tuần hiện tại — cùng quy ước với trang Downtime/RFT.
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
            brand_programs: brandProgramFilter.selected().join(","),
            from_date: document.getElementById("from-date").value,
            to_date: document.getElementById("to-date").value,
            group_by: document.getElementById("group-by").value,
        });
    }

    function chartTextColors() {
        const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
        const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#c7c9d1";
        const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
        return { textColor, gridColor };
    }

    // Màu cố định theo loại vải — DÙNG CHUNG cho đường số liệu (nét liền) và đường Target
    // tương ứng (nét đứt, cùng màu) — cùng bảng màu đã dùng cho Batch/Day Trend.
    const TANK_LOADING_FABRIC_COLORS = { Cotton: "#3fb950", CVC: "#2862d7", Polyester: "#f778ba" };
    let lastData = null;

    function tankLoadingTargetUrl(fabricType) {
        return window.TANK_LOADING_TARGET_URL_TEMPLATE.replace("__FABRIC__", encodeURIComponent(fabricType));
    }

    function formatTankLoadingTarget(value) {
        return value === null || value === undefined ? "-" : `${Number(value).toFixed(1)}%`;
    }

    function renderTargetCell(row) {
        const text = formatTankLoadingTarget(row.target);
        if (!window.TANK_LOADING_CAN_EDIT) return `<td>${text}</td>`;
        return `<td><span class="case-note-cell" data-fabric-type="${escAttr(row.fabric_type)}">${text}</span></td>`;
    }

    function buildTargetCellSpan(row) {
        const span = document.createElement("span");
        span.className = "case-note-cell";
        span.dataset.fabricType = row.fabric_type;
        span.textContent = formatTankLoadingTarget(row.target);
        return span;
    }

    function startEditingTarget(cell) {
        const fabricType = cell.dataset.fabricType;
        const row = (lastData && lastData.rows || []).find((item) => item.fabric_type === fabricType);
        if (!row) return;
        const input = document.createElement("input");
        input.type = "number";
        input.step = "0.1";
        input.className = "case-note-input";
        input.value = row.target === null || row.target === undefined ? "" : row.target;
        cell.replaceWith(input);
        input.focus();
        input.select();
        let settled = false;
        function commit() { if (settled) return; settled = true; saveTarget(input, row, input.value.trim()); }
        function cancel() { if (settled) return; settled = true; input.replaceWith(buildTargetCellSpan(row)); }
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") { event.preventDefault(); input.blur(); }
            if (event.key === "Escape") { event.preventDefault(); cancel(); }
        });
    }

    function saveTarget(inputEl, row, rawValue) {
        const value = rawValue === "" ? 0 : Number(rawValue);
        if (Number.isNaN(value)) {
            inputEl.replaceWith(buildTargetCellSpan(row));
            showToast("Target must be a number.", "error");
            return;
        }
        fetch(tankLoadingTargetUrl(row.fabric_type), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_value: value }),
        }).then((response) => response.json().catch(() => ({})).then((data) => {
            if (!response.ok) throw new Error(data.error || "save failed");
            row.target = value;
            inputEl.replaceWith(buildTargetCellSpan(row));
            showToast(`Target for ${row.fabric_type} saved.`, "success");
            updateChart(lastData);
        })).catch((err) => {
            inputEl.replaceWith(buildTargetCellSpan(row));
            showToast(err && err.message ? err.message : "Failed to save target.", "error");
        });
    }

    document.querySelector("#tank-loading-table tbody").addEventListener("click", (event) => {
        const cell = event.target.closest(".case-note-cell");
        if (!cell || !cell.dataset.fabricType) return;
        startEditingTarget(cell);
    });

    function renderTable(data) {
        const head = document.getElementById("tank-loading-head");
        head.innerHTML = "<th>Fabric Type</th><th>Target</th>" + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        document.querySelector("#tank-loading-table tbody").innerHTML = data.rows.map((row) =>
            `<tr><th>${row.fabric_type}</th>${renderTargetCell(row)}${row.values.map((value) => `<td>${value.toFixed(1)}%</td>`).join("")}<td><strong>${row.total.toFixed(1)}%</strong></td></tr>`
        ).join("");
    }

    function chartCanvasId(fabricType) {
        return `tank-loading-chart-${fabricType.toLowerCase()}`;
    }

    // 3 biểu đồ RIÊNG BIỆT (trái=Cotton, giữa=CVC, phải=Polyester, theo đúng thứ tự
    // MAIN_FABRIC_TYPES) — mỗi biểu đồ chỉ có 1 đường số liệu + 1 đường Target đứt nét
    // của ĐÚNG loại đó, không còn gộp chung 1 chart 3 màu như bản trước.
    function updateChart(data) {
        if (typeof Chart === "undefined") return;
        const { textColor, gridColor } = chartTextColors();
        (data.rows || []).forEach((row) => {
            const canvas = document.getElementById(chartCanvasId(row.fabric_type));
            if (!canvas) return;
            const color = TANK_LOADING_FABRIC_COLORS[row.fabric_type] || "#abaebb";
            const datasets = [{ label: row.fabric_type, data: row.values, borderColor: color, backgroundColor: "transparent", tension: .2, fill: false }];
            if (row.target !== null && row.target !== undefined) {
                datasets.push({
                    label: `${row.fabric_type} Target`,
                    data: data.periods.map(() => row.target),
                    borderColor: color,
                    borderDash: [6, 4],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    isTargetLine: true,
                });
            }
            if (charts[row.fabric_type]) charts[row.fabric_type].destroy();
            charts[row.fabric_type] = new Chart(canvas, {
                type: "line",
                data: { labels: data.periods, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: { ticks: { color: textColor }, grid: { color: gridColor } },
                        y: { beginAtZero: true, ticks: { color: textColor, callback: (value) => `${value}%` }, grid: { color: gridColor }, title: { display: true, text: "Tank Loading %", color: textColor } },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { filter: (item) => !item.dataset.isTargetLine },
                    },
                },
            });
        });
    }

    async function load() {
        const response = await fetch(`${window.TANK_LOADING_API_URL}?${filters()}`);
        if (!response.ok) return;
        const data = await response.json();
        brandProgramFilter.setOptions(data.available_brand_programs || []);
        document.querySelector(".kpi-tank-loading-pct").textContent = `${data.kpis.tank_loading_pct.toFixed(1)}%`;
        document.querySelector(".kpi-total-output").textContent = data.kpis.total_output_kgh.toLocaleString();
        document.querySelector(".kpi-total-max-load").textContent = data.kpis.total_max_load_kgh.toLocaleString();
        lastData = data;
        renderTable(data);
        updateChart(data);
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
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".capacity-dropdown")) {
            capacityMenu.hidden = true;
            capacityToggle.setAttribute("aria-expanded", "false");
        }
    });
    ["from-date", "to-date", "group-by"].forEach((id) => document.getElementById(id).addEventListener("change", load));
    document.addEventListener("colormodechange", load);

    updateCapacityLabel();
    const defaultRange = defaultDateRange();
    document.getElementById("from-date").value = defaultRange.from;
    document.getElementById("to-date").value = defaultRange.to;
    load();
}());
