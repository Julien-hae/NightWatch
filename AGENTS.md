# AGENTS.md

Instructions for AI coding agents (Claude Code, GitHub Copilot, ...) working in this
repository. This is the canonical onboarding doc — `.github/copilot-instructions.md`
just points here. Humans: see `README.md`.

## What this is

NightWatch is an async Python 3.11 crypto **paper**-trading bot (no real exchange
orders are ever placed). It runs as a **single consolidated process** (`trade-service`
in `docker-compose.yml`): ingest live Kraken ticks → evaluate a momentum strategy →
risk-check the signal → simulate a fill → persist atomically to Postgres. It exposes
`/healthz` and `/metrics` (Prometheus) via FastAPI, and ships to a full
Grafana + Loki + Prometheus observability stack.

Scaffolded from [CookieBlueprint](https://github.com/Julien-hae/CookieBlueprint).

## Architecture: the tick pipeline

`main.py` (`python -m Nightwatch.main`, the container `CMD`) runs one asyncio event
loop with three concurrent tasks: the Kraken ingest loop, the uvicorn server, and a
stop-event waiter. **Startup order matters:**

1. `db/bootstrap.py::bootstrap_persistence()` — runs `alembic upgrade head`, opens an
   asyncpg pool, builds every `Pg*Repo`.
2. `PaperTrader.rehydrate()` — restores cash, positions and the processing cursor from
   Postgres.
3. If `NATS_SERVERS` is set, `ControlEventSubscriber.drain_backlog()` restores
   kill-switch state from the **latest** JetStream control event before anything else
   runs — this closes the gap where a kill sent right before a crash could be lost.
   Until this completes, `KillSwitch.ready == False` and **every** tick is suppressed.
   If the backlog is empty (fresh stream, **or** the last control event fell outside the
   `CONTROL` stream's own retention window — 10k msgs / 24h, see
   `control_event_publisher.py`), `main.py::_restore_kill_switch_from_postgres()` falls
   back to the last state recorded in the `kill_switch_state` table instead of defaulting
   to `trading_enabled=True`; every applied control event (from backlog drain or the live
   subscription) is mirrored to that table so this fallback stays current. If
   `NATS_SERVERS` is unset, the kill switch is marked ready immediately and trading
   is never gated (no kill switch available).
4. FastAPI app + Kraken adapter start; ticks flow in.

All three NATS connections opened in `_connect_nats()` (`nats_connector`, `control_sub`,
`tick_publisher`) are wired with disconnect/reconnect callbacks
(`main.py::_nats_reconnect_callbacks`) that log and increment
`nats_disconnects_total{connection}` / `nats_reconnects_total{connection}`. `nats-py`
already reconnects and resumes publish/subscribe on its own; these callbacks only make
an outage observable in Loki/Grafana. Relatedly, `MarketTickPublisher`,
`MarketTickSubscriber` and `ControlEventSubscriber` check `client.is_closed` (not
`not client.is_connected`) before calling `connect()` — calling `connect()` while
`nats-py` is transparently mid-reconnect races its own reconnect loop and can hang
indefinitely; only a fully closed client should trigger a manual reconnect.

Per tick (`pipeline/strategy_runner.py::_evaluate_tick`):

```text
KrakenAdapter.stream_ticks()
  -> MarketTickPublisher.publish()    best-effort NATS broadcast (market.tick.<SYMBOL>); a failure
                                       here is logged and never blocks the pipeline below
  -> TickBuffer.add_tick()            per-symbol rolling deque; discards out-of-order ticks
  -> PaperTrader.observe_price()      updates the equity gauge
  -> kill-switch gate                 ready? trading_enabled?
  -> MomentumBurstStrategy.on_tick()  BUY/SELL when |delta%| over window_sec crosses threshold_pct
  -> RiskEngine.evaluate()            CooldownRule -> MinTradeStrengthRule -> MaxSignalPerMinuteRule
                                       (ordered chain, first rejection wins)
  -> PaperTrader.process_and_persist()
       save signal -> size+dedup order -> paper_execute() fill -> Portfolio.apply_fill() (in-memory)
       -> PgAtomicTradeWriter.write_trade()   ONE db transaction: order+fill+position+cash+cursor+
                                               equity_snapshot, idempotent on signal_id. On failure the
                                               in-memory fill is reverted so memory matches the DB.
```

Every stage increments a `NightwatchMetrics` counter/gauge (`metrics/metrics.py`) —
check there first when adding a new observable event.

The kill switch is the only cross-cutting control:
`BotControlEvent{kill, reason, timestamp}` published to JetStream subject
`control.bot` (stream `CONTROL`, file storage, 10k msgs / 24h retention). **There is no
CLI/ops tool in this repo to publish one** — today only tests exercise
`ControlEventPublisher`. Triggering a real kill means publishing to that subject
directly (e.g. `nats pub`) or writing that tool.

## Repository layout

```text
src/Nightwatch/
  main.py                           production entrypoint — wires everything, graceful SIGINT/SIGTERM shutdown
  api.py                            FastAPI app: GET /healthz, GET /metrics
  adapters/
    exchange_market_adapter.py      ABC for exchange adapters (connect/subscribe/close/parse_message)
    kraken_adapter.py               Kraken WS v2 adapter; exponential backoff reconnect
    tick_recorder.py                JSONL tick recorder — NOT wired into main.py, test-only (see quirks)
    tick_replay_reader.py           TickReplayReader: reads a JSONL tick file back into MarketTick objects,
                                     in order, skipping unparsable lines (read-side counterpart to tick_recorder.py)
  cli/
    replay.py                       `poetry run replay --file <path> --speed fast|real` — reads a tick file and
                                     republishes each tick to NATS on market.tick.<SYMBOL>; fast=no delay,
                                     real=sleeps based on recorded timestamp deltas; logs a summary at the end
  common/
    logging_configuration.py        UTC text formatter + JSON formatter (LOG_FORMAT=json, for Loki)
    utils.py                        normalize_symbol() for NATS-safe subjects
  db/
    bootstrap.py                    bootstrap_persistence(): migrations -> asyncpg pool -> all Pg repos
    database.py                     DatabaseConnector — SELECT 1 health check, DSN normalisation
    repositories.py                 Protocol ports + in-memory implementations (used by tests)
    pg_repositories.py              asyncpg-backed repos + PgAtomicTradeWriter (the one-tx writer)
  messaging/
    nats_connection.py              base NatsConnector (connect/close/client)
    control_event_publisher.py      publishes BotControlEvent to JetStream — test-only today
    control_event_subscriber.py     durable JetStream consumer + startup backlog drain (kill switch)
    publisher.py                    MarketTickPublisher — best-effort tick broadcast over core NATS, wired into main.py
    subscriber.py                   MarketTickSubscriber over core NATS — still unwired, nothing consumes market.tick.* yet
  metrics/metrics.py                NightwatchMetrics — one CollectorRegistry per instance (test isolation)
  models/                           Pydantic models: MarketTick, Signal, Order, Fill, Portfolio, BotControlEvent,
                                    RiskDecision, StrategyDecision, ServiceHealth, TickBuffer, NatsConnectionConfig,
                                    OrderFactoryConfig + SignalDeduplicator, PercentageFeeModel
  pipeline/
    strategy_runner.py              per-tick orchestration (buffer -> kill-switch -> strategy -> risk -> trade)
    risk_engine.py                  ordered RiskRule chain, first rejection wins
    kill_switch.py                  ready / trading_enabled state machine
    paper_trader.py                 signal -> order -> fill -> portfolio -> persistence
  rules/                            RiskRule impls: CooldownRule, MinTradeStrengthRule, MaxSignalPerMinuteRule
  strategies/                       Strategy ABC + MomentumBurstStrategy (only strategy today)

tests/
  Nightwatch/                       unittest test_*.py, mirrors src/ + "infra as code" tests
                                    (test_grafana_compose_wiring.py, test_prometheus_compose_wiring.py,
                                    test_grafana_alerting_provisioning.py) that assert on docker-compose.yml /
                                    grafana provisioning files as plain text
  fixtures/                         make_tick/make_signal/make_order/make_fill/make_risk_decision/make_portfolio
                                    factories; NatsServerFixture (spawns a real nats-server process); db.py
                                    (alembic_cfg, database_url_or_skip, RESET_DB_SQL)

migrations/versions/                Alembic: 0001 signals/orders/fills/positions/equity_snapshots,
                                    0002 portfolio_state, 0003 processing_cursor,
                                    0004 kill_switch_state (Postgres fallback past JetStream retention)
grafana/dashboards/                 bot_health.json, trading.json, nightwatch-overview.json
grafana/provisioning/               datasource.yml (Prometheus + Loki, explicit uids), dashboards.yml
                                    (file provider), alerting/rules.yml (Grafana unified alerting — no
                                    Alertmanager needed: trade-service-down and postgres-unreachable,
                                    both alert-on-no-data, 2m debounce)
promtail.yml                        ships trade-service container logs -> Loki (needs LOG_FORMAT=json)
docker-compose.yml                  trade-db (pg16) + nats(+JetStream) + trade-service + loki +
                                    promtail + prometheus + grafana
```

## Setup

```bash
pyenv install 3.11 --skip-existing && pyenv local 3.11
poetry install                 # or just `make`, which also runs `pre-commit install`
poetry run pre-commit install
```

Python is pinned to `~3.11` in `pyproject.toml`/`.python-version`; `poetry install`
fails outright on 3.12+. If you're stuck on a newer interpreter, fall back to
`pip install <deps>` and run tools via `PYTHONPATH=src python -m <tool>`.

## Running it

```bash
docker compose up --build      # trade-db, nats, trade-service, loki, promtail, prometheus, grafana
curl -s http://localhost:8000/healthz | jq
```

- Grafana: `localhost:3000` (admin/admin) — 3 dashboards auto-provisioned.
- Prometheus: `localhost:9090`. Raw metrics: `localhost:8000/metrics`.
- Running `main.py` outside compose requires `DATABASE_URL` at minimum (it raises
  `RuntimeError` otherwise); everything else has a default (see *Environment
  variables*).
- A gitignored `credentials.env` is auto-loaded via `python-dotenv` on import of
  `models/nats_config.py` if present. `.env.example` documents the three secrets
  `docker-compose.yml` reads from the environment (`POSTGRES_PASSWORD`, `NATS_TOKEN`,
  `GRAFANA_ADMIN_PASSWORD`) — copy it to `.env` and set real values before running
  anywhere reachable beyond your own machine; the compose file's own defaults
  (`tradepass` / `devtoken-change-me` / `admin`) are for local dev only. Every service's
  port is bound to `127.0.0.1` in the shipped compose file, not `0.0.0.0` — `nats` also
  requires `NATS_TOKEN` (`--auth`) to connect, including from `nats pub`/admin tooling.

## Quality gates

```bash
poetry run ruff check .            # lint (pydocstyle, isort, pylint, pyflakes, pep8-naming, ...)
poetry run ruff format .           # auto-format (Black-compatible, line-length 140, double quotes)
poetry run mypy src/               # strict mode — all public functions need full annotations
poetry run coverage run -m xmlrunner discover --output-file junittest.xml
poetry run coverage xml
```

All four are clean on `master` as of this writing (263 tests, 52 skipped locally).
`pre-commit` runs the same set on `git commit`.

## Testing model

Tests use stdlib `unittest` + `xmlrunner` — **no pytest** in this repo, don't add it
without also replacing the runner everywhere (CI, pre-commit, `pyproject.toml`).

| Suite | Command | Needs |
|---|---|---|
| Unit (default) | `coverage run -m xmlrunner discover --output-file junittest.xml` | nothing external |
| Integration — NATS/JetStream | add `RUN_INTEGRATION=1`, `-s tests/Nightwatch -p "test_integration*.py"` | `nats-server` binary on `PATH` |
| Integration — Postgres | same, plus | `DATABASE_URL` pointed at a live Postgres (`docker compose up trade-db`) |

DB-touching files: `test_integration_database.py`, `test_integration_pg_repositories.py`,
`test_integration_migrations.py`, `test_integration_smoke_restart.py`,
`test_integration_transactional_ack.py`, `test_integration_paper_trader.py`,
`test_integration_kill_switch_persistence.py` (also needs `nats-server` on `PATH`). They
`unittest.skipUnless` themselves out when `DATABASE_URL` is absent.

**CI gap**: `.github/workflows/ci.yml`'s `integration` job installs `nats-server` but
never starts Postgres or sets `DATABASE_URL` — the six files above self-skip in CI
today and only actually run locally. A green CI run does not mean the Postgres path
was exercised; run them locally against `docker compose up trade-db` before trusting
DB-layer changes.

## Code conventions

- **Pydantic `BaseModel`** for all wire/domain data (`ConfigDict(str_max_length=255)`,
  `Field` constraints, `field_validator`); plain `@dataclass` for process-local,
  non-serialized state (`ServiceHealth`, `StrategyDecision`, `PersistenceContext`).
- **`Decimal`** everywhere money/quantity is involved — never `float` for price/qty/cash.
- **Async throughout** the networking/DB layer; sync only in strategies/rules (pure
  functions over an in-memory buffer) and the in-memory test repos.
- **ABC for adapters/strategies/rules** (`ExchangeMarketAdapter`, `Strategy`,
  `RiskRule`), **`Protocol`** for persistence ports (`db/repositories.py`) — Pg
  implementations and in-memory test implementations satisfy the same Protocol.
- **Google-style docstrings** on every public class/method (ruff `D` rules enforce
  this outside `tests/`).
- **`LOGGER = logging.getLogger(__name__)`** per module; structured events
  (`signal`, `order_created`, `order_filled`) are logged as one-line `json.dumps(...)`
  strings for Loki, in addition to the human-readable UTC-formatted line.
- **Metrics**: always pass `metrics: NightwatchMetrics | None` through constructors
  and guard with `if self._metrics is not None`; each instance owns its own
  `CollectorRegistry` so tests never leak state into each other or the global registry.
- **Test factories** (`tests/fixtures/*_factory.py`) return fully-valid model
  instances with sensible defaults, overridable via kwargs — prefer them over
  hand-rolling models in new tests.
- **Idempotency** is load-bearing, not incidental: signals are deduped by `uid`
  in-memory (`SignalDeduplicator`) *and* orders are deduped by `idempotency_key =
  signal_id` in Postgres (`ON CONFLICT DO NOTHING`). Any new write path that can be
  retried (redelivery, restart) needs the same double coverage.

## Known quirks & traps

- **`messaging/subscriber.py` (`MarketTickSubscriber`) and `adapters/tick_recorder.py`
  (`MarketTickRecorder`) are dead code in production** — nothing in this repo
  subscribes to the `market.tick.*` subjects `MarketTickPublisher` broadcasts, and
  nothing calls the JSONL recorder. Both remain fully unit-tested but unwired.
- **`api.py`'s startup handler double-connects an already-connected NATS client**:
  `main.py` connects `nats_connector` itself in `_connect_nats()`, then passes that
  *already-connected* instance into `create_app(nats=nats_connector, ...)`, whose own
  `@app.on_event("startup")` unconditionally calls `await _nats.connect()` again.
  `nats-py` logs an internal `ERROR: nats: encountered error (TimeoutError)` for this
  redundant connect on every real startup — harmless in practice (`/healthz` re-reads
  `client.is_connected` live on every request and settles to `true`), but noisy and
  worth fixing by only connecting in `create_app`'s startup handler when the injected
  connector isn't already connected.
- **mypy is pinned to `~1.8` in `pyproject.toml` but nothing in the code requires
  it** — the one issue that used to force the pin (`UTCFormatter.converter` typing in
  `common/logging_configuration.py`) is fixed at the source. The pin is unexercised
  insurance at this point; relaxing it is safe but needs its own `poetry lock`.
- **`NATS_SERVERS` unset disables NATS and the kill switch entirely** — trading is
  never gated, and `main.py` logs a warning when this happens. Separately,
  `NatsConnectionConfig`'s own `nats://127.0.0.1:4222` fallback default is dead code
  in every current production path — every real call site either passes `servers=`
  explicitly or is only reached after `NATS_SERVERS` is already confirmed set.
- **`HEALTH_REQUIRE_WS` defaults to `true`** in the code, but `docker-compose.yml`
  overrides it to `"0"` for `trade-service` — so `/healthz` in the shipped compose
  stack does *not* require the Kraken WebSocket to be connected to report `ok`. This
  is intentional, not a bug — just non-obvious if you only read the code default.
- **`.gitignore`'s blanket `*.jsonl` rule silently swallows new golden fixtures**:
  it exists to keep recorded tick data (`tick_recorder.py` output) out of git, but it
  also matches any new file under `tests/golden/*.jsonl` — a golden test's input
  dataset can be committed as "added" locally while `git add` silently skips it,
  which only surfaces as a `FileNotFoundError` in CI. The narrow negation
  `!tests/golden/*.jsonl` already covers today's golden fixtures; when adding a new
  golden dataset outside that directory (or with a different extension pattern),
  add a matching negation and verify with `git status` that the fixture is actually
  tracked before pushing.

## Environment variables

| Variable | Read by | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | `main.py`, `api.py` | — | **Required** for `main.py`. Accepts `postgresql://` or `postgresql+asyncpg://`. |
| `TRADE_SYMBOL` | `main.py` | `BTC/USD` | Symbol streamed from Kraken. |
| `INITIAL_CASH` | `main.py` | `10000` | Only used when the portfolio has no persisted state yet. |
| `ORDER_NOTIONAL` | `main.py` | `100` | Fixed quote-currency notional per BUY order. |
| `FEE_RATE` | `main.py` | `0.001` | `PercentageFeeModel` rate. |
| `STRATEGY_WINDOW_SEC` | `main.py` | `10.0` | `MomentumBurstStrategy` lookback window. |
| `STRATEGY_THRESHOLD_PCT` | `main.py` | `0.30` | Momentum threshold to emit a signal. |
| `NATS_SERVERS` | `main.py`, `api.py`, `NatsConnectionConfig` | unset | Comma-separated. See *Known quirks* for the unset-behavior split. |
| `NATS_TOKEN` | `NatsConnectionConfig` | `""` | Auth token. |
| `HTTP_HOST` / `HTTP_PORT` | `main.py` | `0.0.0.0` / `8000` | uvicorn bind address. |
| `HEALTH_REQUIRE_WS` | `api.py` | `true` | Whether `/healthz` needs `ws_connected`. compose sets `"0"`. |
| `LOG_LEVEL` | `common/logging_configuration.py` | `INFO` | Falls back to `INFO` with a warning on an unknown name. |
| `LOG_FORMAT` | `common/logging_configuration.py` | `text` | `json` for structured Loki-friendly logs. |
| `MIGRATIONS_DIR` | `db/bootstrap.py` | auto-discovered | Overrides walking up from `db/bootstrap.py` to find `migrations/`. |
| `RUN_INTEGRATION` | tests | unset | `1` to enable `test_integration_*.py`. |

## Observability quick reference

Metric names/labels in `README.md`'s "Metrics Contract" section are a stability
contract — treat renaming or relabeling any of them as a breaking change requiring a
migration note (dashboards in `grafana/dashboards/*.json` query them by name).
