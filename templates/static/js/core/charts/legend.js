/**
 * CORE/CHARTS/LEGEND.JS — renderLegend. Tach nguyen ven tu charts.js.
 */

export function renderLegend(container, items) {
  container.innerHTML = '';
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
