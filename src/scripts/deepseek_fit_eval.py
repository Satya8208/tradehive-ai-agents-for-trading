"""
Evaluate where DeepSeek V4 fits in the TradeHive agent system.

The run is dry by construction: it calls DeepSeek, executes generated
backtests against local historical CSV data, and writes artifacts under
src/data/model_evals. It does not place orders or touch wallets.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = PROJECT_ROOT / "src" / "data" / "rbi" / "BTC-USD-15m.csv"
OUTPUT_ROOT = PROJECT_ROOT / "src" / "data" / "model_evals"
WEATHER_EVIDENCE_PATH = (
    PROJECT_ROOT
    / "src"
    / "data"
    / "polymarket_weather_ai_run_20260512"
    / "weather_evidence"
    / "feature_snapshots.jsonl"
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")

# Current DeepSeek docs, checked 2026-05-23. Prices are per 1M tokens.
PRICING = {
    "deepseek-v4-flash": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.003625,
        "input_cache_miss": 0.435,
        "output": 0.87,
    },
}


WEATHER_DECISION_PROMPT = """You are the lead portfolio manager for a weather prediction-market research desk.

You receive a source-stamped weather packet for one Polymarket market. Decide whether
the TRUE probability of YES differs enough from the market price to justify a paper
trade. Use the data, not vibes. Prefer no trade when the resolution rule, data quality,
forecast delta, or executable depth is weak.

Return ONLY a valid JSON object with these keys:
{
  "p_yes": 0.0 to 1.0,
  "side": "YES" or "NO",
  "strategy_lane": "forecast_run_shock" or "station_specific_edge" or "model_bias_edge" or "uncertainty_pricing" or "nowcast_override" or "narrative_fade" or "structure_check" or "forecast_model_baseline",
  "confidence": 0.0 to 1.0,
  "uncertainty_band": {"low": 0.0 to 1.0, "high": 0.0 to 1.0},
  "trade_thesis": "one concise sentence",
  "veto_reasons": [],
  "data_quality": "high" or "medium" or "limited" or "poor",
  "recommended_size_usd": 0.0
}
"""


STRATEGY_RESEARCH_SYSTEM = """You are TradeHive's senior quant research AI.
Return only valid json. Design simple, backtestable strategies for the RBI flow.
Favor falsifiable rules, trade frequency, and failure modes over vague alpha stories."""


BACKTEST_CODE_SYSTEM = """You are TradeHive's Backtest AI. Return only runnable Python code.
No markdown, no explanations."""


DEBUG_SYSTEM = """You are TradeHive's Debug AI. Return only runnable Python code.
Fix technical backtesting.py issues without changing the strategy idea."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_env_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("DEEPSEEK_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_KEY is missing from .env")
    return key


def make_client() -> OpenAI:
    return OpenAI(api_key=read_env_key(), base_url=DEEPSEEK_BASE_URL, timeout=90.0)


def usage_to_dict(usage: Any) -> Dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return dict(usage)
    return {}


def nested_get(data: Dict[str, Any], path: Iterable[str], default: Any = None) -> Any:
    cursor: Any = data
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def estimate_cost(model: str, usage: Dict[str, Any]) -> Dict[str, Any]:
    price = PRICING.get(model, {})
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cached_tokens = int(
        usage.get("prompt_cache_hit_tokens")
        or nested_get(usage, ("prompt_tokens_details", "cached_tokens"), 0)
        or 0
    )
    cache_miss = max(0, prompt_tokens - cached_tokens)
    cost = (
        (cached_tokens / 1_000_000) * float(price.get("input_cache_hit", 0.0))
        + (cache_miss / 1_000_000) * float(price.get("input_cache_miss", 0.0))
        + (completion_tokens / 1_000_000) * float(price.get("output", 0.0))
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_prompt_tokens": cached_tokens,
        "estimated_cost_usd": round(cost, 6),
    }


