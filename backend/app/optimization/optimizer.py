"""
EnerShare AI Energy Optimization Engine.
Uses SciPy HiGHS solver for linear programming optimization.
Implements full battery, grid, and energy-balance constraints.
Falls back to a deterministic greedy scheduler if needed.
"""
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
import math


# ── Data Classes ──────────────────────────────────────────────────────────────

class BatteryParams:
    def __init__(
        self,
        capacity_kwh: float = 100.0,
        min_soc_pct: float = 20.0,
        max_soc_pct: float = 95.0,
        initial_soc_pct: float = 50.0,
        charge_power_kw: float = 25.0,
        discharge_power_kw: float = 25.0,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
        reserve_pct: float = 20.0,
    ):
        self.capacity_kwh = capacity_kwh
        self.min_soc_pct = min_soc_pct
        self.max_soc_pct = max_soc_pct
        self.initial_soc_pct = initial_soc_pct
        self.charge_power_kw = charge_power_kw
        self.discharge_power_kw = discharge_power_kw
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.reserve_pct = reserve_pct

    @property
    def usable_min_kwh(self):
        return self.capacity_kwh * self.min_soc_pct / 100.0

    @property
    def usable_max_kwh(self):
        return self.capacity_kwh * self.max_soc_pct / 100.0

    @property
    def initial_kwh(self):
        return self.capacity_kwh * self.initial_soc_pct / 100.0

    @property
    def reserve_kwh(self):
        return self.capacity_kwh * self.reserve_pct / 100.0


class GridParams:
    def __init__(
        self,
        import_limit_kw: float = 100.0,
        export_limit_kw: float = 50.0,
        export_permitted: bool = False,
    ):
        self.import_limit_kw = import_limit_kw
        self.export_limit_kw = export_limit_kw
        self.export_permitted = export_permitted


class EVParams:
    def __init__(
        self,
        enabled: bool = False,
        charger_power_kw: float = 7.4,
        daily_demand_kwh: float = 30.0,
        window_start_hour: int = 18,
        window_end_hour: int = 22,
    ):
        self.enabled = enabled
        self.charger_power_kw = charger_power_kw
        self.daily_demand_kwh = daily_demand_kwh
        self.window_start_hour = window_start_hour
        self.window_end_hour = window_end_hour


class IntervalResult:
    """Stores results for a single optimization interval."""
    def __init__(self, interval: int, timestamp: datetime):
        self.interval = interval
        self.timestamp = timestamp
        self.renewable_gen_kwh: float = 0.0
        self.demand_kwh: float = 0.0
        self.renewable_used_kwh: float = 0.0
        self.battery_charge_kwh: float = 0.0
        self.battery_discharge_kwh: float = 0.0
        self.battery_soc_pct: float = 0.0
        self.grid_import_kwh: float = 0.0
        self.grid_export_kwh: float = 0.0
        self.curtailed_kwh: float = 0.0
        self.ev_served_kwh: float = 0.0
        self.unmet_demand_kwh: float = 0.0
        self.interval_cost_inr: float = 0.0
        self.action_summary: str = ""
        self.constraint_notes: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval": self.interval,
            "timestamp": self.timestamp.isoformat(),
            "renewable_gen_kwh": round(self.renewable_gen_kwh, 4),
            "demand_kwh": round(self.demand_kwh, 4),
            "renewable_used_kwh": round(self.renewable_used_kwh, 4),
            "battery_charge_kwh": round(self.battery_charge_kwh, 4),
            "battery_discharge_kwh": round(self.battery_discharge_kwh, 4),
            "battery_soc_pct": round(self.battery_soc_pct, 2),
            "grid_import_kwh": round(self.grid_import_kwh, 4),
            "grid_export_kwh": round(self.grid_export_kwh, 4),
            "curtailed_kwh": round(self.curtailed_kwh, 4),
            "ev_served_kwh": round(self.ev_served_kwh, 4),
            "unmet_demand_kwh": round(self.unmet_demand_kwh, 4),
            "interval_cost_inr": round(self.interval_cost_inr, 4),
            "action_summary": self.action_summary,
            "constraint_notes": self.constraint_notes,
        }


