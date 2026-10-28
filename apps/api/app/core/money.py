"""Decimal-only money helpers. Floats are never accepted."""

from decimal import ROUND_HALF_UP, Decimal


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is not allowed for money; pass str or Decimal")
    return value if isinstance(value, Decimal) else Decimal(value)


def quantize(amount: Decimal, precision: int, rounding: str = ROUND_HALF_UP) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-precision), rounding=rounding)


def allocate(total: Decimal, weights: list[Decimal], precision: int = 2) -> list[Decimal]:
    """Split `total` by `weights` so the parts sum exactly to `total` (largest-remainder method).

    Ties on the remainder go to the earlier weight, which keeps results deterministic.
    """
    if not weights:
        raise ValueError("weights must not be empty")
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights, Decimal(0))
    if weight_sum == 0:
        raise ValueError("weights must not all be zero")

    unit = Decimal(1).scaleb(-precision)
    total = quantize(total, precision)
    sign = -1 if total < 0 else 1
    total_units = int(abs(total) / unit)

    exact = [Decimal(total_units) * w / weight_sum for w in weights]
    floors = [int(e) for e in exact]
    leftover = total_units - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:leftover]:
        floors[i] += 1
    return [sign * Decimal(units) * unit for units in floors]
