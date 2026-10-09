/**
 * CORE/UI.JS — Toast + overlay dung chung.
 *
 * Moi feature goi showToast()/showOverlay() thay vi tu dung
 * document.createElement rai rac — dam bao giao dien thong bao dong
 * nhat toan he thong, va CHI 1 element toast/overlay ton tai tren
 * trang tai bat ky thoi diem nao (goi lien tiep se thay the, khong
 * chong len nhau).
 */

let _toastEl = null;
let _toastTimer = null;
let _overlayEl = null;

function _ensureToastEl() {
  if (_toastEl && document.body.contains(_toastEl)) return _toastEl;
  _toastEl = document.createElement("div");
  _toastEl.className = "app-toast";
  _toastEl.setAttribute("role", "status");
  _toastEl.setAttribute("aria-live", "polite");
  document.body.appendChild(_toastEl);
  return _toastEl;
}

/**
 * @param {string} message
 * @param {{type?: 'info'|'success'|'error', durationMs?: number}} [opts]
 */
export function showToast(message, opts = {}) {
  const { type = "info", durationMs = 3000 } = opts;
  const el = _ensureToastEl();
  el.textContent = message;
  el.className = `app-toast app-toast--${type} is-visible`;

  if (_toastTimer) clearTimeout(_toastTimer);
  if (durationMs > 0) {
    _toastTimer = setTimeout(() => {
      el.classList.remove("is-visible");
    }, durationMs);
  }
}

export function showApiError(err) {
  // err ky vong la ApiError tu core/api.js (co .message da dich san tu
  // server), nhung van an toan neu nhan phai Error thuong.
  showToast(err?.message || "Da xay ra loi.", { type: "error", durationMs: 5000 });
}

export function showOverlay(message = "Dang xu ly...") {
  if (!_overlayEl) {
    _overlayEl = document.createElement("div");
    _overlayEl.className = "app-overlay";
    const box = document.createElement("div");
    box.className = "app-overlay__box";
    _overlayEl.appendChild(box);
    document.body.appendChild(_overlayEl);
  }
  _overlayEl.querySelector(".app-overlay__box").textContent = message;
  _overlayEl.classList.add("is-visible");
}

export function hideOverlay() {
  _overlayEl?.classList.remove("is-visible");
}

/**
 * Boc 1 Promise: tu dong hien overlay luc dang cho, tu dong an khi
 * xong (du thanh cong hay loi), va tu dong showApiError neu loi. Dung
 * cho moi thao tac ghi (luu, xoa, import) — khong con phai tu viet
 * try/finally lap lai o tung noi.
 */
export async function withOverlay(promiseFn, message) {
  showOverlay(message);
  try {
    return await promiseFn();
  } catch (err) {
    showApiError(err);
    throw err;
  } finally {
    hideOverlay();
  }
}

/** Chi dung trong test. */
export function _resetUiForTest() {
  _toastEl?.remove();
  _overlayEl?.remove();
  _toastEl = null;
  _overlayEl = null;
  if (_toastTimer) clearTimeout(_toastTimer);
}
