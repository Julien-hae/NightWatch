"""Unit tests for in-memory repository implementations."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from decimal import Decimal

from Nightwatch.db.repositories import InMemoryOrderRepo, InMemoryPositionRepo, OrderCreateResult
from tests.fixtures.order_factory import make_order


@dataclass
class _Position:
    symbol: str
    qty: Decimal


class TestInMemoryOrderRepo(unittest.TestCase):
    def test_duplicate_idempotency_key_returns_already_exists(self) -> None:
        repo = InMemoryOrderRepo()
        first = make_order()
        second = make_order(signal_id=first.signal_id)

        first_result = repo.create(first)
        second_result = repo.create(second)

        self.assertEqual(first_result, OrderCreateResult.CREATED)
        self.assertEqual(second_result, OrderCreateResult.ALREADY_EXISTS)


class TestInMemoryPositionRepo(unittest.TestCase):
    def test_upsert_and_get_position(self) -> None:
        repo = InMemoryPositionRepo()

        self.assertEqual(repo.get("BTC/USD"), Decimal("0"))

        repo.upsert(_Position(symbol="BTC/USD", qty=Decimal("0.25")))
        self.assertEqual(repo.get("BTC/USD"), Decimal("0.25"))

        repo.upsert(_Position(symbol="BTC/USD", qty=Decimal("0.40")))
        self.assertEqual(repo.get("BTC/USD"), Decimal("0.40"))


if __name__ == "__main__":
    unittest.main()
