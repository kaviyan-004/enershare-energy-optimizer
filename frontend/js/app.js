/**
 * EnerShare AI — Main Application Controller
 */
import { API } from './api.js';
import { Charts } from './charts.js';

// Application State
const state = {
  health: null,
  config: null,
  scenarios: [],
  activeScenarioId: null,
  activeDatasetId: null,
  latestRunId: null,
  latestSchedule: [],
};

// UI Notification Toasts
export function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ'}</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

// Format numbers
const formatNum = (val, decimals = 1) => (val !== null && val !== undefined) ? Number(val).toFixed(decimals) : '—';
const formatCurrency = (val) => (val !== null && val !== undefined) ? `₹${Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

// Tab Navigation
function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.dataset.tab;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');

      // Refresh specific charts on tab view
      if (targetId === 'tab-dashboard' && state.latestSchedule.length) {
        Charts.renderEnergyBalance('dashboard-energy-chart', state.latestSchedule);
      } else if (targetId === 'tab-optimization' && state.latestSchedule.length) {
        Charts.renderEnergyBalance('optimization-flow-chart', state.latestSchedule);
        Charts.renderBatterySoc('optimization-soc-chart', state.latestSchedule);
      }
    });
  });
}

// Load System Health
async function loadHealth() {
  try {
    const health = await API.getHealth();
    state.health = health;
    const badge = document.getElementById('backend-status-text');
    if (badge) {
      badge.textContent = `Online • ${health.components?.xgboost || 'XGBoost Active'} • ${health.components?.pulp_optimizer || 'HiGHS LP'}`;
    }
  } catch (err) {
    console.error('Health fetch failed:', err);
    const badge = document.getElementById('backend-status-text');
    if (badge) badge.textContent = 'Backend Reconnecting...';
  }
}

// Load Site Config
async function loadConfig() {
  try {
    const cfg = await API.getConfig();
    state.config = cfg;
    populateConfigForm(cfg);
  } catch (err) {
    console.error('Config fetch failed:', err);
  }
}

function populateConfigForm(cfg) {
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  };

  setVal('cfg-site-name', cfg.name || 'Demo MSME Site');
  setVal('cfg-solar-cap', cfg.solar_capacity_kw || 50);
  setVal('cfg-bat-cap', cfg.battery?.capacity_kwh || 100);
  setVal('cfg-bat-min-soc', cfg.battery?.min_soc_pct || 20);
  setVal('cfg-bat-max-soc', cfg.battery?.max_soc_pct || 95);
  setVal('cfg-bat-init-soc', cfg.battery?.initial_soc_pct || 50);
  setVal('cfg-bat-power', cfg.battery?.charge_power_kw || 25);
  setVal('cfg-grid-import', cfg.grid?.import_limit_kw || 100);
  setVal('cfg-grid-export', cfg.grid?.export_limit_kw || 50);
  setVal('cfg-tariff-import', cfg.tariff?.import_tariff_inr_kwh || 8.5);
  setVal('cfg-tariff-export', cfg.tariff?.export_tariff_inr_kwh || 3.0);

  const exportToggle = document.getElementById('cfg-export-permitted');
  if (exportToggle) exportToggle.checked = !!cfg.grid?.export_permitted;
}

// Load Datasets and Scenarios
async function loadScenarios() {
  try {
    const scenarios = await API.getScenarios();
    state.scenarios = scenarios;

    // Populate scenario selector dropdowns
    const selectors = ['scenario-select', 'sim-scenario-select'];
    selectors.forEach(selId => {
      const el = document.getElementById(selId);
      if (!el) return;
      el.innerHTML = '';
      scenarios.forEach(sc => {
        const opt = document.createElement('option');
        opt.value = sc.id;
        opt.textContent = `${sc.name} (${sc.preset || 'custom'})`;
        el.appendChild(opt);
      });
    });

    if (scenarios.length > 0) {
      state.activeScenarioId = scenarios[0].id;
    }
  } catch (err) {
    console.error('Scenarios fetch failed:', err);
  }
}

// Load Demo Dataset for initial view
async function loadDemoDataset() {
  try {
    const data = await API.getDemoDataset(7);
    state.activeDatasetId = data.dataset_id;
  } catch (err) {
    console.error('Demo dataset failed:', err);
  }
}

// Refresh Dashboard KPIs
async function refreshDashboard() {
  try {
    const kpi = await API.getKPISummary();
    document.getElementById('kpi-solar-gen').textContent = formatNum(kpi.renewable_generation_kwh);
    document.getElementById('kpi-demand').textContent = formatNum(kpi.energy_demand_kwh);
    document.getElementById('kpi-battery-soc').textContent = `${formatNum(kpi.battery_soc_pct, 0)}%`;
    document.getElementById('kpi-grid-import').textContent = formatNum(kpi.grid_import_kwh);
    document.getElementById('kpi-cost').textContent = formatCurrency(kpi.estimated_cost_inr);
    document.getElementById('kpi-utilization').textContent = `${formatNum(kpi.renewable_utilization_pct, 1)}%`;
    document.getElementById('kpi-rec-text').textContent = kpi.recommendation || 'Operational within parameters.';
  } catch (err) {
    console.error('KPI summary failed:', err);
  }
}

// Execute Optimization
async function triggerOptimization(scenarioId = null) {
  const targetId = scenarioId || state.activeScenarioId || (state.scenarios[0]?.id);
  if (!targetId) {
    showToast('Please create or select a scenario first.', 'error');
    return;
  }

  showToast('Running SciPy HiGHS LP Optimization...', 'info');

  try {
    const res = await API.runOptimization(targetId, true);
    state.latestRunId = res.run_id;
    state.latestSchedule = res.schedule;

    // Render schedule tables and charts
    renderScheduleTable('dispatch-table-body', res.schedule);
    Charts.renderEnergyBalance('dashboard-energy-chart', res.schedule);
    Charts.renderEnergyBalance('optimization-flow-chart', res.schedule);
    Charts.renderBatterySoc('optimization-soc-chart', res.schedule);

    // Update KPI cards with new run metrics
    document.getElementById('kpi-solar-gen').textContent = formatNum(res.schedule.reduce((acc, r) => acc + r.renewable_gen_kwh, 0));
    document.getElementById('kpi-demand').textContent = formatNum(res.schedule.reduce((acc, r) => acc + r.demand_kwh, 0));
    document.getElementById('kpi-battery-soc').textContent = `${formatNum(res.schedule[res.schedule.length - 1]?.battery_soc_pct, 0)}%`;
    document.getElementById('kpi-grid-import').textContent = formatNum(res.total_import_kwh);
    document.getElementById('kpi-cost').textContent = formatCurrency(res.total_cost_inr);
    document.getElementById('kpi-utilization').textContent = `${formatNum(res.renewable_utilization_pct, 1)}%`;
    document.getElementById('kpi-rec-text').textContent = res.recommendation;

    // Enable export links
    const csvBtn = document.getElementById('btn-export-csv');
    const jsonBtn = document.getElementById('btn-export-json');
    if (csvBtn) csvBtn.href = API.getCSVExportUrl(res.run_id);
    if (jsonBtn) jsonBtn.href = API.getJSONExportUrl(res.run_id);

    showToast(`Optimization complete! Cost: ${formatCurrency(res.total_cost_inr)}, Self-consumption: ${formatNum(res.renewable_utilization_pct)}%`, 'success');

    // Also update executive summary
    loadExecutiveSummary(res.run_id);
  } catch (err) {
    console.error('Optimization error:', err);
    showToast('Optimization failed. Check constraints.', 'error');
  }
}

// Render 24-hour Schedule Table
function renderScheduleTable(tbodyId, schedule) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = '';

  schedule.forEach(row => {
    const tr = document.createElement('tr');
    const d = new Date(row.timestamp);
    const timeStr = `${String(d.getHours()).padStart(2, '0')}:00`;

    tr.innerHTML = `
      <td><strong>${row.interval + 1}</strong> (${timeStr})</td>
      <td><span class="badge badge-green">${formatNum(row.renewable_gen_kwh)}</span></td>
      <td><span class="badge badge-blue">${formatNum(row.demand_kwh)}</span></td>
      <td>${formatNum(row.renewable_used_kwh)}</td>
      <td>${row.battery_charge_kwh > 0.05 ? `<span class="badge badge-amber">+${formatNum(row.battery_charge_kwh)}</span>` : '—'}</td>
      <td>${row.battery_discharge_kwh > 0.05 ? `<span class="badge badge-amber">-${formatNum(row.battery_discharge_kwh)}</span>` : '—'}</td>
      <td><strong>${formatNum(row.battery_soc_pct, 1)}%</strong></td>
      <td>${row.grid_import_kwh > 0.05 ? `<span class="badge badge-purple">${formatNum(row.grid_import_kwh)}</span>` : '0.0'}</td>
      <td>${row.grid_export_kwh > 0.05 ? `<span class="badge badge-blue">${formatNum(row.grid_export_kwh)}</span>` : '0.0'}</td>
      <td>${row.curtailed_kwh > 0.05 ? `<span class="badge badge-rose">${formatNum(row.curtailed_kwh)}</span>` : '0.0'}</td>
      <td>${formatCurrency(row.interval_cost_inr)}</td>
      <td style="max-width:240px; font-size:0.75rem; color:var(--text-secondary); text-overflow:ellipsis; overflow:hidden;" title="${row.action_summary}">${row.action_summary}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Run AI Forecasting
