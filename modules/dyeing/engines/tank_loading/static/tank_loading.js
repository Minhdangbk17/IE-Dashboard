(function () {
    "use strict";

    const capacityToggle = document.getElementById("capacity-toggle");
    const capacityMenu = document.getElementById("capacity-menu");
    const capacityAll = document.getElementById("capacity-all");
    const capacityCheckboxes = [...document.querySelectorAll(".capacity-checkbox")];
    let chart = null;

    function escAttr(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }
    function escHtml(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
    const fabricTypeFilter = makeMultiSelectDropdown("fabric-type-toggle", "fabric-type-menu", "All fabric types", load);
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
            fabric_types: fabricTypeFilter.selected().join(","),
            brand_programs: brandProgramFilter.selected().join(","),
            from_date: document.getElementById("from-date").value,
            to_date: document.getElementById("to-date").value,
            group_by: document.getElementById("group-by").value,
        });
    }

    function chartTextColors() {
        const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
        const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#abaebb";
        const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
        return { textColor, gridColor };
    }

    function renderTable(data) {
        const head = document.getElementById("tank-loading-head");
        head.innerHTML = "<th>Tank Loading %</th>" + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        const row = data.rows[0];
        document.querySelector("#tank-loading-table tbody").innerHTML =
            `<tr><th>${row.label}</th>${row.values.map((value) => `<td>${value.toFixed(1)}%</td>`).join("")}<td><strong>${row.total.toFixed(1)}%</strong></td></tr>`;
    }

    function updateChart(data) {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById("tank-loading-chart");
        if (!canvas) return;
        const { textColor, gridColor } = chartTextColors();
        const row = data.rows[0];
        if (chart) chart.destroy();
        chart = new Chart(canvas, {
            type: "bar",
            data: { labels: data.periods, datasets: [{ label: row.label, data: row.values, backgroundColor: "#2862d7", borderColor: "#2862d7", borderWidth: 1 }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: textColor, callback: (value) => `${value}%` }, grid: { color: gridColor }, title: { display: true, text: "Tank Loading %", color: textColor } },
                },
                plugins: { legend: { display: false } },
            },
        });
    }

    async function load() {
        const response = await fetch(`${window.TANK_LOADING_API_URL}?${filters()}`);
        if (!response.ok) return;
        const data = await response.json();
        fabricTypeFilter.setOptions(data.available_fabric_types || []);
        brandProgramFilter.setOptions(data.available_brand_programs || []);
        document.querySelector(".kpi-tank-loading-pct").textContent = `${data.kpis.tank_loading_pct.toFixed(1)}%`;
        document.querySelector(".kpi-total-output").textContent = data.kpis.total_output_kgh.toLocaleString();
        document.querySelector(".kpi-total-max-load").textContent = data.kpis.total_max_load_kgh.toLocaleString();
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
