// theme_toggle.js
// Tiện ích tối giản: đọc/lưu chế độ màu (dark/light) vào localStorage.
// Mặc định ứng dụng dùng Dark Mode (data-color-mode="dark") theo yêu cầu UI/UX.
(function () {
    "use strict";

    const STORAGE_KEY = "mes_dashboard_color_mode";

    function applyStoredMode() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                document.documentElement.setAttribute("data-color-mode", stored);
            }
        } catch (err) {
            // localStorage có thể bị chặn — bỏ qua, giữ mặc định dark.
            console.warn("Không thể đọc chế độ màu đã lưu:", err);
        }
    }

    window.toggleColorMode = function toggleColorMode() {
        const current = document.documentElement.getAttribute("data-color-mode") || "dark";
        const next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-color-mode", next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (err) {
            console.warn("Không thể lưu chế độ màu:", err);
        }
        document.dispatchEvent(new CustomEvent("colormodechange", { detail: { mode: next } }));
    };

    applyStoredMode();
})();
