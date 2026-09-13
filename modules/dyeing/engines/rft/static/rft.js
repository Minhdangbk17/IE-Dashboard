(function () {
    "use strict";

    const capacityToggle = document.getElementById("capacity-toggle");
    const capacityMenu = document.getElementById("capacity-menu");
    const capacityAll = document.getElementById("capacity-all");
    const capacityCheckboxes = [...document.querySelectorAll(".capacity-checkbox")];
    const charts = {};

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
        // Mặc định 6 tuần tính từ tuần hiện tại — cùng quy ước với trang Downtime.
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

    function filters(category) {
        return new URLSearchParams({
            category,
            capacities: selectedCapacities().join(","),
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

    function renderTable(section, data) {
        const head = section.querySelector(".rft-head");
        const label = head.querySelector("th").textContent;
        head.innerHTML = `<th>${label}</th>` + data.periods.map((period) => `<th>${period}</th>`).join("") + "<th>Total</th>";
        const row = data.rows[0];
        section.querySelector(".rft-table tbody").innerHTML =
            `<tr><th>${row.label}</th>${row.values.map((value) => `<td>${value}</td>`).join("")}<td><strong>${row.total}</strong></td></tr>`;
    }

    function updateChart(category, data) {
        if (typeof Chart === "undefined") return;
        const canvas = document.querySelector(`.rft-chart[data-category="${category}"]`);
        if (!canvas) return;
        const { textColor, gridColor } = chartTextColors();
        const row = data.rows[0];
        if (charts[category]) charts[category].destroy();
        charts[category] = new Chart(canvas, {
            type: "bar",
            data: { labels: data.periods, datasets: [{ label: row.label, data: row.values, backgroundColor: "#2862d7", borderColor: "#2862d7", borderWidth: 1 }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: textColor, precision: 0 }, grid: { color: gridColor }, title: { display: true, text: "Number of batches", color: textColor } },
                },
                plugins: { legend: { display: false } },
            },
        });
    }

    async function loadCategory(category) {
        const section = document.getElementById(`page-${category}`);
        if (!section) return;
        const response = await fetch(`${window.RFT_API_URL}?${filters(category)}`);
        if (!response.ok) return;
        const data = await response.json();
        section.querySelector(".kpi-total-batches").textContent = data.kpis.total_batches.toLocaleString();
        section.querySelector(".kpi-category-batches").textContent = data.kpis.category_batches.toLocaleString();
        section.querySelector(".kpi-rate").textContent = `${data.kpis.rate_pct.toFixed(1)}%`;
        renderTable(section, data);
        updateChart(category, data);
    }

    const pageTabsNav = document.getElementById("rft-tabs");
    const pageTabs = pageTabsNav ? [...pageTabsNav.querySelectorAll(".page-tab")] : [];
    const rftPages = [...document.querySelectorAll(".rft-page")];
    const pageTabsData = pageTabs.map((tab) => tab.dataset.page);
    let activePageIndex = 0;

    function activatePage(index) {
        index = Math.max(0, Math.min(rftPages.length - 1, index));
        activePageIndex = index;
        pageTabs.forEach((tab, i) => tab.classList.toggle("is-active", i === index));
        rftPages.forEach((page, i) => { page.hidden = i !== index; });
        // Chart.js đo kích thước container lúc vẽ — canvas ở trang vừa hiện lại
        // trước đó có thể 0x0 (bị "hidden"), phải resize lại sau khi hiện ra.
        requestAnimationFrame(() => {
            const category = pageTabsData[index];
            if (charts[category]) charts[category].resize();
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

    function loadAll() {
        pageTabsData.forEach((category) => loadCategory(category));
    }

    capacityToggle.addEventListener("click", () => {
        capacityMenu.hidden = !capacityMenu.hidden;
        capacityToggle.setAttribute("aria-expanded", String(!capacityMenu.hidden));
    });
    capacityAll.addEventListener("change", () => {
        capacityCheckboxes.forEach((checkbox) => { checkbox.checked = capacityAll.checked; });
        updateCapacityLabel();
        loadAll();
    });
    capacityCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
        updateCapacityLabel();
        loadAll();
    }));
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".capacity-dropdown")) {
            capacityMenu.hidden = true;
            capacityToggle.setAttribute("aria-expanded", "false");
        }
    });
    ["from-date", "to-date", "group-by"].forEach((id) => document.getElementById(id).addEventListener("change", loadAll));
    document.addEventListener("colormodechange", loadAll);

    updateCapacityLabel();
    const defaultRange = defaultDateRange();
    document.getElementById("from-date").value = defaultRange.from;
    document.getElementById("to-date").value = defaultRange.to;
    loadAll();
}());
