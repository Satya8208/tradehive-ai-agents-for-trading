"""
Safe command runner for the Polymarket weather terminal.

The dashboard can start only allowlisted paper/research commands. Live weather
actions are represented by an audited kill-switch confirmation while live order
placement remains unreachable from this command bus.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = PROJECT_ROOT / "src" / "data" / "polymarket_trader" / "weather_control_room"
AUDIT_LOG = AUDIT_DIR / "action_audit.jsonl"


@dataclass
class WeatherCommandJob:
    job_id: str
    action: str
    status: str
    command: List[str] = field(default_factory=list)
    cwd: str = str(PROJECT_ROOT)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    returncode: Optional[int] = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    message: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class WeatherCommandRunner:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = Path(project_root)
        self._jobs: Dict[str, WeatherCommandJob] = {}
        self._lock = threading.Lock()

    def start(self, action: str) -> Dict[str, object]:
        action = (action or "").strip()
        if action == "kill-switch":
            return self._record_kill_switch().to_dict()

        command = self._command_for(action)
        job = WeatherCommandJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status="queued",
            command=command,
            cwd=str(self.project_root),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        self._write_audit(job, "queued")
        thread = threading.Thread(target=self._run_job, args=(job.job_id,), daemon=True)
        thread.start()
        return job.to_dict()

    def get(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
        self._write_audit(job, "started")

        timeout = self._timeout_for(job.action)
        try:
            completed = subprocess.run(
                job.command,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            with self._lock:
                job.returncode = completed.returncode
                job.stdout_tail = self._tail(completed.stdout)
                job.stderr_tail = self._tail(completed.stderr)
                job.status = "succeeded" if completed.returncode == 0 else "failed"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.message = "command finished"
        except subprocess.TimeoutExpired as exc:
            with self._lock:
                job.status = "timed_out"
                job.returncode = None
                job.stdout_tail = self._tail(exc.stdout or "")
                job.stderr_tail = self._tail(exc.stderr or "")
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.message = f"command timed out after {timeout}s"
        except OSError as exc:
            with self._lock:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.stderr_tail = f"{type(exc).__name__}: {exc}"
                job.message = "command launch failed"
        self._write_audit(job, job.status)

    def _record_kill_switch(self) -> WeatherCommandJob:
        job = WeatherCommandJob(
            job_id=str(uuid.uuid4()),
            action="kill-switch",
            status="succeeded",
            command=[],
            message=(
                "Weather live trading is hard-blocked. No authenticated cancel or order endpoint "
                "was called from the dashboard command bus."
            ),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        self._write_audit(job, "succeeded")
        return job

    @staticmethod
    def _command_for(action: str) -> List[str]:
        python = sys.executable
        commands = {
            "status-check": [
                python,
                "-m",
                "src.agents.polymarket_trader.paper_run",
                "--status",
                "--weather",
            ],
            "paper-cycle": [
                python,
                "-m",
                "src.agents.polymarket_trader.paper_run",
                "--weather",
                "--cycles",
                "1",
                "--markets",
                "10",
                "--weather-fetch-orderbook",
            ],
            "candidate-supply": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_candidate_supply_report",
                "--fetch-orderbook",
                "--orderbook-limit",
                "80",
            ],
            "known-outcome": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_known_outcome_scan",
                "--candidate-limit",
                "80",
                "--record-evidence",
            ],
            "resolution-labels": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_resolution_labels",
                "--limit",
                "500",
                "--replay",
            ],
            "replay-evidence": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_replay",
            ],
            "ladder": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_ladder_consistency_alpha",
                "--orderbook-limit",
                "80",
            ],
            "research-report": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_research_team",
                "--markets",
                "25",
            ],
            "test-run": [
                python,
                "-m",
                "src.agents.polymarket_trader.weather_test_run",
                "--known-outcome-limit",
                "50",
                "--replay",
            ],
        }
        if action not in commands:
            raise ValueError(f"Unsupported weather action: {action}")
        return commands[action]

    @staticmethod
    def _timeout_for(action: str) -> int:
        return {
            "status-check": 180,
            "paper-cycle": 900,
            "candidate-supply": 900,
            "known-outcome": 900,
            "resolution-labels": 900,
            "replay-evidence": 600,
            "ladder": 900,
            "research-report": 900,
            "test-run": 1200,
        }.get(action, 180)

    @staticmethod
    def _tail(text: str, limit: int = 6000) -> str:
        text = text or ""
        if len(text) <= limit:
            return text
        return text[-limit:]

    @staticmethod
    def _write_audit(job: WeatherCommandJob, event: str) -> None:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "weather_operator_command_audit_v1",
            "event": event,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "job": job.to_dict(),
        }
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
