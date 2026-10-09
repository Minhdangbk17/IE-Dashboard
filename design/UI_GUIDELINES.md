# UI GUIDELINES — CETVN IE DASHBOARD

> **Nguồn sự thật DUY NHẤT về giao diện.** Mỗi lần yêu cầu cập nhật giao diện, gửi kèm file này.
> Mọi thay đổi UI phải (1) tuân theo các quyết định dưới đây, hoặc (2) ghi một quyết định mới /
> sửa quyết định cũ vào **Mục 10 — Nhật ký quyết định** trước khi code.
>
> - Cập nhật lần cuối: **2026-10-08**
> - File CSS thật: [`static/css/app.css`](../static/css/app.css) (1 file duy nhất)
> - Nguồn cảm hứng gốc: [`design/DESIGN.md`](DESIGN.md) ("AgentQL — Aurora glow over a midnight terminal")
> - Template tham khảo (KHÔNG dùng trực tiếp): [`templates/static/`](../templates/static/) — xem Mục 11

---

## 0. Cách dùng file này

| Tình huống | Làm gì |
|---|---|
| Thêm trang/Engine mới | Chỉ dùng class + token ở Mục 3–7. Không tự đặt màu hex mới. |
| Cần màu/thành phần chưa có | Thêm token vào `app.css` (cả Dark lẫn Light) → ghi vào Mục 3 + Mục 10. |
| Đổi một quyết định cũ | Sửa trạng thái quyết định cũ thành `Thay thế bởi D-xx`, thêm quyết định mới. |
| Trước khi merge | Chạy checklist Mục 12. |

Ký hiệu trạng thái: ✅ Đã áp dụng · 🟡 Đã chốt, chưa làm · 💡 Đề xuất, chờ duyệt · ❌ Đã loại bỏ

---

## 1. Nguyên tắc tổng quát

1. **Mật độ thông tin > trang trí.** Người dùng là kỹ sư IE đọc ma trận/bảng rộng (hàng chục cột ngày). Ưu tiên
   hiển thị được nhiều số liệu trên 1 màn hình; bo góc, bóng, hiệu ứng phải tiết chế.
2. **Không hardcode màu.** Mọi màu đi qua CSS variable. Ngoại lệ duy nhất: bảng mã màu nghiệp vụ (Mục 6) —
   và kể cả khi đó phải khai báo ở đúng 1 chỗ.
3. **Hai theme ngang hàng.** Mọi token phải có giá trị cho cả Light và Dark, và phải đạt độ tương phản ở CẢ HAI.
4. **Không phụ thuộc framework CSS.** Không Primer, Bootstrap, Tailwind. Chỉ CDN Google Fonts + Chart.js.
5. **Giữ nguyên tên class cũ làm hook** (`Box`, `Label`, `BtnGroup`, `f6`, `color-fg-muted`...) — định nghĩa lại
   trong `app.css`, KHÔNG đi sửa hàng loạt template.
6. **MPA, không phải SPA.** Mỗi menu = 1 lần tải trang Flask/Jinja. Không thiết kế theo kiểu "1 màn hình 100vh".

---

## 2. Kiến trúc theme & CSS

| Hạng mục | Quyết định | Trạng thái |
|---|---|---|
| File CSS | 1 file `static/css/app.css`, chia section đánh số (0. Page transitions → 15. Graphify) | ✅ |
| Theme mặc định | **Light** (`<html data-color-mode="light">` trong `templates/base.html`) | ✅ |
| Thuộc tính chuyển theme | `data-color-mode="light" \| "dark"` trên `<html>` (KHÔNG dùng `data-theme`) | ✅ |
| Lưu lựa chọn | `localStorage["mes_dashboard_color_mode"]` | ✅ |
| Chống chớp theme (FOUC) | Script inline đồng bộ, ĐẦU TIÊN trong `<head>` của `base.html` — không `defer`/`async` | ✅ |
| Nút đổi theme | `.theme-toggle-btn` trong khối user cuối sidebar, gọi `toggleColorMode()` (`static/js/theme_toggle.js`) | ✅ |
| Sự kiện đổi theme | `document` bắn `colormodechange` (`detail.mode`) → biểu đồ phải lắng nghe để vẽ lại | ✅ |
| Primer compat shim | Alias `--color-canvas-default`, `--color-border-default`, `--color-fg-muted`, `--color-accent-emphasis`... sang token mới trong `:root` | ✅ |
| Chuyển trang | View Transitions API (`@view-transition { navigation: auto }`), chỉ `.app-main` fade + trượt 6–8px, 200ms `cubic-bezier(0.16,1,0.3,1)`; sidebar đứng yên | ✅ |
| Tách `app.css` thành nhiều file component | Chưa cần; chỉ tách khi file > ~1500 dòng | 💡 |

