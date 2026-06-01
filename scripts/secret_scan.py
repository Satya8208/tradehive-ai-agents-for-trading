"""Lightweight tracked-file secret scanner.

This is a local guardrail for the private-stable cleanup. It scans tracked files
by default and reports only path, line number, and rule name; it never prints the
matched secret value.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "openai_or_provider_key": re.compile(r"\b(?:sk|xai)-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "secret_literal_assignment": re.compile(
        r"(?ix)\b[A-Z0-9_]*(?:API_KEY|PRIVATE_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN|BEARER_TOKEN)[A-Z0-9_]*"
        r"\s*=\s*[\"']([^\"']{16,})[\"']"
    ),
    "env_secret_assignment": re.compile(
        r"(?i)^\s*[A-Z0-9_]*(?:API_KEY|PRIVATE_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN|BEARER_TOKEN)[A-Z0-9_]*=([^\s#]{20,})"
    ),
}

PLACEHOLDER_WORDS = (
    "your_",
    "your",
    "placeholder",
    "example",
    "changeme",
    "replace_me",
    "redacted",
    "os.getenv",
    "getenv",
    "test",
    "fake",
    "dummy",
    "sample",
    "mock",
    "xxxx",
    "****",
)

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".mp3",
    ".mp4",
    ".mov",
    ".zip",
    ".sqlite",
    ".db",
    ".parquet",
}


def git_files(include_untracked: bool) -> list[Path]:
    args = ["git", "ls-files", "-z"]
    if include_untracked:
        args.extend(["--cached", "--others", "--exclude-standard"])

    output = subprocess.check_output(args, cwd=ROOT)
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def is_placeholder(value: str) -> bool:
    clean = value.strip().strip('"').strip("'").lower()
    return not clean or any(word in clean for word in PLACEHOLDER_WORDS)


def scan_file(path: Path) -> list[tuple[int, str]]:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in SECRET_PATTERNS.items():
            match = pattern.search(line)
            if not match:
                continue
            if rule == "openai_or_provider_key" and is_placeholder(match.group(0)):
                continue
            if rule in {"secret_literal_assignment", "env_secret_assignment"} and is_placeholder(match.group(1)):
                continue
            findings.append((line_no, rule))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan tracked files for secret-shaped values.")
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Also scan untracked files that are not ignored.",
    )
    args = parser.parse_args()

    findings: list[tuple[Path, int, str]] = []
    for path in git_files(args.include_untracked):
        rel = path.relative_to(ROOT)
        if any(part in {".git", "node_modules", "__pycache__"} for part in rel.parts):
            continue
        for line_no, rule in scan_file(path):
            findings.append((rel, line_no, rule))

    if findings:
        print("Secret-shaped values found:")
        for rel, line_no, rule in findings:
            print(f"{rel}:{line_no} {rule}")
        return 1

    print("No secret-shaped values found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
