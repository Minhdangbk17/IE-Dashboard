/* Knitting Incentive — filter bar chung (Tháng / As of / Machine Group); tab Overview: KPI + biểu đồ
   %Achieve cộng dồn ở trên, bảng nhóm + bảng ngày ở dưới (bấm ngày -> drawer máy/cuộn). */
(function () {
    "use strict";
    const API = window.KI_API;
    const IS_ADMIN = window.KI_IS_ADMIN;
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmtPct = (v, d = 2) => (v === null || v === undefined) ? "-" : `${Number(v).toFixed(d)}%`;
    const fmtNum = (v, d = 2) => (v === null || v === undefined) ? "-" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    const belowThreshold = (v) => report && report.threshold_pct !== null && v !== null && v !== undefined && v <= report.threshold_pct + 1e-9;

    let report = null;
    let chart = null;
    let seq = 0;

    // ------------------------------------------------------------------ Machine Group multi-select
    const groupToggle = $("ki-group-toggle");
    const groupMenu = $("ki-group-menu");
    let groupOptions = [];
    const groupSelected = new Set();
    function renderGroups() {
        groupToggle.textContent = groupSelected.size === 0 ? "All groups" : groupSelected.size === 1 ? [...groupSelected][0] : `${groupSelected.size} selected`;
        groupMenu.innerHTML = groupOptions.length
            ? `<label class="ki-option"><input type="checkbox" class="ki-all" ${groupSelected.size === 0 ? "checked" : ""}> All</label><div class="border-top my-1"></div>`
              + groupOptions.map((g) => `<label class="ki-option"><input type="checkbox" class="ki-opt" value="${esc(g)}" ${groupSelected.has(g) ? "checked" : ""}> ${esc(g)}</label>`).join("")
            : `<span class="f6 color-fg-muted">No data</span>`;
        const all = groupMenu.querySelector(".ki-all");
        if (all) all.addEventListener("change", () => { if (all.checked) { groupSelected.clear(); renderGroups(); load(); } else { all.checked = true; } });
        groupMenu.querySelectorAll(".ki-opt").forEach((box) => box.addEventListener("change", () => {
            if (box.checked) groupSelected.add(box.value); else groupSelected.delete(box.value);
            renderGroups(); load();
        }));
    }
    groupToggle.addEventListener("click", (e) => { e.stopPropagation(); groupMenu.hidden = !groupMenu.hidden; groupToggle.setAttribute("aria-expanded", String(!groupMenu.hidden)); });
    document.addEventListener("click", (e) => { if (!groupToggle.parentElement.contains(e.target)) groupMenu.hidden = true; });

    function params() {
        const p = new URLSearchParams();
        if ($("ki-month").value) p.set("month", $("ki-month").value);
        if ($("ki-as-of").value) p.set("as_of", $("ki-as-of").value);
        if (groupSelected.size) p.set("groups", [...groupSelected].join("|"));
        return p;
    }

    // ------------------------------------------------------------------ load + render
    async function load() {
        const p = params();
        $("ki-export").href = `${API}export?${p}`;
        const mine = ++seq;
        const res = await fetch(`${API}summary?${p}`);
        const data = await res.json();
        if (mine !== seq) return;
        $("ki-error").hidden = res.ok;
        if (!res.ok) { $("ki-error").textContent = data.error || "Load failed"; return; }
        report = data;
        $("ki-month").value = data.filters.month;
        $("ki-as-of").value = data.filters.to_date;
        $("ki-as-of").min = data.filters.from_date;
        const empty = !data.daily.length;
        $("ki-empty").hidden = !empty;
        document.querySelectorAll(".ki-page[data-page=overview], .ki-page[data-page=machines]").forEach((page) => page.classList.toggle("d-none", empty));
        $("ki-missing").hidden = !data.missing_rolls;
        $("ki-missing").textContent = data.missing_rolls
            ? `${fmtNum(data.missing_rolls, 0)} rolls have no KNT N.W / Std.PTM (imported before these columns were stored). Re-import the Piece Produced file of this month.`
            : "";
        renderBands();
        if (empty) return;
        renderKpis();
        renderGroupTable();
        renderDaily();
        renderMachines();
        renderChart();
    }

    function renderKpis() {
        const w = report.workshop;
        $("kpi-ach").textContent = fmtPct(w.achievement_pct);
        $("kpi-ach").className = belowThreshold(w.achievement_pct) ? "kpi-bad" : "kpi-good";
        $("kpi-ach-sub").textContent = `${report.filters.from_date} → ${report.filters.to_date}`;
        $("kpi-unit").textContent = fmtNum(w.unit, 0);
        const b = w.band;
        $("kpi-unit-sub").textContent = b && b.next_from_pct !== null
            ? `VND/kg — +${fmtPct(b.gap_to_next_pct)} to reach ${fmtNum(b.next_unit, 0)} VND/kg (> ${fmtPct(b.next_from_pct, 1)})`
            : "VND/kg — highest band";
        $("kpi-kg").textContent = fmtNum(w.kg, 0);
        $("kpi-rolls").textContent = fmtNum(w.rolls, 0);
        $("kpi-incentive").textContent = fmtNum(w.incentive, 0);
    }

    function renderGroupTable() {
        const row = (r, total) => {
            const b = r.band;
            const gap = b && b.next_from_pct !== null ? `+${fmtPct(b.gap_to_next_pct)}` : "-";
            return `<tr class="${total ? "total-row" : ""}"><th>${esc(r.name)}</th><td class="num">${fmtNum(r.kg)}</td><td class="num">${fmtNum(r.std_minutes)}</td><td class="num">${fmtNum(r.available)}</td>`
                + `<td class="num${belowThreshold(r.achievement_pct) ? " ratio-warning" : ""}">${fmtPct(r.achievement_pct)}</td><td class="num">${fmtNum(r.unit, 0)}</td><td class="num">${fmtNum(r.incentive, 0)}</td><td class="num">${gap}</td></tr>`;
        };
        $("ki-groups").innerHTML = row(report.workshop, true) + report.groups.map((g) => row(g, false)).join("");
    }

    function renderDaily() {
        $("ki-daily").innerHTML = report.daily.map((d) => `<tr class="cell-clickable" tabindex="0" data-day="${d.date}"><td>${esc(d.date)}</td><td class="num">${fmtNum(d.kg)}</td><td class="num">${fmtNum(d.std_minutes)}</td>`
            + `<td class="num">${fmtNum(d.available)}</td><td class="num${belowThreshold(d.day_pct) ? " ratio-warning" : ""}">${fmtPct(d.day_pct)}</td>`
            + `<td class="num${belowThreshold(d.mtd_pct) ? " ratio-warning" : ""}">${fmtPct(d.mtd_pct)}</td><td class="num">${fmtNum(d.mtd_unit, 0)}</td><td class="num">${fmtNum(d.mtd_incentive, 0)}</td><td class="num">${d.rolls}</td></tr>`).join("");
    }
    $("ki-daily").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-day]"); if (tr) openDay(tr.dataset.day); });
    $("ki-daily").addEventListener("keydown", (e) => {
        const tr = e.target.closest("tr[data-day]");
        if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDay(tr.dataset.day); }
    });

    function machineRows(list) {
        return list.map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.group)}</td><td class="num">${fmtNum(m.kg)}</td><td class="num">${fmtNum(m.std_minutes)}</td><td class="num">${fmtNum(m.available)}</td>`
            + `<td class="num${belowThreshold(m.achievement_pct) ? " ratio-warning" : ""}">${fmtPct(m.achievement_pct)}</td><td class="num">${m.rolls}</td></tr>`).join("")
            || `<tr><td colspan="7" class="color-fg-muted">No machines.</td></tr>`;
    }
    function renderMachines() { $("ki-machines").innerHTML = machineRows(report.machines); }

    // ------------------------------------------------------------------ chart
    function token(name, fallback) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback; }
    function renderChart() {
        if (!report || !report.daily.length || typeof Chart === "undefined") return;
        const axis = token("--text-secondary", "#666");
        const grid = token("--border-subtle", "#ddd");
        const colors = [token("--accent", "#2862d7"), token("--accent-purple", "#625fff"), token("--success", "#3fb950"), token("--warning", "#d29922")];
        const labels = report.daily.map((d) => d.date.slice(5));
        // Quy tắc line chart: <= 4 đường — Xưởng + tối đa 3 nhóm.
        const series = [{ name: "Workshop", data: report.daily.map((d) => d.mtd_pct) }]
            .concat(report.group_names.slice(0, 3).map((g) => ({ name: g, data: report.daily.map((d) => d.mtd_pct_by_group[g]) })));
        const datasets = series.map((s, i) => ({ label: s.name, data: s.data, borderColor: colors[i], backgroundColor: colors[i], tension: 0.2, pointRadius: 2, spanGaps: true, borderWidth: i === 0 ? 2.5 : 1.5 }));
        if (report.threshold_pct !== null) {
            datasets.push({ label: `Incentive threshold (> ${fmtPct(report.threshold_pct, 1)})`, data: labels.map(() => report.threshold_pct), borderColor: token("--danger", "#f85149"), borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, isTargetLine: true });
        }
        if (chart) chart.destroy();
        chart = new Chart($("ki-chart"), {
            type: "line",
            data: { labels, datasets },
            options: {
                responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                scales: {
                    x: { ticks: { color: axis }, grid: { color: grid } },
                    y: { grace: "5%", ticks: { color: axis, callback: (v) => `${v}%` }, grid: { color: grid }, title: { display: true, text: "%Achieve (MTD)", color: axis } },
                },
                plugins: {
                    legend: { position: "bottom", labels: { color: axis, boxWidth: 12, usePointStyle: true } },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? "-" : ctx.parsed.y.toFixed(2) + "%"}` } },
                },
            },
        });
    }
    document.addEventListener("colormodechange", renderChart);

    // ------------------------------------------------------------------ day drawer
    const drawer = $("ki-drawer");
    function closeDrawer() { drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true"); }
    $("ki-drawer-close").addEventListener("click", closeDrawer);
    drawer.addEventListener("click", (e) => { if (e.target === drawer) closeDrawer(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

    async function openDay(day) {
        $("ki-drawer-title").textContent = `Day detail — ${day}`;
        $("ki-drawer-meta").textContent = "";
        $("ki-drawer-body").innerHTML = `<div class="drawer-empty">Loading...</div>`;
        drawer.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
        const p = params();
        p.set("date", day);
        const res = await fetch(`${API}day?${p}`);
        const data = await res.json();
        if (!res.ok) { $("ki-drawer-body").innerHTML = `<div class="drawer-empty">${esc(data.error || "Load failed")}</div>`; return; }
        $("ki-drawer-meta").textContent = `Day %Achieve ${fmtPct(data.achievement_pct)} · KNT N.W ${fmtNum(data.kg)} kg · ${data.rolls.length} rolls`;
        $("ki-drawer-body").innerHTML = `
            <div class="ki-drawer-section"><h4>Machines (${data.machines.length})</h4><div style="overflow-x:auto"><table class="preview-table ki-table">
                <thead><tr><th>M/c Code</th><th>Machine Group</th><th class="num">KNT N.W (kg)</th><th class="num">Std minutes</th><th class="num">Available</th><th class="num">%Achieve</th><th class="num">Rolls</th></tr></thead>
                <tbody>${machineRows(data.machines)}</tbody></table></div></div>
            <div class="ki-drawer-section"><h4>Rolls (${data.rolls.length})</h4><div style="overflow-x:auto"><table class="preview-table ki-table">
                <thead><tr><th>Roll No</th><th>M/c Code</th><th>Job ID</th><th>Greige ID</th><th>Operator</th><th class="num">KNT N.W (kg)</th><th class="num">Std.PTM</th><th class="num">Std minutes</th><th class="num">Available</th><th>Record Start</th></tr></thead>
                <tbody>${data.rolls.map((r) => `<tr><td>${esc(r.roll_no)}</td><td>${esc(r.machine_code)}</td><td>${esc(r.job_id)}</td><td>${esc(r.greige_id)}</td><td>${esc(r.operator_code)}</td>`
                    + `<td class="num">${fmtNum(r.knt_nw_kg)}</td><td class="num">${fmtNum(r.std_ptm, 3)}</td><td class="num">${fmtNum(r.std_minutes)}</td><td class="num">${fmtNum(r.available)}</td><td>${esc(r.record_start)}</td></tr>`).join("")}</tbody></table></div></div>`;
    }

    // ------------------------------------------------------------------ bands
    let editBands = null;
    function renderBands() {
        const bands = editBands || report.bands;
        const current = report.workshop && report.workshop.band ? report.workshop.band.index : -1;
        $("ki-bands").innerHTML = bands.map((b, i) => IS_ADMIN
            ? `<tr class="${i === current && !editBands ? "is-current" : ""}"><td class="num"><input class="form-control" type="number" step="0.1" data-i="${i}" data-k="from_pct" value="${b.from_pct}"></td>`
              + `<td class="num"><input class="form-control" type="number" step="0.1" data-i="${i}" data-k="to_pct" value="${b.to_pct}"></td>`
              + `<td class="num"><input class="form-control" type="number" step="1" min="0" data-i="${i}" data-k="unit" value="${b.unit}"> <button class="btn btn-sm btn-danger ki-band-del" type="button" data-i="${i}" aria-label="Remove band" title="Remove band">×</button></td></tr>`
            : `<tr class="${i === current ? "is-current" : ""}"><td class="num">${fmtPct(b.from_pct, 1)}</td><td class="num">${fmtPct(b.to_pct, 1)}</td><td class="num">${fmtNum(b.unit, 0)}</td></tr>`).join("");
    }
    if (IS_ADMIN) {
        const current = () => (editBands = editBands || report.bands.map((b) => ({ ...b })));
        $("ki-bands").addEventListener("input", (e) => {
            const input = e.target.closest("input[data-i]");
            if (input) current()[Number(input.dataset.i)][input.dataset.k] = input.value === "" ? null : Number(input.value);
        });
        $("ki-bands").addEventListener("click", (e) => {
            const del = e.target.closest(".ki-band-del");
            if (del) { current().splice(Number(del.dataset.i), 1); renderBands(); }
        });
        $("ki-band-add").addEventListener("click", () => {
            const list = current();
            const last = list[list.length - 1];
            list.push({ from_pct: last ? last.to_pct : 0, to_pct: last ? last.to_pct + 2 : 100, unit: last ? last.unit : 0 });
            renderBands();
        });
        $("ki-band-save").addEventListener("click", async () => {
            const res = await fetch(`${API}bands`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bands: current() }) });
            const data = await res.json().catch(() => ({}));
            $("ki-band-msg").className = `f6 mt-2 mb-0 ${res.ok ? "color-fg-success" : "color-fg-danger"}`;
            $("ki-band-msg").textContent = res.ok ? "Bands saved." : (data.error || "Save failed");
            if (res.ok) { editBands = null; load(); }
        });
    }

    // ------------------------------------------------------------------ tabs + init
    const tabs = [...document.querySelectorAll("#ki-tabs .page-tab")];
    tabs.forEach((tab) => tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
        document.querySelectorAll(".ki-page").forEach((page) => { page.hidden = page.dataset.page !== tab.dataset.page; });
        if (tab.dataset.page === "overview" && chart) chart.resize();
    }));
    $("ki-month").addEventListener("change", () => { $("ki-as-of").value = ""; load(); });
    $("ki-as-of").addEventListener("change", load);

    fetch(`${API}options`).then((r) => r.json()).then((data) => {
        groupOptions = data.groups || [];
        renderGroups();
        load();
    });
})();