> ⚠️ `techContext.md` cũ ghi "Dark mặc định" — **đã lỗi thời**, mặc định hiện tại là Light.

---

## 3. Design tokens

### 3.1 Bề mặt, chữ, viền

| Token | Dark | Light | Dùng cho |
|---|---|---|---|
| `--bg-void` | `#0b0c0e` | `#f2f4fa` | Nền sidebar, input lồng |
| `--bg-base` | `#0e111b` | `#ffffff` | Nền trang, nền input |
| `--bg-surface` | `#0d172b` | `#ffffff` | Card, Box, page-tabs, panel |
| `--bg-surface-raised` | `#12244f` | `#eef1fc` | Header bảng, hover, mục active |
| `--bg-overlay` | `#101a30` | `#ffffff` | Popup nổi |
| `--text-primary` | `#ffffff` | `#0b0c0e` | Chữ chính |
| `--text-secondary` | `#c7c9d1` | `#4b4f5b` | Label, chữ phụ, trục biểu đồ |
| `--text-tertiary` | `#abaebb` | `#6b7080` | Hint, placeholder, section sidebar |
| `--text-on-accent` | `#ffffff` | `#ffffff` | Chữ trên nền accent/gradient |
| `--border-default` | `#172540` | `#dde1ea` | Viền card, input, nút |
| `--border-subtle` | `#151e32` | `#e8eaf1` | Viền ô bảng, divider |
| `--border-hairline` | `#24375a` | `#d7dff2` | Viền mảnh nhấn |
| `--border-muted` | `#3c3f44` | `#c7cbd3` | Viền trung tính |

### 3.2 Accent

| Token | Giá trị (cả 2 theme) | Dùng cho |
|---|---|---|
| `--accent` | `#2862d7` | Focus input, dropzone dragover, node Graphify |
| `--accent-2` | `#305fbd` | Điểm đầu gradient |
| `--accent-purple` | `#625fff` | Điểm cuối gradient |
| `--gradient-primary` | `linear-gradient(90deg, #305fbd, #625fff)` — tone **xanh → tím**, giống nhau ở 2 theme | `.btn-primary`, `.page-tab.is-active`, progress bar, logo mark |

- Chữ trên gradient: trắng (`#fff` cứng — nên chuyển thành token khi có dịp).
- Tone xanh–cyan của template đã thử và **bị huỷ** (D-18) — giữ xanh → tím.
| `--accent-wash` | `#85a6e9` (**chưa có bản Light** — xem K-02) | Link, `.Label`, hover viền nút |
| `--accent-wash-bg` | Dark `rgba(133,166,233,.14)` · Light `rgba(40,98,215,.08)` | Nền `.Label`, hover ô sửa được |

### 3.3 Màu trạng thái

**Hiện tại (✅ đang chạy — CÓ VẤN ĐỀ ở Light, xem K-03):** dùng chung 1 bộ cho cả 2 theme.

| Token | Giá trị | Nền `*-bg` Dark / Light |
|---|---|---|
| `--success` | `#3fb950` | `.16` / `.12` alpha |
| `--danger` | `#f85149` | `.16` / `.12` alpha |
| `--warning` | `#d29922` | `.16` / `.14` alpha |
| `--info` | `= --accent` | `.16` / `.10` alpha |

**Mục tiêu (🟡 D-10):** tách giá trị theo theme, lấy từ template tham khảo:

| Token | Dark (giữ) | Light (mới) | Tương phản trên trắng |
|---|---|---|---|
| `--success` | `#3fb950` | `#157A3D` | 2.5 → **5.4 : 1** |
| `--danger` | `#f85149` | `#C8291F` | 3.4 → **5.6 : 1** |
| `--warning` | `#d29922` | `#9A5A08` | 2.5 → **5.5 : 1** (bản template `#B3690A` chỉ 4.3 : 1 — chưa đạt cho chữ nhỏ) |
| `--warning-mid` (mới) | `#FB923C` | `#A3480A` | cấp cảnh báo giữa warning và danger |

### 3.4 Typography

| Vai trò | Font | Cỡ / độ đậm |
|---|---|---|
| Display / tiêu đề trang (`.h2`, `h1–h3`) | **Figtree** 500/600, tracking `-0.02em` | `.h2` = 24px/600 |
| UI / body | **Inter** 300/400/500/600, tracking `-0.01em` | body 14px, bảng 12.5px, nút 13px |
| Số / code | **IBM Plex Mono** 400 | — |
| Label nhỏ, header bảng | Inter 600, UPPERCASE, tracking `.03–.06em` | 10–11.5px |
| Số KPI (`.stat-value`) | Inter/Figtree 600 | 32px |

