(function () {
    "use strict";

    const capacityToggle = document.getElementById("capacity-toggle");
    const capacityMenu = document.getElementById("capacity-menu");
    const capacityAll = document.getElementById("capacity-all");
    const capacityCheckboxes = [...document.querySelectorAll(".capacity-checkbox")];
    const charts = {}; // fabric_type -> Chart instance (1 biểu đồ riêng/loại vải)

    function escAttr(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }
    function escHtml(value) {
        return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // Dropdown multi-select DATA-DRIVEN (cùng cách trình bày với Capacity ở trên, nhưng
    // option list lấy từ response API) — dùng cho Brand Program.
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
        // Mặc định 6 tuần tính từ tuần hiện tại — cùng quy ước với trang Downtime/RFT/Tank Loading.
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

    // Màu cố định theo nhóm màu (không phải màu THẬT của vải — chỉ để phân biệt 5 đường
    // trên chart, tránh dùng đen/trắng thuần vì khó thấy ở cả 2 theme).
    const DCA_COLOR_PALETTE = { Dark: "#8957e5", Light: "#58a6ff", Medium: "#f0883e", Black: "#6e7681", White: "#3fb950" };

    function formatMoney(value) {
        return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    function renderSection(fabricType, data) {
        const section = document.querySelector(`.dca-section[data-fabric="${fabricType}"]`);
        if (!section) return;
        const fabricData = (data.fabrics || {})[fabricType] || { rows: [], kpis: { total_dye_cost: 0, total_batches: 0, dca_cost: 0 } };

        section.querySelector(".dca-kpi-total-cost").textContent = formatMoney(fabricData.kpis.total_dye_cost);
        section.querySelector(".dca-kpi-total-batches").textContent = Number(fabricData.kpis.total_batches || 0).toLocaleString();
        section.querySelector(".dca-kpi-dca-cost").textContent = formatMoney(fabricData.kpis.dca_cost);

        const head = section.querySelector(".dca-head");
        head.innerHTML = "<th>Color</th>" + (data.periods || []).map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        section.querySelector(".dca-table tbody").innerHTML = fabricData.rows.map((row) =>
            `<tr><th>${row.color}</th>${row.values.map((value) => `<td>${formatMoney(value)}</td>`).join("")}<td><strong>${formatMoney(row.total)}</strong></td></tr>`
        ).join("");

        if (typeof Chart === "undefined") return;
        const canvas = section.querySelector(".dca-chart");
        if (!canvas) return;
        const { textColor, gridColor } = chartTextColors();
        const datasets = fabricData.rows.map((row) => ({
            label: row.color,
            data: row.values,
            borderColor: DCA_COLOR_PALETTE[row.color] || "#abaebb",
            backgroundColor: "transparent",
            tension: .2,
            fill: false,
        }));
        if (charts[fabricType]) charts[fabricType].destroy();
        charts[fabricType] = new Chart(canvas, {
            type: "line",
            data: { labels: data.periods || [], datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor }, title: { display: true, text: "DCA Cost", color: textColor } },
                },
                plugins: {
                    legend: { position: "bottom", labels: { color: textColor } },
                    tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${formatMoney(context.parsed.y)}` } },
                },
            },
        });
    }

    async function load() {
        const response = await fetch(`${window.DCA_COST_API_URL}?${filters()}`);
        if (!response.ok) return;
        const data = await response.json();
        brandProgramFilter.setOptions(data.available_brand_programs || []);
        ["Cotton", "CVC", "Polyester"].forEach((fabricType) => renderSection(fabricType, data));
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
