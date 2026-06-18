"""Integration tests for the stable Prometheus metrics contract."""

import re
import unittest

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
from Nightwatch.metrics import NightwatchMetrics


class TestMetricsContractIntegration(unittest.TestCase):
    """Scrape /metrics and assert required contract series are exposed."""

    def test_required_market_and_trade_metrics_are_exposed(self) -> None:
        metrics = NightwatchMetrics()

        # Seed labeled series so they appear in the scrape output.
        metrics.ticks_received_total.labels(symbol="BTC/USD").inc()
        metrics.ticks_published_total.labels(symbol="BTC/USD").inc()
        metrics.signals_total.labels(symbol="BTC/USD", side="BUY", strategy="momentum_burst").inc()
        metrics.signals_rejected_total.labels(symbol="BTC/USD", reason="Cooldown active").inc()
        metrics.orders_created_total.labels(symbol="BTC/USD", side="BUY").inc()
        metrics.orders_filled_total.labels(symbol="BTC/USD", side="BUY").inc()
        metrics.position_qty.labels(symbol="BTC/USD").set(0.25)
        metrics.cash_balance.set(1200)
        metrics.equity.set(1450)
        metrics.fees_paid_total.inc(2.5)

        client = TestClient(create_app(metrics=metrics))
        try:
            response = client.get("/metrics")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        body = response.text

        required_patterns = [
            r"(?m)^ticks_received_total\{symbol=\"[^\"]+\"\}\s+",
            r"(?m)^ticks_published_total\{symbol=\"[^\"]+\"\}\s+",
            r"(?m)^ws_reconnects_total\s+",
            r"(?m)^parse_errors_total\s+",
            r"(?m)^signals_total\{side=\"[^\"]+\",strategy=\"[^\"]+\",symbol=\"[^\"]+\"\}\s+",
            r"(?m)^signals_rejected_total\{reason=\"[^\"]+\",symbol=\"[^\"]+\"\}\s+",
            r"(?m)^orders_created_total\{side=\"[^\"]+\",symbol=\"[^\"]+\"\}\s+",
            r"(?m)^orders_filled_total\{side=\"[^\"]+\",symbol=\"[^\"]+\"\}\s+",
            r"(?m)^position_qty\{symbol=\"[^\"]+\"\}\s+",
            r"(?m)^cash_balance\s+",
            r"(?m)^equity\s+",
            r"(?m)^fees_paid_total\s+",
        ]

        for pattern in required_patterns:
            self.assertIsNotNone(re.search(pattern, body), msg=f"Missing required metric pattern: {pattern}")


if __name__ == "__main__":
    unittest.main()
