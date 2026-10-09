/**
 * CORE/CHARTS/LINE.JS — renderSparkline, renderLine. Tach nguyen ven tu
 * charts.js. Hanh vi giu NGUYEN 100%.
 */

import { fmtUnit, themeVar } from '../format.js';
import { svgEl, clear, emptyState, chartTheme, addVerticalGradient } from './primitives.js';

// ---------------------------------------------------------------
// SPARKLINE — minimal trend indicator for KPI/mini-stat cards.
// ---------------------------------------------------------------
export function renderSparkline(container, values, opts) {
  opts = opts || {};
  const nums = (values || []).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  if (!nums.length) return emptyState(container, '');

  const color = opts.color || themeVar('--primary', '#2952e3');
  const w = Math.max(container.clientWidth, 60) || 120;
  const h = Math.max(container.clientHeight, 24) || 36;
  const pad = { top: 4, right: 3, bottom: 4, left: 3 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minVal = Math.min(...values);
  const maxVal = Math.max(...values, minVal + 0.001);
  const n = values.length;
  const xStep = n > 1 ? plotW / (n - 1) : 0;
  const yOf = (v) => pad.top + plotH - ((v - minVal) / (maxVal - minVal)) * plotH;
  const xOf = (i) => pad.left + (n > 1 ? i * xStep : plotW / 2);

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%', preserveAspectRatio: 'none' });

  if (opts.area !== false) {
    const fill = addVerticalGradient(svg, color, { topOpacity: 0.35, bottomOpacity: 0.02 });
    const areaPts = values.map((v, i) => `${xOf(i)},${yOf(v)}`).join(' ');
    const d = `M ${xOf(0)},${pad.top + plotH} L ${areaPts} L ${xOf(n - 1)},${pad.top + plotH} Z`;
    svg.appendChild(svgEl('path', { d, fill, stroke: 'none' }));
  }

  const linePts = values.map((v, i) => `${xOf(i)},${yOf(v)}`).join(' ');
  svg.appendChild(svgEl('polyline', { points: linePts, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));

  if (opts.showLast !== false) {
    svg.appendChild(svgEl('circle', { cx: xOf(n - 1), cy: yOf(values[n - 1]), r: 3, fill: color }));
  }

  clear(container);
  container.appendChild(svg);
}

// ---------------------------------------------------------------
// LINE CHART — datasets: [{label, data, color, width, opacity}]
// ---------------------------------------------------------------
export function renderLine(container, labels, datasets, opts) {
  opts = opts || {};
  const xFormat = opts.xFormat || 'date';
  const showValues = !!opts.showValues;
  const unit = opts.unit || '';
  if (!labels.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 280) || 700;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 260;
  const pad = { top: showValues ? 26 : 16, right: 16, bottom: 36, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allValues = datasets.flatMap((d) => d.data).filter((v) => v !== null && v !== undefined);
  const maxVal = Math.max(1, ...(allValues.length ? allValues : [1]));
  const n = labels.length;
  const xStep = n > 1 ? plotW / (n - 1) : 0;

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = (maxVal * i) / steps;
    const y = pad.top + plotH - (val / maxVal) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
    t.textContent = fmtUnit(Math.round(val), unit);
    svg.appendChild(t);
  }

  // Datasets marked `muted` draw first (underneath); the highlighted/bold
  // one(s) draw last so it visually sits on top.
  const ordered = [...datasets].sort((a, b) => (a.width || 2.25) - (b.width || 2.25));

  ordered.forEach((ds) => {
    const width = ds.width || 2.25;
    const opacity = ds.opacity != null ? ds.opacity : 1;
    const xOf = (i) => pad.left + (n > 1 ? i * xStep : plotW / 2);
    const yOf = (v) => pad.top + plotH - (v / maxVal) * plotH;

    // Split into contiguous runs of non-null points -- each run is its
    // own polyline, so a null value creates a visible gap instead of
    // connecting across it (or, worse, being treated as 0).
    let run = [];
    const flushRun = () => {
      if (run.length < 2) { run = []; return; }
      const pts = run.map((r) => `${xOf(r.i)},${yOf(r.v)}`).join(' ');
      if (opts.area && datasets.length === 1) {
        const fill = addVerticalGradient(svg, ds.color, { topOpacity: 0.32, bottomOpacity: 0.02 });
        const areaD = `M ${xOf(run[0].i)},${pad.top + plotH} L ${pts} L ${xOf(run[run.length - 1].i)},${pad.top + plotH} Z`;
        svg.appendChild(svgEl('path', { d: areaD, fill, stroke: 'none' }));
      }
      svg.appendChild(svgEl('polyline', {
        points: pts, fill: 'none', stroke: ds.color, 'stroke-width': width, opacity,
        'stroke-linecap': 'round', 'stroke-linejoin': 'round'
      }));
      run = [];
    };

    ds.data.forEach((v, i) => {
      if (v === null || v === undefined) { flushRun(); return; }
      run.push({ i, v });
    });
    flushRun();

    ds.data.forEach((v, i) => {
      if (v === null || v === undefined) return;
      const x = xOf(i), y = yOf(v);
      const dot = svgEl('circle', { cx: x, cy: y, r: width > 2.25 ? 4 : 2.5, fill: ds.color, opacity });
      const titleText = `${labels[i]} — ${ds.label}: ${fmtUnit(v, unit)}`;
      dot.appendChild(svgEl('title', {})).textContent = titleText;
      if (opts.onPointClick) {
        dot.style.cursor = 'pointer';
        dot.addEventListener('click', () => opts.onPointClick(i, v, labels[i], ds));
      }
      svg.appendChild(dot);
      if (showValues && datasets.length === 1) {
        const vt = svgEl('text', { x, y: y - 8, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: theme.text });
        vt.textContent = fmtUnit(v, unit);
        svg.appendChild(vt);
      }
    });
  });

  const labelEvery = xFormat === 'category' ? 1 : Math.max(1, Math.ceil(n / 8));
  labels.forEach((lab, i) => {
    if (i % labelEvery !== 0 && i !== n - 1) return;
    const x = pad.left + (n > 1 ? i * xStep : plotW / 2);
    const t = svgEl('text', { x, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 9.5, fill: theme.axis });
    t.textContent = xFormat === 'category'
      ? (lab.length > 14 ? lab.slice(0, 13) + '…' : lab)
      : (lab.length >= 5 ? lab.slice(5) : lab); // YYYY-MM-DD -> MM-DD
    svg.appendChild(t);
  });

  clear(container);
  container.appendChild(svg);
}
