(function () {
  "use strict";

  const NS = 'http://www.w3.org/2000/svg';

  // Theme-aware chart chrome colors. Read fresh on every render call (cheap)
  // so charts automatically repaint correctly after a dark/light toggle,
  // without charts.js needing to know anything about the theme system.
  function themeVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return v && v.trim() ? v.trim() : fallback;
  }
  function chartTheme() {
    return {
      grid: themeVar('--grid-line', '#e2e2e5'),
      axis: themeVar('--axis-text', '#6b6b72'),
      text: themeVar('--plot-text', '#17171a'),
      faint: themeVar('--text-faint', '#a3a3aa'),
      isDark: (document.documentElement.getAttribute('data-theme') || 'light') === 'dark'
    };
  }

  function svgEl(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function clear(el) { el.innerHTML = ''; }

  function emptyState(container, msg) {
    clear(container);
    const div = document.createElement('div');
    div.className = 'chart-empty';
    div.textContent = msg || 'No Data';
    container.appendChild(div);
  }

  // Every value shown on a chart carries its unit -- no bare numbers.
  // unit examples: '%', 'h', ' batch', ' batch/day'
  function fmtUnit(v, unit) {
    const n = typeof v === 'number' ? (Number.isInteger(v) ? v : Math.round(v * 100) / 100) : v;
    return unit ? `${n}${unit}` : String(n);
  }

  let gradientSeq = 0;
  function nextGradientId(prefix) { gradientSeq += 1; return `${prefix}-${gradientSeq}-${Date.now() % 100000}`; }

  // Vertical gradient: solid color at top fading toward transparent/lighter
  // at the bottom -- used by bars and area fills so every chart shares the
  // same "gradient gives depth" language as the reference design.
  function addVerticalGradient(svg, color, opts) {
    opts = opts || {};
    const id = nextGradientId('grad');
    const defs = svgEl('defs', {});
    const grad = svgEl('linearGradient', { id, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(svgEl('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': opts.topOpacity != null ? opts.topOpacity : 0.95 }));
    grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': opts.bottomOpacity != null ? opts.bottomOpacity : 0.12 }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    return `url(#${id})`;
  }

  // Rounded-top bar path (rounding only the top two corners so the bar
  // still sits flush on the baseline).
  function roundedTopBarPath(x, y, w, h, r) {
    r = Math.min(r, w / 2, Math.max(h, 0));
    if (h <= 0) return '';
    if (r <= 0) return `M ${x} ${y + h} L ${x} ${y} L ${x + w} ${y} L ${x + w} ${y + h} Z`;
    return `M ${x} ${y + h}
            L ${x} ${y + r}
            Q ${x} ${y} ${x + r} ${y}
            L ${x + w - r} ${y}
            Q ${x + w} ${y} ${x + w} ${y + r}
            L ${x + w} ${y + h}
            Z`;
  }

  // ---------------------------------------------------------------
  // SPARKLINE — minimal trend indicator for KPI/mini-stat cards.
  // No axis, no grid, no labels. Optional gradient area fill and a
  // highlighted dot + value on the last point.
  // values: [n, n, n, ...]  opts: {color, area, unit, showLast}
  // ---------------------------------------------------------------
  function renderSparkline(container, values, opts) {
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
  // BAR CHART — labels/values (single series), gradient fill, rounded tops,
  // unit-aware labels.
  // opts: {color, unit, gradient}
  // ---------------------------------------------------------------
  function renderBar(container, labels, values, opts) {
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

  // ---------------------------------------------------------------
  // GROUPED BAR CHART — datasets: [{label, color, data}], bars placed
  // side-by-side per label (not stacked). Used where comparing several
  // series' magnitude directly matters more than seeing their sum
  // (e.g. several downtime types over time) -- overlapping thin lines are
  // much harder to compare at a glance than bars sitting next to each other.
  // opts: {unit, xFormat}
  // ---------------------------------------------------------------
  function renderGroupedBar(container, labels, datasets, opts) {
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
        if (v === null || v === undefined) return; // no data that group -> leave a gap, don't draw a 0-height bar
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

  // ---------------------------------------------------------------
  // DOUGHNUT / PROGRESS RING — segments: [{label, value, color}]
  // Thick ring, rounded segment caps, glow in dark mode, big center number.
  // opts: {thickness: 0..1 (fraction of radius), glow}
  // ---------------------------------------------------------------
  function renderDoughnut(container, segments, centerLabel, opts) {
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

  // ---------------------------------------------------------------
  // LINE CHART — datasets: [{label, data, color, width, opacity}]
  // opts.xFormat: 'date' (default, slices YYYY-MM-DD -> MM-DD) | 'category'
  // opts.showValues: draw the value above each point (single-dataset use only)
  // opts.area: gradient fill under the line (single-dataset use only)
  // opts.unit: appended to every axis tick / point value label
  // A `null`/`undefined` entry in ds.data means "no data that point" -- the
  // line breaks there (gap) instead of dropping to 0, and no dot/label is
  // drawn for it. Per-dataset `width`/`opacity` let a caller draw one bold
  // "highlighted" line alongside several thinner "muted" ones in the same
  // chart (e.g. a Total line + a few contributing-factor lines).
  // ---------------------------------------------------------------
  function renderLine(container, labels, datasets, opts) {
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

  // ---------------------------------------------------------------
  // LEGEND — items: [{label, color}]
  // ---------------------------------------------------------------
  function renderLegend(container, items) {
    clear(container);
    items.forEach((it) => {
      const span = document.createElement('span');
      span.className = 'legend-item';
      const dot = document.createElement('span');
      dot.className = 'legend-dot';
      dot.style.background = it.color;
      span.appendChild(dot);
      span.appendChild(document.createTextNode(it.label));
      container.appendChild(span);
    });
  }

  // ---------------------------------------------------------------
  // STACKED BAR CHART — datasets: [{label, color, data}], one bar per label,
  // segments stacked in dataset order. Used for Root Cause breakdown.
  // opts.unit appended to every value label / axis tick.
  // ---------------------------------------------------------------
  function renderStackedBar(container, labels, datasets, opts) {
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
          // Optional in-segment label (e.g. "27%") when the segment is
          // tall enough to hold text legibly -- ds.dataLabels[i], opt-in
          // per dataset so existing callers without it are unaffected.
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
      const rawLabel = opts.xFormat === 'date'
        ? (lab.length >= 5 ? lab.slice(5) : lab)
        : lab;
      lt.textContent = rawLabel.length > 12 ? rawLabel.slice(0, 11) + '…' : rawLabel;
      svg.appendChild(lt);
    });

    clear(container);
    container.appendChild(svg);
  }

  // ---------------------------------------------------------------
  // STANDARD ACHIEVEMENT 100%-STACKED BAR (spec 12.2) — Y axis fixed at
  // 0-100%, every bar sums to exactly 100% of that period's cases (never
  // a case/day rate). datasets: [{key,label,color,counts:[],pct:[]}].
  // opts.selected: {period, key} -> that segment stays full opacity, every
  // other segment in the whole chart dims (spec 13's "click a segment ->
  // highlight it, dim the rest"). Native <title> tooltips carry period +
  // level + count + pct per segment (spec 12.2's tooltip requirement).
  // ---------------------------------------------------------------
  function renderStandardAchievementBar(container, labels, datasets, opts) {
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

  // ---------------------------------------------------------------
  // STACKED BAR + TREND LINE COMBO — merges the Standard Achievement
  // "100% stacked bar" and the separate "Average Downtime Duration" line
  // chart into ONE chart: bar height now reflects the REAL case count per
  // period (not forced to 100%), so the bars themselves show the case-
  // count trend across periods; the avg-duration line is drawn on top
  // using its own right-hand axis (different unit/scale, per spec never
  // merge the axes).
  // barDatasets: [{key,label,color,counts:[...]}] (severity tiers, stacked)
  // lineData: {label, data:[...], unit} (avg h/case, same `labels` length)
  // ---------------------------------------------------------------
  function renderStackedTrendCombo(container, labels, barDatasets, lineData, opts) {
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

    // left axis (case count)
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const val = Math.round((maxCount * i) / steps);
      const y = pad.top + plotH - (val / maxCount) * plotH;
      svg.appendChild(svgEl('line', { x1: pad.left, x2: w - pad.right, y1: y, y2: y, stroke: theme.grid, 'stroke-width': 1 }));
      const t = svgEl('text', { x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9.5, fill: theme.axis });
      t.textContent = val;
      svg.appendChild(t);
    }
    // right axis (h/case)
    for (let i = 0; i <= steps; i++) {
      const val = (maxLine * i) / steps;
      const y = pad.top + plotH - (val / maxLine) * plotH;
      const t = svgEl('text', { x: w - pad.right + 6, y: y + 3, 'text-anchor': 'start', 'font-size': 9.5, fill: theme.axis });
      t.textContent = val.toFixed(1) + 'h';
      svg.appendChild(t);
    }

    // stacked bars (real height = case count, not normalized to 100%)
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

    // trend line (avg h/case) on the secondary axis, drawn on top of the bars
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

  window.MiniCharts = {
    renderBar, renderDoughnut, renderLine, renderStackedBar, renderGroupedBar,
    renderSparkline, renderStandardAchievementBar, renderStackedTrendCombo, renderLegend
  };
})();
