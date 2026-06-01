# API Readiness Report

## Security Notice

This report was redacted during the private-stable cleanup. Earlier versions of
this file contained credential-shaped values and should be treated as exposed if
the repository history was shared outside the local machine.

Required follow-up if any historical values were real:

1. Rotate the affected provider keys or wallet credentials.
2. Keep replacement values only in the ignored `.env` file.
3. Re-run `python scripts/secret_scan.py` before staging or sharing changes.

## Current Policy

- Tracked documentation must never claim that a real key is configured.
- Tracked examples must use placeholder values only.
- Readiness checks should report whether a variable is present locally without
  printing the value or value pattern.
- Live trading credentials must stay out of git history.

## Environment Template

Use `.env_example` as the tracked template and `.env` as the local private file.
The template intentionally contains only placeholder values.

## Activation Notes

The following systems can be evaluated after local credentials are configured:

- Blackjack and poker tooling can run mostly from local logic, with optional AI.
- Polymarket tooling should start in dry-run or paper mode and pass preflight
  checks before any live action.
- Trading agents that depend on exchange APIs or wallet keys should fail closed
  when required environment variables are missing.

## Pre-Share Checklist

- [ ] Run `python scripts/secret_scan.py`.
- [ ] Verify `git status --short` from WSL, not Windows UNC Git.
- [ ] Confirm `.env`, local settings, logs, runtime output, and generated data
      are not staged.
- [ ] Rotate any key that previously appeared in a tracked file.
