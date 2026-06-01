"""
FastAPI router for the Polymarket weather control room.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.dashboard.backend.polymarket_weather_actions import WeatherCommandRunner
from src.dashboard.backend.polymarket_weather_store import WeatherControlRoomStore


router = APIRouter(prefix="/api/polymarket/weather", tags=["polymarket-weather"])
store = WeatherControlRoomStore()
command_runner = WeatherCommandRunner()


@router.get("/status")
async def weather_status():
    return store.status()


@router.get("/snapshot")
async def weather_snapshot():
    return store.snapshot()


@router.get("/reports")
async def weather_reports():
    snapshot = store.snapshot()
    return {
        "schema_version": "weather_control_room_reports_v1",
        "generated_at": snapshot["generated_at"],
        "artifacts": snapshot["artifacts"],
        "reports": snapshot["reports"],
    }


@router.get("/release")
async def weather_release():
    return store.release()


@router.get("/candidates")
async def weather_candidates(
    lane: str = Query("known_outcome"),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {
        "schema_version": "weather_control_room_candidates_v1",
        "lane": lane,
        "status_filter": status,
        "items": store.candidates(lane=lane, status=status, limit=limit),
    }


@router.get("/evidence/tail")
async def weather_evidence_tail(
    stream: str = Query("market_tape"),
    limit: int = Query(100, ge=1, le=500),
):
    return store.tail_stream(stream=stream, limit=limit)


@router.post("/actions/{action}")
async def start_weather_action(action: str):
    try:
        return command_runner.start(action)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/actions/status-check")
async def start_status_check():
    return command_runner.start("status-check")


@router.post("/actions/paper-cycle")
async def start_paper_cycle():
    return command_runner.start("paper-cycle")


@router.post("/actions/candidate-supply")
async def start_candidate_supply():
    return command_runner.start("candidate-supply")


@router.post("/actions/known-outcome")
async def start_known_outcome():
    return command_runner.start("known-outcome")


@router.post("/actions/resolution-labels")
async def start_resolution_labels():
    return command_runner.start("resolution-labels")


@router.post("/actions/replay-evidence")
async def start_replay_evidence():
    return command_runner.start("replay-evidence")


@router.post("/actions/ladder")
async def start_ladder():
    return command_runner.start("ladder")


@router.post("/actions/research-report")
async def start_research_report():
    return command_runner.start("research-report")


@router.post("/actions/kill-switch")
async def start_kill_switch():
    return command_runner.start("kill-switch")


@router.get("/actions/{job_id}")
async def get_weather_action(job_id: str):
    job = command_runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Weather action job not found")
    return job
