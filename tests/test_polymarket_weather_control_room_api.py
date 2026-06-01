from fastapi.testclient import TestClient

from src.dashboard.backend import polymarket_weather_api
from src.dashboard.backend.polymarket_weather_app import app


def test_weather_terminal_health_is_standalone_and_live_blocked():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "polymarket-weather-terminal"
    assert response.json()["live_trading"] == "hard_blocked"


def test_weather_control_room_snapshot_is_live_blocked_and_artifact_backed():
    client = TestClient(app)

    response = client.get("/api/polymarket/weather/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "weather_control_room_snapshot_v1"
    assert payload["live_status"]["status"] == "hard_blocked"
    assert "allow_live_weather_trading_false" in payload["live_status"]["blockers"]
    assert payload["live_status"]["release_certificate"]["present"] is False
    assert payload["qa_gate"]["release_certificate"]["status"] == "missing"
    assert payload["qa_gate"]["blocker_records"]
    assert payload["qa_gate"]["blocker_summary"]["by_category"]["live_safety"] >= 1
    assert payload["agent_team_plan"]["schema_version"] == "weather_agent_team_plan_v1"
    assert payload["agent_team_plan"]["review_output_contract"]["schema_version"] == "weather_system_review_v1"
    assert payload["agent_team_plan"]["pro_architecture_advice"]["status"] == "incorporated"
    assert "WeatherFeaturePacket" in payload["agent_team_plan"]["promotion_chain"]
    assert payload["agent_team_plan"]["teams"]["strategy_edge_team"]
    assert payload["agent_team_plan"]["teams"]["reviewer_builder_team"]
    assert payload["agent_team_plan"]["current_review_findings"]
    assert payload["summary"]["candidate_supply_state"] in {
        "missing",
        "candidate_supply_needed",
        "orderbook_coverage_needed",
        "candidate_supply_ready_for_alpha_lanes",
        "orderbook_depth_coverage_needed",
    }
    assert any(action["id"] == "paper-cycle" and action["wired"] for action in payload["actions"])
    action_ids = {action["id"] for action in payload["actions"] if action["wired"]}
    assert {"resolution-labels", "replay-evidence", "test-run"}.issubset(action_ids)

    rendered = str(payload).lower()
    assert "polymarket_private_key" not in rendered
    assert "private_key" not in rendered


def test_weather_release_endpoint_exposes_same_hard_gate():
    client = TestClient(app)

    response = client.get("/api/polymarket/weather/release")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "weather_live_eligibility_report_v1"
    assert payload["status"] == "hard_blocked"
    assert payload["release_certificate"]["required"] is True
    assert "allow_live_weather_trading_false" in payload["blockers"]


def test_weather_candidates_endpoint_reads_known_outcome_lane():
    client = TestClient(app)

    response = client.get("/api/polymarket/weather/candidates?lane=known_outcome&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "weather_control_room_candidates_v1"
    assert payload["lane"] == "known_outcome"
    assert isinstance(payload["items"], list)


class StubWeatherRunner:
    def __init__(self):
        self.started = []

    def start(self, action):
        self.started.append(action)
        return {
            "job_id": "job-1",
            "action": action,
            "status": "queued",
            "command": ["python", "-m", "safe"],
            "message": "stubbed",
        }

    def get(self, job_id):
        if job_id == "job-1":
            return {
                "job_id": "job-1",
                "action": self.started[-1] if self.started else "status-check",
                "status": "succeeded",
                "message": "stubbed complete",
            }
        return None


def test_weather_action_endpoint_uses_backend_command_bus(monkeypatch):
    runner = StubWeatherRunner()
    monkeypatch.setattr(polymarket_weather_api, "command_runner", runner)
    client = TestClient(app)

    start = client.post("/api/polymarket/weather/actions/status-check")
    assert start.status_code == 200
    assert start.json()["action"] == "status-check"
    assert runner.started == ["status-check"]

    label_start = client.post("/api/polymarket/weather/actions/resolution-labels")
    assert label_start.status_code == 200
    assert label_start.json()["action"] == "resolution-labels"
    assert runner.started[-1] == "resolution-labels"

    job = client.get("/api/polymarket/weather/actions/job-1")
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"
