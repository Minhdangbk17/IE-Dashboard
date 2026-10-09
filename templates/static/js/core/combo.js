/**
 * CORE/COMBO.JS — Multiselect combo dung chung, tach nguyen ven tu
 * dashboard.js (ham setupCombo). Hanh vi giu NGUYEN 100% — day la ham
 * DA CHAY DUNG trong production, chi doi cach goi thanh ES module.
 */

export function setupCombo(cfg) {
  // cfg: {triggerId, panelId, listId, searchId, selectedSet, allLabel, options: () => [{value,label}]}
  const el = (id) => document.getElementById(id);
  const trigger = el(cfg.triggerId);
  const panel = el(cfg.panelId);
  const list = el(cfg.listId);
  let options = [];

  function renderList(filterText) {
    list.innerHTML = '';
    const ft = (filterText || '').toLowerCase();
    options.filter((o) => !ft || o.label.toLowerCase().includes(ft)).forEach((o) => {
      const label = document.createElement('label');
      const checked = cfg.selectedSet.has(o.value);
      label.innerHTML = `<input type="checkbox" ${checked ? 'checked' : ''}> ${o.label}`;
      label.querySelector('input').addEventListener('change', (e) => {
        if (e.target.checked) cfg.selectedSet.add(o.value); else cfg.selectedSet.delete(o.value);
        updateTriggerLabel();
      });
      list.appendChild(label);
    });
  }

  function updateTriggerLabel() {
    const n = cfg.selectedSet.size;
    if (n === 0) trigger.textContent = cfg.allLabel;
    else if (n === 1) trigger.textContent = String(Array.from(cfg.selectedSet)[0]);
    else trigger.textContent = `${n} selected`;
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const willOpen = panel.classList.contains('hidden');
    document.querySelectorAll('.multiselect-panel').forEach((p) => p.classList.add('hidden'));
    if (willOpen) { panel.classList.remove('hidden'); renderList(''); }
  });
  document.addEventListener('click', (e) => {
    if (!panel.contains(e.target) && e.target !== trigger) panel.classList.add('hidden');
  });

  if (cfg.searchId) {
    el(cfg.searchId).addEventListener('input', (e) => renderList(e.target.value));
  }
  panel.querySelector('[data-combo-action="select-all"]').addEventListener('click', () => {
    options.forEach((o) => cfg.selectedSet.add(o.value));
    updateTriggerLabel();
    renderList(cfg.searchId ? el(cfg.searchId).value : '');
  });
  panel.querySelector('[data-combo-action="clear"]').addEventListener('click', () => {
    cfg.selectedSet.clear();
    updateTriggerLabel();
    renderList(cfg.searchId ? el(cfg.searchId).value : '');
  });

  return {
    setOptions(opts) { options = opts; renderList(''); updateTriggerLabel(); }
  };
}
