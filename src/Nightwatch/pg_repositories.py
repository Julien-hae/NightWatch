"""Postgres-backed async repository implementations using asyncpg."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.signal import Signal
from Nightwatch.repositories import OrderCreateResult

LOGGER = logging.getLogger(__name__)


class AsyncSignalRepo(Protocol):
    """Async persistence port for signals."""

    async def save(self, signal: Signal) -> None:
        """Persist a signal (upsert)."""


class AsyncOrderRepo(Protocol):
    """Async persistence port for orders."""

    async def create(self, order: Order) -> OrderCreateResult:
        """Create an order once, or return already-exists on duplicate idempotency key."""


class AsyncFillRepo(Protocol):
    """Async persistence port for fills."""

    async def append(self, fill: Fill) -> None:
        """Append a fill."""


class AsyncPositionRepo(Protocol):
    """Async persistence port for positions."""

    async def get(self, symbol: str) -> Decimal:
        """Return current quantity for *symbol* or zero if absent."""

    async def get_all(self) -> dict[str, Decimal]:
        """Return all positions as a mapping of symbol to quantity."""

    async def upsert(self, symbol: str, qty: Decimal) -> None:
        """Insert or replace the quantity for *symbol*."""


class AsyncPortfolioStateRepo(Protocol):
    """Async persistence port for portfolio state (cash balance)."""

    async def get_cash(self) -> Decimal:
        """Return current cash balance, or zero if not found."""

    async def save_cash(self, cash: Decimal) -> None:
        """Persist or update cash balance."""


class PgSignalRepo:
    """Postgres signal repository with upsert semantics."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def save(self, signal: Signal) -> None:
        """Upsert *signal* by its uid.

        Args:
            signal: Signal to persist.
        """
        sql = """
            INSERT INTO signals (signal_id, symbol, side, strength, strategy, source, schema_version, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (signal_id) DO UPDATE
                SET symbol = EXCLUDED.symbol,
                    side = EXCLUDED.side,
                    strength = EXCLUDED.strength,
                    strategy = EXCLUDED.strategy,
                    source = EXCLUDED.source,
                    schema_version = EXCLUDED.schema_version,
                    ts = EXCLUDED.ts
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                signal.uid,
                signal.symbol,
                signal.side.value,
                signal.strength,
                signal.strategy,
                signal.source,
                signal.schema_version,
                signal.timestamp,
            )


class PgOrderRepo:
    """Postgres order repository with idempotent create semantics.

    The idempotency key is ``order.signal_id``, matching the in-memory repo.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def create(self, order: Order) -> OrderCreateResult:
        """Insert *order*, skipping on duplicate idempotency key.

        Args:
            order: Order to persist.

        Returns:
            ``CREATED`` when inserted, ``ALREADY_EXISTS`` on conflict.
        """
        sql = """
            INSERT INTO orders (order_id, idempotency_key, signal_id, symbol, side, qty, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (idempotency_key) DO NOTHING
        """
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                sql,
                order.order_id,
                order.signal_id,  # idempotency_key == signal_id
                order.signal_id,
                order.symbol,
                order.side.value,
                order.qty,
                order.status.value,
                order.created_at,
            )
        inserted = int(status.split()[-1])
        return OrderCreateResult.CREATED if inserted == 1 else OrderCreateResult.ALREADY_EXISTS


class PgFillRepo:
    """Postgres append-only fill repository."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def append(self, fill: Fill) -> None:
        """Insert *fill* into the fills table.

        Args:
            fill: Fill to persist.
        """
        sql = """
            INSERT INTO fills (fill_id, order_id, symbol, side, qty, price, fee, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                fill.fill_id,
                fill.order_id,
                fill.symbol,
                fill.side.value,
                fill.qty,
                fill.price,
                fill.fee,
                fill.ts,
            )


class PgPositionRepo:
    """Postgres position repository with upsert semantics."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def get(self, symbol: str) -> Decimal:
        """Return current quantity for *symbol*, or zero if absent.

        Args:
            symbol: Trading symbol to look up.

        Returns:
            Current position quantity, or ``Decimal("0")`` when not found.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT qty FROM positions WHERE symbol = $1", symbol)
        if row is None:
            return Decimal("0")
        return Decimal(str(row["qty"]))

    async def get_all(self) -> dict[str, Decimal]:
        """Return all positions as a mapping of symbol to quantity.

        Returns:
            Dict of symbol → quantity for every row in the positions table.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT symbol, qty FROM positions")
        return {row["symbol"]: Decimal(str(row["qty"])) for row in rows}

    async def upsert(self, symbol: str, qty: Decimal) -> None:
        """Insert or replace position quantity for *symbol*.

        Args:
            symbol: Trading symbol.
            qty: New quantity to store.
        """
        sql = """
            INSERT INTO positions (symbol, qty, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (symbol) DO UPDATE
                SET qty = EXCLUDED.qty,
                    updated_at = EXCLUDED.updated_at
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, symbol, qty)


