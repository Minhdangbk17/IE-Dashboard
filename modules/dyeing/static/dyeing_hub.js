// dyeing_hub.js
// ---------------------------------------------------------------------------
// Điều khiển trang Dyeing Hub Dashboard:
//   1. Co giãn "sân khấu" (#dash-stage, kích thước cố định 1600x900) để luôn vừa khít
//      phần không gian còn lại của trang — KHÔNG BAO GIỜ phát sinh thanh cuộn, bất kể tỉ
//      lệ màn hình. Xem rescaleStage().
//   2. Tính khoảng ngày + filter Capacity DÙNG CHUNG cho mọi widget, gọi song song
//      (Promise.all) tới các API JSON đã có sẵn của từng Engine — KHÔNG thêm route mới.
//   3. Vẽ gauge OEE (nửa hình tròn + kim chỉ) bằng 1 plugin Chart.js tự viết.
//   4. Mở/đóng Modal Import/Export Excel (không đổi so với bản trước).
// ---------------------------------------------------------------------------
(function () {
    "use strict";

    // -----------------------------------------------------------------
    // 1. Co giãn sân khấu — "1 khối tổng" duy nhất, tỉ lệ nội bộ TUYỆT ĐỐI không đổi dù
    // màn hình thật to/nhỏ/tỉ lệ khác nhau thế nào. Chấp nhận dải trống (letterbox) ở
    // màn hình lệch tỉ lệ 16:9 — KHÔNG kéo méo nội dung để lấp đầy.
    // -----------------------------------------------------------------
    const STAGE_W = 1600;
    const STAGE_H = 900;
    const stageOuter = document.getElementById("dash-stage-outer");
    const stage = document.getElementById("dash-stage");

    function rescaleStage() {
        if (!stageOuter || !stage) return;
        const availW = stageOuter.clientWidth;
        const availH = stageOuter.clientHeight;
        if (!availW || !availH) return;
        const scale = Math.min(availW / STAGE_W, availH / STAGE_H);
        stage.style.transform = `scale(${scale})`;
    }

    if (stageOuter && stage && typeof ResizeObserver !== "undefined") {
        new ResizeObserver(rescaleStage).observe(stageOuter);
        rescaleStage();
    }

    if (!stage) return;

    const batchDayTrendUrl = stage.dataset.batchDayTrendUrl;
    const oeeUrl = stage.dataset.oeeUrl;
    const downtimeUrl = stage.dataset.downtimeUrl;
    const tankLoadingUrl = stage.dataset.tankLoadingUrl;
    const rftUrl = stage.dataset.rftUrl;

    // Cùng tập Capacity mặc định đã dùng làm "Capacity chính" ở mọi báo cáo khác trong dự
    // án (Downtime/Batch Matrix/RFT/Tank Loading đều mặc định chọn sẵn 500/600/1200/2400)
    // — ĐÂY CHÍNH XÁC là tập giá trị Capacity >= 500Kg có thật trong dữ liệu (7 mức đang
    // dùng toàn hệ thống: 25/50/300/500/600/1200/2400), không phải suy đoán riêng.
    const CAPACITY_FILTER = "500,600,1200,2400";

    function pad2(value) { return String(value).padStart(2, "0"); }
    function formatDate(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }

    // Quy tắc khoảng ngày CHUNG cho toàn bộ Dashboard: từ ngày 15 trở đi trong tháng, lấy
    // từ đầu tháng hiện tại tới hôm nay (month-to-date) — TRƯỚC ngày 15, dữ liệu tháng
    // hiện tại còn quá ít nên lấy TRỌN tháng TRƯỚC thay vào đó.
    function dashboardWindow() {
        const today = new Date();
        let start;
        let end;
        if (today.getDate() >= 15) {
            start = new Date(today.getFullYear(), today.getMonth(), 1);
            end = today;
        } else {
            end = new Date(today.getFullYear(), today.getMonth(), 0); // ngày cuối tháng trước
            start = new Date(end.getFullYear(), end.getMonth(), 1);
        }
        return { from: formatDate(start), to: formatDate(end) };
    }

    const WINDOW = dashboardWindow();
    const WINDOW_DAYS = Math.max(1, Math.round((new Date(`${WINDOW.to}T00:00:00`) - new Date(`${WINDOW.from}T00:00:00`)) / 86400000) + 1);

    const FABRIC_COLORS = { Cotton: "#3fb950", CVC: "#2862d7", Polyester: "#f778ba" };
    const charts = {}; // key -> Chart instance, để destroy() trước khi vẽ lại

    function destroyChart(key) {
        if (charts[key]) { charts[key].destroy(); delete charts[key]; }
    }

    function fmt1(value) { return Number(value || 0).toFixed(1); }
    function fmt2(value) { return Number(value || 0).toFixed(2); }

    // Sparkline THUẦN — ẩn hẳn trục/lưới/chú giải/tooltip, chỉ giữ lại HÌNH DẠNG đường +
    // màu để đọc được từ xa (đúng yêu cầu tối giản cho màn hình Andon) — khác hẳn chart
    // đầy đủ trục ở các trang report riêng của từng Engine.
    //
    // Khi KHÔNG có kỳ nào để vẽ (`labels` rỗng — VD chưa import dữ liệu Performance nên
    // %Tank Loading không có gì để vẽ), Chart.js vẫn "vẽ" được 1 canvas nhưng hoàn toàn
    // trắng trơn — người dùng dễ hiểu nhầm là LỖI thay vì "chưa có dữ liệu". Hiện rõ dòng
    // chữ "No data for this period" thay vì để canvas trống im lặng.
    function renderSparkline(canvasKey, canvas, labels, series) {
        if (!canvas) return;
        const wrap = canvas.parentElement;
        let emptyNote = wrap ? wrap.querySelector(".dash-spark-empty") : null;
        if (!labels.length) {
            destroyChart(canvasKey);
            canvas.style.visibility = "hidden";
            if (wrap && !emptyNote) {
                emptyNote = document.createElement("div");
                emptyNote.className = "dash-spark-empty";
                emptyNote.textContent = "No data for this period";
                wrap.appendChild(emptyNote);
            }
            return;
        }
        canvas.style.visibility = "";
        if (emptyNote) emptyNote.remove();
        if (typeof Chart === "undefined") return;
        destroyChart(canvasKey);
        charts[canvasKey] = new Chart(canvas, {
            type: "line",
            data: {
                labels,
                datasets: series.map((s) => ({
                    data: s.values, borderColor: s.color, backgroundColor: "transparent",
                    borderWidth: 2, tension: .3, fill: false, pointRadius: 0,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { intersect: false },
                scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
            },
        });
    }

    // -----------------------------------------------------------------
    // Hero: Batch/Day — số lớn (tổng gộp 3 loại vải) + 3 số phụ theo loại + sparkline mờ.
    // -----------------------------------------------------------------
    async function loadHeroWidget() {
        try {
            const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
            const res = await fetch(`${batchDayTrendUrl}?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            document.getElementById("dash-hero-value").textContent = fmt2(data.kpis.batch_per_day);
            const byFabric = {};
            (data.rows || []).forEach((row) => { byFabric[row.fabric_type] = row; });
            document.getElementById("dash-hero-cotton").textContent = byFabric.Cotton ? fmt2(byFabric.Cotton.total) : "--";
            document.getElementById("dash-hero-cvc").textContent = byFabric.CVC ? fmt2(byFabric.CVC.total) : "--";
            document.getElementById("dash-hero-polyester").textContent = byFabric.Polyester ? fmt2(byFabric.Polyester.total) : "--";
            const series = (data.rows || []).map((row) => ({ values: row.values, color: FABRIC_COLORS[row.fabric_type] || "#abaebb" }));
            renderSparkline("hero", document.getElementById("dash-hero-spark"), data.periods || [], series);
        } catch (err) {
            console.error("Lỗi tải widget Batch/Day (hero):", err);
        }
    }

    // -----------------------------------------------------------------
    // %Tank Loading — cùng kiểu với Hero nhưng nhỏ hơn (ô phụ, không phải hero).
    // -----------------------------------------------------------------
    async function loadTankLoadingWidget() {
        try {
            const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
            const res = await fetch(`${tankLoadingUrl}?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            document.getElementById("dash-tankloading-value").textContent = `${fmt1(data.kpis.tank_loading_pct)}%`;
            const byFabric = {};
            (data.rows || []).forEach((row) => { byFabric[row.fabric_type] = row; });
            document.getElementById("dash-tank-cotton").textContent = byFabric.Cotton ? `${fmt1(byFabric.Cotton.total)}%` : "--";
            document.getElementById("dash-tank-cvc").textContent = byFabric.CVC ? `${fmt1(byFabric.CVC.total)}%` : "--";
            document.getElementById("dash-tank-polyester").textContent = byFabric.Polyester ? `${fmt1(byFabric.Polyester.total)}%` : "--";
            const series = (data.rows || []).map((row) => ({ values: row.values, color: FABRIC_COLORS[row.fabric_type] || "#abaebb" }));
            renderSparkline("tankloading", document.getElementById("dash-tankloading-spark"), data.periods || [], series);
        } catch (err) {
            console.error("Lỗi tải widget %Tank Loading:", err);
        }
    }

    // -----------------------------------------------------------------
    // Downtime % — 1 số duy nhất, tô màu theo ngưỡng (mặc định tạm: <=8% xanh, <=15% vàng,
    // >15% đỏ — CHƯA có ngưỡng chính thức từ người dùng, dễ chỉnh lại 1 chỗ này khi có).
    // -----------------------------------------------------------------
    function downtimeColorFor(pct) {
        if (pct <= 8) return "var(--success)";
        if (pct <= 15) return "var(--warning)";
        return "var(--danger)";
    }

    async function loadDowntimeWidget() {
        const el = document.getElementById("dash-downtime-value");
        try {
            const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
            const res = await fetch(`${downtimeUrl}?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const pct = Number(data.kpis.downtime_rate_pct) || 0;
            el.textContent = `${fmt1(pct)}%`;
            el.style.color = downtimeColorFor(pct);
        } catch (err) {
            console.error("Lỗi tải widget Downtime:", err);
            el.textContent = "Error";
        }
    }

    // -----------------------------------------------------------------
    // RFT — 1 card gộp 4 nhóm (Lab to Lab/Lab to Bulk/Bulk to Bulk/2nd Batch). Khi backend
    // báo `classification_ready=false` (chưa có quy tắc phân loại thật — xem
    // rft/service.py::RFT_CLASSIFICATION_READY), hiện trạng thái "đang chờ cấu hình" thay
    // vì số 0% (dễ hiểu nhầm là dữ liệu thật xấu).
    // -----------------------------------------------------------------
    const RFT_WIDGETS = [
        { slug: "lab_to_lab" },
        { slug: "lab_to_bulk" },
        { slug: "bulk_to_bulk" },
        { slug: "second_batch" },
    ];

    function ensureRftPendingNote(card, show) {
        let note = card.querySelector(".dash-rft-pending-note");
        if (show) {
            if (!note) {
                note = document.createElement("div");
                note.className = "dash-rft-pending-note";
                note.textContent = "Đang chờ cấu hình quy tắc phân loại";
                card.appendChild(note);
            }
        } else if (note) {
            note.remove();
        }
    }

    async function loadRftWidget(widget) {
        const cell = document.querySelector(`.dash-rft-cell[data-rft-cell="${widget.slug}"]`);
        if (!cell) return;
        const valueEl = cell.querySelector(".dash-rft-cell-value");
        const canvas = cell.querySelector("canvas");
        try {
            const params = new URLSearchParams({ category: widget.slug, from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
            const res = await fetch(`${rftUrl}?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const ready = !!data.classification_ready;
            const card = document.getElementById("dash-rft-card");
            card.classList.toggle("is-pending", !ready);
            // Chỉ 1 ghi chú "đang chờ" DÙNG CHUNG cho cả 4 ô (không lặp lại 4 lần) — chỉ
            // cần set 1 lần, gọi lại nhiều lần (mỗi widget) không sao vì idempotent.
            ensureRftPendingNote(card, !ready);
            if (!ready) {
                valueEl.textContent = "—";
                destroyChart(`rft-${widget.slug}`);
                return;
            }
            valueEl.textContent = `${fmt1(data.kpis.rate_pct)}%`;
            renderSparkline(`rft-${widget.slug}`, canvas, (data.chart && data.chart.categories) || [], [
                { values: (data.chart && data.chart.rate_values) || [], color: "#2862d7" },
            ]);
        } catch (err) {
            console.error(`Lỗi tải widget RFT ${widget.slug}:`, err);
        }
    }

    // -----------------------------------------------------------------
    // OEE gauge: nửa hình tròn + kim chỉ (tự viết bằng Chart.js, không thêm thư viện
    // ngoài) — xem giải thích công thức đầy đủ trong bản ghi memory-bank.
    // -----------------------------------------------------------------
    const gaugeNeedlePlugin = {
        id: "gaugeNeedle",
        afterDatasetsDraw(chart, _args, opts) {
            if (!opts || opts.value === undefined || opts.value === null) return;
            const { ctx, chartArea } = chart;
            if (!chartArea) return;
            const cx = (chartArea.left + chartArea.right) / 2;
            const cy = chartArea.bottom;
            const radius = Math.min(chartArea.right - chartArea.left, (chartArea.bottom - chartArea.top) * 2) / 2;
            const needleLength = radius * 0.75;
            const clamped = Math.max(0, Math.min(100, opts.value));
            const angle = (Math.PI * (180 + (clamped / 100) * 180)) / 180;
            const needleColor = opts.color || "#e6edf3";
            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(angle);
            ctx.beginPath();
            ctx.moveTo(-7, 0);
            ctx.lineTo(0, -4);
            ctx.lineTo(needleLength, 0);
            ctx.lineTo(0, 4);
            ctx.closePath();
            ctx.fillStyle = needleColor;
            ctx.fill();
            ctx.restore();
            ctx.beginPath();
            ctx.arc(cx, cy, 6, 0, Math.PI * 2);
            ctx.fillStyle = needleColor;
            ctx.fill();
        },
    };

    function gaugeColorFor(value) {
        if (value >= 85) return "#3fb950";
        if (value >= 60) return "#d29922";
        return "#f85149";
    }

    function renderOeeGauge(value) {
        const canvas = document.getElementById("dash-oee-gauge");
        if (!canvas || typeof Chart === "undefined") return;
        const clamped = Math.max(0, Math.min(100, value));
        const needleColor = getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#e6edf3";
        destroyChart("oee");
        charts.oee = new Chart(canvas, {
            type: "doughnut",
            data: { datasets: [{ data: [clamped, 100 - clamped], backgroundColor: [gaugeColorFor(clamped), "rgba(139,148,158,.25)"], borderWidth: 0 }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                rotation: -90,
                circumference: 180,
                cutout: "72%",
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false },
                    gaugeNeedle: { value: clamped, color: needleColor },
                },
            },
            plugins: [gaugeNeedlePlugin],
        });
        document.getElementById("dash-oee-value").textContent = `${clamped.toFixed(1)}%`;
    }

    async function loadOeeWidget() {
        try {
            const params = new URLSearchParams({ days: String(WINDOW_DAYS) });
            const res = await fetch(`${oeeUrl}?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderOeeGauge(Number(data.overall_oee_pct) || 0);
        } catch (err) {
            console.error("Lỗi tải widget OEE:", err);
            renderOeeGauge(0);
        }
    }

    function loadAllWidgets() {
        Promise.all([
            loadHeroWidget(),
            loadOeeWidget(),
            loadDowntimeWidget(),
            loadTankLoadingWidget(),
            ...RFT_WIDGETS.map(loadRftWidget),
        ]).then(rescaleStage);
    }

    loadAllWidgets();
    document.addEventListener("colormodechange", loadAllWidgets);

    // Expose để import_modal.js gọi refresh lại toàn bộ Dashboard sau khi import thành công.
    window.dyeingHub = {
        refreshWidgets: loadAllWidgets,
    };

    // --- Mở/đóng modal Import ---
    const openBtn = document.getElementById("btn-open-import");
    const modal = document.getElementById("import-modal");
    const closeBtn = document.getElementById("btn-close-import");
    const cancelBtn = document.getElementById("btn-cancel-import");

    if (openBtn && modal) {
        openBtn.addEventListener("click", () => modal.classList.remove("d-none"));
    }
    [closeBtn, cancelBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", () => modal.classList.add("d-none"));
    });

    // --- Mở/đóng modal Export + tải file .xlsx theo Data Type/khoảng ngày đã chọn ---
    const exportOpenBtn = document.getElementById("btn-open-export");
    const exportModal = document.getElementById("export-modal");
    const exportCloseBtn = document.getElementById("btn-close-export");
    const exportCancelBtn = document.getElementById("btn-cancel-export");
    const exportConfirmBtn = document.getElementById("btn-confirm-export");
    const exportError = document.getElementById("export-error");

    function closeExportModal() {
        exportModal.classList.add("d-none");
        exportError.classList.add("d-none");
    }

    if (exportOpenBtn && exportModal) {
        exportOpenBtn.addEventListener("click", () => exportModal.classList.remove("d-none"));
    }
    [exportCloseBtn, exportCancelBtn].forEach((btn) => {
        if (btn) btn.addEventListener("click", closeExportModal);
    });
    if (exportConfirmBtn) {
        exportConfirmBtn.addEventListener("click", () => {
            const dataType = document.getElementById("export-data-type").value;
            const fromDate = document.getElementById("export-from-date").value;
            const toDate = document.getElementById("export-to-date").value;
            if (!fromDate || !toDate) {
                exportError.textContent = "Vui lòng chọn đủ Từ ngày và Đến ngày.";
                exportError.classList.remove("d-none");
                return;
            }
            exportError.classList.add("d-none");
            const params = new URLSearchParams({ data_type: dataType, from_date: fromDate, to_date: toDate });
            window.location.href = `${exportModal.dataset.exportUrl}?${params}`;
            closeExportModal();
        });
    }
})();