async function triggerForecasting() {
  if (!state.activeDatasetId) {
    showToast('Loading demo dataset...', 'info');
    await loadDemoDataset();
  }

  const model = document.getElementById('forecast-model-select')?.value || 'xgboost';
  const target = document.getElementById('forecast-target-select')?.value || 'generation';
  const horizon = parseInt(document.getElementById('forecast-horizon-input')?.value || 24, 10);

  showToast(`Training ${model.toUpperCase()} on energy dataset...`, 'info');

  try {
    const res = await API.runForecast(state.activeDatasetId, target, model, horizon);
    Charts.renderForecast('forecast-chart', res.points, target === 'generation' ? 'Solar PV' : 'Demand');

    document.getElementById('metric-mae').textContent = `${formatNum(res.mae, 2)} kWh`;
    document.getElementById('metric-rmse').textContent = `${formatNum(res.rmse, 2)} kWh`;
    document.getElementById('metric-mape').textContent = res.mape ? `${formatNum(res.mape, 1)}%` : '—';
    document.getElementById('metric-model-name').textContent = res.model_name.toUpperCase();

    showToast(`Forecast complete! MAE: ${formatNum(res.mae, 2)} kWh`, 'success');
  } catch (err) {
    console.error('Forecast error:', err);
    showToast('Forecasting failed. Retrying with demo baseline.', 'error');
  }
}