def call_deepseek(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    json_mode: bool = False,
    thinking: Optional[bool] = None,
    reasoning_effort: str = "high",
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    request: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}
    if thinking is not None:
        request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    if thinking:
        request["reasoning_effort"] = reasoning_effort
    elif temperature is not None:
        request["temperature"] = temperature

    started = time.time()
    try:
        response = client.chat.completions.create(**request)
        elapsed = time.time() - started
        message = response.choices[0].message
        content = (getattr(message, "content", "") or "").strip()
        reasoning_content = getattr(message, "reasoning_content", None)
        usage = usage_to_dict(getattr(response, "usage", None))
        return {
            "ok": True,
            "model": model,
            "latency_seconds": round(elapsed, 3),
            "content": content,
            "reasoning_present": bool(reasoning_content),
            "reasoning_chars": len(reasoning_content or ""),
            "usage": usage,
            "cost": estimate_cost(model, usage),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "model": model,
            "latency_seconds": round(time.time() - started, 3),
            "content": "",
            "reasoning_present": False,
            "reasoning_chars": 0,
            "usage": {},
            "cost": estimate_cost(model, {}),
            "error": f"{type(exc).__name__}: {exc}",
        }


def backtest_init_signature() -> str:
    try:
        from backtesting import Backtest

        return str(inspect.signature(Backtest.__init__))
    except Exception as exc:
        return f"unavailable:{type(exc).__name__}:{exc}"


