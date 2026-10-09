/**
 * CORE/CHARTS/STACKED.JS — renderStackedBar, renderStandardAchievementBar,
 * renderStackedTrendCombo. Tach nguyen ven tu charts.js. Hanh vi giu
 * NGUYEN 100%.
 */

import { fmtUnit } from '../format.js';
import { svgEl, clear, emptyState, chartTheme, roundedTopBarPath } from './primitives.js';

// datasets: [{label, color, data}], one bar per label, segments stacked
// in dataset order.
export function renderStackedBar(container, labels, datasets, opts) {
  opts = opts || {};
  const unit = opts.unit || '';
  if (!labels.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 240) || 600;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 260;
  const pad = { top: 20, right: 12, bottom: 44, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const n = labels.length;
  const totals = labels.map((_, i) => datasets.reduce((a, ds) => a + (ds.data[i] || 0), 0));
  const maxVal = Math.max(0.1, ...totals);

  const gap = 14;
  const barW = Math.max(6, (plotW - gap * (n - 1)) / n);

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = (maxVal * i) / steps;
    const y = pad.top + plotH - (val / maxVal) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
    t.textContent = fmtUnit(Math.round(val * 100) / 100, unit);
    svg.appendChild(t);
  }

  labels.forEach((lab, i) => {
    const x = pad.left + i * (barW + gap);
    let yCursor = pad.top + plotH;
    datasets.forEach((ds, dsIndex) => {
      const v = ds.data[i] || 0;
      const segH = maxVal > 0 ? (v / maxVal) * plotH : 0;
      const y = yCursor - segH;
      if (v > 0) {
        const isTop = dsIndex === datasets.length - 1 || datasets.slice(dsIndex + 1).every((d2) => !(d2.data[i] > 0));
        const rect = svgEl('path', {
          d: isTop ? roundedTopBarPath(x, y, barW, Math.max(segH, 0), Math.min(4, barW / 2)) : `M ${x} ${y + segH} L ${x} ${y} L ${x + barW} ${y} L ${x + barW} ${y + segH} Z`,
          fill: ds.color
        });
        if (opts.onSegmentClick) {
          rect.style.cursor = 'pointer';
          rect.addEventListener('click', () => opts.onSegmentClick(dsIndex, i, ds, lab));
        }
        svg.appendChild(rect);
        const tip = svgEl('title', {});
        tip.textContent = `${lab} — ${ds.label}: ${fmtUnit(Math.round(v * 100) / 100, unit)}` + (ds.dataLabels && ds.dataLabels[i] != null ? ` (${ds.dataLabels[i]})` : '');
        rect.appendChild(tip);
        if (ds.dataLabels && ds.dataLabels[i] != null && segH >= 16) {
          const segLabel = svgEl('text', {
            x: x + barW / 2, y: y + segH / 2 + 4, 'text-anchor': 'middle',
            'font-size': 11, 'font-weight': 600, fill: opts.segmentLabelColor || '#17171a'
          });
          segLabel.textContent = ds.dataLabels[i];
          segLabel.style.pointerEvents = 'none';
          svg.appendChild(segLabel);
        }
      }
      yCursor = y;
    });

    if (totals[i] > 0) {
      const vt = svgEl('text', { x: x + barW / 2, y: yCursor - 6, 'text-anchor': 'middle', 'font-size': 10.5, 'font-weight': 700, fill: theme.text });
      vt.textContent = fmtUnit(Math.round(totals[i] * 100) / 100, unit);
      svg.appendChild(vt);
    }

    const lt = svgEl('text', { x: x + barW / 2, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 10, fill: theme.axis });
    const rawLabel = opts.xFormat === 'date' ? (lab.length >= 5 ? lab.slice(5) : lab) : lab;
    lt.textContent = rawLabel.length > 12 ? rawLabel.slice(0, 11) + '…' : rawLabel;
    svg.appendChild(lt);
  });

  clear(container);
  container.appendChild(svg);
}

