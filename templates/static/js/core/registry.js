/**
 * CORE/REGISTRY.JS — Thay the init()/refreshAll() liet ke cung trong
 * dashboard.js hien tai.
 *
 * dashboard.js hien co init() goi 18 ham bindXxx() liet ke cung, va
 * refreshAll() lam tuong tu cho tung tac vu refresh. Them slice moi bat
 * buoc phai sua ca 2 ham do. Module nay thay bang: moi feature tu
 * registerFeature(...) 1 lan, init()/refreshAll() cua registry chi con
 * la 1 VONG LAP qua danh sach da dang ky — KHONG BAO GIO PHAI SUA FILE
 * NAY khi them feature moi.
 *
 * Dung y het thu tu su kien nhu dashboard.js cu: init() chay 1 lan luc
 * tai trang, refresh(filters) chay lai khi bo loc doi HOAC khi nguoi
 * dung mo tab do.
 */

const _features = new Map();

/**
 * @param {{
 *   id: string,               // duy nhat, dung lam khoa
 *   panel?: string,            // id cua the DOM chua noi dung tab nay
 *   state?: object,            // state RIENG cua feature, KHONG dua vao core/state.js
 *   init?: (root, ctx) => void,        // chay 1 lan luc dang ky
 *   refresh?: (filters, ctx) => void,  // chay khi filter doi HOAC tab duoc mo
 * }} feature
 */
export function registerFeature(feature) {
  if (!feature || !feature.id) {
    throw new Error("registerFeature: thieu 'id'. Moi feature phai co id duy nhat.");
  }
  if (_features.has(feature.id)) {
    throw new Error(
      `registerFeature: id '${feature.id}' da duoc dang ky. ` +
      `Ten id phai duy nhat toan he thong — kiem tra co feature nao dang ky trung.`
    );
  }
  _features.set(feature.id, {
    id: feature.id,
    panel: feature.panel || null,
    state: feature.state || {},
    init: feature.init || (() => {}),
    refresh: feature.refresh || (() => {}),
    _initialized: false,
  });
}

/** Chi dung trong test — xoa toan bo dang ky de moi test doc lap nhau. */
export function _resetRegistryForTest() {
  _features.clear();
}

export function listFeatures() {
  return Array.from(_features.values());
}

export function getFeature(id) {
  return _features.get(id) || null;
}

/**
 * Goi 1 lan luc trang tai xong. Duyet TOAN BO feature da dang ky, goi
 * init() cua tung cai. Loi o 1 feature KHONG lam hong cac feature khac
 * (bat loi tung cai rieng, in ra console thay vi crash ca trang).
 */
export function initAll(ctx) {
  for (const f of _features.values()) {
    if (f._initialized) continue;
    try {
      const root = f.panel ? document.getElementById(f.panel) : null;
      f.init(root, ctx);
      f._initialized = true;
    } catch (err) {
      console.error(`[registry] Loi khi init feature '${f.id}':`, err);
    }
  }
}

/**
 * Goi khi filter doi. `activeFeatureId` (neu co) la tab dang hien —
 * CHI feature do duoc refresh ngay; cac feature khac se refresh khi
 * nguoi dung chuyen sang tab cua chung (goi refreshOne rieng luc doi
 * tab). Neu KHONG truyen activeFeatureId, refresh HET (dung khi can
 * force lam moi toan bo, vd sau khi luu du lieu).
 */
export function refreshAll(filters, ctx, activeFeatureId) {
  for (const f of _features.values()) {
    if (activeFeatureId && f.id !== activeFeatureId) continue;
    try {
      f.refresh(filters, ctx);
    } catch (err) {
      console.error(`[registry] Loi khi refresh feature '${f.id}':`, err);
    }
  }
}

export function refreshOne(featureId, filters, ctx) {
  const f = _features.get(featureId);
  if (!f) {
    console.warn(`[registry] refreshOne: khong tim thay feature '${featureId}'`);
    return;
  }
  try {
    f.refresh(filters, ctx);
  } catch (err) {
    console.error(`[registry] Loi khi refresh feature '${featureId}':`, err);
  }
}
