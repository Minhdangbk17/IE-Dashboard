/**
 * CORE/CHARTS/BAR.JS — renderBar, renderGroupedBar. Tach nguyen ven tu
 * charts.js. Hanh vi giu NGUYEN 100%.
 */

import { fmtUnit, themeVar } from '../format.js';
import { svgEl, clear, emptyState, chartTheme, addVerticalGradient, roundedTopBarPath } from './primitives.js';

export function renderBar(container, labels, values, opts) {
  opts = opts || {};
  const color = opts.color || themeVar('--primary', '#2952e3');
  const unit = opts.unit || '';
  if (!labels.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 240) || 600;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 260;
  const pad = { top: 26, right: 12, bottom: 40, left: 44 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const maxVal = Math.max(1, ...values);

  const gap = Math.max(8, plotW / values.length * 0.28);
  const n = values.length;
  const barW = Math.max(6, (plotW - gap * (n - 1)) / n);

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();
  const fill = opts.gradient === false ? color : addVerticalGradient(svg, color);

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = (maxVal * i) / steps;
    const y = pad.top + plotH - (val / maxVal) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 8, y: y + 3, 'text-anchor': 'end', 'font-size': 10, fill: theme.axis });
    t.textContent = fmtUnit(Math.round(val * 10) / 10, unit);
    svg.appendChild(t);
  }

  values.forEach((v, i) => {
    const barH = maxVal > 0 ? (v / maxVal) * plotH : 0;
    const x = pad.left + i * (barW + gap);
    const y = pad.top + plotH - barH;

    svg.appendChild(svgEl('path', { d: roundedTopBarPath(x, y, barW, Math.max(barH, 0), Math.min(6, barW / 2)), fill }));

    const vt = svgEl('text', { x: x + barW / 2, y: y - 7, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: theme.text });
    vt.textContent = fmtUnit(v, unit);
    svg.appendChild(vt);

    const lt = svgEl('text', { x: x + barW / 2, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 10.5, fill: theme.axis });
    lt.textContent = labels[i].length > 14 ? labels[i].slice(0, 13) + '…' : labels[i];
    svg.appendChild(lt);
  });

  clear(container);
  container.appendChild(svg);
}

// datasets: [{label, color, data}], bars placed side-by-side per label
// (not stacked).
export function renderGroupedBar(container, labels, datasets, opts) {
  opts = opts || {};
  const unit = opts.unit || '';
  if (!labels.length || !datasets.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 260) || 620;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 260;
  const pad = { top: 24, right: 12, bottom: 40, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const n = labels.length;
  const groupGap = Math.max(10, plotW / n * 0.22);
  const groupW = (plotW - groupGap * (n - 1)) / n;
  const barGap = 2;
  const barW = Math.max(3, (groupW - barGap * (datasets.length - 1)) / datasets.length);

  const allValues = datasets.flatMap((d) => d.data).filter((v) => v !== null && v !== undefined);
  const maxVal = Math.max(1, ...(allValues.length ? allValues : [1]));

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = (maxVal * i) / steps;
    const y = pad.top + plotH - (val / maxVal) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
    t.textContent = fmtUnit(Math.round(val * 10) / 10, unit);
    svg.appendChild(t);
  }

  labels.forEach((lab, i) => {
    const groupX = pad.left + i * (groupW + groupGap);
    datasets.forEach((ds, dsIndex) => {
      const v = ds.data[i];
      if (v === null || v === undefined) return; // no data that group -> leave a gap
      const barH = maxVal > 0 ? (v / maxVal) * plotH : 0;
      const x = groupX + dsIndex * (barW + barGap);
      const y = pad.top + plotH - barH;
      const rect = svgEl('path', { d: roundedTopBarPath(x, y, barW, Math.max(barH, 0), Math.min(3, barW / 2)), fill: ds.color });
      if (opts.onSegmentClick) {
        rect.style.cursor = 'pointer';
        rect.addEventListener('click', () => opts.onSegmentClick(dsIndex, i, ds, lab));
      }
      svg.appendChild(rect);
    });

    const lt = svgEl('text', { x: groupX + groupW / 2, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 10, fill: theme.axis });
    const rawLabel = opts.xFormat === 'date' ? (lab.length >= 5 ? lab.slice(5) : lab) : lab;
    lt.textContent = rawLabel.length > 12 ? rawLabel.slice(0, 11) + '…' : rawLabel;
    svg.appendChild(lt);
  });

  clear(container);
  container.appendChild(svg);
}