// Run Scenario Simulation & Baseline Comparison
async function triggerComparison() {
  const scenarioId = document.getElementById('sim-scenario-select')?.value || state.activeScenarioId;
  if (!scenarioId) {
    showToast('Please select a scenario.', 'error');
    return;
  }

  showToast('Running Optimized vs Baseline Comparison...', 'info');

  try {
    const res = await API.runComparison(scenarioId);

    // Update diff badges
    document.getElementById('diff-cost-saving').textContent = formatCurrency(res.savings.cost_saving_inr);
    document.getElementById('diff-cost-saving-pct').textContent = `${formatNum(res.savings.cost_saving_pct, 1)}% Cost Reduction`;
    document.getElementById('diff-import-red').textContent = `${formatNum(res.savings.import_reduction_kwh)} kWh`;
    document.getElementById('diff-util-gain').textContent = `+${formatNum(res.savings.renewable_util_improvement_pct, 1)}%`;

    // Render bar chart
    Charts.renderComparisonBars('comparison-bar-chart', res.baseline, res.optimized);

    // Populate comparison table
    const tbody = document.getElementById('comparison-table-body');
    if (tbody) {
      tbody.innerHTML = '';
      res.comparison_table.forEach(row => {
        const tr = document.createElement('tr');
        const isBetter = (row.better === 'lower' && row.delta < 0) || (row.better === 'higher' && row.delta > 0);
        tr.innerHTML = `
          <td><strong>${row.metric}</strong></td>
          <td>${row.baseline} ${row.unit}</td>
          <td><strong style="color:var(--accent-solar)">${row.optimized} ${row.unit}</strong></td>
          <td><span class="badge ${isBetter ? 'badge-green' : 'badge-amber'}">${row.delta > 0 ? '+' : ''}${row.delta} ${row.unit}</span></td>
        `;
        tbody.appendChild(tr);
      });
    }

    showToast(`Comparison complete: saved ${formatCurrency(res.savings.cost_saving_inr)} (${formatNum(res.savings.cost_saving_pct, 1)}%)!`, 'success');
  } catch (err) {
    console.error('Comparison error:', err);
    showToast('Simulation comparison failed.', 'error');
  }
}