- Nạp qua Google Fonts trong `base.html`; luôn có fallback `system-ui` / `monospace` (mạng xưởng có thể chặn CDN).
- Cỡ chữ tối thiểu: **10px** chỉ cho badge; nội dung đọc được ≥ 11px.
- 💡 D-14: số liệu trong bảng/KPI dùng `font-variant-numeric: tabular-nums` để cột số thẳng hàng.

### 3.5 Bo góc, khoảng cách, bóng

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--radius-sm` | 2px | Ô sửa inline, case-note |
| `--radius-md` | 8px | Input, sidebar link, page-tab, flash |
| `--radius-lg` | 12px | Card/Box, page-tabs, dropzone, modal |
| `--radius-full` | 9999px | Nút, badge, toggle |
| `--space-1..4` | 4 / 8 / 16 / 24px | Mọi margin/padding/gap (utility `mt-*`, `mb-*`, `p-*`) |
| `--shadow-sm..xl` | có bản Light riêng | Chỉ toast (`lg`), modal/drawer (`xl`). Card KHÔNG có bóng — phân lớp bằng viền + nền |

---

## 4. Layout

| Thành phần | Quyết định | Trạng thái |
|---|---|---|
| Khung | `.app-shell` flex ngang: `.app-sidebar` (cố định `100vh`, cuộn riêng `.sidebar-body`) + `.app-main` | ✅ |
| Nội dung | `.app-main` padding `28px 32px 48px`, trang cuộn tự nhiên theo chiều dọc | ✅ |
| Thu gọn sidebar | `.sidebar-edge-toggle` bám mép, class `.sidebar-collapsed` trên `.app-shell` (`sidebar_toggle.js`) | ✅ |
| Menu | Sinh từ `NAV_MENU` (Navigation Registry) — **cấm** sửa tay `base.html` để thêm mục | ✅ |
| Mục menu active | `.sidebar-link.is-active` (nền `--bg-surface-raised`); con active `.sidebar-link-child.is-active` | ✅ (lỗi K-01) |
| Nhiều trang trong 1 view | `.page-tabs` + `.page-tab` (active = gradient), hỗ trợ lăn chuột để đổi tab | ✅ |
| Responsive | 1 breakpoint `≤ 900px`: sidebar chuyển thành thanh ngang, ẩn nút thu gọn, `.app-main` padding `20px 16px` | ✅ |
| Bảng rộng | Bọc trong container `overflow:auto`, header `position: sticky` | ✅ |
| Bố cục `100vh` + `overflow:hidden` kiểu slide | **Không dùng** | ❌ |

---

## 5. Thành phần (Components)

### 5.1 Nút

| Class | Mô tả | Trạng thái |
|---|---|---|
| `.btn` | Pill (`radius-full`), padding `7px 16px`, 13px/600, nền `--bg-surface`, viền `--border-default`; hover viền `--accent-wash` + nền raised | ✅ |
| `.btn-primary` | Nền `--gradient-primary`, chữ trắng; hover `brightness(1.08)` | ✅ |
| `.btn-danger` | Nền trong, viền + chữ `--danger`; hover nền `--danger-bg` | ✅ |
| `.btn-sm` | `5px 12px`, 12px | ✅ |
| `.btn-block` | Rộng 100% | ✅ |
| `.btn-group` / `.BtnGroup` | Nhóm nút dính liền, mục chọn `.selected` / `[aria-pressed=true]` / `.is-active` | ✅ (lỗi K-01) |
| Focus | `outline: 2px solid --accent-wash; offset 2px` (chỉ `:focus-visible`) | ✅ |
| `.btn-ghost` (nền trong, không viền) | Cho hành động phụ trong toolbar | 💡 D-12 |
| `.btn-outline` | Hành động thứ cấp cần viền rõ | 💡 D-12 |
| `.btn-icon` (vuông 32px) | Nút chỉ có icon (export, fullscreen) | 💡 D-12 |
| `.btn.is-loading` | Spinner thay chữ khi đang export/import | 💡 D-12 |

**Quy tắc dùng nút:**
- Mỗi vùng thao tác tối đa **1** `.btn-primary` (hành động chính: Import, Áp dụng lọc).
- Export Excel = `.btn` thường (không primary).
- Hành động xoá / không hoàn tác = `.btn-danger` + hộp xác nhận.

### 5.2 Card / Box

| Class | Mô tả |
|---|---|
| `.Box` / `.card` | Nền `--bg-surface`, viền `--border-default`, `radius-lg` (12px), không bóng |
| `.Box-header` / `.Box-title` / `.Box-body` / `.Box-footer` | Padding `--space-3`, header có viền dưới, title 16px |
| `.widget-card` + `h3` + `.stat-value` | Thẻ KPI: tiêu đề 11px UPPERCASE `--text-secondary`, số 32px |
| `.blankslate` | Trạng thái rỗng: padding `64px 24px`, căn giữa |

- ❌ Không dùng bo 26px, hover `scale()`, hover nhấc card (gây nhoè chữ, rung bố cục khi xem số liệu).
- 💡 D-13: KPI card có thêm trend badge ↑↓ (`up-good`/`up-bad`...) — ý tưởng từ template.

### 5.3 Badge / Label

| Class | Mô tả |
|---|---|
| `.Label` / `.badge` | Pill, 11px/600, nền `--accent-wash-bg`, chữ `--accent-wash` |
| `.Label--danger` / `.Label--secondary` | Biến thể đỏ / xám |
| `.status-badge.status-valid` / `.status-invalid` | Pill 10px, xanh/đỏ nền nhạt |

### 5.4 Form

- `.form-group` > `label` (12px/600 `--text-secondary`) + `.form-control` / `.form-select`.
- Input: padding `8px 12px`, nền `--bg-base`, viền `--border-default`, `radius-md`, 13px; focus viền `--accent`.
- Bộ lọc báo cáo: dropdown multi-select (Capacity, Brand Program, Fabric Type, Tank Type...) + checkbox
  (vd "ReDye = 0" mặc định BẬT). Tham số lọc phải được dùng CHUNG 1 `URLSearchParams` cho tải dữ liệu và Export.

### 5.5 Bảng

| Quyết định | Chi tiết |
|---|---|
| Class áp dụng | `table.preview-table`, `.raw-table`, `.matrix-table`, `.batch-matrix-table`, `.downtime-table`, bảng trong `.drawer-body` |
| Cỡ chữ | 12.5px, ô padding `6px 10px`, viền ô `--border-subtle` |
| Header | Sticky, nền `--bg-surface-raised`, 11.5px/600 UPPERCASE |
| Hover dòng | Nền `--bg-surface-raised` |
| Ma trận | `white-space: nowrap` — cuộn ngang, không xuống dòng |
| Ô bấm được | `.cell-clickable` (gạch chân chấm, hover nền accent-wash) |
| Ô sửa inline | `.raw-cell-editable` / `.case-note-cell` (hover viền đứt) |
| Dòng lỗi | `.raw-row-invalid td` nền `--danger-bg`; chữ lỗi `.row-error` |
| Ô tỉ lệ | `.ratio-good` (success) / `.ratio-warning` (danger) |
| 💡 D-14 | Cột số căn phải + `tabular-nums` |

### 5.6 Phản hồi & lớp phủ

| Thành phần | Quyết định |
|---|---|
| Flash (`.flash-success/-error/-warn`) | Nền `*-bg`, viền + chữ màu trạng thái, `radius-md` |
| Toast (`.toast-container`, `.import-toast`) | Góc trên phải, max 380px, z-index 200, trượt vào 180ms |
| Drawer (`.drawer-overlay` / `.drawer-panel`) | Trượt từ phải, rộng `min(92vw, 960px)`, overlay `rgba(4,6,12,.68)`, z-index 150/151 |
| Modal (import, top-batches, day-batches) | Nền `--bg-surface`, `radius-lg`, `--shadow-xl`, overlay `.68–.72` |
| Dropzone | Viền đứt 1.5px, hover accent-wash, dragover `--accent` |
| Progress | Track 8px pill; fill gradient; đang xử lý = sọc chéo chạy |

---

## 6. Bảng màu nghiệp vụ (KHÔNG được đổi tuỳ tiện)

Các màu này mang **ý nghĩa nghiệp vụ**, người dùng đã quen nhận diện — đổi phải có xác nhận của người dùng.

### 6.1 Loại vải (mọi biểu đồ)

| Fabric | Màu | Nơi khai báo hiện tại |
|---|---|---|
| Cotton | `#3fb950` | `dyeing_hub.js`, `rft.js`, `tank_loading.js`, `batch_matrix_view.html` (**4 chỗ trùng**) |
| CVC | `#2862d7` | như trên |
| Polyester | `#f778ba` | như trên |
| Không xác định | `#abaebb` | fallback |