class PgEquitySnapshotRepo:
    """Postgres repository for equity snapshots."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def insert(self, equity: Decimal, cash: Decimal) -> None:
        """Append an equity snapshot row.

        Args:
            equity: Total portfolio equity value.
            cash: Cash component of the portfolio.
        """
        sql = "INSERT INTO equity_snapshots (equity, cash, ts) VALUES ($1, $2, NOW())"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, equity, cash)


class PgPortfolioStateRepo:
    """Postgres repository for portfolio state (cash balance) with single-row semantics."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Shared asyncpg connection pool.
        """
        self._pool = pool

    async def get_cash(self) -> Decimal:
        """Return current cash balance, or zero if not found.

        Returns:
            Current cash balance, or ``Decimal("0")`` when portfolio_state is empty.
        """
        sql = "SELECT cash FROM portfolio_state LIMIT 1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql)
        if row is None:
            return Decimal("0")
        return Decimal(str(row["cash"]))

    async def save_cash(self, cash: Decimal) -> None:
        """Persist or update cash balance (single row).

        Args:
            cash: Cash balance to persist.
        """
        sql = """
            INSERT INTO portfolio_state (cash, updated_at)
            VALUES ($1, NOW())
            ON CONFLICT (cash) DO UPDATE
                SET updated_at = NOW()
        """
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM portfolio_state")
            await conn.execute(sql, cash)


class PgAtomicTradeWriter:
    """Write order/fill/portfolio state in a single DB transaction.

    The order insert is idempotent on ``idempotency_key = signal_id``.
    When the order already exists, no additional writes are performed.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialise with an asyncpg connection pool."""
        self._pool = pool

    async def write_trade(
        self,
        order: Order,
        fill: Fill,
        *,
        position_qty: Decimal,
        cash: Decimal,
        equity: Decimal,
    ) -> OrderCreateResult:
        """Persist one trade atomically and idempotently.

        Args:
            order: Order to insert with signal-id idempotency.
            fill: Fill linked to the order.
            position_qty: Updated position qty for ``fill.symbol``.
            cash: Updated portfolio cash balance.
            equity: Updated total portfolio equity.

        Returns:
            ``CREATED`` when all rows were committed once.
            ``ALREADY_EXISTS`` when the order idempotency key already exists.
        """
        insert_order_sql = """
            INSERT INTO orders (order_id, idempotency_key, signal_id, symbol, side, qty, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (idempotency_key) DO NOTHING
        """
        insert_fill_sql = """
            INSERT INTO fills (fill_id, order_id, symbol, side, qty, price, fee, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        upsert_position_sql = """
            INSERT INTO positions (symbol, qty, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (symbol) DO UPDATE
                SET qty = EXCLUDED.qty,
                    updated_at = EXCLUDED.updated_at
        """
        upsert_cash_sql = """
            INSERT INTO portfolio_state (cash, updated_at)
            VALUES ($1, NOW())
            ON CONFLICT (cash) DO UPDATE
                SET updated_at = NOW()
        """
        insert_equity_sql = "INSERT INTO equity_snapshots (equity, cash, ts) VALUES ($1, $2, NOW())"

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    insert_order_sql,
                    order.order_id,
                    order.signal_id,
                    order.signal_id,
                    order.symbol,
                    order.side.value,
                    order.qty,
                    order.status.value,
                    order.created_at,
                )
                inserted = int(status.split()[-1])
                if inserted == 0:
                    return OrderCreateResult.ALREADY_EXISTS

                await conn.execute(
                    insert_fill_sql,
                    fill.fill_id,
                    fill.order_id,
                    fill.symbol,
                    fill.side.value,
                    fill.qty,
                    fill.price,
                    fill.fee,
                    fill.ts,
                )
                await conn.execute(upsert_position_sql, fill.symbol, position_qty)
                await conn.execute("DELETE FROM portfolio_state")
                await conn.execute(upsert_cash_sql, cash)
                await conn.execute(insert_equity_sql, equity, cash)

        return OrderCreateResult.CREATED