class OptimizationResult:
    def __init__(self):
        self.status: str = "pending"
        self.solver_used: str = "unknown"
        self.objective_value: Optional[float] = None
        self.schedule: List[IntervalResult] = []
        self.warnings: List[str] = []
        self.error_message: Optional[str] = None
        self.recommendation: str = ""

    @property
    def total_cost_inr(self):
        return sum(r.interval_cost_inr for r in self.schedule)

    @property
    def total_import_kwh(self):
        return sum(r.grid_import_kwh for r in self.schedule)

    @property
    def total_export_kwh(self):
        return sum(r.grid_export_kwh for r in self.schedule)

    @property
    def total_curtailed_kwh(self):
        return sum(r.curtailed_kwh for r in self.schedule)

    @property
    def total_unmet_kwh(self):
        return sum(r.unmet_demand_kwh for r in self.schedule)

    @property
    def total_renewable_gen_kwh(self):
        return sum(r.renewable_gen_kwh for r in self.schedule)

    @property
    def renewable_utilization_pct(self):
        gen = self.total_renewable_gen_kwh
        if gen <= 0:
            return 0.0
        used = sum(r.renewable_used_kwh + r.battery_charge_kwh for r in self.schedule)
        return min(100.0, max(0.0, used / gen * 100.0))


# ── LP Optimizer ──────────────────────────────────────────────────────────────