🟡 D-11: gom về token `--fabric-cotton` / `--fabric-cvc` / `--fabric-polyester` trong `app.css`, JS đọc qua
`getComputedStyle`. Giữ nguyên màu, chỉ đổi nơi khai báo.

### 6.2 Mã badge Batch Per Day by Machine (`cleaning_matrix_view.html` ↔ `BADGE_FILL_COLORS` trong `cleaning_matrix.py`)

| Mã | Nền | Chữ | Ghi chú |
|---|---|---|---|
| CM | `#4B7931` | trắng | Cleaning Machine |
| S | `#8250DF` | trắng | Sample |
| B / BR | `#000000` | trắng | |
| D / DR | `#5A738E` | trắng | |
| M / MR | `#F6A97A` | đen | |
| L / LR | `#FFF5CD` | đen | |
| W / WR | `#FFFFFF` | đen | viền `#CCC` để thấy trên nền trắng |
| Hậu tố **R** (Rework) | — | — | Viền đỏ `#FF0000` 2px |

- Badge: 28×24px, `radius 3px`, 11px/700.
- **Bắt buộc đồng bộ 2 nơi**: CSS trên web và `BADGE_FILL_COLORS` trong file Excel export. Đổi 1 nơi = đổi cả 2.
- Các màu này **cố định cho cả 2 theme** (giống quy ước in ấn/Excel), không đổi theo Dark/Light.

