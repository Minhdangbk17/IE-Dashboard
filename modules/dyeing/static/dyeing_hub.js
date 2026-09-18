// dyeing_hub.js
// ---------------------------------------------------------------------------
// Điều khiển trang Dyeing Hub Dashboard:
//   1. Tính khoảng ngày + filter Capacity DÙNG CHUNG cho mọi widget (xem
//      dashboardWindow()), gọi song song (Promise.all) tới các API JSON đã có sẵn của
//      từng Engine (Batch/Day Trend, OEE, Downtime, %Tank Loading, RFT x4) — KHÔNG thêm
//      route mới, chỉ tái dùng đúng API đã dùng ở trang report riêng của mỗi Engine.
//   2. Vẽ gauge OEE (nửa hình tròn + kim chỉ) bằng 1 plugin Chart.js tự viết (không thêm
//      thư viện ngoài).
//   3. Mở/đóng Modal Import/Export Excel (không đổi so với bản trước).
// ---------------------------------------------------------------------------
(function () {
    "use strict";

    const dash = document.getElementById("hub-dashboard");
    if (dash) {
        const batchDayTrendUrl = dash.dataset.batchDayTrendUrl;
        const oeeUrl = dash.dataset.oeeUrl;
        const downtimeUrl = dash.dataset.downtimeUrl;
        const tankLoadingUrl = dash.dataset.tankLoadingUrl;
        const rftUrl = dash.dataset.rftUrl;

        // Cùng tập Capacity mặc định đã dùng làm "Capacity chính" ở mọi báo cáo khác trong
        // dự án (Downtime/Batch Matrix/RFT/Tank Loading đều mặc định chọn sẵn
        // 500/600/1200/2400) — ĐÂY CHÍNH XÁC là tập giá trị Capacity >= 500Kg có thật trong
        // dữ liệu (7 mức đang dùng toàn hệ thống: 25/50/300/500/600/1200/2400), không phải
        // suy đoán riêng cho Dashboard.
        const CAPACITY_FILTER = "500,600,1200,2400";

        function pad2(value) { return String(value).padStart(2, "0"); }
        function formatDate(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }

        // Quy tắc khoảng ngày CHUNG cho toàn bộ Dashboard (theo yêu cầu người dùng): từ
        // ngày 15 trở đi trong tháng, lấy từ đầu tháng hiện tại tới hôm nay (month-to-date)
        // — TRƯỚC ngày 15, dữ liệu tháng hiện tại còn quá ít (chưa tới nửa tháng) nên lấy
        // TRỌN tháng TRƯỚC thay vào đó để biểu đồ có đủ dữ liệu tham khảo.
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

        function chartTextColors() {
            const isLight = document.documentElement.getAttribute("data-color-mode") === "light";
            const textColor = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#abaebb";
            const gridColor = isLight ? "rgba(11, 12, 14, 0.08)" : "rgba(255, 255, 255, 0.08)";
            return { textColor, gridColor };
        }

        const FABRIC_COLORS = { Cotton: "#3fb950", CVC: "#2862d7", Polyester: "#f778ba" };
        const charts = {}; // canvas id -> Chart instance, để destroy() trước khi vẽ lại

        function destroyChart(key) {
            if (charts[key]) { charts[key].destroy(); delete charts[key]; }
        }

        // 3 đường Cotton/CVC/Polyester GỘP CHUNG 1 chart (khác trang report riêng của
        // Batch/Day Trend & %Tank Loading — 2 trang đó đã tách thành 3 chart cạnh nhau theo
        // yêu cầu trước; ở đây là widget tóm tắt trên Hub nên gộp lại cho gọn không gian).
        function renderFabricLineChart(canvasId, data) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || typeof Chart === "undefined") return;
            const { textColor, gridColor } = chartTextColors();
            const datasets = [];
            (data.rows || []).forEach((row) => {
                const color = FABRIC_COLORS[row.fabric_type] || "#abaebb";
                datasets.push({ label: row.fabric_type, data: row.values, borderColor: color, backgroundColor: "transparent", tension: .25, fill: false, pointRadius: 0, borderWidth: 2 });
                if (row.target !== null && row.target !== undefined) {
                    datasets.push({
                        label: `${row.fabric_type} Target`,
                        data: (data.periods || []).map(() => row.target),
                        borderColor: color, borderDash: [5, 4], borderWidth: 1, pointRadius: 0, fill: false, isTargetLine: true,
                    });
                }
            });
            destroyChart(canvasId);
            charts[canvasId] = new Chart(canvas, {
                type: "line",
                data: { labels: data.periods || [], datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: { ticks: { color: textColor, maxTicksLimit: 6 }, grid: { display: false } },
                        y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor } },
                    },
                    plugins: {
                        legend: { position: "bottom", labels: { color: textColor, usePointStyle: true, boxWidth: 8, filter: (item) => !item.text.endsWith(" Target") } },
                        tooltip: { filter: (item) => !item.dataset.isTargetLine },
                    },
                },
            });
        }

        async function loadBatchDayWidget() {
            try {
                const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
                const res = await fetch(`${batchDayTrendUrl}?${params}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                renderFabricLineChart("dash-batch-day-chart", await res.json());
            } catch (err) {
                console.error("Lỗi tải widget Batch/Day:", err);
            }
        }

        async function loadTankLoadingWidget() {
            try {
                const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
                const res = await fetch(`${tankLoadingUrl}?${params}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                renderFabricLineChart("dash-tank-loading-chart", await res.json());
            } catch (err) {
                console.error("Lỗi tải widget %Tank Loading:", err);
            }
        }

        async function loadDowntimeWidget() {
            const el = document.getElementById("dash-downtime-value");
            try {
                const params = new URLSearchParams({ from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
                const res = await fetch(`${downtimeUrl}?${params}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                el.textContent = `${Number(data.kpis.downtime_rate_pct).toFixed(1)}%`;
            } catch (err) {
                console.error("Lỗi tải widget Downtime:", err);
                el.textContent = "Error";
            }
        }

        // 4/6 nhóm RFT theo đúng yêu cầu (bỏ Rework/Adjust Color) — classify_rft_category()
        // hiện LUÔN trả None (chưa có quy tắc phân loại thật, xem rft/service.py) nên cả 4
        // chart này sẽ hiện đường phẳng 0% cho tới khi có quy tắc — ĐÂY LÀ HÀNH VI ĐÚNG,
        // không phải bug của Dashboard.
        const RFT_WIDGETS = [
            { slug: "lab_to_lab", canvas: "dash-rft-lab_to_lab" },
            { slug: "lab_to_bulk", canvas: "dash-rft-lab_to_bulk" },
            { slug: "bulk_to_bulk", canvas: "dash-rft-bulk_to_bulk" },
            { slug: "second_batch", canvas: "dash-rft-second_batch" },
        ];

        function renderRftChart(canvasId, data) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || typeof Chart === "undefined") return;
            const { textColor, gridColor } = chartTextColors();
            destroyChart(canvasId);
            charts[canvasId] = new Chart(canvas, {
                type: "line",
                data: {
                    labels: (data.chart && data.chart.categories) || [],
                    datasets: [{
                        label: "Rate %", data: (data.chart && data.chart.rate_values) || [],
                        borderColor: "#2862d7", backgroundColor: "rgba(40,98,215,.15)", tension: .25, fill: true, pointRadius: 0, borderWidth: 2,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: { ticks: { color: textColor, maxTicksLimit: 5 }, grid: { display: false } },
                        y: { beginAtZero: true, max: 100, ticks: { color: textColor, callback: (v) => `${v}%` }, grid: { color: gridColor } },
                    },
                    plugins: { legend: { display: false } },
                },
            });
        }

        async function loadRftWidget(widget) {
            try {
                const params = new URLSearchParams({ category: widget.slug, from_date: WINDOW.from, to_date: WINDOW.to, capacities: CAPACITY_FILTER, group_by: "date" });
                const res = await fetch(`${rftUrl}?${params}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                renderRftChart(widget.canvas, await res.json());
            } catch (err) {
                console.error(`Lỗi tải widget RFT ${widget.slug}:`, err);
            }
        }

        // --- OEE gauge: nửa hình tròn + kim chỉ ---
        // Chart.js doughnut xoay -90° + circumference 180° = nửa vòng cung phía trên (dạng
        // "rainbow" kinh điển), tâm nằm ở CẠNH DƯỚI vùng vẽ (chartArea.bottom). Kim chỉ vẽ
        // bằng 1 plugin tự viết (KHÔNG thêm thư viện ngoài, đăng ký namespace riêng
        // `gaugeNeedle` trong `options.plugins` — đúng API plugin chuẩn của Chart.js v4,
        // không đụng vào state nội bộ của Chart). Góc kim quét TUYẾN TÍNH từ 180° (trái,
        // value=0%) qua 270° (thẳng đứng, value=50%) tới 360°/0° (phải, value=100%).
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

        let oeeGauge = null;
        function renderOeeGauge(value) {
            const canvas = document.getElementById("dash-oee-gauge");
            if (!canvas || typeof Chart === "undefined") return;
            const clamped = Math.max(0, Math.min(100, value));
            const needleColor = getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#e6edf3";
            if (oeeGauge) oeeGauge.destroy();
            oeeGauge = new Chart(canvas, {
                type: "doughnut",
                data: { datasets: [{ data: [clamped, 100 - clamped], backgroundColor: [gaugeColorFor(clamped), "rgba(139,148,158,.25)"], borderWidth: 0 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
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
                loadBatchDayWidget(),
                loadOeeWidget(),
                loadDowntimeWidget(),
                loadTankLoadingWidget(),
                ...RFT_WIDGETS.map(loadRftWidget),
            ]);
        }

        loadAllWidgets();
        document.addEventListener("colormodechange", loadAllWidgets);

        // Expose để import_modal.js gọi refresh lại toàn bộ Dashboard sau khi import thành công.
        window.dyeingHub = {
            refreshWidgets: loadAllWidgets,
        };
    }

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
