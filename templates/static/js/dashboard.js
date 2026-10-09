(function () {
  "use strict";

  const el = (id) => document.getElementById(id);

  function themeVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return v && v.trim() ? v.trim() : fallback;
  }
  function palette() {
    return [
      themeVar('--chart-1', '#2952e3'), themeVar('--chart-2', '#157a3d'),
      themeVar('--chart-3', '#b3690a'), themeVar('--chart-4', '#c8291f'),
      themeVar('--chart-5', '#7c3aed'), themeVar('--chart-6', '#49c6e5'),
      themeVar('--chart-7', '#a3821a'), themeVar('--chart-8', '#946b8f')
    ];
  }
  function fabricColors() {
    return {
      Cotton: themeVar('--fabric-cotton', '#2952e3'),
      CVC: themeVar('--fabric-cvc', '#b3690a'),
      Polyester: themeVar('--fabric-polyester', '#157a3d')
    };
  }

  // -------------------------------------------------------------
  // GLOBAL STATE
  // -------------------------------------------------------------
  const state = {
    filters: { machines: new Set(), capacities: new Set(), fabrics: new Set() },
    mainTab: 'productivity',
    productivityLayer: 'dashboard',
    activeKpi: 'batch',          // which KPI's trend is showing in layer 2
    batchGranularity: 'day',
    tankGranularity: 'day',
    downtimeGranularity: 'day',
    detailGranularity: 'day',
    selectedTypes: new Set(['dt_load', 'dt_unload', 'dt_wait_chemical', 'dt_wait_color', 'dt_sample_checking', 'dt_ph_checking']),
    typeLabels: {},
    selectedStandardType: null,
    standardData: [],
    standardGranularity: {},     // per type: {granularity}
    rootCauseGranularity: {},    // per type: {granularity} -- Root Cause's own Day/Week/Month
    rootCause: { key: null, label: null },
    appLinks: {},               // link_key -> url (RFT / RFT Core Color OneDrive)
    loading: false
  };

  // -------------------------------------------------------------
  // BASIC HELPERS
  // -------------------------------------------------------------
  function showOverlay() { el('globalOverlay').classList.add('show'); }
  function hideOverlay() { el('globalOverlay').classList.remove('show'); }

  function showToast(message, isError) {
    const stack = el('toastStack');
    const t = document.createElement('div');
    t.className = 'toast' + (isError ? ' error' : '');
    t.textContent = message;
    stack.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.message || `Request Failed (${res.status})`);
    }
    return res.json();
  }

  async function postJSON(url, body) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({ ok: false, message: 'Invalid Server Response.' }));
    if (!res.ok || data.ok === false) throw new Error(data.message || `Request Failed (${res.status})`);
    return data;
  }

  async function safeRefresh(label, fn) {
    try { await fn(); } catch (e) { console.error(label, e); showToast(`${label}: ${e.message}`, true); }
  }
  async function safeRefreshChart(label, fn, containerId) {
    try { await fn(); } catch (e) {
      console.error(label, e);
      const c = el(containerId);
      if (c) c.innerHTML = `<div class="chart-empty">${label} Failed To Load</div>`;
    }
  }

  function initDates() {
    const today = new Date();
    const from = new Date(today); from.setDate(from.getDate() - 29);
    el('dateTo').value = today.toISOString().slice(0, 10);
    el('dateFrom').value = from.toISOString().slice(0, 10);
  }

  function getFilterParams() {
    const p = new URLSearchParams();
    p.set('date_from', el('dateFrom').value);
    p.set('date_to', el('dateTo').value);
    if (state.filters.machines.size > 0) p.set('machines', Array.from(state.filters.machines).join(','));
    if (state.filters.capacities.size > 0) p.set('capacities', Array.from(state.filters.capacities).join(','));
    if (state.filters.fabrics.size > 0) p.set('fabrics', Array.from(state.filters.fabrics).join(','));
    return p;
  }

  function fmtVal(v, unit) {
    if (v === null || v === undefined) return '—';
    const n = typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : v;
    return unit ? `${n}${unit}` : String(n);
  }

  // -------------------------------------------------------------
  // GENERIC SEARCHABLE MULTI-SELECT COMBOBOX (spec section 4)
  // Machine / Capacity / Fabric Type all share this exact pattern:
  // closed state shows "All X" / one value / "N selected"; open state has
  // a search box (when `searchable`), Select All, Clear, a scrollable
  // checkbox list. No API call on tick -- only Apply Filters re-fetches.
  // -------------------------------------------------------------
  function setupCombo(cfg) {
    // cfg: {triggerId, panelId, listId, searchId, selectedSet, allLabel, options: () => [{value,label}]}
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

  let machineCombo, capacityCombo, fabricCombo;

  function bindCombos() {
    machineCombo = setupCombo({
      triggerId: 'machineComboTrigger', panelId: 'machineComboPanel', listId: 'machineOptionsList',
      searchId: 'machineSearch', selectedSet: state.filters.machines, allLabel: 'All Machines'
    });
    capacityCombo = setupCombo({
      triggerId: 'capacityComboTrigger', panelId: 'capacityComboPanel', listId: 'capacityOptionsList',
      searchId: 'capacitySearch', selectedSet: state.filters.capacities, allLabel: 'All Capacities'
    });
    fabricCombo = setupCombo({
      triggerId: 'fabricComboTrigger', panelId: 'fabricComboPanel', listId: 'fabricOptionsList',
      selectedSet: state.filters.fabrics, allLabel: 'All Fabric Types'
    });
  }

  async function loadFilterOptions() {
    const [machines, capacities, fabrics] = await Promise.all([
      getJSON('/api/machines'), getJSON('/api/capacities'), getJSON('/api/fabric-types')
    ]);
    machineCombo.setOptions(machines.map((m) => ({ value: m, label: m })));
    capacityCombo.setOptions(capacities.map((c) => ({ value: String(c), label: String(c) })));
    fabricCombo.setOptions(fabrics.map((f) => ({ value: f, label: f })));
  }

  // -------------------------------------------------------------
  // PRODUCTIVITY — 4-LAYER NAVIGATION (Dashboard KPI -> KPI Trend ->
  // Detail Downtime -> Root Cause), full-viewport layers, breadcrumb
  // doubles as back-navigation.
  // -------------------------------------------------------------
  const LAYERS = ['dashboard', 'trend', 'detail', 'rootcause'];

  function goToLayer(name, opts) {
    opts = opts || {};
    if (!LAYERS.includes(name)) return;
    state.productivityLayer = name;
    const idx = LAYERS.indexOf(name);

    document.querySelectorAll('#layersViewport > .layer').forEach((sec) => {
      sec.classList.toggle('is-active', sec.dataset.layer === name);
    });
    el('productivityNav').querySelectorAll('.breadcrumb-step').forEach((btn) => {
      const bIdx = LAYERS.indexOf(btn.dataset.layer);
      btn.classList.toggle('is-active', btn.dataset.layer === name);
      btn.classList.toggle('is-done', bIdx < idx);
    });

    triggerFlyIn(name);
    if (!opts.skipRefresh) {
      if (name === 'dashboard') { safeRefresh('Dashboard KPI', refreshDashboardKpis); safeRefresh('RFT Tab', refreshRftTab); }
      if (name === 'trend') showTrendSection(state.activeKpi);
      if (name === 'detail') safeRefresh('Detail Downtime', refreshDetailLayer);
      // rootcause is populated explicitly by openRootCause(), not on generic entry
    }
  }

  function triggerFlyIn(name) {
    const layer = el('layer-' + name);
    if (!layer) return;
    const items = layer.querySelectorAll('.panel, .kpi-card, .root-cause-block, .analysis-card');
    items.forEach((node, i) => {
      node.classList.remove('fly-in');
      void node.offsetWidth;
      node.style.animationDelay = (i * 0.05) + 's';
      node.classList.add('fly-in');
    });
  }

  function bindProductivityNav() {
    el('productivityNav').querySelectorAll('button[data-layer]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.dataset.layer === 'rootcause' && !state.rootCause.key) {
          showToast('Chọn 1 Segment Ở Standard Achievement Trước.', true);
          return;
        }
        goToLayer(btn.dataset.layer);
      });
    });
    document.querySelectorAll('.kpi-card[data-kpi]').forEach((card) => {
      card.addEventListener('click', () => {
        state.activeKpi = card.dataset.kpi;
        goToLayer('trend');
      });
    });
    el('goDetailDowntimeBtn').addEventListener('click', () => goToLayer('detail'));
    el('rootCauseBackBtn').addEventListener('click', () => goToLayer('detail'));
  }

  // -------------------------------------------------------------
  // LAYER 1 — DASHBOARD KPI (3 boxes)
  // -------------------------------------------------------------
  function applyTrendBadge(elId, trendPct, higherIsBad) {
    const node = el(elId);
    if (!node) return;
    if (trendPct === undefined || trendPct === null || trendPct === 0) {
      node.className = 'trend-badge flat'; node.innerHTML = '0%'; return;
    }
    const isUp = trendPct > 0;
    const bad = higherIsBad ? isUp : !isUp;
    const cls = (isUp ? 'up-' : 'down-') + (bad ? 'bad' : 'good');
    node.className = 'trend-badge ' + cls;
    node.innerHTML = `${isUp ? '&#9650;' : '&#9660;'} ${Math.abs(trendPct)}%`;
  }

  function fillFabricBreakdown(prefix, fabrics, unit) {
    ['Cotton', 'CVC', 'Polyester'].forEach((f) => {
      const node = el(`${prefix}-${f}`);
      if (node) node.textContent = fmtVal(fabrics ? fabrics[f] : null, unit);
    });
  }

  async function refreshDashboardKpis() {
    const params = getFilterParams();
    const kpis = await getJSON(
      '/api/productivity/kpis?' + params.toString()
    );

    const rangeText = `${kpis.date_from} &rarr; ${kpis.date_to}`;

    el('kpiBatchRange').innerHTML = rangeText;
    el('kpiTankRange').innerHTML = rangeText;

    const renderComparison = (id, fabrics, hideUnit = false) => {
      el(id).innerHTML = ['Cotton', 'CVC', 'Polyester']
        .map((f) => {
          const d = fabrics[f] || {};

          const baseline =
            d.previous_target != null
              ? d.previous_target
              : d.previous;

          const unit = hideUnit ? '' : d.unit;

          return `
            <div class="flex items-center gap-2"
                style="font-size:13pxpx;min-height:28px;">

              <span class="dot"
                    style="background:${fabricColors()[f]}">
              </span>

              <strong style="min-width:62px;">
                ${f}
              </strong>

              <span class="num" style="white-space:nowrap;">
                ${fmtVal(baseline, unit)}
                &rarr;
                ${fmtVal(d.current, unit)}
              </span>

              <span class="hint"
                    style="margin-left:auto;white-space:nowrap;">
                Target ${d.target_year}:
                <strong>${fmtVal(d.target, unit)}</strong>
              </span>
            </div>
          `;
        })
        .join('');
    };

    // true: ẩn chữ “batch/day”
    renderComparison(
      'kpiBatchComparison',
      kpis.batch_per_day.fabrics,
      true
    );

    // false: vẫn giữ đơn vị %
    renderComparison(
      'kpiTankComparison',
      kpis.tank_loading.fabrics,
      false
    );

    el('kpiDowntimeValue').textContent =
      fmtVal(kpis.downtime_pct.current);

    applyTrendBadge(
      'kpiDowntimeTrend',
      kpis.downtime_pct.trend_pct,
      true
    );

    el('kpiDowntimeRange').innerHTML = rangeText;
  }
  async function refreshEngineeringOptions() { return Promise.resolve(); }

  async function refreshEngineering() {
    const selectedDate = el('dateTo').value || new Date().toISOString().slice(0,10);
    const year = Number(selectedDate.slice(0,4));
    const p = new URLSearchParams({year,summary:'fabric'});
    const rows=await getJSON('/api/engineering-development?'+p.toString());
    el('engineeringRangeText').textContent=`Average of all Shade/Program rows · Target ${year}`;
    el('engineeringComparison').innerHTML=rows.map(r=>`<div class="flex items-center gap-2" style="font-size:13px;min-height:28px;"><span class="dot" style="background:${fabricColors()[r.fabric_type]}"></span><strong style="min-width:62px;">${r.fabric_type}</strong><span class="num" style="white-space:nowrap;">${fmtVal(r.before_pth)} &rarr; ${fmtVal(r.current_pth)} PTH</span><span class="hint" style="margin-left:auto;white-space:nowrap;">Target ${year}: <strong>${fmtVal(r.target_pth)} PTH</strong></span></div>`).join('');
  }

  function bindEngineeringFilters() {}

  // -------------------------------------------------------------
  // LAYER 2 — KPI TREND (only the clicked KPI's section shows; spec
  // section 7-9: never show two trend charts at once)
  // -------------------------------------------------------------
  function showTrendSection(kpi) {
    ['batch', 'tank', 'downtime'].forEach((k) => {
      el(`trendSection${k[0].toUpperCase()}${k.slice(1)}`).classList.toggle('hidden', k !== kpi);
    });
    if (kpi === 'batch') safeRefreshChart('Batch/Day Trend', refreshBatchTrend, 'batchTrendChart');
    if (kpi === 'tank') safeRefreshChart('%Tank Loading Trend', refreshTankTrend, 'tankTrendChart');
    if (kpi === 'downtime') safeRefreshChart('%Downtime Trend', refreshDowntimeTrend, 'downtimeTrendChart');
  }

  function bindTrendGranularity(groupId, stateKey, refreshFn) {
    el(groupId).querySelectorAll('button[data-g]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (state.loading || state[stateKey] === btn.dataset.g) return;
        state[stateKey] = btn.dataset.g;
        el(groupId).querySelectorAll('button').forEach((b) => b.classList.remove('selected'));
        btn.classList.add('selected');
        safeRefresh('Trend', refreshFn);
      });
    });
  }

  // Total (bold) + Cotton/CVC/Polyester (muted) -- shared rendering shape
  // for Batch/Day and %Downtime (both already return {labels,total,fabrics}).
  function totalPlusFabricDatasets(payload) {
    const fColors = fabricColors();
    const totalDs = { label: payload.total.label, data: payload.total.data, color: themeVar('--primary', '#2952e3'), width: 3, opacity: 1 };
    const fabricDs = payload.fabrics.map((f) => ({
      label: f.label, data: f.data, color: fColors[f.key] || themeVar('--chart-2', '#157a3d'), width: 1.5, opacity: 0.55
    }));
    return [totalDs, ...fabricDs];
  }

  async function refreshBatchTrend() {
    const params = getFilterParams();
    params.set('granularity', state.batchGranularity);
    const data = await getJSON('/api/productivity/batch-day-trend?' + params.toString());
    const datasets = totalPlusFabricDatasets(data);
    MiniCharts.renderLine(el('batchTrendChart'), data.labels, datasets, {
      xFormat: 'date', unit: ' batch',
      onPointClick: (i, v, label) => openAvailabilityDetail(label)
    });
    MiniCharts.renderLegend(el('batchTrendLegend'), datasets.map((d) => ({ label: d.label, color: d.color })));
  }

  async function refreshTankTrend() {
    const params = getFilterParams();
    params.set('granularity', state.tankGranularity);
    const data = await getJSON('/api/productivity/tank-loading-trend?' + params.toString());
    const datasets = totalPlusFabricDatasets(data);
    MiniCharts.renderLine(el('tankTrendChart'), data.labels, datasets, {
      xFormat: 'date', unit: '%',
      onPointClick: (i, v, label) => openTankLoadingDetail(label)
    });
    MiniCharts.renderLegend(el('tankTrendLegend'), datasets.map((d) => ({ label: d.label, color: d.color })));
  }

  async function refreshDowntimeTrend() {
    const params = getFilterParams();
    params.set('granularity', state.downtimeGranularity);
    const data = await getJSON('/api/productivity/downtime-pct-trend?' + params.toString());
    const datasets = totalPlusFabricDatasets(data).slice(0, 1);
    MiniCharts.renderLine(el('downtimeTrendChart'), data.labels, datasets, { xFormat: 'date', unit: '%' });
    MiniCharts.renderLegend(el('downtimeTrendLegend'), datasets.map((d) => ({ label: d.label, color: d.color })));
  }

  // -------------------------------------------------------------
  // TANK LOADING DETAIL DRAWER (Performance-sourced -- spec: bam vao
  // %Tank Loading Trend se show bang Performance)
  // -------------------------------------------------------------
  async function openTankLoadingDetail(periodLabel) {
    const params = getFilterParams();
    params.set('granularity', state.tankGranularity);
    if (periodLabel) params.set('period', periodLabel);
    showOverlay();
    try {
      const rows = await getJSON('/api/productivity/batch-details?' + params.toString());
      el('batchDetailTitle').textContent = periodLabel ? `Tank Loading Detail — ${periodLabel}` : 'Tank Loading Detail — Whole Range';
      const tbody = el('batchDetailTable').querySelector('tbody');
      tbody.innerHTML = rows.length ? rows.map((r) => `
        <tr>
          <td>${r.dyelot}</td><td>${r.machine}</td><td>${r.fabric_type}</td><td class="num">${fmtVal(r.capacity)}</td>
          <td>${r.start_time || '—'}</td><td>${r.end_time}</td>
          <td class="num">${fmtVal(r.output_kg)}</td><td class="num">${fmtVal(r.tank_loading_pct, '%')}</td>
        </tr>`).join('') : `<tr><td colspan="8" class="empty-row">No Batches</td></tr>`;
      el('batchDetailOverlay').classList.add('show');
    } finally {
      hideOverlay();
    }
  }

  function bindBatchDetailDrawer() {
    el('batchDetailClose').addEventListener('click', () => el('batchDetailOverlay').classList.remove('show'));
    el('batchDetailOverlay').addEventListener('click', (e) => { if (e.target.id === 'batchDetailOverlay') el('batchDetailOverlay').classList.remove('show'); });
  }

  // -------------------------------------------------------------
  // BATCH/DAY DETAIL DRAWER (Availability-sourced -- spec: bam vao
  // Batch/Day Trend se show bang Availability, cung nguon voi cong thuc
  // Batch/Day dang dung, thay vi Performance nhu truoc)
  // -------------------------------------------------------------
  async function openAvailabilityDetail(periodLabel) {
    const params = getFilterParams();
    params.set('granularity', state.batchGranularity);
    if (periodLabel) params.set('period', periodLabel);
    showOverlay();
    try {
      const rows = await getJSON('/api/productivity/availability-details?' + params.toString());
      el('availabilityDetailTitle').textContent = periodLabel ? `Batch/Day Detail — ${periodLabel}` : 'Batch/Day Detail — Whole Range';
      const tbody = el('availabilityDetailTable').querySelector('tbody');
      tbody.innerHTML = rows.length ? rows.map((r) => `
        <tr>
          <td>${r.batch}</td><td>${r.batch_ref_no || '—'}</td><td>${r.machine}</td><td>${r.fabric_type}</td>
          <td class="num">${fmtVal(r.capacity)}</td><td>${r.program || '—'}</td>
          <td>${r.start_time || '—'}</td><td>${r.end_time}</td>
          <td class="num">${fmtVal(r.availability_pct, '%')}</td><td class="num">${fmtVal(r.planned_prd_time)}</td>
          <td class="num">${fmtVal(r.running_time)}</td><td class="num">${fmtVal(r.total_downtime)}</td>
        </tr>`).join('') : `<tr><td colspan="12" class="empty-row">No Records</td></tr>`;
      el('availabilityDetailOverlay').classList.add('show');
    } finally {
      hideOverlay();
    }
  }

  function bindAvailabilityDetailDrawer() {
    el('availabilityDetailClose').addEventListener('click', () => el('availabilityDetailOverlay').classList.remove('show'));
    el('availabilityDetailOverlay').addEventListener('click', (e) => { if (e.target.id === 'availabilityDetailOverlay') el('availabilityDetailOverlay').classList.remove('show'); });
  }

  // -------------------------------------------------------------
  // LAYER 3a — DETAIL DOWNTIME TREND (multi-select type checkboxes,
  // never hardcoded to a fixed 3 -- spec section 9)
  // -------------------------------------------------------------
  function bindTypeChipsToggle() {
    el('typeFilterToggleBtn').addEventListener('click', () => el('typeChipsPanel').classList.toggle('hidden'));
  }

  async function loadTypeChips() {
    const types = await getJSON('/api/downtime-types');
    types.forEach((t) => { state.typeLabels[t.key] = t.label; });
    const wrap = el('typeChipsPanel');
    wrap.innerHTML = '';
    types.forEach((t) => {
      const label = document.createElement('label');
      label.className = 'chip-check' + (state.selectedTypes.has(t.key) ? ' selected' : '');
      label.innerHTML = `<input type="checkbox" ${state.selectedTypes.has(t.key) ? 'checked' : ''}> ${t.label}`;
      label.addEventListener('click', (e) => {
        e.preventDefault();
        if (state.loading) return;
        if (state.selectedTypes.has(t.key)) { state.selectedTypes.delete(t.key); label.classList.remove('selected'); }
        else { state.selectedTypes.add(t.key); label.classList.add('selected'); }
        label.querySelector('input').checked = state.selectedTypes.has(t.key);
        safeRefresh('Detail Downtime Trend', refreshDetailDowntimeTrend);
      });
      wrap.appendChild(label);
    });
  }

  function bindDetailGranularity() {
    el('detailDowntimeGranularity').querySelectorAll('button[data-g]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (state.loading || state.detailGranularity === btn.dataset.g) return;
        state.detailGranularity = btn.dataset.g;
        el('detailDowntimeGranularity').querySelectorAll('button').forEach((b) => b.classList.remove('selected'));
        btn.classList.add('selected');
        safeRefresh('Detail Downtime Trend', refreshDetailDowntimeTrend);
      });
    });
  }

  async function refreshDetailDowntimeTrend() {
    const params = getFilterParams();
    if (state.selectedTypes.size > 0) params.set('types', Array.from(state.selectedTypes).join(','));
    params.set('granularity', state.detailGranularity);
    const data = await getJSON('/api/productivity/detail-downtime-trend?' + params.toString());
    el('detailDowntimeCount').textContent = state.selectedTypes.size > 0 ? `(Selected ${data.datasets.length})` : '(Top 3)';
    const p = palette();
    const datasets = data.datasets.map((ds, i) => ({ label: ds.label, data: ds.data, color: p[i % p.length] }));
    MiniCharts.renderLine(el('detailDowntimeChart'), data.labels, datasets, { xFormat: 'date', unit: 'h' });
    MiniCharts.renderLegend(el('detailDowntimeLegend'), datasets.map((d) => ({ label: d.label, color: d.color })));
  }

  // -------------------------------------------------------------
  // LAYER 3b — STANDARD ACHIEVEMENT (spec section 12) — master list of
  // downtime types (reusing /api/compliance-by-type) + 3 independent
  // views (pie / 100%-stacked / duration trend) for the selected type.
  // -------------------------------------------------------------
  function getStdGranularity(key) {
    if (!state.standardGranularity[key]) state.standardGranularity[key] = 'day';
    return state.standardGranularity[key];
  }

  async function refreshDetailLayer() {
    await Promise.all([
      safeRefreshChart('Detail Downtime Trend', refreshDetailDowntimeTrend, 'detailDowntimeChart'),
      safeRefresh('Standard Achievement List', refreshStandardList)
    ]);
  }

  async function refreshStandardList() {
    const params = getFilterParams();
    if (state.selectedTypes.size > 0) params.set('types', Array.from(state.selectedTypes).join(','));
    const complianceData = await getJSON('/api/compliance-by-type?' + params.toString());
    state.standardData = complianceData;

    const list = el('standardTypeList');
    list.innerHTML = '';
    if (complianceData.length === 0) {
      el('standardTypeDetail').innerHTML = `<div class="empty-state">No Downtime Types Selected</div>`;
      state.selectedStandardType = null;
      return;
    }
    complianceData.forEach((d) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'rail-item' + (d.key === state.selectedStandardType ? ' is-active' : '');
      const badge = d.has_standard ? `<span class="rail-badge">${d.fail_count}/${d.total} Not Achieved</span>` : `<span class="rail-badge hint">No Standard</span>`;
      item.innerHTML = `<span class="rail-meta"><span class="rail-dot" style="background:${d.has_standard && d.fail_count > 0 ? 'var(--danger)' : 'var(--success)'}"></span>${d.label}</span>${badge}`;
      item.addEventListener('click', () => {
        if (state.selectedStandardType === d.key) return;
        state.selectedStandardType = d.key;
        list.querySelectorAll('.rail-item').forEach((n) => n.classList.toggle('is-active', n === item));
        renderStandardDetail(d.key);
      });
      list.appendChild(item);
    });

    const stillPresent = complianceData.some((d) => d.key === state.selectedStandardType);
    if (!stillPresent) state.selectedStandardType = complianceData[0].key;
    renderStandardDetail(state.selectedStandardType);
  }

  function renderStandardDetail(key) {
    const d = state.standardData.find((x) => x.key === key);
    const container = el('standardTypeDetail');
    if (!d) { container.innerHTML = `<div class="empty-state">No Data</div>`; return; }
    if (!d.has_standard) {
      container.innerHTML = `<div class="analysis-card fly-in"><div class="card-head"><div class="card-title">${d.label}</div></div><div class="card-empty">No Standard Set</div></div>`;
      return;
    }
    const g = getStdGranularity(key);
    container.innerHTML = `
      <div class="analysis-card fly-in">
        <div class="card-head"><div class="card-title">${d.label} — STANDARD ACHIEVEMENT</div></div>
        <div class="card-body">
          <div>
            <div class="hint mb-1">Achieved vs Not Achieved</div>
            <div class="card-chart" data-role="sa-pie"></div>
            <div class="card-total" data-role="sa-pie-total"></div>
          </div>
          <div>
            <div class="hint mb-1">Average Downtime Duration (min/case) — Achieved vs Not Achieved</div>
            <div class="rc-controls" data-role="sa-granularity">
              <button type="button" class="chip ${g === 'day' ? 'selected' : ''}" data-g="day">Day</button>
              <button type="button" class="chip ${g === 'week' ? 'selected' : ''}" data-g="week">Week</button>
              <button type="button" class="chip ${g === 'month' ? 'selected' : ''}" data-g="month">Month</button>
            </div>
            <div class="combo-chart" data-role="sa-bar"></div>
            <div class="chart-legend" data-role="sa-bar-legend"></div>
          </div>
        </div>
      </div>
    `;
    container.querySelectorAll('[data-role="sa-granularity"] button[data-g]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (state.loading) return;
        state.standardGranularity[key] = btn.dataset.g;
        container.querySelectorAll('[data-role="sa-granularity"] button').forEach((b) => b.classList.toggle('selected', b === btn));
        renderStandardBar(container, key);
      });
    });

    renderStandardPie(container, key, d);
    renderStandardBar(container, key);
  }

  // Overview donut: % case Achieved vs Not Achieved (spec: "biểu đồ quạt
  // để thể hiện tổng quan bao nhiêu % case achieve standard").
  async function renderStandardPie(container, key, d) {
    const params = getFilterParams();
    params.set('type', key);
    const pie = await getJSON('/api/standard-achievement/pie?' + params.toString());
    MiniCharts.renderDoughnut(container.querySelector('[data-role="sa-pie"]'), [
      { label: 'Achieved', value: pie.achieved_count, color: themeVar('--success', '#157a3d') },
      { label: 'Not Achieved', value: pie.not_achieved_count, color: themeVar('--danger', '#c8291f') }
    ], { label: 'ACHIEVED', value: pie.achieved_pct + '%' }, { thickness: 0.38 });
    container.querySelector('[data-role="sa-pie-total"]').textContent = `${pie.total} Cases`;
  }

  // Standard Achievement bar (spec: bo pie + duration line rieng, gop lam
  // 1 -- chieu cao = thoi gian downtime trung binh/mẻ (min/case), 2 phan
  // xanh/do la ty le case dat/khong dat standard trong ky do).
  async function renderStandardBar(container, key) {
    const g = getStdGranularity(key);
    const params = getFilterParams();
    params.set('type', key);
    params.set('granularity', g);
    const data = await getJSON('/api/standard-achievement/bar?' + params.toString());

    const datasets = data.datasets.map((ds, i) => ({
      key: ds.key, label: ds.label, color: ds.color, data: ds.data,
      dataLabels: data.achieved_pct.map((p) => {
        if (p == null) return null;
        return i === 0 ? `${p}%` : `${Math.round((100 - p) * 10) / 10}%`;
      })
    }));

    MiniCharts.renderStackedBar(container.querySelector('[data-role="sa-bar"]'), data.labels, datasets, {
      xFormat: 'date', unit: ' min',
      onSegmentClick: (dsIndex, i, ds) => {
        if (ds.key !== 'not_achieved') return;
        const d = state.standardData.find((x) => x.key === key);
        openRootCause(key, d ? d.label : key);
      }
    });
    MiniCharts.renderLegend(container.querySelector('[data-role="sa-bar-legend"]'), datasets.map((d) => ({ label: d.label, color: d.color })));
  }

  // -------------------------------------------------------------
  // LAYER 4 — ROOT CAUSE: trend chart (one line per root cause, case
  // count over time, Not Achieved cases only) + one button per root
  // cause opening the whole-range case detail table.
  // -------------------------------------------------------------
  function openRootCause(key, label) {
    state.rootCause = { key, label };
    goToLayer('rootcause', { skipRefresh: true });
    renderRootCauseLayer();
  }

  // Root Cause trend: one line per cause (dataschema.ROOT_CAUSES, fixed
  // order), Y = case count (Not Achieved only), own Day/Week/Month
  // granularity control (separate from Standard Achievement's).
  async function renderRootCauseLayer() {
    const rc = state.rootCause;
    const g = state.rootCauseGranularity[rc.key] || 'day';
    const params = getFilterParams();
    params.set('type', rc.key);
    params.set('granularity', g);

    el('rootCauseTitle').textContent = `ROOT CAUSES — ${rc.label}`;
    const gWrap = el('rootCauseGranularity');
    gWrap.innerHTML = ['day', 'week', 'month'].map((opt) =>
      `<button type="button" class="chip ${g === opt ? 'selected' : ''}" data-g="${opt}">${opt[0].toUpperCase()}${opt.slice(1)}</button>`
    ).join('');
    gWrap.querySelectorAll('button[data-g]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (state.loading) return;
        state.rootCauseGranularity[rc.key] = btn.dataset.g;
        renderRootCauseLayer();
      });
    });

    const [data, causeNames] = await Promise.all([
      getJSON('/api/root-cause/time?' + params.toString()),
      getJSON('/api/root-causes')
    ]);

    const container = el('rootCauseChart');
    const hasAny = data.datasets.some((ds) => ds.data.some((v) => v > 0));
    if (!hasAny) {
      container.innerHTML = `<div class="chart-empty">No Root Cause Data In This Range</div>`;
      el('rootCauseLegend').innerHTML = '';
    } else {
      const p = palette();
      const lineDatasets = data.datasets.map((ds, i) => ({
        label: ds.cause, data: ds.data, color: p[i % p.length], width: 2, opacity: 1
      }));
      MiniCharts.renderLine(container, data.labels, lineDatasets, { xFormat: 'date', unit: ' case' });
      MiniCharts.renderLegend(el('rootCauseLegend'), lineDatasets.map((d) => ({ label: d.label, color: d.color })));
    }

    // One button per root cause -> whole-range Case Detail (spec: "hien
    // thi toan bo khoang ngay dang loc cho cause do").
    const btnWrap = el('rootCauseButtons');
    btnWrap.innerHTML = causeNames.map((cause) => `<button type="button" class="btn btn-sm btn-outline" data-cause="${cause}">${cause}</button>`).join('');
    btnWrap.querySelectorAll('button[data-cause]').forEach((btn) => {
      btn.addEventListener('click', () => openCaseDetailForCause(rc, btn.dataset.cause));
    });
  }

  // Exact case list for the clicked cause, across the WHOLE currently-
  // filtered date range (spec: bam nut root cause -> hien thi toan bo
  // khoang ngay dang loc, sap xep theo thoi gian giam dan, cho phep sua
  // Note truc tiep trong bang).
  async function openCaseDetailForCause(rc, cause) {
    const params = getFilterParams();
    params.set('type', rc.key);
    params.set('cause', cause);
    showOverlay();
    let rows = [];
    try {
      rows = await getJSON('/api/root-cause/cases?' + params.toString());
    } finally {
      hideOverlay();
    }
    const label = rc.label ? `${rc.label} — ${cause}` : cause;
    el('caseDetailTitle').textContent = `Case Detail — ${label}`;
    el('caseDetailCount').textContent = `(${rows.length} Cases)`;
    renderCaseDetailRows(rows);
    const btn = el('caseDetailExportBtn');
    btn.dataset.type = rc.key;
    btn.dataset.cause = cause;
    delete btn.dataset.period;
    el('caseDetailOverlay').classList.add('show');
  }

  // Shared row renderer for the Case Detail table -- Note is an editable
  // input + Save button (spec: "cho phep nguoi dung chinh sua phan note"),
  // wired to POST /api/cases/note (backend already existed, was never
  // wired to any UI before this).
  function renderCaseDetailRows(rows) {
    const tbody = el('caseDetailTable').querySelector('tbody');
    tbody.innerHTML = rows.length ? rows.map((c) => `
      <tr class="${c.flagged ? 'is-flagged' : ''}">
        <td>
          <button type="button" class="star-btn ${c.flagged ? 'is-active' : ''}" data-log-id="${c.log_id}" data-category-key="${c.category_key}" title="Đánh Dấu Cần Cải Thiện">${c.flagged ? '★' : '☆'}</button>
        </td>
        <td>${c.case_id || c.log_id}</td><td>${c.machine}</td><td>${c.batch}</td><td>${c.end_time}</td>
        <td class="num">${fmtVal(c.downtime_hours)}</td><td class="num">${fmtVal(c.standard_hours)}</td>
        <td>${c.cause || '—'}</td>
        <td>
          <div class="note-cell">
            <input type="text" class="note-input" value="${(c.note || '').replace(/"/g, '&quot;')}" data-log-id="${c.log_id}" data-category-key="${c.category_key}">
            <button type="button" class="btn note-save-btn" data-log-id="${c.log_id}" data-category-key="${c.category_key}">Save</button>
          </div>
        </td>
      </tr>`).join('') : `<tr><td colspan="9" class="empty-row">No Cases</td></tr>`;

    tbody.querySelectorAll('.note-save-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const input = tbody.querySelector(`.note-input[data-log-id="${btn.dataset.logId}"][data-category-key="${btn.dataset.categoryKey}"]`);
        btn.disabled = true;
        try {
          const res = await postJSON('/api/cases/note', {
            log_id: Number(btn.dataset.logId), category_key: btn.dataset.categoryKey, note: input.value
          });
          showToast(res.message, !res.ok);
        } catch (e) {
          showToast(e.message, true);
        } finally {
          btn.disabled = false;
        }
      });
    });

    // Star toggle (spec: "danh dau sao cac diem can cai thien de neu bat
    // len van de") -- flips flagged state immediately, no confirm needed.
    tbody.querySelectorAll('.star-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const nextFlagged = !btn.classList.contains('is-active');
        btn.disabled = true;
        try {
          const res = await postJSON('/api/cases/flag', {
            log_id: Number(btn.dataset.logId), category_key: btn.dataset.categoryKey, flagged: nextFlagged
          });
          if (res.ok) {
            btn.classList.toggle('is-active', nextFlagged);
            btn.textContent = nextFlagged ? '★' : '☆';
            btn.closest('tr').classList.toggle('is-flagged', nextFlagged);
          } else {
            showToast(res.message, true);
          }
        } catch (e) {
          showToast(e.message, true);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  function bindCaseDetailModal() {
    el('caseDetailClose').addEventListener('click', () => el('caseDetailOverlay').classList.remove('show'));
    el('caseDetailOverlay').addEventListener('click', (e) => { if (e.target.id === 'caseDetailOverlay') el('caseDetailOverlay').classList.remove('show'); });
    el('caseDetailExportBtn').addEventListener('click', () => {
      const params = getFilterParams();
      const ds = el('caseDetailExportBtn').dataset;
      if (ds.type) params.set('type', ds.type);
      if (ds.cause) params.set('cause', ds.cause);
      if (ds.period) params.set('period', ds.period);
      if (ds.granularity) params.set('granularity', ds.granularity);
      if (ds.severity) params.set('severity', ds.severity);
      window.open('/api/cases/export?' + params.toString(), '_blank');
    });
  }

  // -------------------------------------------------------------
  // RIGHT FIRST TIME TAB (spec section 10-11) — RFT (6 metrics) + RFT
  // CORE COLOR (3-metric subset). Both are manual/import data, NOT
  // affected by the Machine/Capacity/Fabric filter. Missing months show
  // "—", never "0%".
  // -------------------------------------------------------------
  function rftColors() {
    const p = palette();
    return { lab_to_lab: p[0], lab_to_bulk: p[1], bulk_to_bulk: p[2], second_batch: p[3], adjustment: themeVar('--text-secondary', '#6b6b72'), rework: p[4] };
  }

  // Click-to-open-link (spec: click khối RFT/RFT Core Color mở link OneDrive
  // đã cấu hình trong Admin). Links are cached in state.appLinks and only
  // re-fetched once per RFT tab visit.
  async function loadAppLinks() {
    try {
      const links = await getJSON('/api/app-links');
      state.appLinks = {};
      links.forEach((l) => { state.appLinks[l.link_key] = l.url; });
    } catch (e) { /* non-fatal: click just won't open a link this session */ }
  }

  function bindMiniStatGridLink(gridId, linkKey) {
    const grid = el(gridId);
    if (!grid || grid.dataset.linkBound) return;
    grid.dataset.linkBound = '1';
    grid.style.cursor = 'pointer';
    grid.title = 'Click Để Mở Link OneDrive';
    grid.addEventListener('click', () => {
      const url = state.appLinks[linkKey];
      if (url) window.open(url, '_blank');
      else showToast('Chưa Cấu Hình Link OneDrive (Admin → RFT).', true);
    });
  }

  async function refreshRftChart() {
    const data = await getJSON('/api/rft-trend');
    const colors = rftColors();
    data.datasets.forEach((ds) => {
      const sparkEl = el(`rftChart-${ds.key}`);
      const valueEl = el(`rftValue-${ds.key}`);
      if (!sparkEl) return;
      const lastVal = [...ds.data].reverse().find((v) => v !== null && v !== undefined);
      if (valueEl) valueEl.textContent = lastVal !== undefined ? `${lastVal.toFixed(1)}%` : '—';
      const series = ds.data.filter((v) => v !== null && v !== undefined);
      if (series.length) MiniCharts.renderSparkline(sparkEl, series, { color: colors[ds.key] || themeVar('--primary'), area: true });
      else sparkEl.innerHTML = `<div class="chart-empty">No Data</div>`;
    });
    bindMiniStatGridLink('rftGrid', 'rft');
  }

  async function refreshRftCoreChart() {
    const data = await getJSON('/api/rft-core-color-trend');
    const p = palette();
    data.datasets.forEach((ds, i) => {
      const sparkEl = el(`rftCoreChart-${ds.key}`);
      const valueEl = el(`rftCoreValue-${ds.key}`);
      if (!sparkEl) return;
      const lastVal = [...ds.data].reverse().find((v) => v !== null && v !== undefined);
      if (valueEl) valueEl.textContent = lastVal !== undefined ? `${lastVal.toFixed(1)}%` : '—';
      const series = ds.data.filter((v) => v !== null && v !== undefined);
      if (series.length) MiniCharts.renderSparkline(sparkEl, series, { color: p[i % p.length], area: true });
      else sparkEl.innerHTML = `<div class="chart-empty">No Data</div>`;
    });
    bindMiniStatGridLink('rftCoreGrid', 'rft_core_color');
  }

  async function refreshRftTab() {
    await loadAppLinks();
    await Promise.all([
      safeRefreshChart('RFT', refreshRftChart, 'rftChart-lab_to_lab'),
      safeRefreshChart('RFT Core Color', refreshRftCoreChart, 'rftCoreChart-bulk_to_bulk')
    ]);
  }

  // -------------------------------------------------------------
  // ADMIN MODAL — Data Import, Standards, Import Root Cause, RFT Data,
  // RFT Core Color.
  // -------------------------------------------------------------
  function bindAdminModal() {
    el('adminBtn').addEventListener('click', () => el('adminModalOverlay').classList.add('show'));
    el('adminModalClose').addEventListener('click', () => el('adminModalOverlay').classList.remove('show'));
    el('adminModalOverlay').addEventListener('click', (e) => { if (e.target.id === 'adminModalOverlay') el('adminModalOverlay').classList.remove('show'); });

    el('adminTabs').querySelectorAll('button[data-admin-tab]').forEach((btn) => {
      btn.addEventListener('click', () => {
        el('adminTabs').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
        document.querySelectorAll('#adminModalOverlay .tab-panel').forEach((p) => p.classList.add('hidden'));
        el('admin-' + btn.dataset.adminTab).classList.remove('hidden');
        if (btn.dataset.adminTab === 'standards') safeRefresh('Standards', refreshStandardsAdmin);
        if (btn.dataset.adminTab === 'rft') { safeRefresh('RFT Table', loadRftTable); safeRefresh('RFT Link', loadRftLinkInput); }
        if (btn.dataset.adminTab === 'rftcore') { safeRefresh('RFT Core Color Table', loadRftCoreTable); safeRefresh('RFT Core Color Link', loadRftCoreLinkInput); }
        if (btn.dataset.adminTab === 'targets') safeRefresh('KPI Targets', loadTargetsAdmin);
        if (btn.dataset.adminTab === 'engineering') safeRefresh('Engineering Development', loadEngineeringAdmin);
      });
    });
  }

  async function refreshStandardsAdmin() {
    const rows = await getJSON('/api/standards');
    const tbody = el('standardsTable').querySelector('tbody');
    tbody.innerHTML = rows.map((r) => `
      <tr data-key="${r.category_key}">
        <td>${r.category_label}</td>
        <td class="num"><input type="number" step="0.01" class="std-input" value="${r.standard_hours || 0}" style="width:80px;"></td>
        <td><button class="btn btn-sm" data-save-standard="${r.category_key}">Save</button></td>
      </tr>`).join('');
    tbody.querySelectorAll('button[data-save-standard]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const key = btn.dataset.saveStandard;
        const input = tbody.querySelector(`tr[data-key="${key}"] .std-input`);
        try {
          await postJSON('/api/standards', { category_key: key, standard_hours: parseFloat(input.value) || 0 });
          showToast('Standard Saved.');
        } catch (e) { showToast(e.message, true); }
      });
    });
  }

  function bindUploadData() {
    function wireUpload(btnId, fileId, url, label) {
      el(btnId).addEventListener('click', () => el(fileId).click());
      el(fileId).addEventListener('change', async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData(); fd.append('file', f);
        showOverlay();
        try {
          const res = await fetch(url, { method: 'POST', body: fd });
          const data = await res.json();
          showToast(data.message || (data.ok ? `${label} Imported.` : 'Import Failed.'), !data.ok);
          if (data.ok) await safeRefresh('Refresh After Import', refreshAll);
        } catch (err) {
          showToast(`${label} Import Failed: ${err.message}`, true);
        } finally {
          hideOverlay();
          e.target.value = '';
        }
      });
    }
    wireUpload('uploadAvailabilityBtn', 'uploadAvailabilityFile', '/api/import-downtime-data', 'Availability');
    wireUpload('uploadPerformanceBtn', 'uploadPerformanceFile', '/api/import-performance-data', 'Performance');
  }

  function bindExportImport() {
    el('exportBtn').addEventListener('click', () => {
      const params = getFilterParams();
      window.open('/api/cases/export?' + params.toString(), '_blank');
    });
    el('importBtn').addEventListener('click', () => el('importFile').click());
    el('importFile').addEventListener('change', async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      showOverlay();
      try {
        const res = await fetch('/api/cases/import', { method: 'POST', body: fd });
        const data = await res.json();
        showToast(data.message || (data.ok ? 'Imported.' : 'Import Failed.'), !data.ok);
        if (data.ok) await safeRefresh('Refresh After Cause Import', refreshAll);
      } catch (err) {
        showToast(`Import Failed: ${err.message}`, true);
      } finally { hideOverlay(); e.target.value = ''; }
    });
  }

  // ---- RFT admin table (6 metrics) ----
  function rftRowHtml(entry) {
    const cols = ['lab_to_lab', 'lab_to_bulk', 'bulk_to_bulk', 'second_batch', 'adjustment', 'rework'];
    return `<tr data-period="${entry.period}">
      <td>${entry.period}</td>
      ${cols.map((c) => `<td class="num"><input type="number" step="0.01" data-col="${c}" value="${entry[c] != null ? entry[c] : ''}" style="width:64px;"></td>`).join('')}
      <td><button class="btn btn-sm" data-rft-save="${entry.period}">Save</button> <button class="btn btn-sm btn-danger" data-rft-del="${entry.period}">Del</button></td>
    </tr>`;
  }

  async function loadRftTable() {
    const rows = await getJSON('/api/rft-data');
    el('rftTableBody').innerHTML = rows.map(rftRowHtml).join('');
    bindRftRowActions();
  }

  function bindRftRowActions() {
    el('rftTableBody').querySelectorAll('button[data-rft-save]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const period = btn.dataset.rftSave;
        const tr = el('rftTableBody').querySelector(`tr[data-period="${period}"]`);
        const values = { period };
        tr.querySelectorAll('input[data-col]').forEach((inp) => { if (inp.value !== '') values[inp.dataset.col] = inp.value; });
        try {
          const res = await postJSON('/api/rft-data', values);
          showToast(res.message);
          await safeRefresh('RFT Trend', refreshRftChart);
        } catch (e) { showToast(e.message, true); }
      });
    });
    el('rftTableBody').querySelectorAll('button[data-rft-del]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const period = btn.dataset.rftDel;
        if (!confirm(`Xóa RFT ${period}?`)) return;
        const res = await fetch('/api/rft-data?period=' + encodeURIComponent(period), { method: 'DELETE' });
        const data = await res.json();
        showToast(data.message, !data.ok);
        await safeRefresh('RFT Table', loadRftTable);
        await safeRefresh('RFT Trend', refreshRftChart);
      });
    });
  }

  function bindRftAdmin() {
    el('rftAddBtn').addEventListener('click', async () => {
      const period = el('rftNewPeriod').value;
      if (!period) { showToast('Chọn Period.', true); return; }
      const values = { period };
      [['lab_to_lab', 'rftNewLabToLab'], ['lab_to_bulk', 'rftNewLabToBulk'], ['bulk_to_bulk', 'rftNewBulkToBulk'],
       ['second_batch', 'rftNewSecondBatch'], ['adjustment', 'rftNewAdjustment'], ['rework', 'rftNewRework']].forEach(([k, id]) => {
        if (el(id).value !== '') values[k] = el(id).value;
      });
      try {
        const res = await postJSON('/api/rft-data', values);
        showToast(res.message);
        ['rftNewPeriod', 'rftNewLabToLab', 'rftNewLabToBulk', 'rftNewBulkToBulk', 'rftNewSecondBatch', 'rftNewAdjustment', 'rftNewRework'].forEach((id) => { el(id).value = ''; });
        await safeRefresh('RFT Table', loadRftTable);
        await safeRefresh('RFT Trend', refreshRftChart);
      } catch (e) { showToast(e.message, true); }
    });

    el('uploadRftBtn').addEventListener('click', () => el('uploadRftFile').click());
    el('uploadRftFile').addEventListener('change', async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData(); fd.append('file', f); fd.append('year', el('rftImportYear').value || new Date().getFullYear());
      showOverlay();
      try {
        const res = await fetch('/api/rft-data/import', { method: 'POST', body: fd });
        const data = await res.json();
        showToast(data.message, !data.ok);
        await safeRefresh('RFT Table', loadRftTable);
        await safeRefresh('RFT Trend', refreshRftChart);
      } finally { hideOverlay(); e.target.value = ''; }
    });

    el('rftLinkSaveBtn').addEventListener('click', async () => {
      const url = el('rftLinkInput').value.trim();
      if (!url) { showToast('Nhập Link OneDrive.', true); return; }
      try {
        const res = await postJSON('/api/app-links', { link_key: 'rft', url, label: 'RFT Data (OneDrive)' });
        showToast(res.message, !res.ok);
        await loadAppLinks();
      } catch (e) { showToast(e.message, true); }
    });
  }

  async function loadRftLinkInput() {
    try {
      const link = await getJSON('/api/app-links?key=rft');
      el('rftLinkInput').value = (link && link.url) || '';
    } catch (e) { el('rftLinkInput').value = ''; }
  }

  // ---- RFT Core Color admin table (3 metrics) ----
  function rftCoreRowHtml(entry) {
    const cols = ['bulk_to_bulk', 'second_batch'];
    return `<tr data-period="${entry.period}">
      <td>${entry.period}</td>
      ${cols.map((c) => `<td class="num"><input type="number" step="0.01" data-col="${c}" value="${entry[c] != null ? entry[c] : ''}" style="width:70px;"></td>`).join('')}
      <td><button class="btn btn-sm" data-rftcore-save="${entry.period}">Save</button> <button class="btn btn-sm btn-danger" data-rftcore-del="${entry.period}">Del</button></td>
    </tr>`;
  }

  async function loadRftCoreTable() {
    const rows = await getJSON('/api/rft-core-color-data');
    el('rftCoreTableBody').innerHTML = rows.map(rftCoreRowHtml).join('');
    el('rftCoreTableBody').querySelectorAll('button[data-rftcore-save]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const period = btn.dataset.rftcoreSave;
        const tr = el('rftCoreTableBody').querySelector(`tr[data-period="${period}"]`);
        const values = { period };
        tr.querySelectorAll('input[data-col]').forEach((inp) => { if (inp.value !== '') values[inp.dataset.col] = inp.value; });
        try {
          const res = await postJSON('/api/rft-core-color-data', values);
          showToast(res.message);
          await safeRefresh('RFT Core Color Trend', refreshRftCoreChart);
        } catch (e) { showToast(e.message, true); }
      });
    });
    el('rftCoreTableBody').querySelectorAll('button[data-rftcore-del]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const period = btn.dataset.rftcoreDel;
        if (!confirm(`Xóa RFT Core Color ${period}?`)) return;
        const res = await fetch('/api/rft-core-color-data?period=' + encodeURIComponent(period), { method: 'DELETE' });
        const data = await res.json();
        showToast(data.message, !data.ok);
        await safeRefresh('RFT Core Color Table', loadRftCoreTable);
        await safeRefresh('RFT Core Color Trend', refreshRftCoreChart);
      });
    });
  }

  function bindRftCoreAdmin() {
    el('rftCoreAddBtn').addEventListener('click', async () => {
      const period = el('rftCoreNewPeriod').value;
      if (!period) { showToast('Chọn Period.', true); return; }
      const values = { period };
      [['bulk_to_bulk', 'rftCoreNewBulkToBulk'], ['second_batch', 'rftCoreNewSecondBatch']].forEach(([k, id]) => {
        if (el(id).value !== '') values[k] = el(id).value;
      });
      try {
        const res = await postJSON('/api/rft-core-color-data', values);
        showToast(res.message);
        ['rftCoreNewPeriod', 'rftCoreNewBulkToBulk', 'rftCoreNewSecondBatch'].forEach((id) => { el(id).value = ''; });
        await safeRefresh('RFT Core Color Table', loadRftCoreTable);
        await safeRefresh('RFT Core Color Trend', refreshRftCoreChart);
      } catch (e) { showToast(e.message, true); }
    });

    el('uploadRftCoreBtn').addEventListener('click', () => el('uploadRftCoreFile').click());
    el('uploadRftCoreFile').addEventListener('change', async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData(); fd.append('file', f); fd.append('year', el('rftCoreImportYear').value || new Date().getFullYear());
      showOverlay();
      try {
        const res = await fetch('/api/rft-core-color-data/import', { method: 'POST', body: fd });
        const data = await res.json();
        showToast(data.message, !data.ok);
        await safeRefresh('RFT Core Color Table', loadRftCoreTable);
        await safeRefresh('RFT Core Color Trend', refreshRftCoreChart);
      } finally { hideOverlay(); e.target.value = ''; }
    });

    el('rftCoreLinkSaveBtn').addEventListener('click', async () => {
      const url = el('rftCoreLinkInput').value.trim();
      if (!url) { showToast('Nhập Link OneDrive.', true); return; }
      try {
        const res = await postJSON('/api/app-links', { link_key: 'rft_core_color', url, label: 'RFT Core Color (OneDrive)' });
        showToast(res.message, !res.ok);
        await loadAppLinks();
      } catch (e) { showToast(e.message, true); }
    });
  }

  async function loadRftCoreLinkInput() {
    try {
      const link = await getJSON('/api/app-links?key=rft_core_color');
      el('rftCoreLinkInput').value = (link && link.url) || '';
    } catch (e) { el('rftCoreLinkInput').value = ''; }
  }

  async function loadTargetsAdmin() {
    const rows=await getJSON('/api/kpi-targets');
    el('targetTableBody').innerHTML=rows.map(r=>`<tr><td>${r.year}</td><td>${r.kpi_key}</td><td>${r.fabric_type}</td><td class="num">${fmtVal(r.target_value)} ${r.unit}</td><td><button class="btn btn-sm btn-danger" data-target-del="${r.year}|${r.kpi_key}|${r.fabric_type}">Del</button></td></tr>`).join('');
    el('targetTableBody').querySelectorAll('[data-target-del]').forEach(b=>b.addEventListener('click',async()=>{const [year,kpi,fabric]=b.dataset.targetDel.split('|');const res=await fetch(`/api/kpi-targets?year=${year}&kpi_key=${encodeURIComponent(kpi)}&fabric_type=${encodeURIComponent(fabric)}`,{method:'DELETE'});const d=await res.json();showToast(d.message,!d.ok);await loadTargetsAdmin();await refreshDashboardKpis();}));
  }

  function bindTargetsAdmin() {
    el('targetNewYear').value=new Date().getFullYear();
    el('targetSaveBtn').addEventListener('click',async()=>{try{const res=await postJSON('/api/kpi-targets',{year:el('targetNewYear').value,kpi_key:el('targetNewKpi').value,fabric_type:el('targetNewFabric').value,target_value:el('targetNewValue').value});showToast(res.message);el('targetNewValue').value='';await loadTargetsAdmin();await refreshDashboardKpis();}catch(e){showToast(e.message,true);}});
  }

  function engineeringRowHtml(r) { const years=[2026,2027,2028,2029]; return `<tr data-eng-id="${r.id}"><td><input data-col="fabric_type" value="${r.fabric_type}"></td><td><input data-col="shade" value="${r.shade}"></td><td><input data-col="program" value="${r.program}"></td><td><input type="number" min="0" step="0.01" data-col="before_pth" value="${r.before_pth??''}"></td><td><input type="number" min="0" step="0.01" data-col="current_pth" value="${r.current_pth??''}"></td>${years.map(y=>`<td><input type="number" min="0" step="0.01" data-year="${y}" value="${r.targets[String(y)]??''}" style="width:60px;"></td>`).join('')}<td><button class="btn btn-sm" data-eng-save>Save</button> <button class="btn btn-sm btn-danger" data-eng-del>Del</button></td></tr>`; }

  async function loadEngineeringAdmin(){const rows=await getJSON('/api/engineering-development/data');const body=el('engineeringAdminBody');body.innerHTML=rows.map(engineeringRowHtml).join('');body.querySelectorAll('tr').forEach(tr=>{tr.querySelector('[data-eng-save]').addEventListener('click',()=>saveEngineeringRow(tr));tr.querySelector('[data-eng-del]').addEventListener('click',async()=>{const res=await fetch('/api/engineering-development/data?id='+tr.dataset.engId,{method:'DELETE'});const d=await res.json();showToast(d.message,!d.ok);await loadEngineeringAdmin();await refreshEngineeringOptions();await refreshEngineering();});});}

  async function saveEngineeringRow(tr){const payload={id:tr.dataset.engId,targets:{}};tr.querySelectorAll('[data-col]').forEach(i=>payload[i.dataset.col]=i.value);tr.querySelectorAll('[data-year]').forEach(i=>payload.targets[i.dataset.year]=i.value);try{const r=await postJSON('/api/engineering-development/data',payload);showToast(r.message);await loadEngineeringAdmin();await refreshEngineeringOptions();await refreshEngineering();}catch(e){showToast(e.message,true);}}

  function bindEngineeringAdmin(){el('engineeringAddBtn').addEventListener('click',async()=>{const payload={fabric_type:el('engineeringNewFabric').value,shade:el('engineeringNewShade').value,program:el('engineeringNewProgram').value,before_pth:el('engineeringNewBefore').value,current_pth:el('engineeringNewCurrent').value,targets:{}};document.querySelectorAll('[data-eng-new-year]').forEach(i=>payload.targets[i.dataset.engNewYear]=i.value);try{const r=await postJSON('/api/engineering-development/data',payload);showToast(r.message);await loadEngineeringAdmin();await refreshEngineeringOptions();await refreshEngineering();}catch(e){showToast(e.message,true);}});el('uploadEngineeringBtn').addEventListener('click',()=>el('uploadEngineeringFile').click());el('uploadEngineeringFile').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;const fd=new FormData();fd.append('file',f);const res=await fetch('/api/engineering-development/import',{method:'POST',body:fd});const d=await res.json();showToast(d.message,!d.ok);e.target.value='';await loadEngineeringAdmin();await refreshEngineeringOptions();await refreshEngineering();});}

  // -------------------------------------------------------------
  // THEME TOGGLE — persisted, full repaint (SVG colors don't retroactively
  // follow CSS variables).
  // -------------------------------------------------------------
  function bindThemeToggle() {
    el('themeToggleBtn').addEventListener('click', async () => {
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('dyeing-theme', next); } catch (e) { /* storage unavailable */ }
      await safeRefresh('Theme Repaint', refreshAll);
    });
  }

  // -------------------------------------------------------------
  // APPLY FILTERS — re-fetches everything visible for the current tab +
  // layer. Per spec section 4, comboboxes never trigger a fetch on their
  // own; only this button (or a granularity chip / layer navigation) does.
  // -------------------------------------------------------------
  async function refreshAll() {
    if (state.loading) return;
    state.loading = true;
    el('applyFiltersBtn').disabled = true;
    showOverlay();
    try {
      const tasks = [safeRefresh('Dashboard KPI', refreshDashboardKpis), safeRefresh('Engineering Development', refreshEngineering)];

      if (state.productivityLayer === 'trend') tasks.push(safeRefresh('KPI Trend', () => showTrendSection(state.activeKpi)));
      if (state.productivityLayer === 'detail') tasks.push(safeRefresh('Detail Downtime', refreshDetailLayer));
      if (state.productivityLayer === 'rootcause' && state.rootCause.key) tasks.push(safeRefresh('Root Cause', () => renderRootCauseLayer()));

      tasks.push(safeRefresh('RFT Tab', refreshRftTab));

      await Promise.all(tasks);
    } finally {
      hideOverlay();
      el('applyFiltersBtn').disabled = false;
      state.loading = false;
    }
  }

  function bindFilterBar() {
    el('applyFiltersBtn').addEventListener('click', refreshAll);
  }

  // -------------------------------------------------------------
  // INIT
  // -------------------------------------------------------------
  async function init() {
    initDates();
    bindCombos();
    bindProductivityNav();
    bindTrendGranularity('batchTrendGranularity', 'batchGranularity', refreshBatchTrend);
    bindTrendGranularity('tankTrendGranularity', 'tankGranularity', refreshTankTrend);
    bindTrendGranularity('downtimeTrendGranularity', 'downtimeGranularity', refreshDowntimeTrend);
    bindDetailGranularity();
    bindTypeChipsToggle();
    bindBatchDetailDrawer();
    bindAvailabilityDetailDrawer();
    bindCaseDetailModal();
    bindAdminModal();
    bindUploadData();
    bindExportImport();
    bindRftAdmin();
    bindRftCoreAdmin();
    bindTargetsAdmin();
    bindEngineeringAdmin();
    bindEngineeringFilters();
    bindThemeToggle();
    bindFilterBar();

    goToLayer('dashboard', { skipRefresh: true });

    showOverlay();
    try {
      await safeRefresh('Filter Options', loadFilterOptions);
      await safeRefresh('Engineering Options', refreshEngineeringOptions);
      await safeRefresh('Downtime Types', loadTypeChips);
      await refreshAll();
    } finally {
      hideOverlay();
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