### 6.3 File Excel export

- Header: nền `#24292F`, chữ trắng đậm — dùng chung cho mọi `export_*_excel()`.
- Ô ngày ma trận: tô màu theo 6.2, mỗi mẻ 1 ô riêng.
- Ô vượt Target (Idle Time): style "Bad" chuẩn Excel — nền `FFC7CE`, chữ `9C0006` (tương đương `.ratio-warning` trên web).

---

## 7. Biểu đồ

### 7.1 Kỹ thuật

| Quyết định | Chi tiết | Trạng thái |
|---|---|---|
| Thư viện | Chart.js **4.4.4** qua `cdn.jsdelivr.net` (nạp riêng trong từng view cần) | ✅ |
| Graphify | SVG thuần, màu node/edge theo token (`.graph-node`, `.graph-edge`) | ✅ |
| Màu trục/lưới/chú giải | Đọc động `--text-secondary` bằng `getComputedStyle` lúc vẽ | ✅ |
| Đổi theme | Lắng nghe `colormodechange` → `destroy()` rồi vẽ lại | ✅ |
| Màu series | Theo Mục 6.1; series không phải fabric dùng token accent/status | ✅ |
| Token chung `--chart-grid`, `--chart-axis`, `--chart-1..6` | Thay cho fallback hex trong JS | 🟡 D-11 |

### 7.2 Quy tắc chọn & trình bày biểu đồ (bắt buộc)

1. **Bar chart**: chỉ để so sánh hạng mục rời rạc / xếp hạng. 3–7 cột (tối đa 10–12 cột dọc); nhiều hơn → **bar ngang**.
2. **Line chart**: chỉ cho chuỗi thời gian / dữ liệu liên tục. Tối đa **3–4 đường** / biểu đồ; nhiều hơn → tách
   biểu đồ nhỏ (vd RFT, %Tank Loading: 3 biểu đồ Cotton / CVC / Polyester cạnh nhau).
3. **Data label**: hiện khi ít điểm, cần nhấn chỉ số chính, đánh dấu đỉnh/đáy. **Ẩn** khi nhiều điểm (chồng chữ),
   khi mục tiêu là xem xu hướng, hoặc đã có tooltip.
4. **Đường Target (bắt buộc)**: mọi biểu đồ phải có benchmark.
   - Vẽ là **đường ngang nét đứt** `borderDash: [6, 4]`, `borderWidth: 1.5`, `pointRadius: 0`, cùng màu series,
     cờ `isTargetLine: true`.
   - Dữ liệu chưa có Target → đề xuất thêm cột "Target" cạnh cột hạng mục, không tự bịa số.
5. **Tự kiểm trước khi giao**: đúng loại biểu đồ? data label hợp lý? có đường Target? — sai thì sửa trước.

---

## 8. Khả năng truy cập (Accessibility)

| Quy tắc | Mức |
|---|---|
| Chữ thường ≥ **4.5:1**, chữ lớn (≥ 18px hoặc 14px đậm) và viền/biểu tượng ≥ **3:1** — ở CẢ Light và Dark | Bắt buộc |
| Không truyền đạt thông tin chỉ bằng màu (Rework có thêm viền đỏ + hậu tố R; ratio có số kèm màu) | Bắt buộc |
| Nút chỉ có icon phải có `aria-label` + `title` | Bắt buộc |
| Focus bàn phím nhìn thấy được (`:focus-visible`) | Bắt buộc |
| Tôn trọng `prefers-reduced-motion` (tắt view transition, stripe, slide) | 💡 D-15 |

---

## 9. Lỗi / nợ giao diện đã biết

