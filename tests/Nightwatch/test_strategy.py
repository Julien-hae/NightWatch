"""Tests for the Strategy class."""

import unittest

from Nightwatch.strategy import Strategy


class TestStrategy(unittest.TestCase):
    """Unit tests for the Strategy class."""

    def test_cannot_instantiate_directly(self) -> None:
        """Given Strategy is abstract, When instantiated, Then TypeError."""
        with self.assertRaises(TypeError):
            Strategy()  # type: ignore