// Save Configuration
async function saveConfigForm(e) {
  e.preventDefault();
  const getVal = (id, fallback) => {
    const el = document.getElementById(id);
    return el ? parseFloat(el.value) : fallback;
  };

  const payload = {
    name: document.getElementById('cfg-site-name')?.value || 'Demo MSME Site',
    solar_capacity_kw: getVal('cfg-solar-cap', 50),
    battery: {
      capacity_kwh: getVal('cfg-bat-cap', 100),
      min_soc_pct: getVal('cfg-bat-min-soc', 20),
      max_soc_pct: getVal('cfg-bat-max-soc', 95),
      initial_soc_pct: getVal('cfg-bat-init-soc', 50),
      charge_power_kw: getVal('cfg-bat-power', 25),
      discharge_power_kw: getVal('cfg-bat-power', 25),
      charge_efficiency: 0.95,
      discharge_efficiency: 0.95,
      reserve_pct: 20.0,
    },
    grid: {
      import_limit_kw: getVal('cfg-grid-import', 100),
      export_limit_kw: getVal('cfg-grid-export', 50),
      export_permitted: document.getElementById('cfg-export-permitted')?.checked || false,
    },
    tariff: {
      import_tariff_inr_kwh: getVal('cfg-tariff-import', 8.5),
      export_tariff_inr_kwh: getVal('cfg-tariff-export', 3.0),
      export_permitted: document.getElementById('cfg-export-permitted')?.checked || false,
    },
  };

  showToast('Saving site parameters...', 'info');
  try {
    const updated = await API.updateConfig(payload);
    state.config = updated;
    showToast('Configuration successfully updated and active!', 'success');
    // Trigger re-optimization with new parameters
    triggerOptimization();
  } catch (err) {
    console.error('Config save error:', err);
    showToast('Failed to save configuration.', 'error');
  }
}

// Load Executive Pitch Summary
async function loadExecutiveSummary(runId) {
  if (!runId) return;
  try {
    const summary = await API.getExecutiveSummary(runId);
    document.getElementById('rep-scenario-name').textContent = summary.scenario_name;
    document.getElementById('rep-cost').textContent = summary.key_metrics.operating_cost_inr;
    document.getElementById('rep-import').textContent = summary.key_metrics.grid_import_kwh;
    document.getElementById('rep-curtailed').textContent = summary.key_metrics.curtailed_kwh;
    document.getElementById('rep-util').textContent = summary.key_metrics.renewable_utilization;
    document.getElementById('rep-takeaway').textContent = summary.executive_takeaway;
  } catch (err) {
    console.error('Executive summary error:', err);
  }
}

// Initial Bootstrapping
async function init() {
  setupNavigation();

  // Bind Buttons
  document.getElementById('btn-run-optimization')?.addEventListener('click', () => triggerOptimization());
  document.getElementById('btn-run-forecast')?.addEventListener('click', () => triggerForecasting());
  document.getElementById('btn-run-sim')?.addEventListener('click', () => triggerComparison());
  document.getElementById('config-form')?.addEventListener('submit', saveConfigForm);

  document.getElementById('scenario-select')?.addEventListener('change', (e) => {
    state.activeScenarioId = e.target.value;
    triggerOptimization(e.target.value);
  });

  // Step 1: Health & config
  await loadHealth();
  await loadConfig();

  // Step 2: Datasets & Scenarios
  await loadDemoDataset();
  await loadScenarios();

  // Step 3: Run initial forecast & optimization
  await refreshDashboard();
  if (state.scenarios.length > 0) {
    await triggerOptimization(state.scenarios[0].id);
    await triggerForecasting();
    await triggerComparison();
  }
}

window.addEventListener('DOMContentLoaded', init);