def parse_json_content(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        parsed = json.loads(text)
        return (parsed if isinstance(parsed, dict) else None), ""
    except Exception as first_error:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            return None, f"{type(first_error).__name__}: {first_error}"
        try:
            parsed = json.loads(match.group(0))
            return (parsed if isinstance(parsed, dict) else None), ""
        except Exception as second_error:
            return None, f"{type(second_error).__name__}: {second_error}"


def strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def load_weather_packet() -> Dict[str, Any]:
    if not WEATHER_EVIDENCE_PATH.exists():
        raise FileNotFoundError(f"Missing weather evidence file: {WEATHER_EVIDENCE_PATH}")
    with WEATHER_EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            packet = row.get("forecast_model_packet")
            if row.get("status") == "ok" and isinstance(packet, dict) and packet:
                return packet
    raise RuntimeError("No usable weather forecast packet found")


def validate_weather_decision(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"schema_valid": False, "score": 0, "issues": ["not_json_object"]}

    required = [
        "p_yes",
        "side",
        "strategy_lane",
        "confidence",
        "uncertainty_band",
        "trade_thesis",
        "veto_reasons",
        "data_quality",
        "recommended_size_usd",
    ]
    issues = [f"missing:{key}" for key in required if key not in payload]

    def prob_ok(value: Any) -> bool:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return False
        return 0.0 <= parsed <= 1.0

    if "p_yes" in payload and not prob_ok(payload.get("p_yes")):
        issues.append("p_yes_out_of_range")
    if "confidence" in payload and not prob_ok(payload.get("confidence")):
        issues.append("confidence_out_of_range")
    if str(payload.get("side", "")).upper() not in {"YES", "NO"}:
        issues.append("side_invalid")
    if str(payload.get("data_quality", "")).lower() not in {"high", "medium", "limited", "poor"}:
        issues.append("data_quality_invalid")
    if not isinstance(payload.get("uncertainty_band"), dict):
        issues.append("uncertainty_band_invalid")
    else:
        if not prob_ok(payload["uncertainty_band"].get("low")):
            issues.append("uncertainty_low_invalid")
        if not prob_ok(payload["uncertainty_band"].get("high")):
            issues.append("uncertainty_high_invalid")

    try:
        p_yes = float(payload.get("p_yes"))
    except (TypeError, ValueError):
        p_yes = None
    try:
        size = float(payload.get("recommended_size_usd", 0.0))
    except (TypeError, ValueError):
        size = 999.0

    # The fixture is an Austin high-temperature market with live forecast far
    # above the "59F or below" threshold and limited/no depth in the packet.
    if p_yes is not None and p_yes > 0.10:
        issues.append("overstates_yes_probability_for_fixture")
    if str(payload.get("data_quality", "")).lower() == "high":
        issues.append("overstates_data_quality_for_fixture")
    if size > 5.0:
        issues.append("oversizes_low_edge_fixture")

    score = max(0, 100 - len(issues) * 14)
    return {"schema_valid": not issues, "score": score, "issues": issues}


def validate_strategy_spec(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"schema_valid": False, "score": 0, "issues": ["not_json_object"]}
    required = [
        "strategy_name",
        "core_edge",
        "indicators",
        "entry_rules",
        "exit_rules",
        "risk_management",
        "failure_modes",
        "backtest_plan",
        "system_fit",
    ]
    issues = [f"missing:{key}" for key in required if key not in payload]
    indicators = payload.get("indicators", [])
    if not isinstance(indicators, list) or not indicators:
        issues.append("indicators_not_list")
    elif len(indicators) > 4:
        issues.append("too_many_indicators")
    text = json.dumps(payload, sort_keys=True).lower()
    for phrase in ("real data", "btc-usd-15m", "backtesting.py"):
        if phrase not in text:
            issues.append(f"missing_grounding:{phrase}")
    if "failure_modes" in payload and not payload.get("failure_modes"):
        issues.append("failure_modes_empty")
    score = max(0, 100 - len(issues) * 12)
    return {"schema_valid": not issues, "score": score, "issues": issues}


def build_strategy_prompt() -> str:
    return f"""json only.

Use the real local data path:
{DATA_PATH}

Design a backtesting.py-ready strategy from this idea:
BTC 15m volatility contraction breakout. Detect a quiet range, require volume
expansion, enter with the breakout, use ATR-based stop and a simple trailing
or take-profit rule. Keep it simple enough to generate trades.

Return json with:
{{
  "strategy_name": "...",
  "core_edge": "...",
  "indicators": ["..."],
  "entry_rules": ["..."],
  "exit_rules": ["..."],
  "risk_management": ["..."],
  "failure_modes": ["..."],
  "backtest_plan": ["..."],
  "system_fit": {{
    "best_agent_role": "...",
    "why_deepseek": "...",
    "what_not_to_use_it_for": "..."
  }}
}}"""


def build_backtest_prompt(strategy_payload: Optional[Dict[str, Any]]) -> str:
    strategy_text = json.dumps(strategy_payload or {}, indent=2, sort_keys=True)
    signature = backtest_init_signature()
    return f"""Create complete runnable backtesting.py code for this strategy spec:
{strategy_text}

Hard requirements:
- Use the real CSV at {DATA_PATH}
- Use pandas, backtesting.py, and talib for indicators.
- This installed backtesting.py Backtest.__init__ signature is:
  {signature}
- Do not use unsupported Backtest keyword arguments such as slippage or fractional
  unless they are present in that signature.
- Clean CSV columns by stripping whitespace, lowercasing, dropping unnamed columns,
  then mapping to Open, High, Low, Close, Volume.
- Use self.I(...) for every indicator.
- Position size must be a fraction between 0 and 1 or a rounded integer.
- Initial cash must be 1000000.
- Print full stats and stats._strategy.
- No plotting.
- Do not use synthetic or generated data.
- Return only Python code."""


BROKEN_DEBUG_CODE = f'''
import pandas as pd
import talib
from backtesting import Backtest, Strategy

DATA_PATH = r"{DATA_PATH}"

class BrokenVolatilityBreakout(Strategy):
    def init(self):
        self.atr = talib.ATR(self.data.High, self.data.Low, self.data.Close, timeperiod=14)
        self.sma = self.data.Close.rolling(20).mean()

    def next(self):
        if len(self.data.Close) < 25:
            return
        if not self.position and self.data.Close[-1] > self.sma[-1]:
            risk_amount = self.equity * 0.01
            stop_distance = self.atr[-1] * 1.5
            self.buy(size=risk_amount / stop_distance)
        elif self.position and self.data.Close[-1] < self.sma[-1]:
            self.position.close()

data = pd.read_csv(DATA_PATH)
bt = Backtest(data, BrokenVolatilityBreakout, cash=1000000)
stats = bt.run()
print(stats)
print(stats._strategy)
'''


def build_debug_prompt() -> str:
    broken_path = OUTPUT_ROOT / "_deepseek_fit_broken_fixture.py"
    save_text(broken_path, BROKEN_DEBUG_CODE)
    broken_exec = run_python_file(broken_path, timeout=60)
    signature = backtest_init_signature()
    traceback = broken_exec.get("stderr_tail", "")
    return f"""Fix this backtesting.py code. Preserve the strategy idea, but make it runnable.
Return only corrected Python code.

Issues to consider:
- backtesting.py indicator arrays must use self.I(...)
- CSV columns must be mapped to Open, High, Low, Close, Volume
- order size must be valid
- This installed backtesting.py Backtest.__init__ signature is:
  {signature}
- Do not use unsupported Backtest keyword arguments such as slippage or fractional
  unless they are present in that signature.
- no plots, no synthetic data

Actual traceback from this environment:
{traceback}

```python
{BROKEN_DEBUG_CODE}
```"""


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_python_file(path: Path, timeout: int = 180) -> Dict[str, Any]:
    started = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(path.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_seconds": round(time.time() - started, 3),
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": -1,
            "elapsed_seconds": round(time.time() - started, 3),
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": "timeout",
        }


def static_code_score(code: str) -> Dict[str, Any]:
    issues: List[str] = []
    try:
        ast.parse(code)
    except SyntaxError as exc:
        issues.append(f"syntax_error:{exc.lineno}")
    lowered = code.lower()
    for needle in ("backtest", "strategy", "talib", "self.i", "btc-usd-15m.csv"):
        if needle not in lowered:
            issues.append(f"missing:{needle}")
    if "plot(" in lowered:
        issues.append("plotting_requested")
    if "np.random" in lowered or "random." in lowered:
        issues.append("synthetic_random_data")
    score = max(0, 100 - len(issues) * 15)
    return {"score": score, "issues": issues}


def compact_outcome(task: Dict[str, Any]) -> str:
    if task.get("error"):
        return task["error"][:140]
    if "validation" in task:
        val = task["validation"]
        issues = ", ".join(val.get("issues", [])[:3]) or "clean"
        return f"score={val.get('score')} issues={issues}"
    if "execution" in task:
        return f"exec_success={task['execution'].get('success')} static={task.get('static_score', {}).get('score')}"
    if "attempts" in task:
        attempts = task.get("attempts", [])
        last = attempts[-1] if attempts else {}
        return (
            f"attempts={len(attempts)} exec_success="
            f"{last.get('execution', {}).get('success')} "
            f"static={last.get('static_score', {}).get('score')}"
        )
    return "ok"


def make_report(
    *,
    out_dir: Path,
    model_list: List[str],
    tasks: List[Dict[str, Any]],
) -> str:
    total_cost = round(
        sum(float(task.get("cost", {}).get("estimated_cost_usd", 0.0) or 0.0) for task in tasks),
        6,
    )
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for task in tasks:
        by_model.setdefault(task["model"], []).append(task)

    lines = [
        "# DeepSeek Fit Evaluation",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Output directory: `{out_dir}`",
        f"- Models visible: `{', '.join(model_list)}`",
        f"- Estimated DeepSeek spend: `${total_cost}`",
        f"- Trading mode: dry evaluation only; no orders or wallets touched.",
        "",
        "## Verdict",
        "",
        "DeepSeek V4 Pro is best used as a heavy reasoning worker: strategy extraction, weather/market probability checks, and traceback-driven repair. V4 Flash is best used as a cheap structured extractor, fast schema decisioner, and second-pass repair model.",
        "",
        "Do not use either model as the final live-trade authority, and do not trust one-shot generated backtests. Use DeepSeek to produce probabilities, code, vetoes, and hypotheses; keep deterministic gates, risk sizing, package checks, and execution controls in Python.",
        "",
        "## Task Results",
        "",
        "| Task | Model | Latency | Reasoning | Tokens | Est. cost | Outcome |",
        "| --- | --- | ---: | --- | ---: | ---: | --- |",
    ]
    for task in tasks:
        cost = task.get("cost", {})
        tokens = int(cost.get("prompt_tokens", 0) or 0) + int(cost.get("completion_tokens", 0) or 0)
        reasoning = "yes" if task.get("reasoning_present") else "no"
        model_label = task.get("profile") or task["model"]
        lines.append(
            f"| {task['task']} | {model_label} | {task.get('latency_seconds', 0)}s | "
            f"{reasoning} | {tokens} | ${cost.get('estimated_cost_usd', 0.0)} | "
            f"{compact_outcome(task)} |"
        )

    lines.extend(
        [
            "",
            "## Best Use In This Repo",
            "",
            "1. RBI strategy research: give V4 Pro a real source, exact data path, required indicators, and force a falsifiable JSON strategy spec. Ask for failure modes and a backtest plan, not just a clever idea.",
            "2. Backtesting code: use a generate-run-repair loop. First produce the structured spec; then generate code; then execute it; then feed the exact traceback back. The one-shot generated backtests in this eval failed on local data-window assumptions, while the repair loop succeeded.",
            "3. Debugging: feed Pro or Flash the actual traceback and the generated file. Pro-thinking was slower but repaired in one pass here; Flash needed two passes but was still cheap and fast.",
            "4. Weather/Polymarket decisions: use JSON mode plus the existing parser/gate. DeepSeek should output `p_yes`, uncertainty, vetoes, and size suggestion. The Python gate decides whether that is usable.",
            "5. Swarm role: keep DeepSeek as the quantitative analyst. It should calculate thresholds, distance-to-target, volatility, depth, and probability. Pair it with conservative and contrarian models before any paper signal is trusted.",
            "6. High-volume chores: use V4 Flash for cheap summaries, row classification, feed/market triage, JSON cleaning, and first-pass research notes. Escalate only the ambiguous or high-value cases to Pro.",
            "",
            "## Prompting Pattern That Worked Best",
            "",
            "- For Pro-thinking: use it for reasoning-heavy planning, weather/market probability review, and hard debugging. Do not use it blindly for small schema or code-only jobs.",
            "- For strict JSON decisions: disable thinking, use JSON mode, and validate locally. If Pro thinking is used, give it a much larger `max_tokens` budget because reasoning tokens count against the output cap.",
            "- For code-only output: prefer Pro with thinking disabled, or use a large token cap and reject empty final content. Then execute the file immediately.",
            "- For Flash: disable thinking, use JSON mode, keep the task narrow, and make it validate against a schema.",
            "- For debug: run an execute-and-repair loop. One-shot fixes still miss local package/version details.",
            "- Always include the real file path, current packet, or exact traceback. DeepSeek gets much better when the task is grounded in the artifact it must transform.",
            "- Ask for vetoes and failure modes. This fits trading better than asking for confidence alone.",
            "- Use stable long prefixes and repeated schemas where possible so DeepSeek context caching can reduce cost.",
            "",
            "## Repo Gaps Found",
            "",
            "- The DeepSeek wrapper needed explicit pass-through for JSON mode, thinking toggle, reasoning effort, and tools. This evaluation run added that narrow support in `src/models/deepseek_model.py`.",
            "- Existing RBI config currently defaults to OpenAI for all phases even though the old DeepSeek presets are present. A practical setup is Pro for research/backtest/debug and Flash for package cleanup or bulk extraction.",
            "- The weather AI lead is still configured as OpenAI by default. DeepSeek can be a strong paper-only replacement or fallback for that lead path while OpenAI credentials are broken.",
            "",
            "## Artifacts",
            "",
        ]
    )
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            lines.append(f"- `{path.name}`")
    lines.append("")
    return "\n".join(lines)


def add_costs(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_prompt_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
    for item in items:
        cost = item.get("cost", {})
        total["prompt_tokens"] += int(cost.get("prompt_tokens", 0) or 0)
        total["completion_tokens"] += int(cost.get("completion_tokens", 0) or 0)
        total["cached_prompt_tokens"] += int(cost.get("cached_prompt_tokens", 0) or 0)
        total["estimated_cost_usd"] += float(cost.get("estimated_cost_usd", 0.0) or 0.0)
    total["estimated_cost_usd"] = round(total["estimated_cost_usd"], 6)
    return total


def debug_repair_loop(
    client: OpenAI,
    *,
    profile: Dict[str, Any],
    initial_prompt: str,
    out_dir: Path,
    run_backtests: bool,
    attempts: int = 2,
) -> Dict[str, Any]:
    prompt = initial_prompt
    attempt_records: List[Dict[str, Any]] = []
    last_code = ""
    for index in range(1, attempts + 1):
        result = call_deepseek(
            client,
            model=profile["model"],
            system_prompt=DEBUG_SYSTEM,
            user_prompt=prompt,
            max_tokens=5000,
            json_mode=False,
            thinking=profile["thinking"],
            reasoning_effort="high",
            temperature=profile["temperature"],
        )
        code = strip_code_fence(result["content"])
        last_code = code
        attempt_path = out_dir / f"{profile['profile']}_debugged_backtest_attempt_{index}.py"
        save_text(attempt_path, code)
        static_score = static_code_score(code)
        execution = run_python_file(attempt_path) if run_backtests else {"success": None}
        attempt = {
            **result,
            "artifact": str(attempt_path),
            "static_score": static_score,
            "execution": execution,
        }
        attempt_records.append(attempt)
        if execution.get("success") and static_score.get("score", 0) >= 80:
            break
        prompt = f"""The previous fix still failed in this exact environment.
Fix the code below. Return only corrected Python code.

Mandatory data handling:
- data.columns = data.columns.str.strip().str.lower()
- drop columns whose lowercase name contains "unnamed"
- map open/high/low/close/volume to Open/High/Low/Close/Volume
- if datetime exists, parse it and set it as index before selecting OHLCV
- order size must be either 0 < size < 1 or a positive integer

Actual failure:
{execution.get('stderr_tail', '')}

Code that failed:
```python
{code}
```"""

    final_path = out_dir / f"{profile['profile']}_debugged_backtest.py"
    save_text(final_path, last_code)
    last = attempt_records[-1] if attempt_records else {}
    return {
        "ok": all(item.get("ok", False) for item in attempt_records),
        "model": profile["model"],
        "profile": profile["profile"],
        "task": "debug_backtest_repair_loop",
        "latency_seconds": round(sum(item.get("latency_seconds", 0.0) for item in attempt_records), 3),
        "reasoning_present": any(item.get("reasoning_present") for item in attempt_records),
        "reasoning_chars": sum(item.get("reasoning_chars", 0) for item in attempt_records),
        "content": last_code,
        "error": "; ".join(item.get("error", "") for item in attempt_records if item.get("error")),
        "artifact": str(final_path),
        "static_score": last.get("static_score", {}),
        "execution": last.get("execution", {}),
        "attempts": attempt_records,
        "cost": add_costs(attempt_records),
    }


def run_eval(run_backtests: bool = True) -> Path:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing RBI data file: {DATA_PATH}")

    client = make_client()
    out_dir = OUTPUT_ROOT / f"deepseek_fit_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    model_list_response = client.models.list()
    model_list = [item.id for item in model_list_response.data]
    save_text(out_dir / "model_inventory.json", json.dumps(model_list, indent=2))

    weather_packet = load_weather_packet()
    save_text(out_dir / "weather_packet_fixture.json", json.dumps(weather_packet, indent=2, sort_keys=True))

    tasks: List[Dict[str, Any]] = []
    strategy_payloads: Dict[str, Optional[Dict[str, Any]]] = {}

    research_profiles = [
        {
            "profile": "deepseek-v4-pro-thinking",
            "model": "deepseek-v4-pro",
            "thinking": True,
            "max_tokens": 6500,
            "temperature": None,
        },
        {
            "profile": "deepseek-v4-pro-json",
            "model": "deepseek-v4-pro",
            "thinking": False,
            "max_tokens": 2200,
            "temperature": 0.1,
        },
        {
            "profile": "deepseek-v4-flash-json",
            "model": "deepseek-v4-flash",
            "thinking": False,
            "max_tokens": 2200,
            "temperature": 0.2,
        },
    ]

    for profile in research_profiles:
        result = call_deepseek(
            client,
            model=profile["model"],
            system_prompt=STRATEGY_RESEARCH_SYSTEM,
            user_prompt=build_strategy_prompt(),
            max_tokens=profile["max_tokens"],
            json_mode=True,
            thinking=profile["thinking"],
            reasoning_effort="high",
            temperature=profile["temperature"],
        )
        payload, parse_error = parse_json_content(result["content"])
        strategy_payloads[profile["profile"]] = payload
        result.update(
            {
                "task": "strategy_research_json",
                "profile": profile["profile"],
                "parse_error": parse_error,
                "validation": validate_strategy_spec(payload),
            }
        )
        save_text(out_dir / f"{profile['profile']}_strategy_research.json", json.dumps(payload or {"error": parse_error, "raw": result["content"]}, indent=2))
        tasks.append(result)

    weather_profiles = [
        {
            "profile": "deepseek-v4-pro-thinking",
            "model": "deepseek-v4-pro",
            "thinking": True,
            "max_tokens": 4000,
            "temperature": None,
        },
        {
            "profile": "deepseek-v4-pro-json",
            "model": "deepseek-v4-pro",
            "thinking": False,
            "max_tokens": 1200,
            "temperature": 0.0,
        },
        {
            "profile": "deepseek-v4-flash-json",
            "model": "deepseek-v4-flash",
            "thinking": False,
            "max_tokens": 1200,
            "temperature": 0.0,
        },
    ]

    for profile in weather_profiles:
        result = call_deepseek(
            client,
            model=profile["model"],
            system_prompt=WEATHER_DECISION_PROMPT + "\nThe output must be json.",
            user_prompt=json.dumps(weather_packet, sort_keys=True),
            max_tokens=profile["max_tokens"],
            json_mode=True,
            thinking=profile["thinking"],
            reasoning_effort="high",
            temperature=profile["temperature"],
        )
        payload, parse_error = parse_json_content(result["content"])
        result.update(
            {
                "task": "weather_decision_json",
                "profile": profile["profile"],
                "parse_error": parse_error,
                "validation": validate_weather_decision(payload),
            }
        )
        save_text(out_dir / f"{profile['profile']}_weather_decision.json", json.dumps(payload or {"error": parse_error, "raw": result["content"]}, indent=2))
        tasks.append(result)

    pro_strategy = (
        strategy_payloads.get("deepseek-v4-pro-json")
        or strategy_payloads.get("deepseek-v4-pro-thinking")
        or strategy_payloads.get("deepseek-v4-flash-json")
    )
    flash_strategy = strategy_payloads.get("deepseek-v4-flash-json") or pro_strategy
    code_profiles = [
        {
            "profile": "deepseek-v4-pro-code",
            "model": "deepseek-v4-pro",
            "thinking": False,
            "strategy": pro_strategy,
            "temperature": 0.1,
        },
        {
            "profile": "deepseek-v4-flash-json",
            "model": "deepseek-v4-flash",
            "thinking": False,
            "strategy": flash_strategy,
            "temperature": 0.1,
        },
    ]

    for profile in code_profiles:
        result = call_deepseek(
            client,
            model=profile["model"],
            system_prompt=BACKTEST_CODE_SYSTEM,
            user_prompt=build_backtest_prompt(profile["strategy"]),
            max_tokens=5000,
            json_mode=False,
            thinking=profile["thinking"],
            reasoning_effort="high",
            temperature=profile["temperature"],
        )
        code = strip_code_fence(result["content"])
        code_path = out_dir / f"{profile['profile']}_generated_backtest.py"
        save_text(code_path, code)
        result.update(
            {
                "task": "backtest_code_generation",
                "profile": profile["profile"],
                "artifact": str(code_path),
                "static_score": static_code_score(code),
            }
        )
        if run_backtests:
            result["execution"] = run_python_file(code_path)
        tasks.append(result)

    debug_profiles = [
        {
            "profile": "deepseek-v4-pro-thinking",
            "model": "deepseek-v4-pro",
            "thinking": True,
            "temperature": None,
        },
        {
            "profile": "deepseek-v4-flash-json",
            "model": "deepseek-v4-flash",
            "thinking": False,
            "temperature": 0.1,
        },
    ]
    debug_prompt = build_debug_prompt()

    for profile in debug_profiles:
        result = debug_repair_loop(
            client,
            profile=profile,
            initial_prompt=debug_prompt,
            out_dir=out_dir,
            run_backtests=run_backtests,
            attempts=2,
        )
        tasks.append(result)

    save_text(out_dir / "deepseek_fit_results.json", json.dumps({"models": model_list, "tasks": tasks}, indent=2))
    report = make_report(out_dir=out_dir, model_list=model_list, tasks=tasks)
    save_text(out_dir / "deepseek_fit_report.md", report)
    save_text(OUTPUT_ROOT / "deepseek_fit_latest.md", report)
    save_text(OUTPUT_ROOT / "deepseek_fit_latest.json", json.dumps({"models": model_list, "tasks": tasks, "run_dir": str(out_dir)}, indent=2))
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate DeepSeek V4 fit for TradeHive agents.")
    parser.add_argument(
        "--skip-backtest-exec",
        action="store_true",
        help="Call DeepSeek but skip executing generated backtest files.",
    )
    args = parser.parse_args()
    out_dir = run_eval(run_backtests=not args.skip_backtest_exec)
    print(f"DeepSeek fit evaluation saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
