#!/usr/bin/env python3
"""Fail if tracked files contain real-looking secrets."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SECRET_PATTERNS = [
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{31,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("Stripe key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    ("Twilio account SID", re.compile(r"\bAC[a-fA-F0-9]{32}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)?PRIVATE KEY-----")),
]

ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Z0-9_]+)\s*=\s*(?P<value>.*)$")

PLACEHOLDER = re.compile(
    r"^(?:$|your[_-]|example|placeholder|change_?me|replace_?me|xxx|xxxx|"
    r"<|\$\{|redacted|test|demo|none|null|dummy|https?://localhost|\.\.\.)",
    re.IGNORECASE,
)

SKIP_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reason: str


def run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)


def tracked_files() -> list[str]:
    return [line for line in run_git(["ls-files"]).splitlines() if line]


def is_skipped(path: str) -> bool:
    return any(part in SKIP_PARTS for part in Path(path).parts)


def read_text(path: str) -> str | None:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:
            return None


def clean_assignment_value(value: str) -> str:
    value = re.sub(r"\s+#.*$", "", value).strip()
    return value.strip("'\"")


def is_sensitive_key(key: str) -> bool:
    markers = (
        "API_KEY",
        "AUTH_TOKEN",
        "CLIENT_SECRET",
        "PRIVATE_KEY",
        "SECRET",
        "PASSWORD",
        "ACCOUNT_SID",
        "CREDENTIALS",
        "WEBHOOK_SECRET",
        "EMBED_TOKEN",
    )
    return any(marker in key for marker in markers)


def is_runtime_lookup(value: str) -> bool:
    return any(
        marker in value
        for marker in (
            "os.getenv",
            "os.environ",
            "getenv(",
            "process.env",
            "settings.",
            "config.",
        )
    )


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for reason, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path, line_number, reason))
                break

        match = ASSIGNMENT.match(line)
        if not match:
            continue
        if not is_sensitive_key(match.group("key")):
            continue

        value = clean_assignment_value(match.group("value"))
        if PLACEHOLDER.match(value):
            continue
        if is_runtime_lookup(value):
            continue
        if value.lower() in {"true", "false"}:
            continue
        if len(value) >= 5:
            findings.append(Finding(path, line_number, f"non-placeholder value for {match.group('key')}"))
    return findings


def scan_worktree() -> list[Finding]:
    findings: list[Finding] = []
    for path in tracked_files():
        if is_skipped(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        findings.extend(scan_text(path, text))
    return findings


def scan_history(ref: str) -> list[Finding]:
    findings: list[Finding] = []
    rev_args = ["rev-list", "--all"] if ref == "--all" else ["rev-list", ref]
    commits = [line for line in run_git(rev_args).splitlines() if line]
    for commit in commits:
        files = [
            line
            for line in run_git(["ls-tree", "-r", "--name-only", commit]).splitlines()
            if line and not is_skipped(line)
        ]
        for path in files:
            try:
                blob = subprocess.check_output(
                    ["git", "show", f"{commit}:{path}"],
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                continue
            if b"\0" in blob:
                continue
            text = blob.decode("utf-8", errors="ignore")
            for finding in scan_text(f"{commit[:7]}:{path}", text):
                findings.append(finding)
                if len(findings) >= 200:
                    return findings
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true", help="scan all reachable git history")
    parser.add_argument("--ref", default="--all", help="history ref to scan, for example HEAD")
    args = parser.parse_args()

    findings = scan_history(args.ref) if args.history else scan_worktree()
    if not findings:
        scope = "git history" if args.history else "tracked files"
        print(f"secret_guard: no secret-looking values found in {scope}")
        return 0

    print("secret_guard: possible secrets found; values are intentionally not printed", file=sys.stderr)
    for finding in findings[:80]:
        print(f"{finding.path}:{finding.line}: {finding.reason}", file=sys.stderr)
    if len(findings) > 80:
        print(f"...and {len(findings) - 80} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    raise SystemExit(main())
