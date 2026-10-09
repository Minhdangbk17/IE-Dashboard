/**
 * CORE/CHARTS/INDEX.JS — Gom toan bo module chart lai 1 cho.
 *
 * Xuat ca 2 kieu:
 *   1. ES module named export — dung cho feature moi (giai doan 3).
 *   2. window.MiniCharts — GIU NGUYEN de dashboard.js CU (chua migrate)
 *      tiep tuc chay dung khong doi mot dong nao, cho den khi no duoc
 *      thay the hoan toan boi cac feature moi.
 *
 * Import file nay 1 lan (vd trong index.html) la du cho ca 2 the gioi
 * cung ton tai song song trong giai doan chuyen tiếp.
 */

import { renderSparkline, renderLine } from './line.js';
import { renderBar, renderGroupedBar } from './bar.js';
import { renderDoughnut } from './doughnut.js';
import { renderStackedBar, renderStandardAchievementBar, renderStackedTrendCombo } from './stacked.js';
import { renderLegend } from './legend.js';

export {
  renderSparkline, renderLine, renderBar, renderGroupedBar, renderDoughnut,
  renderStackedBar, renderStandardAchievementBar, renderStackedTrendCombo,
  renderLegend,
};

if (typeof window !== 'undefined') {
  window.MiniCharts = {
    renderBar, renderDoughnut, renderLine, renderStackedBar, renderGroupedBar,
    renderSparkline, renderStandardAchievementBar, renderStackedTrendCombo, renderLegend
  };
}