| ID | Mô tả | Vị trí | Mức |
|---|---|---|---|
| K-01 | Light mode: `.sidebar-link.is-active a` và `.btn-group .btn.selected` dùng `color:#fff` cứng trên nền `--bg-surface-raised` (`#eef1fc`) → chữ trắng trên nền gần trắng, gần như không đọc được | `app.css` mục 3 (sidebar) + 5 (btn-group) | Cao |
| K-02 | `--accent-wash` (`#85a6e9`) không có bản Light → link, `.Label`, mục con sidebar active chỉ ≈ 2.4:1 trên trắng | `app.css` `[data-color-mode="light"]` | Cao |
| K-03 | Màu trạng thái dùng chung 2 theme → badge/flash/ratio 10–12px ở Light chỉ 2.5–3.4:1 | `app.css` mục 1 | Cao |
| K-04 | Màu fabric khai báo trùng 4 file JS/HTML | xem 6.1 | Trung bình |
| K-05 | `cleaning_matrix_view.html` có khối `<style>` inline dài + `.matrix-day-label{color:#8b949e}` hex cứng | template reports | Thấp |
| K-06 | Overlay `rgba(4,6,12,.68)` và stripe progress `#305fbd/#625fff` hardcode thay vì token | `app.css` mục 11, 13 | Thấp |
| K-07 | Còn 52 mã hex trong 7 template `modules/**/*.html` | grep `#[0-9a-fA-F]{6}` | Thấp |

---

## 10. Nhật ký quyết định (Decision log)

| ID | Ngày | Quyết định | Lý do | Trạng thái |
|---|---|---|---|---|
| D-01 | 2026-09-11 | Bỏ GitHub Primer CSS, viết design system riêng trong `app.css` theo `design/DESIGN.md` (AgentQL Aurora) | Muốn nhận diện riêng, bỏ phụ thuộc CDN unpkg | ✅ |
| D-02 | 2026-09-11 | Giữ tên class Primer làm hook + shim biến `--color-*` | Không phải sửa hàng loạt template/JS dựng DOM | ✅ |
| D-03 | 2026-09-11 | Hỗ trợ cả Dark và Light qua `data-color-mode` + nút toggle trong sidebar | Người dùng tự chọn theme theo môi trường làm việc | ✅ |
| D-04 | — | Theme mặc định = **Light**; script chống FOUC đầu `<head>` | Tránh chớp sáng khi chuyển trang có view transition | ✅ |
| D-05 | — | Chuyển trang bằng View Transitions API, chỉ animate `.app-main` | Mượt khi trình chiếu, không cần SPA | ✅ |
| D-06 | 2026-09-11 | Figtree (display) + Inter (UI) + IBM Plex Mono, qua Google Fonts có fallback | Theo DESIGN.md | ✅ |
| D-07 | — | Nút + badge dạng pill; card bo 12px, không bóng, phân lớp bằng viền | Gọn, hợp mật độ dữ liệu cao | ✅ |
| D-08 | 2026-09-25 | Màu badge ma trận cố định (Mục 6.2), đồng bộ web ↔ Excel export | Người dùng nhận diện mã theo màu quen thuộc | ✅ |
| D-09 | 2026-09-18 | Quy tắc biểu đồ + đường Target nét đứt bắt buộc (Mục 7.2) | Chuẩn trực quan hoá theo benchmark | ✅ |
| D-10 | 2026-09-29 | Tách màu trạng thái theo theme (Light dùng `#157A3D` / `#C8291F` / `#9A5A08`), thêm `--warning-mid`, thêm `--accent-wash` bản Light | Sửa K-02, K-03 — đạt WCAG AA | 💡 |
| D-11 | 2026-09-29 | Thêm token `--fabric-*`, `--chart-grid`, `--chart-axis`, `--chart-1..6`; JS đọc từ CSS | Sửa K-04, bỏ hex rải rác | 💡 |
| D-12 | 2026-09-29 | Bổ sung `.btn-ghost`, `.btn-outline`, `.btn-icon`, `.btn.is-loading` | Lấy từ template tham khảo | 💡 |
| D-13 | 2026-09-29 | KPI card có trend badge ↑↓ (xanh = tốt, đỏ = xấu, theo chiều nghiệp vụ) | Lấy từ template tham khảo | 💡 |
| D-14 | 2026-09-29 | Cột số: căn phải + `tabular-nums` | Dễ so sánh số theo cột | 💡 |
| D-15 | 2026-09-29 | Hỗ trợ `prefers-reduced-motion` | Accessibility | 💡 |
| D-16 | 2026-09-29 | Sửa K-01: thay `color:#fff` bằng `var(--text-primary)` (hoặc accent) cho mục active | Lỗi hiển thị Light mode | 💡 |
| D-18 | 2026-09-29 | Đổi gradient chính từ xanh→tím (`90deg #305fbd→#625fff`) sang **xanh–cyan** `135deg`, token theo theme (Mục 3.2); thêm `--text-on-gradient` thay `#fff` cứng | Đã code rồi người dùng huỷ ngay trong ngày — giữ gradient xanh → tím. Không đề xuất lại trừ khi người dùng yêu cầu | ❌ (đã huỷ) |
| D-17 | 2026-09-29 | **Không** áp dụng từ template: card bo 26px, hover `scale()`, shell `100vh overflow:hidden`, topbar thay sidebar, `data-theme`, file `dashboard.css` | Xung đột mật độ dữ liệu / kiến trúc MPA / hook hiện có | ❌ (đã loại) |