def optimize_lp(
    generation_kwh: List[float],
    demand_kwh: List[float],
    timestamps: List[datetime],
    import_tariffs: List[float],
    battery: BatteryParams,
    grid: GridParams,
    ev: EVParams,
    interval_hours: float = 1.0,
    export_tariff: float = 3.0,
    unmet_penalty: float = 500.0,
    curtail_penalty: float = 5.0,
    battery_cycle_cost: float = 0.5,
) -> OptimizationResult:
    """
    Full LP optimization using SciPy HiGHS solver.
    Minimizes: import_cost - export_revenue + unmet_penalty + curtail_penalty
               + battery_cycle_cost
    Subject to: energy balance, battery continuity & bounds, grid limits.
    Falls back to deterministic greedy scheduler on any solver failure.
    """
    result = OptimizationResult()
    result.solver_used = "highs_lp"
    n = len(generation_kwh)

    try:
        from scipy.optimize import linprog

        # 9 variables per interval i:
        # 0: ru_i, 1: bc_i, 2: bd_i, 3: gi_i, 4: ge_i, 5: cu_i, 6: ev_i, 7: um_i, 8: soc_i
        n_vars = 9 * n
        c = np.zeros(n_vars)
        bounds = []

        max_charge_energy = battery.charge_power_kw * interval_hours
        max_discharge_energy = battery.discharge_power_kw * interval_hours
        max_import_energy = grid.import_limit_kw * interval_hours
        max_export_energy = (grid.export_limit_kw * interval_hours) if grid.export_permitted else 0.0

        ev_available = [0.0] * n
        if ev.enabled:
            remaining_ev = ev.daily_demand_kwh
            for i, ts in enumerate(timestamps):
                h = ts.hour
                if ev.window_start_hour <= h < ev.window_end_hour and remaining_ev > 0:
                    avail = min(ev.charger_power_kw * interval_hours, remaining_ev)
                    ev_available[i] = avail

        for i in range(n):
            gen = float(generation_kwh[i])
            dem = float(demand_kwh[i])

            c[i * 9 + 1] = battery_cycle_cost  # bc
            c[i * 9 + 2] = battery_cycle_cost  # bd
            c[i * 9 + 3] = float(import_tariffs[i])  # gi
            c[i * 9 + 4] = -float(export_tariff) if grid.export_permitted else 0.0  # ge
            c[i * 9 + 5] = curtail_penalty  # cu
            c[i * 9 + 7] = unmet_penalty  # um

            bounds.extend([
                (0.0, gen),  # 0: ru
                (0.0, max_charge_energy),  # 1: bc
                (0.0, max_discharge_energy),  # 2: bd
                (0.0, max_import_energy),  # 3: gi
                (0.0, max_export_energy),  # 4: ge
                (0.0, gen),  # 5: cu
                (0.0, ev_available[i]),  # 6: ev
                (0.0, dem),  # 7: um
                (battery.usable_min_kwh, battery.usable_max_kwh),  # 8: soc
            ])

        # Equality constraints: 3 per interval = 3 * n
        A_eq = np.zeros((3 * n, n_vars))
        b_eq = np.zeros(3 * n)

        for i in range(n):
            gen = float(generation_kwh[i])
            dem = float(demand_kwh[i])

            # Eq 1: ru_i + bc_i + ge_i + cu_i = gen_i
            A_eq[i * 3 + 0, i * 9 + 0] = 1.0
            A_eq[i * 3 + 0, i * 9 + 1] = 1.0
            A_eq[i * 3 + 0, i * 9 + 4] = 1.0
            A_eq[i * 3 + 0, i * 9 + 5] = 1.0
            b_eq[i * 3 + 0] = gen

            # Eq 2: ru_i + bd_i + gi_i + um_i - ev_i = dem_i
            A_eq[i * 3 + 1, i * 9 + 0] = 1.0
            A_eq[i * 3 + 1, i * 9 + 2] = 1.0
            A_eq[i * 3 + 1, i * 9 + 3] = 1.0
            A_eq[i * 3 + 1, i * 9 + 7] = 1.0
            A_eq[i * 3 + 1, i * 9 + 6] = -1.0
            b_eq[i * 3 + 1] = dem

            # Eq 3: soc_i - soc_{i-1} - eta_ch * bc_i + (1/eta_dis) * bd_i = 0 (or = soc_0 for i=0)
            A_eq[i * 3 + 2, i * 9 + 8] = 1.0
            A_eq[i * 3 + 2, i * 9 + 1] = -battery.charge_efficiency
            A_eq[i * 3 + 2, i * 9 + 2] = 1.0 / battery.discharge_efficiency
            if i == 0:
                b_eq[i * 3 + 2] = battery.initial_kwh
            else:
                A_eq[i * 3 + 2, (i - 1) * 9 + 8] = -1.0
                b_eq[i * 3 + 2] = 0.0

        sol = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")

        if not sol.success:
            result.warnings.append(f"HiGHS solver reported: {sol.message}. Falling back to greedy scheduler.")
            return _greedy_fallback(
                generation_kwh, demand_kwh, timestamps, import_tariffs,
                battery, grid, ev, interval_hours, export_tariff
            )

        result.status = "optimal"
        result.objective_value = float(sol.fun)

        x = sol.x
        for i in range(n):
            ir = IntervalResult(i, timestamps[i])
            ir.renewable_gen_kwh = float(generation_kwh[i])
            ir.demand_kwh = float(demand_kwh[i])
            ir.renewable_used_kwh = max(0.0, float(x[i * 9 + 0]))
            ir.battery_charge_kwh = max(0.0, float(x[i * 9 + 1]))
            ir.battery_discharge_kwh = max(0.0, float(x[i * 9 + 2]))
            ir.grid_import_kwh = max(0.0, float(x[i * 9 + 3]))
            ir.grid_export_kwh = max(0.0, float(x[i * 9 + 4]))
            ir.curtailed_kwh = max(0.0, float(x[i * 9 + 5]))
            ir.ev_served_kwh = max(0.0, float(x[i * 9 + 6]))
            ir.unmet_demand_kwh = max(0.0, float(x[i * 9 + 7]))
            soc_kwh = max(0.0, float(x[i * 9 + 8]))
            ir.battery_soc_pct = soc_kwh / battery.capacity_kwh * 100.0

            ir.interval_cost_inr = (
                ir.grid_import_kwh * float(import_tariffs[i])
                - ir.grid_export_kwh * float(export_tariff)
                + ir.unmet_demand_kwh * unmet_penalty
            )
            ir.action_summary, ir.constraint_notes = _describe_action(ir, battery, grid)
            result.schedule.append(ir)

        result.recommendation = _generate_recommendation(result, battery, grid)
        return result

    except Exception as e:
        result.status = "error"
        result.error_message = f"Solver exception: {str(e)}"
        result.warnings.append("LP solver encountered an error. Falling back to greedy scheduler.")
        return _greedy_fallback(
            generation_kwh, demand_kwh, timestamps, import_tariffs,
            battery, grid, ev, interval_hours, export_tariff
        )


# ── Greedy Fallback ──────────────────────────────────────────────────────────

