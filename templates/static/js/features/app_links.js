/**
 * STATIC/JS/FEATURES/APP_LINKS.JS — Feature dau tien cua giai doan 3,
 * lam mau hinh dang cho 11 feature con lai.
 */

import { getJSON, postJSON, ApiError } from '../core/api.js';
import { registerFeature } from '../core/registry.js';
import { showToast, showApiError, withOverlay } from '../core/ui.js';

const API = '/api/dyeing/app-links';

function render(root, links) {
  const list = root.querySelector('[data-app-links-list]');
  list.innerHTML = '';
  links.forEach((link) => {
    const row = document.createElement('div');
    row.className = 'app-links-row';
    row.innerHTML = `
      <span class="app-links-label">${link.label}</span>
      <input type="url" class="app-links-url" value="${link.url}" data-key="${link.link_key}">
      <button type="button" class="app-links-save">Lưu</button>
    `;
    row.querySelector('.app-links-save').addEventListener('click', async () => {
      const url = row.querySelector('.app-links-url').value.trim();
      try {
        await withOverlay(
          () => postJSON(API, { link_key: link.link_key, url }),
          'Đang lưu...'
        );
        showToast('Đã lưu liên kết.', { type: 'success' });
      } catch (err) {
        // withOverlay đã tự showApiError, không cần lặp lại ở đây.
      }
    });
    list.appendChild(row);
  });
}

registerFeature({
  id: 'app_links',
  panel: 'panel-app-links',
  init(root) {
    if (!root) return;
  },
  async refresh(_filters, _ctx) {
    const root = document.getElementById('panel-app-links');
    if (!root) return;
    try {
      const links = await getJSON(API);
      render(root, links);
    } catch (err) {
      showApiError(err);
    }
  },
});
