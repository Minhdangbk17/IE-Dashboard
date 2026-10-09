/* Modal Import trên Knitting Hub — nhiều file, tải TUẦN TỰ từng file (mỗi file 1 request, 1 dòng
   kết quả), Data Type auto-detect hoặc chọn tay; khối Data status + lịch sử import bên dưới. */
(function () {
    "use strict";
    const modal = document.getElementById("kh-import");
    if (!modal) return;
    const IMPORT_URL = modal.dataset.importUrl;
    const STATUS_URL = modal.dataset.statusUrl;
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmt = (v) => Number(v || 0).toLocaleString("en-US");
    const TYPE_LABELS = { KNITTING_STOP_REASON: "Stop Reason", KNITTING_PIECE_PRODUCED: "Piece Produced", KNITTING_PROGRAM: "Knitting program" };
    let busy = false;

    function open() { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); loadStatus(); }
    function close() { if (busy) return; modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }
    $("kh-open-import").addEventListener("click", open);
    $("kh-close-import").addEventListener("click", close);
    $("kh-cancel-import").addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal.classList.contains("is-open")) close(); });

    const dropzone = $("kh-dropzone");
    const input = $("kh-file-input");
    dropzone.addEventListener("click", () => { if (!busy) input.click(); });
    dropzone.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); input.click(); } });
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); if (!busy) importFiles([...e.dataTransfer.files]); });
    input.addEventListener("change", () => { importFiles([...input.files]); input.value = ""; });

    function summary(data) {
        if (data.file_type === "KNITTING_PIECE_PRODUCED") {
            return `Piece Produced: ${fmt(data.rolls)} rolls, ${data.machines} machines, Record End ${esc(data.date_from)} → ${esc(data.date_to)}`;
        }
        if (data.file_type === "KNITTING_PROGRAM") {
            return `Knitting program: ${data.greige_codes} Greige codes, ${data.programs} programs, core: ${data.core_programs.map(esc).join(", ")}`;
        }
        return `Stop Reason <strong>${esc(data.production_date)}</strong>: ${data.machines} machines, ${data.stops} stop rows${data.replaced_existing ? " (replaced)" : ""}`;
    }

    async function importFiles(files) {
        files = files.filter((f) => /\.(csv|xlsx)$/i.test(f.name)).sort((a, b) => a.name.localeCompare(b.name));
        if (!files.length) return;
        busy = true;
        const results = $("kh-results");
        results.innerHTML = "";
        $("kh-progress-track").classList.remove("d-none");
        $("kh-progress-label").classList.remove("d-none");
        let ok = 0;
        for (const [i, file] of files.entries()) {
            $("kh-progress-fill").style.width = `${Math.round((i / files.length) * 100)}%`;
            $("kh-progress-label").textContent = `Importing ${i + 1}/${files.length}: ${file.name}`;
            const line = document.createElement("p");
            line.className = "flash";
            results.prepend(line);
            const body = new FormData();
            body.append("file", file, file.name);
            body.append("data_type", $("kh-data-type").value);
            try {
                const res = await fetch(IMPORT_URL, { method: "POST", body });
                const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
                if (!res.ok) throw new Error(data.error || "Import failed");
                ok += 1;
                const notes = [...data.errors.map((er) => `Row ${er.row}: ${er.error}`), ...data.warnings];
                line.className = `flash flash-${data.status === "completed" && !data.warnings.length ? "success" : "warn"}`;
                line.innerHTML = `${esc(file.name)} → ${summary(data)}`
                    + (notes.length ? "<br>" + notes.slice(0, 5).map(esc).join("<br>") + (notes.length > 5 ? `<br>… ${notes.length - 5} more` : "") : "");
            } catch (err) {
                line.className = "flash flash-error";
                line.textContent = `${file.name}: ${err.message || err}`;
            }
        }
        $("kh-progress-fill").style.width = "100%";
        $("kh-progress-label").textContent = `Done: ${ok}/${files.length} file(s) imported.`;
        busy = false;
        loadStatus();
    }

    async function loadStatus() {
        const res = await fetch(STATUS_URL);
        if (!res.ok) return;
        const data = await res.json();
        const days = data.days || [];
        $("kh-status-stop").innerHTML = days.length
            ? `<strong>Stop Reason:</strong> latest production days ${days.slice(0, 7).map((d) => esc(d.production_date)).join(", ")}${days.length > 7 ? " …" : ""}`
            : `<strong>Stop Reason:</strong> not imported yet.`;
        const s = data.sources;
        $("kh-status-rolls").innerHTML = s.rolls
            ? `<strong>Piece Produced:</strong> ${fmt(s.rolls)} rolls, ${s.roll_machines} machines, Record End ${esc(s.rolls_from)} → ${esc(s.rolls_to)}`
            : `<strong>Piece Produced:</strong> not imported — Program is blank for every machine-day.`;
        $("kh-status-programs").innerHTML = s.greige_codes
            ? `<strong>Knitting program:</strong> ${s.greige_codes} Greige codes, ${s.programs} programs. Core: ${s.core_programs.map(esc).join(", ") || "-"}`
            : `<strong>Knitting program:</strong> not imported yet.`;
        $("kh-history").innerHTML = (data.imports || []).map((r) => `<tr><td>${esc(r.imported_at)}</td><td class="kh-file">${esc(r.file_name)}</td>`
            + `<td>${esc(TYPE_LABELS[r.file_type] || r.file_type)}</td><td><span class="Label${r.status === "completed" ? "" : " Label--danger"}">${esc(r.status)}</span></td>`
            + `<td class="num">${fmt(r.imported_rows)}</td><td>${esc(r.imported_by)}</td></tr>`).join("")
            || `<tr><td colspan="6" class="color-fg-muted">No imports yet.</td></tr>`;
    }
})();