// STANDARD ACHIEVEMENT 100%-STACKED BAR — Y axis fixed 0-100%, every bar
// sums to exactly 100%. datasets: [{key,label,color,counts:[],pct:[]}].
export function renderStandardAchievementBar(container, labels, datasets, opts) {
  opts = opts || {};
  if (!labels.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 240) || 600;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 260;
  const pad = { top: 20, right: 12, bottom: 44, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const n = labels.length;
  const gap = 14;
  const barW = Math.max(6, (plotW - gap * (n - 1)) / n);

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();

  [0, 25, 50, 75, 100].forEach((val) => {
    const y = pad.top + plotH - (val / 100) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
    t.textContent = val + '%';
    svg.appendChild(t);
  });

  labels.forEach((lab, i) => {
    const x = pad.left + i * (barW + gap);
    let yCursor = pad.top + plotH;
    const periodTotal = datasets.reduce((a, ds) => a + (ds.counts[i] || 0), 0);

    datasets.forEach((ds, dsIndex) => {
      const pctVal = ds.pct[i] || 0;
      const count = ds.counts[i] || 0;
      const segH = (pctVal / 100) * plotH;
      const y = yCursor - segH;
      const isSelected = opts.selected && opts.selected.period === lab && opts.selected.key === ds.key;
      const dimmed = opts.selected && !isSelected;
      if (pctVal > 0) {
        const isTop = dsIndex === datasets.length - 1 || datasets.slice(dsIndex + 1).every((d2) => !(d2.pct[i] > 0));
        const rect = svgEl('path', {
          d: isTop ? roundedTopBarPath(x, y, barW, Math.max(segH, 0), Math.min(4, barW / 2)) : `M ${x} ${y + segH} L ${x} ${y} L ${x + barW} ${y} L ${x + barW} ${y + segH} Z`,
          fill: ds.color, opacity: dimmed ? 0.3 : 1
        });
        if (isSelected) { rect.setAttribute('stroke', theme.text); rect.setAttribute('stroke-width', '1.5'); }
        rect.appendChild(svgEl('title', {})).textContent = `${lab} — ${ds.label}: ${count} case (${pctVal}%) / ${periodTotal} total`;
        if (opts.onSegmentClick) {
          rect.style.cursor = 'pointer';
          rect.addEventListener('click', () => opts.onSegmentClick(dsIndex, i, ds, lab));
        }
        svg.appendChild(rect);
      }
      yCursor = y;
    });

    const lt = svgEl('text', { x: x + barW / 2, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 10, fill: theme.axis });
    const rawLabel = opts.xFormat === 'date' ? (lab.length >= 5 ? lab.slice(5) : lab) : lab;
    lt.textContent = rawLabel.length > 12 ? rawLabel.slice(0, 11) + '…' : rawLabel;
    svg.appendChild(lt);
  });

  clear(container);
  container.appendChild(svg);
}

// STACKED BAR + TREND LINE COMBO.
// barDatasets: [{key,label,color,counts:[...]}] (stacked)
// lineData: {label, data:[...], unit} (secondary axis)
export function renderStackedTrendCombo(container, labels, barDatasets, lineData, opts) {
  opts = opts || {};
  if (!labels.length) return emptyState(container);

  const w = Math.max(container.clientWidth, 280) || 640;
  const h = Math.max(container.clientHeight, opts.minHeight || 220) || 320;
  const pad = { top: 20, right: 44, bottom: 44, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const n = labels.length;
  const gap = 14;
  const barW = Math.max(6, (plotW - gap * (n - 1)) / n);

  const periodTotals = labels.map((_, i) => barDatasets.reduce((a, ds) => a + (ds.counts[i] || 0), 0));
  const maxCount = Math.max(1, ...periodTotals);
  const lineVals = (lineData && lineData.data ? lineData.data : []).filter((v) => v !== null && v !== undefined);
  const maxLine = Math.max(1, ...(lineVals.length ? lineVals : [1]));

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, width: '100%', height: '100%' });
  const theme = chartTheme();

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = Math.round((maxCount * i) / steps);
    const y = pad.top + plotH - (val / maxCount) * plotH;
    svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
    const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
    t.textContent = val;
    svg.appendChild(t);
  }
  for (let i = 0; i <= steps; i++) {
    const val = (maxLine * i) / steps;
    const y = pad.top + plotH - (val / maxLine) * plotH;
    const t = svgEl('text', { x: w - pad.right + 6, y: y + 3, 'text-anchor': 'start', 'font-size': 9.5, fill: theme.axis });
    t.textContent = val.toFixed(1) + 'h';
    svg.appendChild(t);
  }

  const barCenters = [];
  labels.forEach((lab, i) => {
    const x = pad.left + i * (barW + gap);
    barCenters.push(x + barW / 2);
    let yCursor = pad.top + plotH;
    const total = periodTotals[i];

    barDatasets.forEach((ds, dsIndex) => {
      const count = ds.counts[i] || 0;
      if (count <= 0) return;
      const segH = (count / maxCount) * plotH;
      const y = yCursor - segH;
      const isTop = dsIndex === barDatasets.length - 1 || barDatasets.slice(dsIndex + 1).every((d2) => !(d2.counts[i] > 0));
      const isSelected = opts.selected && opts.selected.period === lab && opts.selected.key === ds.key;
      const dimmed = opts.selected && !isSelected;
      const rect = svgEl('path', {
        d: isTop ? roundedTopBarPath(x, y, barW, Math.max(segH, 0), Math.min(4, barW / 2)) : `M ${x} ${y + segH} L ${x} ${y} L ${x + barW} ${y} L ${x + barW} ${y + segH} Z`,
        fill: ds.color, opacity: dimmed ? 0.3 : 1
      });
      if (isSelected) { rect.setAttribute('stroke', theme.text); rect.setAttribute('stroke-width', '1.5'); }
      const pctOfPeriod = total > 0 ? Math.round((count / total) * 1000) / 10 : 0;
      rect.appendChild(svgEl('title', {})).textContent = `${lab} — ${ds.label}: ${count} case (${pctOfPeriod}% / ${total} total)`;
      if (opts.onSegmentClick) {
        rect.style.cursor = 'pointer';
        rect.addEventListener('click', () => opts.onSegmentClick(dsIndex, i, ds, lab));
      }
      svg.appendChild(rect);
      yCursor = y;
    });

    const lt = svgEl('text', { x: x + barW / 2, y: pad.top + plotH + 16, 'text-anchor': 'middle', 'font-size': 10, fill: theme.axis });
    const rawLabel = opts.xFormat === 'date' ? (lab.length >= 5 ? lab.slice(5) : lab) : lab;
    lt.textContent = rawLabel.length > 12 ? rawLabel.slice(0, 11) + '…' : rawLabel;
    svg.appendChild(lt);
  });

  if (lineData && lineData.data && lineData.data.length === n) {
    const color = lineData.color || theme.text;
    const yOf = (v) => pad.top + plotH - (v / maxLine) * plotH;
    let run = [];
    const flushRun = () => {
      if (run.length >= 2) {
        const pts = run.map((r) => `${barCenters[r.i]},${yOf(r.v)}`).join(' ');
        svg.appendChild(svgEl('polyline', {
          points: pts, fill: 'none', stroke: color, 'stroke-width': 2.25,
          'stroke-linecap': 'round', 'stroke-linejoin': 'round'
        }));
      }
      run = [];
    };
    lineData.data.forEach((v, i) => {
      if (v === null || v === undefined) { flushRun(); return; }
      run.push({ i, v });
    });
    flushRun();
    lineData.data.forEach((v, i) => {
      if (v === null || v === undefined) return;
      const dot = svgEl('circle', { cx: barCenters[i], cy: yOf(v), r: 3, fill: color });
      dot.appendChild(svgEl('title', {})).textContent = `${labels[i]} — ${lineData.label || 'Avg Duration'}: ${v}${lineData.unit || 'h'}/case`;
      svg.appendChild(dot);
    });
  }

  clear(container);
  container.appendChild(svg);
}
