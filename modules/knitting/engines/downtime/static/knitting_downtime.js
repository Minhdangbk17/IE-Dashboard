/* Knitting Downtime — filter bar dùng chung cho mọi tab, pivot % Downtime, biểu đồ, drill-down,
   Stop Code Mapping, import nhiều file. */
(function () {
    "use strict";
    const API = window.KD_API;
    const IS_ADMIN = window.KD_IS_ADMIN;
    const CATEGORIES = window.KD_CATEGORIES;
    const MAX_EXTRA_SERIES = 3;

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmtPct = (v) => (v === null || v === undefined) ? "-" : `${Number(v).toFixed(1)}%`;
    const fmtNum = (v, d = 2) => (v === null || v === undefined) ? "-" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    let unit = "pct";
    let report = null;
    let chart = null;
    let extraSeries = [];
    let requestSeq = 0;

    // ------------------------------------------------------------------ multi-select
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
        toggle.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; toggle.setAttribute("aria-expanded", String(!menu.hidden)); });
        document.addEventListener("click", (e) => { if (!toggle.parentElement.contains(e.target)) { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); } });
        updateLabel();
        return {
            setOptions(values) { options = values; [...selected].forEach((v) => { if (!values.includes(v)) selected.delete(v); }); render(); updateLabel(); },
            selected: () => [...selected],
        };
    }

    const machineFilter = makeMultiSelect("kd-machine-toggle", "kd-machine-menu", "All machines", scheduleLoad, true);
    const structureFilter = makeMultiSelect("kd-structure-toggle", "kd-structure-menu", "All structures", scheduleLoad, false);
    const programFilter = makeMultiSelect("kd-program-toggle", "kd-program-menu", "All programs", scheduleLoad, true);
    $("kd-core-only").addEventListener("change", scheduleLoad);

    function filterParams() {
        const p = new URLSearchParams({ from_date: $("kd-from").value, to_date: $("kd-to").value, group_by: $("kd-group-by").value });
        if (machineFilter.selected().length) p.set("machines", machineFilter.selected().join(","));
        if (structureFilter.selected().length) p.set("structures", structureFilter.selected().join(","));
        // Tên Program có thể chứa dấu phẩy -> phân tách bằng "|".
        if (programFilter.selected().length) p.set("programs", programFilter.selected().join("|"));
        if ($("kd-core-only").checked) p.set("core_only", "1");
        return p;
    }

    // ------------------------------------------------------------------ load + pivot
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
        $("kd-report").hidden = empty;
        $("kd-unmapped").hidden = !data.unmapped_codes.length;
        $("kd-unmapped").innerHTML = data.unmapped_codes.length
            ? `Stop codes without a category (counted in Total as "Unmapped"): ${data.unmapped_codes.map((c) => `<strong>${esc(c.stop_code)}</strong> ${esc(c.stop_description)}`).join(", ")}. Set them in Stop Code Mapping.`
            : "";
        if (!empty) { renderPivot(); renderChart(); }
    }

    function cellValue(row, index) { return unit === "pct" ? row.pct[index] : row.stop_time[index]; }
    function fmtCell(v) { return unit === "pct" ? fmtPct(v) : fmtNum(v); }
    function over(row, v) { return unit === "pct" && row.target !== null && v !== null && v > row.target + 1e-9; }

    function renderPivot() {
        const head = $("kd-pivot-head");
        head.innerHTML = `<th>Downtime ${unit === "pct" ? "(%)" : "(stop time)"}</th><th class="num">Before</th><th class="num">Target</th>`
            + report.periods.map((p) => `<th class="num">${esc(p)}</th>`).join("") + `<th class="num">Total</th>`;
        const body = $("kd-pivot").querySelector("tbody");
        const rowHtml = (row, isTotal) => {
            const refCell = (field) => {
                const editable = IS_ADMIN && !isTotal && row.category !== "Unmapped";
                return `<td class="num ref${editable ? " cell-clickable kd-target" : ""}" ${editable ? `tabindex="0" data-field="${field}" data-category="${esc(row.category)}"` : ""}>${fmtPct(row[field])}</td>`;
            };
            const cells = report.period_keys.map((key, i) => {
                const v = cellValue(row, i);
                return `<td class="num cell-clickable${over(row, v) ? " ratio-warning" : ""}" tabindex="0" data-period="${key}" data-category="${esc(row.category)}">${fmtCell(v)}</td>`;
            }).join("");
            const total = unit === "pct" ? row.total_pct : row.total_stop_time;
            return `<tr class="${isTotal ? "total-row" : ""}"><th>${esc(row.category)}</th>${refCell("before")}${refCell("target")}${cells}`
                + `<td class="num cell-clickable${over(row, total) ? " ratio-warning" : ""}" tabindex="0" data-period="ALL" data-category="${esc(row.category)}"><strong>${fmtCell(total)}</strong></td></tr>`;
        };
        const planRow = `<tr class="plan-row"><th>Plan PRD (Available)</th><td></td><td></td>${report.available.map((v) => `<td class="num">${fmtNum(v)}</td>`).join("")}<td class="num">${fmtNum(report.total_available)}</td></tr>`;
        body.innerHTML = report.rows.map((r) => rowHtml(r, false)).join("") + rowHtml(report.total_row, true) + planRow;
    }

    $("kd-pivot").addEventListener("click", (e) => {
        const target = e.target.closest(".kd-target");
        if (target) { editTarget(target); return; }
        const cell = e.target.closest("td[data-period]");
        if (cell) openDrawer(cell.dataset.period, cell.dataset.category);
    });
    $("kd-pivot").addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const cell = e.target.closest("td.cell-clickable");
        if (!cell || cell.querySelector("input")) return;
        e.preventDefault();
        cell.click();
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
                await loadReport();
            } else {
                renderPivot();
            }
        };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
        input.addEventListener("blur", () => finish(true));
    }

    // ------------------------------------------------------------------ chart
    function token(name, fallback) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback; }

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

    function renderChart() {
        if (!report || typeof Chart === "undefined") return;
        const palette = [token("--accent", "#2862d7"), token("--accent-purple", "#625fff"), token("--success", "#3fb950"), token("--warning", "#d29922")];
        const axis = token("--text-secondary", "#666");
        const grid = token("--border-subtle", "#ddd");
        const fewPoints = report.periods.length <= 12;
        const series = [report.total_row, ...extraSeries.map((c) => report.rows.find((r) => r.category === c)).filter(Boolean)];
        const datasets = [];
        series.forEach((row, i) => {
            const color = palette[i % palette.length];
            datasets.push({ label: row.category, data: row.pct, borderColor: color, backgroundColor: color, tension: 0.2, pointRadius: 3, showLabels: fewPoints && i === 0 });
            if (row.target !== null && row.target !== undefined) {
                datasets.push({ label: `${row.category} target`, data: report.periods.map(() => row.target), borderColor: color, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, isTargetLine: true });
            }
        });
        if (chart) chart.destroy();
        chart = new Chart($("kd-chart"), {
            type: "line",
            data: { labels: report.periods, datasets },
            plugins: [valueLabels],
            options: {
                responsive: true, maintainAspectRatio: false, layout: { padding: { top: 20, left: 8, right: 16 } },
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: axis }, grid: { color: grid } },
                    y: { beginAtZero: true, grace: "10%", ticks: { color: axis, callback: (v) => `${v}%` }, grid: { color: grid } },
                },
                plugins: {
                    legend: { labels: { color: axis, boxWidth: 12 } },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? "-" : ctx.parsed.y.toFixed(2) + "%"}` } },
                },
            },
        });
    }

    (function initSeriesSelector() {
        const toggle = $("kd-series-toggle");
        const menu = $("kd-series-menu");
        function updateLabel() { toggle.textContent = extraSeries.length ? `Total + ${extraSeries.length} categories` : "Total"; }
        function render() {
            menu.innerHTML = `<label class="kd-option"><input type="checkbox" checked disabled> Total</label><div class="border-top my-1"></div>`
                + CATEGORIES.map((c) => {
                    const checked = extraSeries.includes(c);
                    const disabled = !checked && extraSeries.length >= MAX_EXTRA_SERIES;
                    return `<label class="kd-option"><input type="checkbox" value="${esc(c)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}> ${esc(c)}</label>`;
                }).join("");
            menu.querySelectorAll("input[value]").forEach((box) => box.addEventListener("change", () => {
                if (box.checked) extraSeries.push(box.value); else extraSeries = extraSeries.filter((c) => c !== box.value);
                render(); updateLabel(); renderChart();
            }));
        }
        toggle.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; toggle.setAttribute("aria-expanded", String(!menu.hidden)); });
        document.addEventListener("click", (e) => { if (!toggle.parentElement.contains(e.target)) menu.hidden = true; });
        render();
    })();
    document.addEventListener("colormodechange", renderChart);

    // ------------------------------------------------------------------ drill-down
    const drawer = $("kd-drawer");
    function closeDrawer() { drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true"); }
    $("kd-drawer-close").addEventListener("click", closeDrawer);
    drawer.addEventListener("click", (e) => { if (e.target === drawer) closeDrawer(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

    async function openDrawer(period, category) {
        const label = period === "ALL" ? "Total" : report.periods[report.period_keys.indexOf(period)];
        $("kd-drawer-title").textContent = `${category} — ${label}`;
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
        $("kd-drawer-meta").textContent = `${data.from_date} → ${data.to_date} · Stop time ${fmtNum(data.stop_time)} / Plan PRD ${fmtNum(data.available)} (${data.machine_days} machine-days) = ${fmtPct(data.pct)} · ${data.rows.length} rows`;
        const showCategory = category === "Total";
        $("kd-drawer-body").innerHTML = data.rows.length ? `<table class="preview-table kd-table"><thead><tr><th>Production Date</th><th>M/c Code</th><th>Structure</th><th>Stop Code</th><th>Description</th>${showCategory ? "<th>Category</th>" : ""}<th>Program</th><th class="num">Stop Time</th><th class="num">Stop #</th></tr></thead><tbody>`
            + data.rows.map((r) => `<tr><td>${esc(r.production_date)}</td><td>${esc(r.machine_code)}</td><td>${esc(r.knitting_structure)}</td><td>${esc(r.stop_code)}</td><td>${esc(r.stop_description)}</td>${showCategory ? `<td>${esc(r.category)}</td>` : ""}<td title="${esc(r.greige_id || "")}">${esc(r.program)}</td><td class="num">${fmtNum(r.stop_time)}</td><td class="num">${fmtNum(r.stop_count, 0)}</td></tr>`).join("")
            + `</tbody></table>` : `<div class="drawer-empty">No stops in this cell.</div>`;
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
            const res = await fetch(`${API}stop-codes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stop_code: select.dataset.code, category: select.value || null }) });
            if (!res.ok) { const err = await res.json().catch(() => ({})); alert(err.error || "Save failed"); }
            await Promise.all([loadMapping(), loadReport()]);
        }));
    }

    // ------------------------------------------------------------------ import + days
    async function loadDays() {
        const res = await fetch(`${API}days`);
        const data = await res.json();
        $("kd-days").innerHTML = (data.days || []).map((d) => `<tr><td>${esc(d.production_date)}</td><td>${esc(d.period_start)} → ${esc(d.period_end)}</td>`
            + `<td class="num">${d.machines}</td><td>${esc(d.file_name)}</td><td>${esc(d.imported_by)}</td><td>${esc(d.imported_at)}</td></tr>`).join("")
            || `<tr><td colspan="6" class="color-fg-muted">No imports yet.</td></tr>`;
        const s = data.sources;
        $("kd-sources-rolls").innerHTML = s.rolls
            ? `<strong>Piece Produced:</strong> ${fmtNum(s.rolls, 0)} rolls, ${s.roll_machines} machines, Record End ${esc(s.rolls_from)} → ${esc(s.rolls_to)}`
            : `<strong>Piece Produced:</strong> not imported — Program is blank for every machine-day (filter "(Blank)").`;
        $("kd-sources-programs").innerHTML = s.greige_codes
            ? `<strong>Knitting program:</strong> ${s.greige_codes} Greige codes, ${s.programs} programs. Core: ${s.core_programs.map(esc).join(", ") || "-"}`
            : `<strong>Knitting program:</strong> not imported.`;
    }

    const form = $("kd-import-form");
    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const files = [...$("kd-file").files].sort((a, b) => a.name.localeCompare(b.name));
            if (!files.length) return;
            const list = $("kd-import-result");
            list.innerHTML = "";
            $("kd-import-btn").disabled = true;
            let ok = 0;
            for (const [i, file] of files.entries()) {
                const line = document.createElement("p");
                line.className = "flash mb-1";
                line.textContent = `(${i + 1}/${files.length}) ${file.name} — uploading...`;
                list.prepend(line);
                const body = new FormData();
                body.append("file", file, file.name);
                try {
                    const res = await fetch(`${API}import`, { method: "POST", body });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || "Import failed");
                    ok += 1;
                    const notes = [...data.errors.map((er) => `Row ${er.row}: ${er.error}`), ...data.warnings];
                    line.className = `flash flash-${data.status === "completed" && !data.warnings.length ? "success" : "warn"} mb-1`;
                    let summary;
                    if (data.file_type === "KNITTING_PIECE_PRODUCED") {
                        summary = `Piece Produced: ${fmtNum(data.rolls, 0)} rolls, ${data.machines} machines, Record End ${esc(data.date_from)} → ${esc(data.date_to)}`;
                    } else if (data.file_type === "KNITTING_PROGRAM") {
                        summary = `Knitting program: ${data.greige_codes} Greige codes, ${data.programs} programs, core: ${data.core_programs.map(esc).join(", ")}`;
                    } else {
                        summary = `<strong>${esc(data.production_date)}</strong>: ${data.machines} machines, ${data.stops} stop rows${data.replaced_existing ? " (replaced)" : ""}`;
                    }
                    line.innerHTML = `${esc(file.name)} → ${summary}` + (notes.length ? "<br>" + notes.slice(0, 5).map(esc).join("<br>") + (notes.length > 5 ? `<br>… ${notes.length - 5} more` : "") : "");
                } catch (err) {
                    line.className = "flash flash-error mb-1";
                    line.textContent = `${file.name}: ${err.message || err}`;
                }
            }
            $("kd-import-btn").disabled = false;
            form.reset();
            const summary = document.createElement("p");
            summary.className = "f6 text-bold mb-1";
            summary.textContent = `Done: ${ok}/${files.length} file(s) imported.`;
            list.prepend(summary);
            await initFilters(false);
            await Promise.all([loadDays(), loadReport()]);
        });
    }

    // ------------------------------------------------------------------ tabs + init
    const tabs = [...document.querySelectorAll("#kd-tabs .page-tab")];
    tabs.forEach((tab) => tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
        document.querySelectorAll(".kd-page").forEach((page) => { page.hidden = page.dataset.page !== tab.dataset.page; });
        if (tab.dataset.page === "mapping") loadMapping();
        if (tab.dataset.page === "import") loadDays();
        if (tab.dataset.page === "overview") renderChart();
    }));

    document.querySelectorAll("#kd-unit .btn").forEach((btn) => btn.addEventListener("click", () => {
        unit = btn.dataset.unit;
        document.querySelectorAll("#kd-unit .btn").forEach((b) => { b.classList.toggle("is-active", b === btn); b.setAttribute("aria-pressed", String(b === btn)); });
        if (report) renderPivot();
    }));
    ["kd-from", "kd-to", "kd-group-by"].forEach((id) => $(id).addEventListener("change", scheduleLoad));

    async function initFilters(setDates) {
        const res = await fetch(`${API}filters`);
        const data = await res.json();
        machineFilter.setOptions(data.machines);
        structureFilter.setOptions(data.structures);
        programFilter.setOptions(data.programs);
        if (setDates || !$("kd-from").value) {
            // Giống Dyeing: 6 tuần (từ Thứ Hai 5 tuần trước), tính theo ngày mới nhất đã import.
            const end = data.latest_date ? new Date(`${data.latest_date}T00:00:00`) : new Date();
            const start = new Date(end);
            start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 5 * 7);
            $("kd-from").value = isoDate(start);
            $("kd-to").value = isoDate(end);
        }
    }

    initFilters(true).then(loadReport);
})();