---

## 11. Template tham khảo `templates/static/`

Chỉ để **tham khảo**, KHÔNG link vào `base.html`, KHÔNG copy nguyên file.

| Lấy ý tưởng | Không lấy |
|---|---|
| Bộ màu trạng thái Light (D-10; riêng warning phải làm đậm hơn) | Bo góc card 26px, padding 22px |
| Token biểu đồ `--chart-*`, `--fabric-*`, `--grid-line`, `--axis-text` (D-11) | Hover `scale(1.01–1.02)` trên card |
| Biến thể nút ghost/outline/icon/loading (D-12) | Layout `100vh` + `overflow:hidden`, bento 12 cột kiểu slide |
| Trend badge, `--focus-ring`, z-index scale, `prefers-reduced-motion` | `data-theme` (xung đột `data-color-mode`) |
| Cách chia file component (khi `app.css` quá lớn) | `dashboard.css` (file cũ, `:root` riêng đè biến) |
| | `--text-secondary #7B8794` / `--text-faint #A7B2C2` Light (chỉ 3.7 / 2.1 : 1) |

---

## 12. Checklist trước khi merge thay đổi UI

- [ ] Không có mã hex mới ngoài `app.css` (trừ bảng màu nghiệp vụ Mục 6, khai báo đúng 1 chỗ).
- [ ] Token mới có giá trị cho **cả** Dark và Light.
- [ ] Kiểm tra trang ở **cả 2 theme**, bấm toggle khi đang mở trang (biểu đồ vẽ lại đúng màu).
- [ ] Độ tương phản chữ ≥ 4.5:1 ở cả 2 theme (đặc biệt badge, hint, mục active).
- [ ] Không sửa `base.html` để thêm menu — dùng `register_menu(...)`.
- [ ] Biểu đồ: đúng loại, data label hợp lý, có đường Target nét đứt `[6, 4]`.
- [ ] Đổi màu badge ma trận → đã đổi cả `BADGE_FILL_COLORS` (Excel).
- [ ] Bảng rộng cuộn ngang được, header sticky, không vỡ ở `≤ 900px`.
- [ ] Nút icon có `aria-label`; focus bàn phím nhìn thấy.
- [ ] Cập nhật file này: token/component mới (Mục 3–7), quyết định (Mục 10), lỗi đã sửa (Mục 9), changelog (Mục 13).

---

## 13. Changelog của tài liệu

