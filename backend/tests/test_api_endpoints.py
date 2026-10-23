"""Integration test for FastAPI REST endpoints using TestClient with lifespan."""
import sys
import os
sys.path.insert(0, os.path.abspath("."))

from fastapi.testclient import TestClient
from app.main import app

def run_api_tests():
    with TestClient(app) as client:
        # 1. Health check
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        print("[PASS] /api/health passed")

        # 2. Detailed health
        res = client.get("/api/health/detailed")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        print("[PASS] /api/health/detailed passed")

        # 3. Config endpoint
        res = client.get("/api/config")
        assert res.status_code == 200
        config_data = res.json()
        assert "battery" in config_data
        assert config_data["battery"]["capacity_kwh"] > 0
        print("[PASS] /api/config GET passed")

        # 4. Datasets demo
        res = client.get("/api/datasets/demo?days=3")
        assert res.status_code == 200
        demo_json = res.json()
        assert "records" in demo_json
        assert len(demo_json["records"]) == 3 * 24
        dataset_id = demo_json["dataset_id"]
        print("[PASS] /api/datasets/demo passed")

        # 5. Scenarios list & presets
        res = client.get("/api/scenarios/presets")
        assert res.status_code == 200
        assert len(res.json()) >= 5
        print("[PASS] /api/scenarios/presets passed")

        res = client.get("/api/scenarios")
        assert res.status_code == 200
        scenarios = res.json()
        assert len(scenarios) > 0
        test_scenario_id = scenarios[0]["id"]
        print(f"[PASS] /api/scenarios passed (found {len(scenarios)} scenarios)")

        # 6. Forecasting endpoint
        res = client.post("/api/forecast", json={
            "dataset_id": dataset_id,
            "target": "generation",
            "model_name": "xgboost",
            "horizon_hours": 24,
        })
        assert res.status_code == 200
        f_json = res.json()
        assert len(f_json["points"]) == 24
        assert "mae" in f_json
        print(f"[PASS] /api/forecast passed (MAE: {f_json['mae']})")

        # 7. Optimization endpoint
        res = client.post("/api/optimize", json={
            "scenario_id": test_scenario_id,
            "use_forecast": True,
        })
        assert res.status_code == 200
        opt_json = res.json()
        assert opt_json["status"] == "done"
        assert len(opt_json["schedule"]) == 24
        assert opt_json["total_cost_inr"] is not None
        run_id = opt_json["run_id"]
        print(f"[PASS] /api/optimize passed (Cost: INR {opt_json['total_cost_inr']:.2f}, Util: {opt_json['renewable_utilization_pct']:.1f}%)")

        # 8. Baseline comparison
        res = client.post("/api/optimize/compare", json={
            "scenario_id": test_scenario_id,
        })
        assert res.status_code == 200
        comp_json = res.json()
        assert "savings" in comp_json
        assert "comparison_table" in comp_json
        print(f"[PASS] /api/optimize/compare passed (Savings: INR {comp_json['savings']['cost_saving_inr']:.2f})")

        # 9. KPI endpoint
        res = client.get("/api/optimize/kpi")
        assert res.status_code == 200
        kpi_json = res.json()
        assert "renewable_generation_kwh" in kpi_json
        print(f"[PASS] /api/optimize/kpi passed (Gen: {kpi_json['renewable_generation_kwh']} kWh)")

        # 10. Reports export
        res = client.get(f"/api/reports/export/csv/{run_id}")
        assert res.status_code == 200
        assert "Interval,Timestamp" in res.text
        print("[PASS] /api/reports/export/csv passed")

        res = client.get(f"/api/reports/summary/{run_id}")
        assert res.status_code == 200
        assert "executive_takeaway" in res.json()
        print("[PASS] /api/reports/summary passed")

        print("\nALL API INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_api_tests()
