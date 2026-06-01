# Maintained Surfaces

This repository is a private research workbench. Cleanup should protect active
systems without rewriting old experiments.

## First-Class Packages

- `src/agents/polymarket_trader`: active Polymarket paper/live runner, research
  modules, weather edge work, risk controls, and preflight checks.
- `src/agents/poker`: active poker advisor, dashboard, vision, scoring, and
  strategy modules.
- `src/agents/blackjack`: active blackjack trainer, scoring, live table,
  dashboard, and related content tooling.
- `src/models`: shared LLM provider abstraction used by agent packages.
- `src/dashboard`: shared operator dashboard surface.

## Runtime Policy

- Bulk run output belongs outside git or under ignored `src/data` runtime
  folders.
- Keep only small deterministic fixtures and curated reports that are required
  by tests or documentation.
- Do not delete local artifacts during cleanup unless explicitly requested.

## Legacy And Experiment Policy

- Older RBI variants, legacy Polymarket folders, root-level reports, generated
  strategy HTML, and one-off scripts are archive candidates.
- Do not refactor or remove legacy areas unless a current entrypoint proves they
  are active.
- `src/main.py` is a minimal orchestrator; most maintained systems are run from
  package-specific entrypoints.

## Safety Checks

- Run `python scripts/secret_scan.py` before staging or sharing changes.
- Use WSL-native Git from `/home/satya/tradehive-ai-agents`.
- Keep `.env`, local settings, logs, caches, and generated data untracked.
