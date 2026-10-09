/**
 * CORE/STATE.JS — State toan cuc, CHI chua bo loc dung chung.
 *
 * State hien tai trong dashboard.js co 16 khoa, 13/16 la chuyen rieng
 * cua tung tab (batchGranularity, tankGranularity, selectedTypes,
 * rootCause, activeKpi...). Module nay CHU DINH chi giu phan thuc su
 * dung chung — moi feature tu quan ly state rieng trong object no dang
 * ky qua registry.js (xem registerFeature({ state: {...} })).
 */

const _state = {
  dateFrom: null,
  dateTo: null,
  machines: [],
  capacities: [],
  fabrics: [],
  plants: [],   // giao dien 1 nha may hien chi co 1 phan tu, san sang cho da nha may
};

const _listeners = new Set();

export function getState() {
  // Tra ban sao nong — nguoi goi KHONG duoc sua truc tiep object tra ve,
  // phai qua setState().
  return { ..._state };
}

export function setState(patch) {
  Object.assign(_state, patch);
  for (const fn of _listeners) fn(getState());
}

/** Dang ky ham chay moi khi state doi. Tra ve ham huy dang ky. */
export function subscribe(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
