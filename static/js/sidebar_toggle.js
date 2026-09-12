// sidebar_toggle.js
// Thu gọn/mở rộng thanh điều hướng (sidebar) — trạng thái lưu vào localStorage,
// áp dụng lại ngay khi tải trang mới (đồng bộ trên mọi trang qua base.html).
(function () {
    "use strict";

    const STORAGE_KEY = "cetvn_sidebar_collapsed";
    const shell = document.querySelector(".app-shell");
    const toggleBtn = document.getElementById("sidebar-toggle-btn");

    function apply(collapsed) {
        if (!shell) return;
        shell.classList.toggle("sidebar-collapsed", collapsed);
        if (toggleBtn) {
            const label = collapsed ? "Expand navigation" : "Collapse navigation";
            toggleBtn.setAttribute("aria-label", label);
            toggleBtn.setAttribute("title", label);
        }
    }

    window.toggleSidebar = function toggleSidebar() {
        const collapsed = !shell.classList.contains("sidebar-collapsed");
        apply(collapsed);
        try {
            localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
        } catch (err) {
            console.warn("Không thể lưu trạng thái thanh điều hướng:", err);
        }
    };

    try {
        apply(localStorage.getItem(STORAGE_KEY) === "1");
    } catch (err) {
        // localStorage có thể bị chặn — giữ mặc định mở rộng.
    }
}());
