/**
 * CORE/CHARTS/PRIMITIVES.JS — svgEl, clear, emptyState, chartTheme,
 * gradient, rounded-bar-path. Tach nguyen ven tu dau charts.js. Hanh vi
 * giu NGUYEN 100%.
 */

import { themeVar } from '../format.js';

const NS = 'http://www.w3.org/2000/svg';

export function chartTheme() {
  return {
    grid: themeVar('--grid-line', '#e2e2e5'),
    axis: themeVar('--axis-text', '#6b6b72'),
    text: themeVar('--plot-text', '#17171a'),
    faint: themeVar('--text-faint', '#a3a3aa'),
    isDark: (document.documentElement.getAttribute('data-theme') || 'light') === 'dark'
  };
}

export function svgEl(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

export function clear(el) { el.innerHTML = ''; }

export function emptyState(container, msg) {
  clear(container);
  const div = document.createElement('div');
  div.className = 'chart-empty';
  div.textContent = msg || 'No Data';
  container.appendChild(div);
}

let gradientSeq = 0;
export function nextGradientId(prefix) { gradientSeq += 1; return `${prefix}-${gradientSeq}-${Date.now() % 100000}`; }

// Vertical gradient: solid color at top fading toward transparent/lighter
// at the bottom -- used by bars and area fills so every chart shares the
// same "gradient gives depth" language as the reference design.
export function addVerticalGradient(svg, color, opts) {
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
export function roundedTopBarPath(x, y, w, h, r) {
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
