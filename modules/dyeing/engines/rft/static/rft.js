(function () {
    "use strict";

    const charts = {}; // `${category}::${fabricType}` -> Chart instance (1 biểu đồ riêng/loại vải/tab)
    const lastDataByCategory = {}; // category -> response API gần nhất (cần lại khi sửa Target)

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

    // Dropdown multi-select, danh sách lựa chọn lấy từ response API (available_*). Không chọn
    // gì = không lọc theo chiều đó.
    function makeMultiSelectDropdown(toggleId, menuId, defaultLabel, formatOption, onChange) {
        const toggle = document.getElementById(toggleId);
        const menu = document.getElementById(menuId);
        let selected = new Set();
        let options = [];
        function updateLabel() {
            if (selected.size === 0) toggle.textContent = defaultLabel;
            else if (selected.size === 1) toggle.textContent = formatOption([...selected][0]);
            else toggle.textContent = `${selected.size} selected`;
        }
        function render() {
            menu.innerHTML = options.length
                ? `<label class="capacity-option"><input type="checkbox" class="ms-all-option" ${selected.size === 0 ? "checked" : ""}> All</label><div class="border-top my-1"></div>` +
                  options.map((value) => `<label class="capacity-option"><input type="checkbox" class="ms-option" value="${escAttr(value)}" ${selected.has(value) ? "checked" : ""}> ${escHtml(formatOption(value))}</label>`).join("")
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
    const capacityFilter = makeMultiSelectDropdown("capacity-toggle", "capacity-menu", "All capacities", (value) => `${value} Kg`, loadAll);
    const machineGroupFilter = makeMultiSelectDropdown("machine-group-toggle", "machine-group-menu", "All machine groups", (value) => value, loadAll);
    const brandProgramFilter = makeMultiSelectDropdown("brand-program-toggle", "brand-program-menu", "All brand programs", (value) => value, loadAll);

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

    // Tham số lọc dùng CHUNG cho bảng và Export.
    function filterParams() {
        return new URLSearchParams({
            capacities: capacityFilter.selected().join(","),
            machine_groups: machineGroupFilter.selected().join(","),
            brand_programs: brandProgramFilter.selected().join(","),
            from_date: document.getElementById("from-date").value,
            to_date: document.getElementById("to-date").value,
            group_by: document.getElementById("group-by").value,
        });
    }

    function chartTextColors() {
        const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
        const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim();
        const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
        return { textColor, gridColor };
    }

    // Màu nghiệp vụ theo loại vải (UI_GUIDELINES Mục 6.1) — dùng chung cho đường số liệu (nét
    // liền) và đường Target (nét đứt, cùng màu).
    const RFT_FABRIC_COLORS = { Cotton: "#3fb950", CVC: "#2862d7", Polyester: "#f778ba" };

    function rftTargetUrl(category, fabricType) {
        return window.RFT_TARGET_URL_TEMPLATE.replace("__SLUG__", encodeURIComponent(category)).replace("__FABRIC__", encodeURIComponent(fabricType));
    }

    function formatPct(value) {
        return value === null || value === undefined ? "-" : `${Number(value).toFixed(1)}%`;
    }

    // Target "min" (RFT — cao là tốt) / "max" (Rework, Adjustment — thấp là tốt).
    function ratioClass(value, target, direction) {
        if (value === null || value === undefined || target === null || target === undefined) return "";
        const ok = direction === "max" ? value <= target : value >= target;
        return ok ? "ratio-good" : "ratio-warning";
    }

    function buildTargetCellSpan(category, row) {
        const span = document.createElement("span");
        span.className = "case-note-cell";
        span.dataset.category = category;
        span.dataset.fabricType = row.fabric_type;
        span.textContent = formatPct(row.target);
        return span;
    }

    function renderTargetCell(category, row) {
        const text = formatPct(row.target);
        if (!window.RFT_CAN_EDIT) return `<td>${text}</td>`;
        return `<td><span class="case-note-cell" data-category="${escAttr(category)}" data-fabric-type="${escAttr(row.fabric_type)}">${text}</span></td>`;
    }

    function startEditingTarget(cell) {
        const category = cell.dataset.category;
        const fabricType = cell.dataset.fabricType;
        const data = lastDataByCategory[category];
        const row = data && (data.rows || []).find((item) => item.fabric_type === fabricType);
        if (!row) return;
        const input = document.createElement("input");
        input.type = "number";
        input.step = "0.1";
        input.min = "0";
        input.max = "100";
        input.className = "case-note-input";
        input.value = row.target === null || row.target === undefined ? "" : row.target;
        cell.replaceWith(input);
        input.focus();
        input.select();
        let settled = false;
        function commit() { if (settled) return; settled = true; saveTarget(input, category, row); }
        function cancel() { if (settled) return; settled = true; input.replaceWith(buildTargetCellSpan(category, row)); }
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") { event.preventDefault(); input.blur(); }
            if (event.key === "Escape") { event.preventDefault(); cancel(); }
        });
    }

    function saveTarget(inputEl, category, row) {
        const rawValue = inputEl.value.trim();
        const value = rawValue === "" ? 0 : Number(rawValue);
        if (Number.isNaN(value)) {
            inputEl.replaceWith(buildTargetCellSpan(category, row));
            showToast("Target must be a number.", "error");
            return;
        }
        fetch(rftTargetUrl(category, row.fabric_type), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_value: value }),
        }).then((response) => response.json().catch(() => ({})).then((data) => {
            if (!response.ok) throw new Error(data.error || "save failed");
            row.target = value;
            const section = document.getElementById(`page-${category}`);
            renderTable(section, category, lastDataByCategory[category]);
            updateChart(category, lastDataByCategory[category]);
            showToast(`Target for ${row.fabric_type} saved.`, "success");
        })).catch((err) => {
            inputEl.replaceWith(buildTargetCellSpan(category, row));
            showToast(err && err.message ? err.message : "Failed to save target.", "error");
        });
    }

    document.querySelectorAll(".rft-table").forEach((table) => {
        table.addEventListener("click", (event) => {
            const cell = event.target.closest(".case-note-cell");
            if (!cell || !cell.dataset.fabricType) return;
            startEditingTarget(cell);
        });
    });

    function valueCells(row, direction) {
        return row.values.map((value, index) => {
            const cls = ratioClass(value, row.target, direction);
            const title = `${row.batches[index]} batch(es)`;
            return `<td class="${cls}" title="${title}">${formatPct(value)}</td>`;
        }).join("");
    }

    function renderTable(section, category, data) {
        const direction = data.target_direction;
        const head = section.querySelector(".rft-head");
        const targetLabel = direction === "max" ? "Target (max)" : "Target (min)";
        head.innerHTML = `<th>Fabric Type</th><th class="num">${targetLabel}</th>` + data.periods.map((period) => `<th class="num">${escHtml(period)}</th>`).join("") + `<th class="num">Total</th>`;
        const fabricRows = data.rows.map((row) =>
            `<tr><th>${escHtml(row.fabric_type)}</th>${renderTargetCell(category, row)}${valueCells(row, direction)}` +
            `<td class="${ratioClass(row.total, row.target, direction)}" title="${row.total_batches} batch(es)"><strong>${formatPct(row.total)}</strong></td></tr>`
        ).join("");
        const total = data.total_row;
        const totalRow = `<tr class="total-row"><th>Total</th><td>-</td>` +
            total.values.map((value, index) => `<td title="${total.batches[index]} batch(es)">${formatPct(value)}</td>`).join("") +
            `<td title="${total.total_batches} batch(es)"><strong>${formatPct(total.total)}</strong></td></tr>`;
        section.querySelector(".rft-table tbody").innerHTML = fabricRows + totalRow;
    }

    // 3 biểu đồ riêng/tab (Cotton / CVC / Polyester) — mỗi biểu đồ 1 đường số liệu + 1 đường
    // Target nét đứt cùng màu (UI_GUIDELINES Mục 7.2).
    function updateChart(category, data) {
        if (typeof Chart === "undefined" || !data) return;
        const { textColor, gridColor } = chartTextColors();
        const yTitle = data.target_direction === "max" ? `${data.category} rate (%)` : "RFT rate (%)";
        (data.rows || []).forEach((row) => {
            const canvas = document.querySelector(`.rft-chart[data-category="${category}"][data-fabric="${row.fabric_type}"]`);
            if (!canvas) return;
            const color = RFT_FABRIC_COLORS[row.fabric_type];
            const datasets = [{ label: row.fabric_type, data: row.values, borderColor: color, backgroundColor: "transparent", tension: .2, fill: false, spanGaps: false }];
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
            const key = `${category}::${row.fabric_type}`;
            if (charts[key]) charts[key].destroy();
            charts[key] = new Chart(canvas, {
                type: "line",
                data: { labels: data.periods, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: { ticks: { color: textColor }, grid: { color: gridColor } },
                        y: { beginAtZero: true, max: 100, ticks: { color: textColor, callback: (value) => `${value}%` }, grid: { color: gridColor }, title: { display: true, text: yTitle, color: textColor } },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            filter: (item) => !item.dataset.isTargetLine,
                            callbacks: { label: (context) => `${context.formattedValue}% (${row.batches[context.dataIndex]} batch(es))` },
                        },
                    },
                },
            });
        });
    }

    // Đổi bộ lọc liên tiếp bắn nhiều request song song — chỉ nhận response của lần tải MỚI
    // NHẤT mỗi tab, tránh response cũ về sau ghi đè kết quả mới.
    const latestRequest = {};

    async function loadCategory(category) {
        const section = document.getElementById(`page-${category}`);
        if (!section) return;
        const params = filterParams();
        params.set("category", category);
        const requestId = (latestRequest[category] || 0) + 1;
        latestRequest[category] = requestId;
        const response = await fetch(`${window.RFT_API_URL}?${params}`);
        if (!response.ok || requestId !== latestRequest[category]) return;
        const data = await response.json();
        if (requestId !== latestRequest[category]) return;
        capacityFilter.setOptions(data.available_capacities || []);
        machineGroupFilter.setOptions(data.available_machine_groups || []);
        brandProgramFilter.setOptions(data.available_brand_programs || []);
        section.querySelector(".kpi-total-batches").textContent = data.kpis.total_batches.toLocaleString();
        section.querySelector(".kpi-hit-batches").textContent = data.kpis.hit_batches.toLocaleString();
        section.querySelector(".kpi-rate").textContent = `${data.kpis.rate_pct.toFixed(1)}%`;
        const unknownGroupEl = section.querySelector(".rft-unknown-group");
        if (unknownGroupEl) {
            unknownGroupEl.hidden = !data.unknown_machine_group_count;
            unknownGroupEl.textContent = `${data.unknown_machine_group_count} batch(es) have no readable MachineGroup and are excluded from this tab.`;
        }
        lastDataByCategory[category] = data;
        renderTable(section, category, data);
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
        // Chart.js đo kích thước container lúc vẽ — canvas ở trang vừa hiện lại trước đó có
        // thể 0x0 (bị "hidden"), phải resize lại sau khi hiện ra.
        requestAnimationFrame(() => {
            const category = pageTabsData[index];
            Object.keys(charts).forEach((key) => {
                if (key.startsWith(`${category}::`) && charts[key]) charts[key].resize();
            });
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

    document.getElementById("rft-export").addEventListener("click", () => {
        window.location.href = `${window.RFT_EXPORT_URL}?${filterParams()}`;
    });
    ["from-date", "to-date", "group-by"].forEach((id) => document.getElementById(id).addEventListener("change", loadAll));
    document.addEventListener("colormodechange", loadAll);

    const defaultRange = defaultDateRange();
    document.getElementById("from-date").value = defaultRange.from;
    document.getElementById("to-date").value = defaultRange.to;
    loadAll();
}());