| Ngày | Thay đổi |
|---|---|
| 2026-10-09 | **Knitting Downtime — bộ lọc Program**: thêm dropdown multi-select Program (dùng lại `.kd-dropdown`/`.kd-menu` có ô tìm) + checkbox "Core only" có nhãn "Core program" phía trên để thẳng hàng các ô lọc; drawer thêm cột Program (title = Greige ID); tab Import thêm Box "Program sources". Không thêm token/hex. |
| 2026-10-09 | **Knitting Downtime** (báo cáo %): filter bar ngoài tab giống Dyeing Downtime (From/To, Group By, M/c Code có ô tìm, Knitting Structure, Unit `.BtnGroup`, Export `.btn`); `.page-tabs` Overview / Stop Code Mapping / Import Data; line chart Total + ≤ 3 nhóm, Target nét đứt `[6,4]` cùng màu, màu series = token `--accent`/`--accent-purple`/`--success`/`--warning`, data label chỉ ở Total khi ≤ 12 kỳ; pivot Before/Target (`.ref`) + ô > Target `.ratio-warning` (định nghĩa cục bộ bằng token), dòng `.total-row` + dòng Plan; drill-down `.drawer-overlay/.drawer-panel`; Source mapping dùng `.Label`/`.Label--secondary`/`.Label--danger`. **Vá K-01 cục bộ**: `#kd-unit .btn.is-active` nền `--gradient-primary`, chữ `--text-on-accent` (chưa sửa toàn cục — D-16 vẫn 💡). Không thêm token/hex. |
| 2026-10-09 | Trang mới **Knitting Downtime** (`knitting_downtime_view.html`, khung sườn): form import `.btn-primary` (ẩn khi thiếu quyền edit), kết quả import `.flash-success/-warn/-error`, filter From/To + nút Load `.btn`, 4 `.widget-card` KPI, 2 bảng `.preview-table` cạnh nhau (xếp dọc ≤ 900px), cột số căn phải + `tabular-nums` (D-14 áp cục bộ), trạng thái rỗng `.blankslate`. Chưa có biểu đồ (chờ Target). Stop Color từ file (ARGB) chưa hiển thị — nếu dùng sau này là màu nghiệp vụ, ghi vào Mục 6. Không thêm token/hex. |
| 2026-10-08 | **Right First Time** (viết lại): giữ nguyên bố cục (filter bar, tab, 3 KPI, 3 biểu đồ Cotton/CVC/Polyester, bảng). 5 tab (Lab to Bulk / Bulk to Bulk / 2nd Batch / Rework / Adjustment); bảng thêm dòng **Total** (`.total-row`, viền trên `--border-default`); cột Target ghi rõ `Target (min)` / `Target (max)`, ô kỳ + ô Total tô `.ratio-good` / `.ratio-warning` theo chiều Target (định nghĩa trong `rft_view.html` bằng token, có số % kèm màu, title = số mẻ); cột số căn phải + `tabular-nums` (D-14 áp cục bộ). Capacity / Machine Group / Brand Program đều là dropdown data-driven; thêm nút Export Excel `.btn` dùng chung tham số lọc. Bỏ hex fallback trong `.capacity-menu` (chỉ dùng token). Hub: 4 ô RFT đổi thành Lab to Bulk / Bulk to Bulk / 2nd Batch / Rework (≥500kg). Không thêm token/hex mới. |
| 2026-10-06 | **Modal Import**: bỏ bảng "Preview (first 5 valid rows)" — bảng nhiều cột làm modal cao, đẩy nút Confirm Import khuất màn hình. Chỉ giữ thông báo số dòng hợp lệ / danh sách dòng lỗi (`#preview-errors`). Không thêm token/hex. |
| 2026-10-06 | **Fabric/Color Matrix**: thanh lọc giống hệt tab Trend (From/To, Capacity, Brand Program, Tank Type, Group By, ReDye = 0, nút Export `.btn`), bỏ Fabric Type + nút "View Report" (lọc tự tải lại), bỏ thẻ "Date Range". Ô kỳ + ô Total của dòng màu dùng `.cell-clickable` + `tabindex=0` mở modal day-batches. Không thêm token/hex. |
| 2026-10-06 | **Batch/Day Trend**: ô số liệu + ô Total dùng `.cell-clickable` (thêm `tabindex=0`, Enter/Space mở được bằng bàn phím) -> drawer `.drawer-overlay/.drawer-panel` liệt kê mẻ (checkbox "Only Normal", Counted = `.Label` / `.Label--secondary` để không chỉ dựa vào màu). Nút Export Excel `.btn` thường ở filter bar + `.btn-sm` trong drawer, dùng chung `URLSearchParams` với bảng. Excel header `#24292F` (Mục 6.3). Không thêm token/hex. |
| 2026-10-05 | Trang mới **Idle Entry** (`idle_entry_view.html`, dùng trên điện thoại): form 1 cột, input/nút cao ≥ 44px, chữ 16px (tránh iOS tự zoom), ≤ 520px các ô đôi xếp dọc; danh sách lần dừng dạng thẻ, nhãn trạng thái viền theo `--warning`/`--success`/`--danger`. Drawer Idle Time: mỗi khoảng idle chia đoạn theo nguyên nhân, cột Source hiện giờ người dùng nhập + độ lệch. Không thêm token/hex. |
| 2026-10-05 | Trang mới **Idle Time** (`idle_time_view.html`): dùng lại `.capacity-dropdown`, `.BtnGroup` (chuyển Idle/Operating), `.cell-clickable`, `.ratio-warning` (ô vượt Target), drawer `.drawer-overlay/.drawer-panel` cho danh sách khoảng idle. Style inline chỉ dùng token, không hex. Excel: ô vượt Target dùng style "Bad" chuẩn Excel (nền `FFC7CE`/chữ `9C0006`) — ghi ở Mục 6.3. |
| 2026-10-05 | Batch Per Day by Machine: thêm dropdown multi-select "Tank Type" (cạnh Capacity), dùng lại component `.capacity-dropdown`/`makeMultiSelectDropdown`, không thêm CSS. |
| 2026-10-05 | Bảng "Normal Dyeing Batches by Colour" (Batch Per Day by Machine) tách nhóm theo loại vải Cotton → CVC → Polyester: cột Fabric rowspan dùng lại `.summary-group-cell`, dòng Subtotal dùng `.summary-total-group`, dòng Total dùng `.total-row`. Không thêm token/hex mới. Excel "Color Summary" cùng bố cục (cột Fabric merge dọc). |
| 2026-09-29 | D-18: thử gradient xanh–cyan rồi **huỷ**, `app.css` đã hoàn tác về xanh → tím. |
| 2026-09-29 | Tạo tài liệu: ghi lại trạng thái UI hiện tại, bảng màu nghiệp vụ, quy tắc biểu đồ, lỗi đã biết K-01..K-07, đề xuất D-10..D-17 sau khi so sánh với `templates/static/`. |
