"""
FastAPI backend for the Live Blackjack Table.

Single in-memory TableSession per process (this is a single-player desktop
app, not a multi-tenant server). Exposes state, event log, and action
endpoints. Also serves the static frontend.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

# Make 'src.' importable
_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from src.agents.blackjack.live_table.session import TableSession  # noqa: E402


app = FastAPI(title="Live Blackjack Table")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_session: TableSession = TableSession(
    num_seats=5,
    human_seat_index=2,
    starting_bankroll=1000.0,
    min_bet=25.0,
    max_bet=500.0,
)


# ---------- Request models ----------
class StartRoundBody(BaseModel):
    bet: float


class InsuranceBody(BaseModel):
    take: bool


class ActionBody(BaseModel):
    action: str  # "H", "S", "D", "P", "R"


# ---------- Routes ----------
@app.api_route("/", methods=["GET", "HEAD"])
def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "live_table.html"))


@app.get("/state")
def get_state() -> Dict[str, Any]:
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }


@app.post("/start_round")
def start_round(body: StartRoundBody) -> Dict[str, Any]:
    if body.bet <= 0:
        raise HTTPException(status_code=400, detail="bet must be > 0")
    try:
        _session.start_round(body.bet)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }


@app.post("/insurance")
def insurance(body: InsuranceBody) -> Dict[str, Any]:
    _session.resolve_insurance(body.take)
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }


@app.post("/action")
def action(body: ActionBody) -> Dict[str, Any]:
    valid = {"H", "S", "D", "P", "R"}
    if body.action.upper() not in valid:
        raise HTTPException(status_code=400, detail=f"action must be one of {valid}")
    _session.human_action(body.action.upper())
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }


@app.post("/next_round")
def next_round() -> Dict[str, Any]:
    _session.next_round()
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }


@app.post("/reset")
def reset_session() -> Dict[str, Any]:
    """Fresh session — new bankroll, new NPCs, new shoe."""
    global _session
    _session = TableSession(
        num_seats=5,
        human_seat_index=2,
        starting_bankroll=1000.0,
        min_bet=25.0,
        max_bet=500.0,
    )
    return {
        "snapshot": _session.snapshot(),
        "events": _session.drain_events(),
    }