def _greedy_fallback(
    generation_kwh: List[float],
    demand_kwh: List[float],
    timestamps: List[datetime],
    import_tariffs: List[float],
    battery: BatteryParams,
    grid: GridParams,
    ev: EVParams,
    interval_hours: float = 1.0,
    export_tariff: float = 3.0,
) -> OptimizationResult:
    """
    Deterministic rule-based scheduler used as a robust baseline and fallback.
    Order of operations:
      1. Use renewable to serve current demand.
      2. If EV enabled and window active, serve EV from remaining surplus.
      3. Charge battery with any remaining surplus up to max_soc and power limits.
      4. Export remaining surplus to grid if permitted; else curtail.
      5. If deficit remains, discharge battery down to min_soc and power limits.
      6. Import from grid to cover any remaining deficit up to import_limit.
      7. Any leftover demand is recorded as unmet.
    """
    result = OptimizationResult()
    result.solver_used = "greedy_fallback"
    result.status = "fallback"
    result.warnings.append("Using deterministic greedy scheduler.")

    soc_kwh = battery.initial_kwh
    ev_remaining = ev.daily_demand_kwh if ev.enabled else 0.0

    for i, ts in enumerate(timestamps):
        gen = float(generation_kwh[i])
        dem = float(demand_kwh[i])
        tariff = float(import_tariffs[i])
        max_charge = battery.charge_power_kw * interval_hours
        max_discharge = battery.discharge_power_kw * interval_hours
        max_import = grid.import_limit_kw * interval_hours

        ir = IntervalResult(i, ts)
        ir.renewable_gen_kwh = gen
        ir.demand_kwh = dem

        surplus = gen
        demand_remaining = dem

        # 1. Renewable -> demand
        renew_to_demand = min(gen, demand_remaining)
        ir.renewable_used_kwh = renew_to_demand
        surplus -= renew_to_demand
        demand_remaining -= renew_to_demand

        # 2. EV from renewable during window
        if ev.enabled and ev_remaining > 0:
            h = ts.hour
            if ev.window_start_hour <= h < ev.window_end_hour:
                ev_avail = min(ev.charger_power_kw * interval_hours, ev_remaining)
                ev_from_renew = min(surplus, ev_avail)
                ir.ev_served_kwh = ev_from_renew
                surplus -= ev_from_renew
                ev_remaining -= ev_from_renew

        # 3. Charge battery with surplus renewable
        available_charge_capacity = battery.usable_max_kwh - soc_kwh
        charge_energy = min(surplus, max_charge, available_charge_capacity / battery.charge_efficiency)
        charge_energy = max(0.0, charge_energy)
        ir.battery_charge_kwh = charge_energy
        soc_kwh += charge_energy * battery.charge_efficiency
        surplus -= charge_energy

        # 4. Export or curtail remainder
        if surplus > 0.001:
            if grid.export_permitted:
                export_cap = grid.export_limit_kw * interval_hours
                export = min(surplus, export_cap)
                ir.grid_export_kwh = export
                surplus -= export
            ir.curtailed_kwh = max(0.0, surplus)
            surplus = 0.0

        # 5. Discharge battery for deficit
        if demand_remaining > 0.001:
            available_discharge = min(
                max_discharge,
                (soc_kwh - battery.usable_min_kwh) * battery.discharge_efficiency,
            )
            available_discharge = max(0.0, available_discharge)
            discharge = min(demand_remaining, available_discharge)
            ir.battery_discharge_kwh = discharge
            soc_kwh -= discharge / battery.discharge_efficiency
            demand_remaining -= discharge

        # 6. Grid import
        if demand_remaining > 0.001:
            imp = min(demand_remaining, max_import)
            ir.grid_import_kwh = imp
            demand_remaining -= imp

        # 7. Unmet demand
        ir.unmet_demand_kwh = max(0.0, demand_remaining)

        soc_kwh = max(battery.usable_min_kwh, min(battery.usable_max_kwh, soc_kwh))
        ir.battery_soc_pct = soc_kwh / battery.capacity_kwh * 100.0
        ir.interval_cost_inr = (
            ir.grid_import_kwh * tariff
            - ir.grid_export_kwh * export_tariff
        )
        ir.action_summary, ir.constraint_notes = _describe_action(ir, battery, grid)
        result.schedule.append(ir)

    result.recommendation = _generate_recommendation(result, battery, grid)
    return result


# ── Baseline Strategy ─────────────────────────────────────────────────────────

