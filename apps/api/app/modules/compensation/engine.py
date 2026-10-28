"""Salary formula definitions and the calculation (docs/architecture.md, Section 9).

Pure and deterministic: Decimal in, Decimal out, no database. A definition is stored as JSON on a
formula version and validated by `FormulaDefinition` before it is saved.
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.money import quantize

ZERO = Decimal(0)
Amount = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]
Rate = Annotated[Decimal, Field(ge=0, le=1, max_digits=12, decimal_places=10)]


class CurvePoint(BaseModel):
    revenue: Amount
    rate: Rate


class RateTier(BaseModel):
    from_revenue: Amount
    rate: Rate


class RateSchedule(BaseModel):
    """How the revenue share is computed.

    - none: no revenue share (fixed salary only)
    - linear_curve: straight lines between points, whole revenue at the resulting rate; holds the last
      rate above the last point; below the first point either nothing or the first rate
    - flat_tiers: the tier containing the revenue sets the rate for the whole revenue
    - progressive_tiers: each slice of revenue at its own tier's rate (like tax bands)
    """

    mode: Literal["none", "linear_curve", "flat_tiers", "progressive_tiers"]
    below_first_point: Literal["zero", "first_rate"] = "zero"
    points: list[CurvePoint] = []
    tiers: list[RateTier] = []

    @model_validator(mode="after")
    def _check(self) -> "RateSchedule":
        if self.mode == "linear_curve":
            if not self.points:
                raise ValueError("A rate curve needs at least one point")
            revenues = [p.revenue for p in self.points]
            if revenues != sorted(set(revenues)):
                raise ValueError("Curve points must have increasing revenue")
        if self.mode in ("flat_tiers", "progressive_tiers"):
            if not self.tiers:
                raise ValueError("Add at least one tier")
            starts = [t.from_revenue for t in self.tiers]
            if starts != sorted(set(starts)):
                raise ValueError("Tiers must start at increasing revenue")
        return self


class RuleBonus(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    min_revenue: Amount
    amount: Amount


class RoundingRule(BaseModel):
    mode: Literal["half_up", "down"] = "half_up"
    precision: int = Field(default=2, ge=0, le=4)


class FormulaDefinition(BaseModel):
    rate_schedule: RateSchedule
    fixed_amount: Amount = ZERO
    bonuses: list[RuleBonus] = []
    min_payout: Amount | None = None
    max_payout: Amount | None = None
    rounding: RoundingRule = RoundingRule()

    @model_validator(mode="after")
    def _check(self) -> "FormulaDefinition":
        if self.min_payout is not None and self.max_payout is not None and self.min_payout > self.max_payout:
            raise ValueError("Minimum payout is above the maximum")
        return self


# Provisional rule from Q4/F1-F3: nothing below $3k, 8% at $3k rising linearly to 30% at $30k, held
# above, applied to the whole period revenue.
DEFAULT_DEFINITION = FormulaDefinition(
    rate_schedule=RateSchedule(
        mode="linear_curve",
        below_first_point="zero",
        points=[
            CurvePoint(revenue=Decimal(3000), rate=Decimal("0.08")),
            CurvePoint(revenue=Decimal(30000), rate=Decimal("0.30")),
        ],
    ),
)


@dataclass
class Component:
    component: str  # revenue_share | fixed | bonus | min_payout | max_payout | adjustment
    label: str
    amount: Decimal
    basis: Decimal | None = None
    rate: Decimal | None = None


@dataclass
class Result:
    revenue: Decimal
    rate: Decimal  # effective revenue-share rate (share / revenue); unrounded
    formula_amount: Decimal  # revenue share + fixed + bonuses, after min/max
    adjustments_total: Decimal
    amount: Decimal  # formula_amount + adjustments
    components: list[Component] = field(default_factory=list)


def rate_for(schedule: RateSchedule, revenue: Decimal) -> Decimal:
    """Rate applied to the whole revenue (curve and flat tiers). Not rounded."""
    if schedule.mode == "linear_curve":
        pts = schedule.points
        if revenue < pts[0].revenue:
            return pts[0].rate if schedule.below_first_point == "first_rate" else ZERO
        for lo, hi in itertools.pairwise(pts):
            if revenue <= hi.revenue:
                return lo.rate + (hi.rate - lo.rate) * (revenue - lo.revenue) / (hi.revenue - lo.revenue)
        return pts[-1].rate
    if schedule.mode == "flat_tiers":
        rate = ZERO
        for t in schedule.tiers:
            if revenue >= t.from_revenue:
                rate = t.rate
        return rate
    return ZERO


def _progressive(tiers: list[RateTier], revenue: Decimal) -> list[Component]:
    out = []
    for i, t in enumerate(tiers):
        upper = tiers[i + 1].from_revenue if i + 1 < len(tiers) else None
        if revenue <= t.from_revenue:
            break
        slice_ = (min(revenue, upper) if upper is not None else revenue) - t.from_revenue
        label = f"{t.from_revenue}–{upper}" if upper is not None else f"above {t.from_revenue}"
        out.append(Component("revenue_share", f"Revenue {label}", slice_ * t.rate, basis=slice_, rate=t.rate))
    return out


def calculate(
    definition: FormulaDefinition, revenue: Decimal, adjustments: Sequence[tuple[str, Decimal]] = ()
) -> Result:
    """Salary for one employee and one period (Section 9.4).

    Revenue share + fixed + rule bonuses, then min/max payout, then manual adjustments (which are never
    capped). Components are rounded once each, so the breakdown always adds up to the total.
    """
    r = definition.rounding
    rnd = ROUND_HALF_UP if r.mode == "half_up" else ROUND_DOWN

    def q(x: Decimal) -> Decimal:
        return quantize(x, r.precision, rnd)

    schedule = definition.rate_schedule
    parts: list[Component] = []
    if schedule.mode == "progressive_tiers":
        slices = _progressive(schedule.tiers, revenue)
        share = q(sum((c.amount for c in slices), ZERO))
        rate = share / revenue if revenue > 0 else ZERO
        parts.append(Component("revenue_share", "Revenue share", share, basis=revenue, rate=rate))
    elif schedule.mode != "none":
        rate = rate_for(schedule, revenue)
        parts.append(Component("revenue_share", "Revenue share", q(revenue * rate), basis=revenue, rate=rate))
    else:
        rate = ZERO
    if definition.fixed_amount:
        parts.append(Component("fixed", "Fixed amount", q(definition.fixed_amount)))
    for b in definition.bonuses:
        if revenue >= b.min_revenue:
            parts.append(Component("bonus", b.label, q(b.amount), basis=b.min_revenue))

    formula_amount = sum((c.amount for c in parts), ZERO)
    if definition.min_payout is not None and formula_amount < definition.min_payout:
        parts.append(Component("min_payout", "Topped up to minimum", q(definition.min_payout - formula_amount)))
        formula_amount = q(definition.min_payout)
    if definition.max_payout is not None and formula_amount > definition.max_payout:
        parts.append(Component("max_payout", "Capped at maximum", q(definition.max_payout - formula_amount)))
        formula_amount = q(definition.max_payout)

    adj_total = ZERO
    for label, amount in adjustments:
        parts.append(Component("adjustment", label, q(amount)))
        adj_total += q(amount)
    return Result(
        revenue=revenue,
        rate=rate,
        formula_amount=formula_amount,
        adjustments_total=adj_total,
        amount=formula_amount + adj_total,
        components=parts,
    )
