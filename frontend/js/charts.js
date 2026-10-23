/**
 * EnerShare AI — Charts & Visualization Engine
 * Clean, professional enterprise white-theme Chart.js configuration.
 */

const chartRegistry = {};

function destroyChart(id) {
  if (chartRegistry[id]) {
    chartRegistry[id].destroy();
    delete chartRegistry[id];
  }
}

const commonOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'top',
      labels: {
        color: '#334155',
        font: { size: 12, weight: 600, family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
        padding: 16,
        usePointStyle: true,
        pointStyle: 'circle',
      },
    },
    tooltip: {
      backgroundColor: '#ffffff',
      titleColor: '#0f172a',
      bodyColor: '#334155',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      padding: 12,
      boxPadding: 4,
      usePointStyle: true,
      shadowOffsetX: 0,
      shadowOffsetY: 4,
      shadowBlur: 10,
      shadowColor: 'rgba(0, 0, 0, 0.1)',
    },
  },
  scales: {
    x: {
      grid: { color: '#f1f5f9' },
      ticks: { color: '#64748b', font: { size: 11 } },
    },
    y: {
      grid: { color: '#f1f5f9' },
      ticks: { color: '#64748b', font: { size: 11 } },
    },
  },
};

export const Charts = {
  // 1. Dashboard Energy Balance Chart
  renderEnergyBalance(canvasId, schedule) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return;

    const labels = schedule.map(s => {
      const d = new Date(s.timestamp);
      return `${String(d.getHours()).padStart(2, '0')}:00`;
    });

    const solar = schedule.map(s => s.renewable_gen_kwh);
    const demand = schedule.map(s => s.demand_kwh);
    const batteryCharge = schedule.map(s => s.battery_charge_kwh);
    const batteryDischarge = schedule.map(s => s.battery_discharge_kwh);
    const gridImport = schedule.map(s => s.grid_import_kwh);
    const gridExport = schedule.map(s => s.grid_export_kwh);

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Solar Gen (kWh)',
            data: solar,
            borderColor: '#059669',
            backgroundColor: 'rgba(5, 150, 105, 0.08)',
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 0,
            pointHoverRadius: 5,
          },
          {
            label: 'Site Demand (kWh)',
            data: demand,
            borderColor: '#0284c7',
            borderDash: [5, 4],
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 5,
          },
          {
            label: 'Battery Charge (kWh)',
            data: batteryCharge,
            borderColor: '#d97706',
            backgroundColor: 'rgba(217, 119, 6, 0.1)',
            fill: false,
            tension: 0.25,
            borderWidth: 2,
            pointRadius: 0,
          },
          {
            label: 'Battery Discharge (kWh)',
            data: batteryDischarge,
            borderColor: '#f59e0b',
            borderDash: [3, 3],
            tension: 0.25,
            borderWidth: 2,
            pointRadius: 0,
          },
          {
            label: 'Grid Import (kWh)',
            data: gridImport,
            borderColor: '#6366f1',
            tension: 0.25,
            borderWidth: 1.8,
            pointRadius: 0,
          },
          {
            label: 'Grid Export (kWh)',
            data: gridExport,
            borderColor: '#2563eb',
            tension: 0.25,
            borderWidth: 1.8,
            pointRadius: 0,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b', font: { size: 11 } },
          },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b', font: { size: 11 } },
            title: { display: true, text: 'Energy Flow (kWh)', color: '#475569', font: { size: 12, weight: 600 } },
          },
        },
      },
    });
  },

  // 2. Battery SOC Trajectory Chart
  renderBatterySoc(canvasId, schedule, minSoc = 20, maxSoc = 95) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return;

    const labels = schedule.map(s => {
      const d = new Date(s.timestamp);
      return `${String(d.getHours()).padStart(2, '0')}:00`;
    });
    const socValues = schedule.map(s => s.battery_soc_pct);

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Battery State of Charge (%)',
            data: socValues,
            borderColor: '#d97706',
            backgroundColor: 'rgba(217, 119, 6, 0.08)',
            fill: true,
            tension: 0.3,
            borderWidth: 2.5,
            pointRadius: 3,
            pointBackgroundColor: '#d97706',
          },
          {
            label: 'Min Safe Threshold (20%)',
            data: Array(labels.length).fill(minSoc),
            borderColor: '#e11d48',
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          },
          {
            label: 'Max Safe Threshold (95%)',
            data: Array(labels.length).fill(maxSoc),
            borderColor: '#059669',
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b' },
          },
          y: {
            min: 0,
            max: 100,
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b' },
            title: { display: true, text: 'Battery SOC (%)', color: '#475569', font: { size: 12, weight: 600 } },
          },
        },
      },
    });
  },

  // 3. AI Forecast vs Actual Chart
  renderForecast(canvasId, points, targetName = 'Solar PV') {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return;

    const labels = points.map(p => {
      const d = new Date(p.timestamp);
      return `${String(d.getHours()).padStart(2, '0')}:00`;
    });
    const predicted = points.map(p => p.predicted);
    const actual = points.map(p => p.actual !== null ? p.actual : null);

    const datasets = [
      {
        label: `AI Predicted ${targetName} (kWh)`,
        data: predicted,
        borderColor: '#059669',
        backgroundColor: 'rgba(5, 150, 105, 0.08)',
        fill: true,
        tension: 0.35,
        borderWidth: 2.5,
        pointRadius: 2,
      },
    ];

    if (actual.some(v => v !== null)) {
      datasets.push({
        label: `Actual / Measured (kWh)`,
        data: actual,
        borderColor: '#64748b',
        borderDash: [5, 4],
        tension: 0.35,
        borderWidth: 2,
        fill: false,
        pointRadius: 0,
      });
    }

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        ...commonOptions,
        scales: {
          x: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b' },
          },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b' },
            title: { display: true, text: 'Energy (kWh)', color: '#475569', font: { size: 12, weight: 600 } },
          },
        },
      },
    });
  },

  // 4. Comparison Bar Chart
  renderComparisonBars(canvasId, baseline, optimized) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return;

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Operating Cost (₹)', 'Grid Import (kWh)', 'Curtailed (kWh)'],
        datasets: [
          {
            label: 'Baseline (Heuristic Dispatch)',
            data: [baseline.total_cost_inr, baseline.total_import_kwh, baseline.total_curtailed_kwh],
            backgroundColor: '#cbd5e1',
            borderColor: '#94a3b8',
            borderWidth: 1,
            borderRadius: 6,
          },
          {
            label: 'EnerShare AI (Optimized)',
            data: [optimized.total_cost_inr, optimized.total_import_kwh, optimized.total_curtailed_kwh],
            backgroundColor: '#059669',
            borderColor: '#047857',
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: '#334155', font: { size: 12, weight: 600 } },
          },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { color: '#64748b' },
          },
        },
      },
    });
  },
};
