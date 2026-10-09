/**
 * CORE/CHARTS/DOUGHNUT.JS — renderDoughnut. Tach nguyen ven tu
 * charts.js. Hanh vi giu NGUYEN 100%.
 */

import { svgEl, clear, chartTheme, nextGradientId } from './primitives.js';

// segments: [{label, value, color}]. opts: {thickness: 0..1, glow}
export function renderDoughnut(container, segments, centerLabel, opts) {
  opts = opts || {};
  const total = segments.reduce((a, s) => a + s.value, 0);
  const w = Math.max(container.clientWidth, 160) || 220;
  const h = Math.max(container.clientHeight, opts.minHeight || 160) || 220;
  const size = Math.min(w, h);
  const cx = size / 2, cy = size / 2;
  const rOuter = size / 2 - 8;
  const thicknessFrac = opts.thickness || 0.34;
  const strokeW = rOuter * thicknessFrac * 2;
  const rMid = rOuter - strokeW / 2;

  const svg = svgEl('svg', { viewBox: `0 0 ${size} ${size}`, width: '100%', height: h + 'px' });
  const theme = chartTheme();

  let filterId = null;
  if (theme.isDark) {
    filterId = nextGradientId('glow');
    const defs = svgEl('defs', {});
    const filter = svgEl('filter', { id: filterId, x: '-50%', y: '-50%', width: '200%', height: '200%' });
    filter.appendChild(svgEl('feGaussianBlur', { stdDeviation: '3', result: 'blur' }));
    const merge = svgEl('feMerge', {});
    merge.appendChild(svgEl('feMergeNode', { in: 'blur' }));
    merge.appendChild(svgEl('feMergeNode', { in: 'SourceGraphic' }));
    filter.appendChild(merge);
    defs.appendChild(filter);
    svg.appendChild(defs);
  }

  if (total <= 0) {
    svg.appendChild(svgEl('circle', { cx, cy, r: rMid, fill: 'none', stroke: theme.grid, 'stroke-width': strokeW, 'stroke-linecap': 'round' }));
    const t = svgEl('text', { x: cx, y: cy + 4, 'text-anchor': 'middle', 'font-size': 12, fill: theme.faint });
    t.textContent = 'No Data';
    svg.appendChild(t);
  } else {
    const gapRad = segments.filter((s) => s.value > 0).length > 1 ? 0.045 : 0;
    let start = -Math.PI / 2;
    segments.forEach((seg) => {
      if (seg.value <= 0) return;
      const frac = seg.value / total;
      let end = start + frac * 2 * Math.PI;
      if (frac >= 0.9999) end = start + 2 * Math.PI - 0.001;
      const segStart = start + gapRad / 2;
      const segEnd = Math.max(segStart, end - gapRad / 2);
      const x1 = cx + rMid * Math.cos(segStart), y1 = cy + rMid * Math.sin(segStart);
      const x2 = cx + rMid * Math.cos(segEnd), y2 = cy + rMid * Math.sin(segEnd);
      const largeArc = segEnd - segStart > Math.PI ? 1 : 0;
      const path = svgEl('path', {
        d: `M ${x1} ${y1} A ${rMid} ${rMid} 0 ${largeArc} 1 ${x2} ${y2}`,
        fill: 'none', stroke: seg.color, 'stroke-width': strokeW, 'stroke-linecap': 'round'
      });
      if (filterId) path.setAttribute('filter', `url(#${filterId})`);
      const pctLabel = Math.round(frac * 1000) / 10;
      path.appendChild(svgEl('title', {})).textContent = `${seg.label}: ${seg.value} case (${pctLabel}%)`;
      svg.appendChild(path);
      start = end;
    });

    if (centerLabel) {
      const t1 = svgEl('text', { x: cx, y: cy - 3, 'text-anchor': 'middle', 'font-size': 22, 'font-weight': 800, fill: theme.text });
      t1.textContent = centerLabel.value;
      svg.appendChild(t1);
      const t2 = svgEl('text', { x: cx, y: cy + 17, 'text-anchor': 'middle', 'font-size': 10.5, fill: theme.axis });
      t2.textContent = centerLabel.label;
      svg.appendChild(t2);
    }
  }

  clear(container);
  container.appendChild(svg);
}
