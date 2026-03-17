# Copilot Instructions for NightWatch

## Project Overview

NightWatch is a Python 3.11 trading-bot / market-monitoring service.
It ingests live market data from the Kraken exchange via WebSocket,
publishes ticks over NATS messaging, and exposes health and Prometheus
metrics endpoints through FastAPI.

## Repository Layout

```
src/Nightwatch/              # Main package (note the capital "N")
  common/                    # Shared utilities: logging, symbol normalisation
  models/                    # Pydantic / dataclass models (MarketTick, Signal, TickBuffer, …)
  api.py                     # FastAPI app (healthz, /metrics)
  exchange_market_adapter.py # Abstract base class for exchange adapters
  kraken_adapter.py          # Kraken WebSocket adapter
  nats_connection.py         # Base NATS connector
  publisher.py               # MarketTickPublisher (extends NatsConnector)
  subscriber.py              # MarketTickSubscriber (extends NatsConnector)
  metrics.py                 # Prometheus counters (NightwatchMetrics)
  tick_recorder.py           # JSONL tick recorder

tests/
  Nightwatch/                # Unit and integration tests (mirror src layout)
  fixtures/                  # Reusable test helpers: NatsServerFixture, tick/signal factories
```

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

### Integration tests (require nats-server binary)

```bash
# Install nats-server first (see CI workflow for exact steps)
RUN_INTEGRATION=1 poetry run coverage run -m xmlrunner discover \
    --output-file junittest.xml -s tests/Nightwatch -p "test_integration*.py"
```

Integration tests use `tests/fixtures/nats_server.py` which spawns a
temporary `nats-server` process on a random port.

## CI Pipeline (`.github/workflows/ci.yml`)

The CI pipeline has two jobs:

| Job | Trigger | Steps |
|-----|---------|-------|
| **quality** | push + PR | `ruff check .` → `mypy src/` → unit tests + coverage |
| **integration** | push only | installs `nats-server`, runs `test_integration*.py` with `RUN_INTEGRATION=1` |

CI uses `actions/setup-python@v5` with `python-version: "3.11"`.

## Code Conventions

1. **Pydantic models** for all data structures — use `BaseModel` with
   `Field` constraints, `field_validator`, and `ConfigDict(str_max_length=255)`.
2. **Async/await** throughout the networking layer (WebSocket, NATS).
3. **Abstract base classes** for adapter interfaces (e.g., `ExchangeMarketAdapter`).
4. **Google-style docstrings** on every public class and method.
5. **`logging`** module with a centralised UTC formatter
   (`Nightwatch.common.logging_configuration`). Use `LOGGER = logging.getLogger(__name__)`.
6. **Prometheus metrics** via an isolated `CollectorRegistry` per `NightwatchMetrics`
   instance (avoids global state leaking between tests).
7. **Import style**: absolute imports from the `Nightwatch` package
   (e.g., `from Nightwatch.models.market_tick import MarketTick`).
8. **Test fixtures** live in `tests/fixtures/` and provide factory
   functions (`make_tick()`, `make_signal()`) with sensible defaults.

## Known Issues & Workarounds

- **mypy error with `UTCFormatter`**: On newer mypy versions (≥1.9) the
  `converter = time.gmtime` assignment in
  `src/Nightwatch/common/logging_configuration.py` produces a type
  incompatibility error. The CI pins `mypy ~1.8` via Poetry to avoid this.
  If you see this error locally with a newer mypy, it is a known upstream
  typing issue and does not affect runtime behaviour.
- **Python ~3.11 constraint**: The Poetry lockfile and `pyproject.toml`
  restrict the project to `~3.11`. Running `poetry install` on 3.12+
  will fail. See the workaround above.
- **No `models/__init__.py`**: The `src/Nightwatch/models/` directory has
  no `__init__.py`. Imports work because each model is imported directly
  from its module (e.g., `from Nightwatch.models.market_tick import MarketTick`).
- **`pytest` not in dependencies**: The CI and `pyproject.toml` use
  `xmlrunner` (unittest runner), not pytest. Do not add pytest without
  also updating the test infrastructure.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LOG_LEVEL` | Root log level | `"INFO"` |
| `NATS_SERVERS` | Comma-separated NATS URLs | `nats://127.0.0.1:4222` |
| `NATS_TOKEN` | NATS auth token | `""` |
| `RUN_INTEGRATION` | Gate integration tests | unset (tests skipped) |

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
