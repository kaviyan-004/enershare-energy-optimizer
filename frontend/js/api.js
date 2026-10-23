/**
 * EnerShare AI — Frontend API Client
 * Seamlessly interfaces with the FastAPI backend REST endpoints.
 */

const API_BASE = '/api';

export const API = {
  // System Health
  async getHealth() {
    const res = await fetch(`${API_BASE}/health/detailed`);
    return res.json();
  },

  // Site Configuration
  async getConfig() {
    const res = await fetch(`${API_BASE}/config`);
    return res.json();
  },

  async updateConfig(configData) {
    const res = await fetch(`${API_BASE}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(configData),
    });
    return res.json();
  },

  // Datasets
  async getDemoDataset(days = 7) {
    const res = await fetch(`${API_BASE}/datasets/demo?days=${days}`);
    return res.json();
  },

  // Scenarios
  async getPresets() {
    const res = await fetch(`${API_BASE}/scenarios/presets`);
    return res.json();
  },

  async getScenarios() {
    const res = await fetch(`${API_BASE}/scenarios`);
    return res.json();
  },

  async createScenario(scenarioData) {
    const res = await fetch(`${API_BASE}/scenarios`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scenarioData),
    });
    return res.json();
  },

  // Forecasting
  async runForecast(datasetId, target = 'generation', modelName = 'xgboost', horizonHours = 24) {
    const res = await fetch(`${API_BASE}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: datasetId,
        target: target,
        model_name: modelName,
        horizon_hours: horizonHours,
      }),
    });
    return res.json();
  },

  // Optimization
  async runOptimization(scenarioId, useForecast = true) {
    const res = await fetch(`${API_BASE}/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario_id: scenarioId,
        use_forecast: useForecast,
      }),
    });
    return res.json();
  },

  async runComparison(scenarioId) {
    const res = await fetch(`${API_BASE}/optimize/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario_id: scenarioId,
      }),
    });
    return res.json();
  },

  async getKPISummary() {
    const res = await fetch(`${API_BASE}/optimize/kpi`);
    return res.json();
  },

  async getRunDetails(runId) {
    const res = await fetch(`${API_BASE}/optimize/runs/${runId}`);
    return res.json();
  },

  // Reports
  async getExecutiveSummary(runId) {
    const res = await fetch(`${API_BASE}/reports/summary/${runId}`);
    return res.json();
  },

  getCSVExportUrl(runId) {
    return `${API_BASE}/reports/export/csv/${runId}`;
  },

  getJSONExportUrl(runId) {
    return `${API_BASE}/reports/export/json/${runId}`;
  },
};
