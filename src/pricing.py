from decimal import Decimal

COST_PER_MILLION = Decimal("1_000_000")

MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "gpt-4o-mini": {
        "input": Decimal("0.15"),
        "output": Decimal("0.60"),
    },
    "gpt-4o": {
        "input": Decimal("2.50"),
        "output": Decimal("10.00"),
    },
    "gpt-4o-mini-2024-07-18": {
        "input": Decimal("0.15"),
        "output": Decimal("0.60"),
    },
    "gpt-4o-2024-08-06": {
        "input": Decimal("2.50"),
        "output": Decimal("10.00"),
    },
}


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return Decimal("0")
    input_cost = pricing["input"] * Decimal(tokens_in) / COST_PER_MILLION
    output_cost = pricing["output"] * Decimal(tokens_out) / COST_PER_MILLION
    return input_cost + output_cost
