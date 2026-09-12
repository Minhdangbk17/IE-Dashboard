// theme_toggle.js
// Chỉ còn giữ hàm toggleColorMode() cho nút bấm trong sidebar. Việc ÁP DỤNG chế độ
// màu đã lưu lúc tải trang đã chuyển lên script inline đầu <head> của base.html
// (PHẢI chạy sớm, trước khi trang vẽ khung hình đầu tiên, để tránh chớp sai theme —
// xem comment ở base.html). Mặc định ứng dụng dùng Light Mode
// (data-color-mode="light", đặt trong base.html) khi chưa có lựa chọn nào lưu lại.
(function () {
    "use strict";

    const STORAGE_KEY = "mes_dashboard_color_mode";

    window.toggleColorMode = function toggleColorMode() {
        const current = document.documentElement.getAttribute("data-color-mode") || "light";
        const next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-color-mode", next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (err) {
            console.warn("Không thể lưu chế độ màu:", err);
        }
        document.dispatchEvent(new CustomEvent("colormodechange", { detail: { mode: next } }));
    };
})();