def run_baseline(
    generation_kwh: List[float],
    demand_kwh: List[float],
    timestamps: List[datetime],
    import_tariffs: List[float],
    battery: BatteryParams,
    grid: GridParams,
    ev: EVParams,
    interval_hours: float = 1.0,
    export_tariff: float = 3.0,
) -> OptimizationResult:
    """
    Simple baseline strategy.
    Used for comparison against the LP-optimized schedule.
    """
    result = _greedy_fallback(
        generation_kwh, demand_kwh, timestamps, import_tariffs,
        battery, grid, ev, interval_hours, export_tariff
    )
    result.solver_used = "simple_priority_baseline"
    result.status = "baseline_complete"
    result.warnings = []
    return result


# ── Action Description ────────────────────────────────────────────────────────

def _describe_action(ir: IntervalResult, battery: BatteryParams, grid: GridParams) -> Tuple[str, List[str]]:
    """Generate human-readable action summary and constraint notes."""
    actions = []
    notes = []

    if ir.renewable_used_kwh > 0.01:
        actions.append(f"Renewable -> Demand ({ir.renewable_used_kwh:.2f} kWh)")
    if ir.battery_charge_kwh > 0.01:
        actions.append(f"Charge battery ({ir.battery_charge_kwh:.2f} kWh, "
                       f"SOC->{ir.battery_soc_pct:.1f}%)")
    if ir.battery_discharge_kwh > 0.01:
        actions.append(f"Discharge battery ({ir.battery_discharge_kwh:.2f} kWh)")
    if ir.grid_import_kwh > 0.01:
        actions.append(f"Grid import ({ir.grid_import_kwh:.2f} kWh)")
    if ir.grid_export_kwh > 0.01:
        actions.append(f"Grid export ({ir.grid_export_kwh:.2f} kWh)")
    if ir.ev_served_kwh > 0.01:
        actions.append(f"EV charging ({ir.ev_served_kwh:.2f} kWh)")
    if ir.curtailed_kwh > 0.01:
        actions.append(f"Curtailed ({ir.curtailed_kwh:.2f} kWh, storage/export limit)")
    if ir.unmet_demand_kwh > 0.01:
        actions.append(f"[!] Unmet demand: {ir.unmet_demand_kwh:.2f} kWh")
        notes.append("Demand could not be fully served within grid and battery limits.")

    if not grid.export_permitted and ir.renewable_gen_kwh > ir.demand_kwh + 0.5:
        notes.append("Grid export disabled; surplus managed via storage or curtailment.")

    if ir.battery_soc_pct <= battery.min_soc_pct + 1.0:
        notes.append(f"Battery near minimum SOC ({battery.min_soc_pct}%); discharge restricted.")

    summary = " | ".join(actions) if actions else "Standby (no significant energy flow)"
    return summary, notes


def _generate_recommendation(result: OptimizationResult, battery: BatteryParams, grid: GridParams) -> str:
    """Generate a top-level recommendation from the optimization result."""
    gen = result.total_renewable_gen_kwh
    imp = result.total_import_kwh
    exp = result.total_export_kwh
    curtailed = result.total_curtailed_kwh
    unmet = result.total_unmet_kwh
    util = result.renewable_utilization_pct

    if unmet > 1.0:
        return (
            f"Warning: {unmet:.1f} kWh of demand could not be served. "
            "Consider increasing grid import limit or battery capacity."
        )
    if curtailed > 5.0 and not grid.export_permitted:
        return (
            f"{curtailed:.1f} kWh of renewable energy was curtailed because "
            "export is disabled and storage is insufficient. "
            "Consider enabling export or increasing battery capacity."
        )
    if imp > gen * 0.5:
        return (
            f"Grid import ({imp:.1f} kWh) is significant relative to generation ({gen:.1f} kWh). "
            "Increasing solar capacity or battery size could reduce import costs."
        )
    if util > 85:
        return (
            f"Excellent renewable utilization: {util:.1f}%. "
            f"The optimizer scheduled {imp:.1f} kWh of grid import and "
            f"managed {battery.capacity_kwh:.0f} kWh battery effectively."
        )
    return (
        f"Optimization complete. Renewable utilization: {util:.1f}%. "
        f"Grid import: {imp:.1f} kWh. "
        + (f"Grid export: {exp:.1f} kWh. " if exp > 0.01 else "")
        + (f"Curtailed: {curtailed:.1f} kWh." if curtailed > 0.01 else "")
    )
