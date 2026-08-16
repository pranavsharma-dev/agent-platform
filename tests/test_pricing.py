from decimal import Decimal

from src.pricing import compute_cost


class TestComputeCost:
    def test_gpt4o_mini_cost(self):
        cost = compute_cost("gpt-4o-mini", tokens_in=1000, tokens_out=500)
        expected_in = Decimal("0.15") * Decimal("1000") / Decimal("1000000")
        expected_out = Decimal("0.60") * Decimal("500") / Decimal("1000000")
        assert cost == expected_in + expected_out

    def test_gpt4o_cost(self):
        cost = compute_cost("gpt-4o", tokens_in=1000, tokens_out=500)
        expected_in = Decimal("2.50") * Decimal("1000") / Decimal("1000000")
        expected_out = Decimal("10.00") * Decimal("500") / Decimal("1000000")
        assert cost == expected_in + expected_out

    def test_unknown_model_returns_zero(self):
        cost = compute_cost("unknown-model", tokens_in=1000, tokens_out=500)
        assert cost == Decimal("0")

    def test_zero_tokens(self):
        cost = compute_cost("gpt-4o-mini", tokens_in=0, tokens_out=0)
        assert cost == Decimal("0")

    def test_large_token_count(self):
        cost = compute_cost("gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
        assert cost == Decimal("0.15") + Decimal("0.60")

    def test_dated_model_variant(self):
        cost_base = compute_cost("gpt-4o-mini", tokens_in=100, tokens_out=100)
        cost_dated = compute_cost("gpt-4o-mini-2024-07-18", tokens_in=100, tokens_out=100)
        assert cost_base == cost_dated
