/**
 * CORE/FORMAT.JS — themeVar/palette/fabricColors/fmtUnit, GOP TU 2 BAN
 * TRUNG NHAU trong dashboard.js va charts.js (cung logic, tung dinh
 * nghia rieng o 2 noi). Tu gio chi con 1 nguon duy nhat.
 *
 * Hanh vi giu NGUYEN 100% so voi ban goc — copy nguyen van, khong sua.
 */

export function themeVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name);
  return v && v.trim() ? v.trim() : fallback;
}

export function palette() {
  return [
    themeVar('--chart-1', '#2952e3'), themeVar('--chart-2', '#157a3d'),
    themeVar('--chart-3', '#b3690a'), themeVar('--chart-4', '#c8291f'),
    themeVar('--chart-5', '#7c3aed'), themeVar('--chart-6', '#49c6e5'),
    themeVar('--chart-7', '#a3821a'), themeVar('--chart-8', '#946b8f')
  ];
}

export function fabricColors() {
  return {
    Cotton: themeVar('--fabric-cotton', '#2952e3'),
    CVC: themeVar('--fabric-cvc', '#b3690a'),
    Polyester: themeVar('--fabric-polyester', '#157a3d')
  };
}

export function fmtUnit(v, unit) {
  const n = typeof v === 'number' ? (Number.isInteger(v) ? v : Math.round(v * 100) / 100) : v;
  return unit ? `${n}${unit}` : String(n);
}
