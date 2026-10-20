/* Knitting Downtime — cùng bố cục Dyeing Downtime: filter bar dùng chung cho mọi tab; mỗi tab biểu đồ
   ở trên, bảng chi tiết ở dưới; bấm ô -> drawer chi tiết THEO NGÀY (rồi máy-ngày, mã dừng). */
(function () {
    "use strict";
    const API = window.KD_API;
    const IS_ADMIN = window.KD_IS_ADMIN;
    const CATEGORIES = window.KD_CATEGORIES;
    const MERGEABLE = window.KD_MERGEABLE;
    const OTHERS = "Others";
    const MAX_EXTRA_SERIES = 3;
    const MERGED_STORAGE_KEY = "kd_merged_categories";

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmtPct = (v) => (v === null || v === undefined) ? "-" : `${Number(v).toFixed(1)}%`;
    const fmtNum = (v, d = 2) => (v === null || v === undefined) ? "-" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const isOver = (v, target) => target !== null && target !== undefined && v !== null && v !== undefined && v > target + 1e-9;

    let unit = "pct";
    let report = null;
    let requestSeq = 0;
    const charts = {};

    // ------------------------------------------------------------------ dropdowns
    function closeOnOutside(toggle, menu) {
        toggle.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; toggle.setAttribute("aria-expanded", String(!menu.hidden)); });
        document.addEventListener("click", (e) => { if (!toggle.parentElement.contains(e.target)) { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); } });
    }

    function makeMultiSelect(toggleId, menuId, allLabel, onChange, searchable) {
        const toggle = $(toggleId);
        const menu = $(menuId);
        let options = [];
        const selected = new Set();
        let query = "";
        function updateLabel() {
            toggle.textContent = selected.size === 0 ? allLabel : selected.size === 1 ? [...selected][0] : `${selected.size} selected`;
        }
        function render() {
            if (!options.length) { menu.innerHTML = `<span class="f6 color-fg-muted">No data</span>`; return; }
            const visible = options.filter((o) => o.toLowerCase().includes(query.toLowerCase()));
            menu.innerHTML = (searchable ? `<input type="search" class="form-control kd-search" placeholder="Search..." value="${esc(query)}">` : "")
                + `<label class="kd-option"><input type="checkbox" class="kd-all" ${selected.size === 0 ? "checked" : ""}> All</label><div class="border-top my-1"></div>`
                + visible.map((o) => `<label class="kd-option"><input type="checkbox" class="kd-opt" value="${esc(o)}" ${selected.has(o) ? "checked" : ""}> ${esc(o)}</label>`).join("");
            const search = menu.querySelector(".kd-search");
            if (search) {
                search.addEventListener("input", () => { query = search.value; render(); const s = menu.querySelector(".kd-search"); s.focus(); s.setSelectionRange(query.length, query.length); });
            }
            menu.querySelector(".kd-all").addEventListener("change", (e) => {
                if (e.target.checked) { selected.clear(); render(); updateLabel(); onChange(); } else { e.target.checked = true; }
            });
            menu.querySelectorAll(".kd-opt").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) selected.add(box.value); else selected.delete(box.value);
                render(); updateLabel(); onChange();
            }));
        }
        closeOnOutside(toggle, menu);
        updateLabel();
        return {
            setOptions(values) { options = values; [...selected].forEach((v) => { if (!values.includes(v)) selected.delete(v); }); render(); updateLabel(); },
            selected: () => [...selected],
        };
    }

    // Line chart Achievement: chọn tối đa MAX_EXTRA_SERIES nhóm vẽ thêm cạnh Total (quy tắc <= 4 đường).
    // Danh sách nhóm lấy từ report (đã gộp Others) -> setOptions() mỗi lần tải.
    function makeSeriesSelector(toggleId, menuId, onChange) {
        const toggle = $(toggleId);
        const menu = $(menuId);
        let options = [];
        let picked = [];
        function render() {
            toggle.textContent = picked.length ? `Total + ${picked.length} categories` : "Total";
            menu.innerHTML = `<label class="kd-option"><input type="checkbox" checked disabled> Total</label><div class="border-top my-1"></div>`
                + options.map((c) => {
                    const checked = picked.includes(c);
                    const disabled = !checked && picked.length >= MAX_EXTRA_SERIES;
                    return `<label class="kd-option"><input type="checkbox" value="${esc(c)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}> ${esc(c)}</label>`;
                }).join("");
            menu.querySelectorAll("input[value]").forEach((box) => box.addEventListener("change", () => {
                picked = box.checked ? [...picked, box.value] : picked.filter((c) => c !== box.value);
                render(); onChange();
            }));
        }
        closeOnOutside(toggle, menu);
        render();
        return {
            setOptions(values) { options = values; picked = picked.filter((c) => values.includes(c)); render(); },
            picked: () => picked,
        };
    }

    // Biểu đồ cột chồng Downtime: chọn TUỲ Ý số nhóm (mặc định tất cả). Lưu nhóm BỊ ẨN (không lưu nhóm
    // được chọn) để nhóm mới xuất hiện sau khi đổi gộp Others mặc định vẫn hiện.
    function makeStackSelector(toggleId, menuId, onChange) {
        const toggle = $(toggleId);
        const menu = $(menuId);
        let options = [];
        const hidden = new Set();
        const picked = () => options.filter((c) => !hidden.has(c));
        function render() {
            const n = picked().length;
            toggle.textContent = n === options.length ? "All categories" : n === 0 ? "Total only" : `${n} of ${options.length} categories`;
            menu.innerHTML = `<label class="kd-option"><input type="checkbox" class="kd-all" ${n === options.length ? "checked" : ""}> All categories</label><div class="border-top my-1"></div>`
                + options.map((c) => `<label class="kd-option"><input type="checkbox" class="kd-opt" value="${esc(c)}" ${hidden.has(c) ? "" : "checked"}> ${esc(c)}</label>`).join("");
            menu.querySelector(".kd-all").addEventListener("change", (e) => {
                if (e.target.checked) hidden.clear(); else options.forEach((c) => hidden.add(c));
                render(); onChange();
            });
            menu.querySelectorAll(".kd-opt").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) hidden.delete(box.value); else hidden.add(box.value);
                render(); onChange();
            }));
        }
        closeOnOutside(toggle, menu);
        render();
        return { setOptions(values) { options = values; render(); }, picked };
    }

    // Bộ lọc "Categories" (giống Group trong pivot): tick = tách dòng riêng, bỏ tick = gộp vào Others.
    // Gửi lên server (`merged`) để pivot / achievement / drill-down / export cùng 1 cách gộp.
    function makeGroupSelector(toggleId, menuId, onChange) {
        const toggle = $(toggleId);
        const menu = $(menuId);
        let merged = new Set();
        try {
            const saved = JSON.parse(localStorage.getItem(MERGED_STORAGE_KEY) || "[]");
            merged = new Set(saved.filter((c) => MERGEABLE.includes(c)));
        } catch (e) { /* localStorage không dùng được -> mặc định tách hết */ }
        function save() { try { localStorage.setItem(MERGED_STORAGE_KEY, JSON.stringify([...merged])); } catch (e) { /* bỏ qua */ } }
        function render() {
            toggle.textContent = merged.size === 0 ? "All separate" : `${MERGEABLE.length - merged.size} separate + Others`;
            menu.innerHTML = `<p class="f6 color-fg-muted my-1 px-2">Ticked = own row. Unticked = merged into Others.</p>`
                + `<div class="d-flex px-2 mb-1" style="gap:6px"><button type="button" class="btn btn-sm" data-act="split">Split all</button><button type="button" class="btn btn-sm" data-act="merge">Merge all</button></div>`
                + `<div class="border-top my-1"></div>`
                + MERGEABLE.map((c) => `<label class="kd-option"><input type="checkbox" value="${esc(c)}" ${merged.has(c) ? "" : "checked"}> ${esc(c)}</label>`).join("")
                + `<label class="kd-option" title="Others always has its own row"><input type="checkbox" checked disabled> ${OTHERS}</label>`;
            menu.querySelectorAll("button[data-act]").forEach((btn) => btn.addEventListener("click", () => {
                merged = btn.dataset.act === "merge" ? new Set(MERGEABLE) : new Set();
                save(); render(); onChange();
            }));
            menu.querySelectorAll("input[value]").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) merged.delete(box.value); else merged.add(box.value);
                save(); render(); onChange();
            }));
        }
        closeOnOutside(toggle, menu);
        render();
        // Giữ thứ tự CATEGORIES để URL ổn định.
        return { merged: () => MERGEABLE.filter((c) => merged.has(c)) };
    }

    // Nhãn dòng: Others đang gộp -> "Others (+3)" kèm title liệt kê nhóm bị gộp.
    const rowLabel = (row) => (row.merged && row.merged.length ? `${row.category} (+${row.merged.length})` : row.category);
    const rowTitle = (row) => (row.merged && row.merged.length ? `Others + ${row.merged.join(", ")}` : "");

    const machineFilter = makeMultiSelect("kd-machine-toggle", "kd-machine-menu", "All machines", scheduleLoad, true);
    const structureFilter = makeMultiSelect("kd-structure-toggle", "kd-structure-menu", "All structures", scheduleLoad, false);
    const programFilter = makeMultiSelect("kd-program-toggle", "kd-program-menu", "All programs", scheduleLoad, true);
    const groupFilter = makeGroupSelector("kd-group-toggle", "kd-group-menu", scheduleLoad);
    const downtimeSeries = makeStackSelector("kd-series-toggle", "kd-series-menu", () => renderDowntimeChart());
    const achievementSeries = makeSeriesSelector("kd-ach-toggle", "kd-ach-menu", () => renderAchievementChart());
    $("kd-core-only").addEventListener("change", scheduleLoad);

    function filterParams() {
        const p = new URLSearchParams({ from_date: $("kd-from").value, to_date: $("kd-to").value, group_by: $("kd-group-by").value });
        if (machineFilter.selected().length) p.set("machines", machineFilter.selected().join(","));
        if (structureFilter.selected().length) p.set("structures", structureFilter.selected().join(","));
        // Tên Program có thể chứa dấu phẩy -> phân tách bằng "|".
        if (programFilter.selected().length) p.set("programs", programFilter.selected().join("|"));
        if ($("kd-core-only").checked) p.set("core_only", "1");
        // Tên nhóm có "/" và "+" -> phân tách bằng "|".
        if (groupFilter.merged().length) p.set("merged", groupFilter.merged().join("|"));
        return p;
    }

    // ------------------------------------------------------------------ load
    let loadTimer = null;
    function scheduleLoad() { clearTimeout(loadTimer); loadTimer = setTimeout(loadReport, 250); }

    async function loadReport() {
        const params = filterParams();
        $("kd-export").href = `${API}export?${params}`;
        if (!$("kd-from").value || !$("kd-to").value) return;
        const seq = ++requestSeq;
        const res = await fetch(`${API}summary?${params}`);
        const data = await res.json();
        if (seq !== requestSeq) return; // response cũ không được ghi đè kết quả lọc mới
        $("kd-error").hidden = res.ok;
        if (!res.ok) { $("kd-error").textContent = data.error || "Load failed"; return; }
        report = data;
        const empty = !data.period_keys.length;
        $("kd-empty").hidden = !empty;
        document.querySelectorAll(".kd-page[data-page=overview], .kd-page[data-page=achievement]").forEach((page) => {
            page.classList.toggle("d-none", empty);
        });
        $("kd-unmapped").hidden = !data.unmapped_codes.length;
        $("kd-unmapped").innerHTML = data.unmapped_codes.length
            ? `Stop codes without a category (counted in Total as "Unmapped"): ${data.unmapped_codes.map((c) => `<strong>${esc(c.stop_code)}</strong> ${esc(c.stop_description)}`).join(", ")}. Set them in Stop Code Mapping.`
            : "";
        if (empty) return;
        downtimeSeries.setOptions(data.rows.map((r) => r.category));
        achievementSeries.setOptions(data.achievement.rows.map((r) => r.category));
        renderKpis();
        renderPivot();
        renderAchievementTable();
        renderDowntimeChart();
        renderAchievementChart();
    }

    function renderKpis() {
        const k = report.kpis;
        $("kpi-plan").textContent = fmtNum(k.plan, 0);
        $("kpi-machine-days").textContent = fmtNum(k.machine_days, 0);
        $("kpi-downtime").textContent = fmtNum(k.downtime, 0);
        $("kpi-rate").textContent = fmtPct(k.downtime_pct);
        $("kpi-rate").className = isOver(k.downtime_pct, k.target_pct) ? "kpi-bad" : "kpi-good";
        $("kpi-target").textContent = fmtPct(k.target_pct);
        $("kpi-achievement").textContent = fmtPct(k.achievement_pct);
    }

    // ------------------------------------------------------------------ Overview pivot
    function renderPivot() {
        const head = $("kd-pivot-head");
        head.innerHTML = `<th>Downtime ${unit === "pct" ? "(%)" : "(stop time)"}</th><th class="num">Before</th><th class="num">Target</th>`
            + report.periods.map((p) => `<th class="num">${esc(p)}</th>`).join("") + `<th class="num">Total</th>`;
        const value = (row, i) => (unit === "pct" ? row.pct[i] : row.stop_time[i]);
        const fmtCell = (v) => (unit === "pct" ? fmtPct(v) : fmtNum(v));
        const over = (row, v) => unit === "pct" && isOver(v, row.target);
        const rowHtml = (row, isTotal) => {
            const refCell = (field) => {
                // Others đang gộp hiển thị TỔNG Target nhiều nhóm -> không sửa trực tiếp được.
                const editable = IS_ADMIN && !isTotal && row.category !== "Unmapped" && !(row.merged && row.merged.length);
                return `<td class="num ref${editable ? " cell-clickable kd-target" : ""}" ${editable ? `tabindex="0" data-field="${field}" data-category="${esc(row.category)}"` : ""}>${fmtPct(row[field])}</td>`;
            };
            const cells = report.period_keys.map((key, i) => {
                const v = value(row, i);
                return `<td class="num cell-clickable${over(row, v) ? " ratio-warning" : ""}" tabindex="0" data-period="${key}" data-category="${esc(row.category)}">${fmtCell(v)}</td>`;
            }).join("");
            const total = unit === "pct" ? row.total_pct : row.total_stop_time;
            return `<tr class="${isTotal ? "total-row" : ""}"><th title="${esc(rowTitle(row))}">${esc(rowLabel(row))}</th>${refCell("before")}${refCell("target")}${cells}`
                + `<td class="num cell-clickable${over(row, total) ? " ratio-warning" : ""}" tabindex="0" data-period="ALL" data-category="${esc(row.category)}"><strong>${fmtCell(total)}</strong></td></tr>`;
        };
        const planRow = `<tr class="plan-row"><th>Plan PRD (Available)</th><td></td><td></td>${report.available.map((v) => `<td class="num">${fmtNum(v)}</td>`).join("")}<td class="num">${fmtNum(report.total_available)}</td></tr>`;
        $("kd-pivot").querySelector("tbody").innerHTML = report.rows.map((r) => rowHtml(r, false)).join("") + rowHtml(report.total_row, true) + planRow;
    }

    $("kd-pivot").addEventListener("click", (e) => {
        const target = e.target.closest(".kd-target");
        if (target) { editTarget(target); return; }
        const cell = e.target.closest("td[data-period]");
        if (cell) openDrawer(cell.dataset.period, cell.dataset.category, "downtime");
    });

    function editTarget(cell) {
        if (cell.querySelector("input")) return;
        const row = report.rows.find((r) => r.category === cell.dataset.category);
        const field = cell.dataset.field;
        const input = document.createElement("input");
        input.type = "number"; input.step = "0.1"; input.min = "0"; input.max = "100";
        input.className = "form-control target-edit";
        input.value = row[field] ?? "";
        cell.textContent = "";
        cell.appendChild(input);
        input.focus();
        let done = false;
        const finish = async (save) => {
            if (done) return;
            done = true;
            if (save && input.value !== String(row[field] ?? "")) {
                const payload = { category: row.category, before_pct: row.before, target_pct: row.target };
                payload[field === "before" ? "before_pct" : "target_pct"] = input.value === "" ? null : Number(input.value);
                const res = await fetch(`${API}targets`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                if (!res.ok) { const err = await res.json().catch(() => ({})); alert(err.error || "Save failed"); }
                await loadReport(); // Target đổi -> Achievement cũng đổi, tải lại toàn bộ
            } else {
                renderPivot();
            }
        };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
        input.addEventListener("blur", () => finish(true));
    }

    // ------------------------------------------------------------------ Achievement table
    function renderAchievementTable() {
        $("kd-ach-head").innerHTML = `<th>Category</th><th class="num">Target</th>` + report.periods.map((p) => `<th class="num">${esc(p)}</th>`).join("") + `<th class="num">Total</th>`;
        const rowHtml = (row, isTotal) => {
            const cells = report.period_keys.map((key, i) => {
                const title = row.evaluated[i] ? `${row.passed[i]} / ${row.evaluated[i]} machine-days` : "No machine-day evaluated";
                return `<td class="num cell-clickable" tabindex="0" title="${title}" data-period="${key}" data-category="${esc(row.category)}">${row.values[i] === null ? "N/A" : fmtPct(row.values[i])}</td>`;
            }).join("");
            return `<tr class="${isTotal ? "total-row" : ""}"><th title="${esc(rowTitle(row))}">${esc(rowLabel(row))}</th><td class="num ref">${fmtPct(row.target)}</td>${cells}`
                + `<td class="num cell-clickable" tabindex="0" title="${row.total_passed} / ${row.total_evaluated} machine-days" data-period="ALL" data-category="${esc(row.category)}"><strong>${row.rate_pct === null ? "N/A" : fmtPct(row.rate_pct)}</strong></td></tr>`;
        };
        $("kd-ach-table").querySelector("tbody").innerHTML = report.achievement.rows.map((r) => rowHtml(r, false)).join("") + rowHtml(report.achievement.total_row, true);
    }

    $("kd-ach-table").addEventListener("click", (e) => {
        const cell = e.target.closest("td[data-period]");
        if (cell) openDrawer(cell.dataset.period, cell.dataset.category, "achievement");
    });
    document.querySelectorAll("#kd-pivot, #kd-ach-table").forEach((table) => table.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const cell = e.target.closest("td.cell-clickable");
        if (!cell || cell.querySelector("input")) return;
        e.preventDefault();
        cell.click();
    }));

    // ------------------------------------------------------------------ charts
    function token(name, fallback) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback; }
    function palette() { return [token("--accent", "#2862d7"), token("--accent-purple", "#625fff"), token("--success", "#3fb950"), token("--warning", "#d29922")]; }

    const valueLabels = {
        id: "kdValueLabels",
        afterDatasetsDraw(c) {
            const ctx = c.ctx;
            c.data.datasets.forEach((ds, i) => {
                if (!ds.showLabels || !c.isDatasetVisible(i)) return;
                c.getDatasetMeta(i).data.forEach((point, j) => {
                    const v = ds.data[j];
                    if (v === null || v === undefined) return;
                    ctx.save();
                    ctx.fillStyle = token("--text-secondary", "#666");
                    ctx.font = "11px Inter, system-ui, sans-serif";
                    ctx.textAlign = "center";
                    ctx.fillText(`${v.toFixed(1)}%`, point.x, point.y - 8);
                    ctx.restore();
                });
            });
        },
    };

    function drawLineChart(id, datasets, yOptions) {
        if (typeof Chart === "undefined") return;
        const axis = token("--text-secondary", "#666");
        const grid = token("--border-subtle", "#ddd");
        if (charts[id]) charts[id].destroy();
        charts[id] = new Chart($(id), {
            type: "line",
            data: { labels: report.periods, datasets },
            plugins: [valueLabels],
            options: {
                responsive: true, maintainAspectRatio: false, layout: { padding: { top: 20, left: 8, right: 16 } },
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: axis }, grid: { color: grid } },
                    y: { beginAtZero: true, grace: "10%", ticks: { color: axis, callback: (v) => `${v}%` }, grid: { color: grid }, ...yOptions },
                },
                plugins: {
                    legend: { position: "bottom", labels: { color: axis, boxWidth: 12, usePointStyle: true } },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? "-" : ctx.parsed.y.toFixed(2) + "%"}` } },
                },
            },
        });
    }

    // Màu theo THỰC THỂ: vị trí cố định của nhóm trong CATEGORIES (không theo thứ tự đang hiện) ->
    // ẩn/gộp nhóm khác không làm đổi màu nhóm còn lại. Others / Unmapped = xám trung tính.
    function categoryColor(category) {
        if (category === OTHERS) return token("--chart-other", "#8b8f9c");
        if (category === "Unmapped") return token("--text-tertiary", "#6b7080");
        return token(`--chart-${CATEGORIES.indexOf(category) + 1}`, "#2a78d6");
    }

    // Cột chồng = các nhóm đang chọn (% Downtime), đường = Total (mọi nhóm, không phụ thuộc lựa chọn),
    // nét đứt = Target Total. KHÔNG vẽ Target từng nhóm: tới 13 nhóm chọn tự do -> rối (bài học
    // commit e198720 bên Dyeing Downtime).
    function renderDowntimeChart() {
        if (!report || !report.period_keys.length || typeof Chart === "undefined") return;
        const fewPoints = report.periods.length <= 12;
        const axis = token("--text-secondary", "#666");
        const grid = token("--border-subtle", "#ddd");
        const surface = token("--bg-surface", "#fff");
        const totalColor = token("--text-primary", "#0b0c0e");
        const picked = new Set(downtimeSeries.picked());
        const datasets = report.rows.filter((row) => picked.has(row.category)).map((row) => ({
            type: "bar", label: rowLabel(row), data: row.pct, backgroundColor: categoryColor(row.category),
            borderColor: surface, borderWidth: { top: 1 }, borderSkipped: false, stack: "downtime", order: 2,
            barPercentage: 0.75, categoryPercentage: 0.8,
        }));
        const total = report.total_row;
        datasets.push({
            type: "line", label: "Total downtime", data: total.pct, borderColor: totalColor, backgroundColor: totalColor,
            borderWidth: 2, tension: 0.2, pointRadius: 3, pointHoverRadius: 5, spanGaps: true, order: 0, showLabels: fewPoints,
        });
        if (total.target !== null && total.target !== undefined) {
            datasets.push({
                type: "line", label: `Total target (${fmtPct(total.target)})`, data: report.periods.map(() => total.target),
                borderColor: token("--danger", "#f85149"), borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0,
                order: 1, isTargetLine: true,
            });
        }
        if (charts["kd-chart"]) charts["kd-chart"].destroy();
        charts["kd-chart"] = new Chart($("kd-chart"), {
            type: "bar",
            data: { labels: report.periods, datasets },
            plugins: [valueLabels],
            options: {
                responsive: true, maintainAspectRatio: false, layout: { padding: { top: 20, left: 8, right: 16 } },
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { stacked: true, ticks: { color: axis }, grid: { display: false } },
                    y: {
                        stacked: true, beginAtZero: true, grace: "10%", ticks: { color: axis, callback: (v) => `${v}%` }, grid: { color: grid },
                        title: { display: true, text: "Downtime (%)", color: axis },
                    },
                },
                plugins: {
                    legend: { position: "bottom", labels: { color: axis, boxWidth: 12, usePointStyle: true } },
                    tooltip: {
                        // Bỏ nhóm = 0 cho gọn; Total + Target luôn hiện.
                        filter: (item) => item.dataset.type === "line" || (item.parsed.y !== null && item.parsed.y > 0),
                        callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? "-" : ctx.parsed.y.toFixed(2) + "%"}` },
                    },
                },
            },
        });
    }

    // Bấm 1 cột/điểm trên biểu đồ -> drawer chi tiết của đúng ô đó (cùng drawer với bảng).
    $("kd-chart").addEventListener("click", (e) => {
        const chart = charts["kd-chart"];
        if (!chart) return;
        const hit = chart.getElementsAtEventForMode(e, "nearest", { intersect: true }, false)[0];
        if (!hit) return;
        const ds = chart.data.datasets[hit.datasetIndex];
        if (ds.isTargetLine) return;
        const row = ds.type === "bar" ? report.rows.find((r) => rowLabel(r) === ds.label) : report.total_row;
        if (row) openDrawer(report.period_keys[hit.index], row.category, "downtime");
    });

    function renderAchievementChart() {
        if (!report || !report.period_keys.length) return;
        const fewPoints = report.periods.length <= 12;
        const ach = report.achievement;
        const rows = [ach.total_row, ...achievementSeries.picked().map((c) => ach.rows.find((r) => r.category === c)).filter(Boolean)];
        const colors = palette();
        const datasets = rows.map((row, i) => ({
            label: rowLabel(row), data: row.values, borderColor: colors[i % colors.length], backgroundColor: colors[i % colors.length],
            tension: 0.2, pointRadius: 3, spanGaps: true, showLabels: fewPoints && i === 0,
        }));
        drawLineChart("kd-ach-chart", datasets, { max: 100, grace: 0, title: { display: true, text: "Achievement (%)", color: token("--text-secondary", "#666") } });
    }
    document.addEventListener("colormodechange", () => { renderDowntimeChart(); renderAchievementChart(); });

    // ------------------------------------------------------------------ drill-down (chi tiết hằng ngày)
    const drawer = $("kd-drawer");
    let detail = null;
    let detailDay = null;
    let detailMode = "downtime";
    function closeDrawer() { drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true"); }
    $("kd-drawer-close").addEventListener("click", closeDrawer);
    drawer.addEventListener("click", (e) => { if (e.target === drawer) closeDrawer(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

    async function openDrawer(period, category, mode) {
        detailMode = mode;
        detailDay = null;
        const label = period === "ALL" ? "Total" : report.periods[report.period_keys.indexOf(period)];
        const row = report.rows.find((r) => r.category === category);
        $("kd-drawer-title").textContent = `${row ? rowLabel(row) : category} — ${label}${mode === "achievement" ? " (Standard Achievement)" : ""}`;
        $("kd-drawer-meta").textContent = "";
        $("kd-drawer-body").innerHTML = `<div class="drawer-empty">Loading...</div>`;
        drawer.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
        const params = filterParams();
        params.set("period", period);
        params.set("category", category);
        const res = await fetch(`${API}cell?${params}`);
        const data = await res.json();
        if (!res.ok) { $("kd-drawer-body").innerHTML = `<div class="drawer-empty">${esc(data.error || "Load failed")}</div>`; return; }
        detail = data;
        $("kd-drawer-meta").textContent = `${data.from_date} → ${data.to_date} · Stop ${fmtNum(data.stop_time)} / Plan PRD ${fmtNum(data.available)} = ${fmtPct(data.pct)} (target ${fmtPct(data.target)})`
            + ` · Achievement ${fmtPct(data.achievement_pct)} (${data.passed}/${data.evaluated} machine-days)`;
        renderDrawer();
    }

    function renderDrawer() {
        const d = detail;
        // Total hoặc Others đang gộp -> cần cột Category gốc để biết dòng dừng thuộc nhóm nào.
        const showCategory = d.category === "Total" || (d.merged && d.merged.length > 0);
        const dailyRows = d.daily.map((day) => `<tr class="cell-clickable${detailDay === day.production_date ? " is-selected" : ""}" tabindex="0" data-day="${day.production_date}">`
            + `<td>${esc(day.production_date)}</td><td class="num">${fmtNum(day.available)}</td><td class="num">${fmtNum(day.stop_time)}</td>`
            + `<td class="num${isOver(day.pct, d.target) ? " ratio-warning" : ""}">${fmtPct(day.pct)}</td><td class="num">${day.machines}</td>`
            + `<td class="num">${day.passed} / ${day.evaluated}</td><td class="num">${day.achievement_pct === null ? "N/A" : fmtPct(day.achievement_pct)}</td></tr>`).join("");
        const inDay = (r) => !detailDay || r.production_date === detailDay;
        let machineDays = d.machine_day_rows.filter(inDay);
        machineDays = detailMode === "achievement"
            ? machineDays.sort((a, b) => (a.achieved === b.achieved ? (b.pct ?? -1) - (a.pct ?? -1) : a.achieved === false ? -1 : 1))
            : machineDays.sort((a, b) => b.stop_time - a.stop_time);
        const status = (ok) => ok === null ? `<span class="Label Label--secondary">N/A</span>` : ok ? `<span class="Label">Achieved</span>` : `<span class="Label Label--danger">Not achieved</span>`;
        const stops = d.rows.filter(inDay);
        $("kd-drawer-body").innerHTML = `
            <div class="kd-drawer-section"><h4>Daily detail${detailDay ? ` <button class="btn btn-sm ml-2" type="button" id="kd-all-days">Show all days</button>` : ""}</h4>
                <p class="f6 color-fg-muted mt-0 mb-2">Click a day to see its machines and stop codes.</p>
                <div style="overflow-x:auto"><table class="preview-table kd-table" id="kd-daily"><thead><tr><th>Production Date</th><th class="num">Plan PRD</th><th class="num">Stop Time</th><th class="num">Downtime %</th><th class="num">Machines</th><th class="num">Achieved</th><th class="num">Achievement</th></tr></thead><tbody>${dailyRows}</tbody></table></div>
            </div>
            <div class="kd-drawer-section"><h4>Machine-days${detailDay ? ` — ${esc(detailDay)}` : ""} (${machineDays.length})</h4>
                <div style="overflow-x:auto"><table class="preview-table kd-table"><thead><tr><th>Production Date</th><th>M/c Code</th><th>Structure</th><th>Program</th><th class="num">Plan PRD</th><th class="num">Stop Time</th><th class="num">Downtime %</th><th>vs Target</th></tr></thead><tbody>`
            + (machineDays.map((m) => `<tr><td>${esc(m.production_date)}</td><td>${esc(m.machine_code)}</td><td>${esc(m.knitting_structure)}</td><td title="${esc(m.greige_id || "")}">${esc(m.program)}</td>`
                + `<td class="num">${fmtNum(m.available)}</td><td class="num">${fmtNum(m.stop_time)}</td><td class="num${isOver(m.pct, d.target) ? " ratio-warning" : ""}">${fmtPct(m.pct)}</td><td>${status(m.achieved)}</td></tr>`).join("")
                || `<tr><td colspan="8" class="color-fg-muted">No machine-days.</td></tr>`)
            + `</tbody></table></div></div>
            <div class="kd-drawer-section"><h4>Stops${detailDay ? ` — ${esc(detailDay)}` : ""} (${stops.length})</h4>
                <div style="overflow-x:auto"><table class="preview-table kd-table"><thead><tr><th>Production Date</th><th>M/c Code</th><th>Stop Code</th><th>Description</th>${showCategory ? "<th>Category</th>" : ""}<th class="num">Stop Time</th><th class="num">Stop #</th></tr></thead><tbody>`
            + (stops.map((r) => `<tr><td>${esc(r.production_date)}</td><td>${esc(r.machine_code)}</td><td>${esc(r.stop_code)}</td><td>${esc(r.stop_description)}</td>${showCategory ? `<td>${esc(r.category)}</td>` : ""}`
                + `<td class="num">${fmtNum(r.stop_time)}</td><td class="num">${fmtNum(r.stop_count, 0)}</td></tr>`).join("")
                || `<tr><td colspan="7" class="color-fg-muted">No stops.</td></tr>`)
            + `</tbody></table></div></div>`;
        const pick = (row) => { detailDay = detailDay === row.dataset.day ? null : row.dataset.day; renderDrawer(); };
        $("kd-daily").querySelectorAll("tr[data-day]").forEach((row) => {
            row.addEventListener("click", () => pick(row));
            row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(row); } });
        });
        const all = $("kd-all-days");
        if (all) all.addEventListener("click", () => { detailDay = null; renderDrawer(); });
    }

    // ------------------------------------------------------------------ Stop Code Mapping
    async function loadMapping() {
        const res = await fetch(`${API}stop-codes`);
        const data = await res.json();
        const body = $("kd-mapping");
        body.innerHTML = data.stop_codes.map((r) => {
            const category = IS_ADMIN
                ? `<select class="form-select kd-map-select" data-code="${esc(r.stop_code)}">`
                    + `<option value="">Default (${esc(r.default_category)})</option>`
                    + data.categories.map((c) => `<option value="${esc(c)}" ${r.source === "manual" && r.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")
                    + `</select>`
                : esc(r.category);
            const sourceClass = r.source === "unmapped" ? "Label Label--danger" : r.source === "manual" ? "Label" : "Label Label--secondary";
            return `<tr><td>${esc(r.stop_code)}</td><td>${esc(r.stop_description)}</td><td>${category}</td><td><span class="${sourceClass}">${esc(r.source)}</span></td>`
                + `<td class="num">${fmtNum(r.stop_time)}</td><td class="num">${r.records}</td><td>${esc(r.first_date)}</td><td>${esc(r.last_date)}</td></tr>`;
        }).join("") || `<tr><td colspan="8" class="color-fg-muted">No stop codes imported yet.</td></tr>`;
        body.querySelectorAll(".kd-map-select").forEach((select) => select.addEventListener("change", async () => {
            const res2 = await fetch(`${API}stop-codes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stop_code: select.dataset.code, category: select.value || null }) });
            if (!res2.ok) { const err = await res2.json().catch(() => ({})); alert(err.error || "Save failed"); }
            await Promise.all([loadMapping(), loadReport()]);
        }));
    }

    // ------------------------------------------------------------------ tabs + init
    const tabs = [...document.querySelectorAll("#kd-tabs .page-tab")];
    tabs.forEach((tab) => tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
        document.querySelectorAll(".kd-page").forEach((page) => { page.hidden = page.dataset.page !== tab.dataset.page; });
        if (tab.dataset.page === "mapping") loadMapping();
        if (tab.dataset.page === "overview" && charts["kd-chart"]) charts["kd-chart"].resize();
        if (tab.dataset.page === "achievement" && charts["kd-ach-chart"]) charts["kd-ach-chart"].resize();
    }));

    document.querySelectorAll("#kd-unit .btn").forEach((btn) => btn.addEventListener("click", () => {
        unit = btn.dataset.unit;
        document.querySelectorAll("#kd-unit .btn").forEach((b) => { b.classList.toggle("is-active", b === btn); b.setAttribute("aria-pressed", String(b === btn)); });
        if (report && report.period_keys.length) renderPivot();
    }));
    ["kd-from", "kd-to", "kd-group-by"].forEach((id) => $(id).addEventListener("change", scheduleLoad));

    async function initFilters() {
        const res = await fetch(`${API}filters`);
        const data = await res.json();
        machineFilter.setOptions(data.machines);
        structureFilter.setOptions(data.structures);
        programFilter.setOptions(data.programs);
        // Giống Dyeing: 6 tuần (từ Thứ Hai 5 tuần trước), tính theo ngày mới nhất đã import.
        const end = data.latest_date ? new Date(`${data.latest_date}T00:00:00`) : new Date();
        const start = new Date(end);
        start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 5 * 7);
        $("kd-from").value = isoDate(start);
        $("kd-to").value = isoDate(end);
    }

    initFilters().then(loadReport);
})();
