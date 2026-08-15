# Copilot Instructions for NightWatch

> **Source of truth:** [`/AGENTS.md`](../AGENTS.md) at the repo root. It covers the
> full architecture (tick pipeline, kill switch, persistence), the complete repository
> layout, known quirks/traps, and every environment variable. Read it first — this
> file is only a condensed cheat-sheet for Copilot so the essentials don't require a
> hop, kept intentionally short to avoid drifting out of sync with `AGENTS.md` again.

## Project Overview

NightWatch is an async Python 3.11 crypto **paper**-trading bot. It runs as a single
process (`trade-service`): ingest live Kraken ticks -> momentum strategy -> risk
engine -> simulated fill -> atomic Postgres write. It exposes `/healthz` and
`/metrics` via FastAPI, plus a Grafana + Loki + Prometheus stack
(`docker-compose.yml`). See `AGENTS.md` for the full per-tick pipeline.

## Repository Layout

```
src/Nightwatch/    main.py (entrypoint), api.py, adapters/, common/, db/, messaging/,
                    metrics/, models/, pipeline/, rules/, strategies/
tests/Nightwatch/  unittest test_*.py, mirrors src/
tests/fixtures/    factories + NatsServerFixture + db.py helpers
migrations/        Alembic migrations for Postgres
grafana/            dashboards + provisioning
```

Full annotated layout, and which pieces are vestigial/not wired up, are in `AGENTS.md`.

## Prerequisites

| Tool   | Version | Notes |
|--------|---------|-------|
| Python | ~3.11   | Specified in `pyproject.toml` (`python = "~3.11"`) and `.python-version`. Use `pyenv install 3.11` if needed. |
| Poetry | latest  | Dependency and venv manager (`pip install poetry`). |
| pyenv  | latest  | Optional but recommended for managing Python versions. |

## Environment Setup

```bash
# If you have pyenv:
pyenv install 3.11 --skip-existing && pyenv local 3.11

# Install all dependencies (dev included):
poetry install

# Or use the Makefile (calls pyenv + poetry + pre-commit install):
make
```

**Workaround — Python version mismatch:**
The project constraint is `python = "~3.11"`. If only Python 3.12+ is
available and you cannot install 3.11, you can install the dependencies
directly with pip as a fallback:

```bash
pip install ruff mypy coverage unittest-xml-reporting \
    pydantic nats-py fastapi prometheus-client httpx websockets python-dotenv
```

Then run tools with `PYTHONPATH=src:$PYTHONPATH python -m <tool>` instead
of `poetry run <tool>`.

## Linting & Formatting

**Ruff** handles both linting and formatting (configured in `pyproject.toml`):

```bash
poetry run ruff check .          # Lint (pydocstyle, isort, pylint, pyflakes, …)
poetry run ruff format .         # Auto-format (Black-compatible)
poetry run ruff check --fix .    # Auto-fix import ordering
```

Key ruff settings:
- Line length: **140**
- Quote style: double quotes
- Indent: 4 spaces
- Docstrings follow the **Google convention**
- Tests (`tests/**/*.py`) are exempt from pydocstyle (`D`), error (`E`), and warning (`W`) rules

## Type Checking

**mypy** runs in **strict** mode:

```bash
poetry run mypy src/
```

All public functions and methods must have full type annotations.
Use `str | None` union syntax (Python 3.10+ style, not `Optional`).

## Running Tests

Tests use Python's built-in `unittest` framework with `xmlrunner` for
JUnit-style XML output. There is **no pytest dependency**.

### Unit tests (default — no external services needed)

```bash
poetry run coverage run -m xmlrunner discover --output-file junittest.xml
poetry run coverage xml          # Generate coverage report
```

This discovers and runs all `test_*.py` files under `tests/`.
Integration tests that need NATS are automatically **skipped** when
`RUN_INTEGRATION` is not set (they use `@unittest.skipUnless`).

### Integration tests (require nats-server binary; some also require Postgres)

```bash
# Install nats-server first (see CI workflow for exact steps)
RUN_INTEGRATION=1 poetry run coverage run -m xmlrunner discover \
    --output-file junittest.xml -s tests/Nightwatch -p "test_integration*.py"
```

Integration tests use `tests/fixtures/nats_server.py` which spawns a
temporary `nats-server` process on a random port. A subset also needs
`DATABASE_URL` pointed at a live Postgres (`docker compose up trade-db`) and
self-skip without it — **CI does not set `DATABASE_URL`, so those never run in
CI today.** See `AGENTS.md`'s Testing model section for the exact file list
and why this matters before trusting a green CI run for DB-layer changes.

## CI Pipeline (`.github/workflows/ci.yml`)

The CI pipeline has two jobs:

| Job | Trigger | Steps |
|-----|---------|-------|
| **quality** | push + PR | `ruff check .` → `mypy src/` → unit tests + coverage |
| **integration** | push only | installs `nats-server`, runs `test_integration*.py` with `RUN_INTEGRATION=1` |

CI uses `actions/setup-python@v5` with `python-version: "3.11"`.

## Code Conventions

Pydantic `BaseModel` for domain data, async throughout the networking/DB layer, ABCs
for adapters/strategies/rules, `Protocol` for persistence ports, Google-style
docstrings, one `NightwatchMetrics` (isolated `CollectorRegistry`) threaded through
every layer. Full list with rationale in `AGENTS.md`'s Code conventions section —
kept there only, to avoid this list drifting out of sync again.

## Known Issues & Workarounds

- **`pytest` not in dependencies**: the CI and `pyproject.toml` use `xmlrunner`
  (unittest runner), not pytest. Do not add pytest without also updating the test
  infrastructure everywhere it's referenced (CI, pre-commit, this doc, `AGENTS.md`).
- **Python ~3.11 constraint**: `poetry install` fails outright on 3.12+; see the
  workaround above.
- More traps, and their current resolution status, are catalogued in `AGENTS.md`'s
  Known quirks & traps section — check there before assuming something is still
  broken (or still unfixed).

## Environment Variables

Full table (all vars, defaults, which module reads them) is in `AGENTS.md`. The two
you'll touch most often locally: `DATABASE_URL` (required to run `main.py`) and
`RUN_INTEGRATION` (gates `test_integration_*.py`).

## Pre-commit Hooks

Pre-commit is configured in `.pre-commit-config.yaml` and runs:
1. `poetry check`
2. Trailing-whitespace & end-of-file fixers
3. `ruff format` (formatter)
4. `ruff check` (linter, outputs `sonar_report.json`)
5. `mypy` (strict type checking)
6. `coverage run` (unit tests)
7. `coverage xml` (coverage report)

Install hooks after cloning: `poetry run pre-commit install`.
