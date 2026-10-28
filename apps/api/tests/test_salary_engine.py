"""Pure salary math: the formula engine (Section 9) and salary period dates (Section 10.1)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.compensation.engine import DEFAULT_DEFINITION, FormulaDefinition, calculate, rate_for
from app.modules.compensation.service import parse_definition
from app.modules.salary import cycle

D = Decimal


@pytest.mark.parametrize(
    ("revenue", "salary"),
    [
        ("0", "0.00"),
        ("2999.99", "0.00"),  # F2: the step at $3,000 is intended
        ("3000", "240.00"),
        ("4000", "352.59"),
        ("6000", "626.67"),
        ("10000", "1370.37"),
        ("20000", "4370.37"),
        ("30000", "9000.00"),
        ("40000", "12000.00"),  # F1: 30% holds above $30k
    ],
)
def test_default_formula_matches_the_design_table(revenue: str, salary: str) -> None:
    assert calculate(DEFAULT_DEFINITION, D(revenue)).amount == D(salary)


def test_rate_is_not_rounded_and_applies_to_whole_revenue() -> None:
    r = calculate(DEFAULT_DEFINITION, D(6000))
    assert D("0.104444") < r.rate < D("0.104445")  # 8% + 22% x 3,000 / 27,000
    assert r.components[0].basis == D(6000)  # F3: the whole amount, not a slice


def _defn(**schedule: object) -> FormulaDefinition:
    return FormulaDefinition.model_validate({"rate_schedule": schedule})


def test_flat_and_progressive_tiers() -> None:
    tiers = [{"from_revenue": "0", "rate": "0.05"}, {"from_revenue": "5000", "rate": "0.10"}]
    flat = _defn(mode="flat_tiers", tiers=tiers)
    progressive = _defn(mode="progressive_tiers", tiers=tiers)
    assert calculate(flat, D(8000)).amount == D("800.00")  # 10% of everything
    assert calculate(progressive, D(8000)).amount == D("550.00")  # 5% of 5,000 + 10% of 3,000
    assert calculate(progressive, D(8000)).rate == D("550.00") / D(8000)
    assert rate_for(flat.rate_schedule, D(4999.99)) == D("0.05")


def test_curve_below_first_point_options() -> None:
    pts = [{"revenue": "1000", "rate": "0.1"}, {"revenue": "2000", "rate": "0.2"}]
    assert calculate(_defn(mode="linear_curve", points=pts), D(500)).amount == 0
    first = _defn(mode="linear_curve", points=pts, below_first_point="first_rate")
    assert calculate(first, D(500)).amount == D("50.00")
    assert calculate(first, D(1500)).amount == D("225.00")  # 15% interpolated


def test_fixed_bonus_min_max_and_adjustments() -> None:
    d = FormulaDefinition.model_validate(
        {
            "rate_schedule": {"mode": "flat_tiers", "tiers": [{"from_revenue": "0", "rate": "0.1"}]},
            "fixed_amount": "1000",
            "bonuses": [{"label": "Big month", "min_revenue": "20000", "amount": "500"}],
            "min_payout": "1200",
            "max_payout": "3000",
        }
    )
    low = calculate(d, D(1000))  # 100 + 1000 -> topped up to 1200
    assert low.formula_amount == D(1200) and [c.component for c in low.components][-1] == "min_payout"
    high = calculate(d, D(25000), [("Bonus: launch", D(400)), ("Deduction: advance", D(-100))])
    # 2,500 + 1,000 + 500 = 4,000 -> capped at 3,000; adjustments are never capped
    assert high.formula_amount == D(3000) and high.adjustments_total == D(300) and high.amount == D(3300)
    assert sum(c.amount for c in high.components) == high.amount


def test_fixed_salary_only() -> None:
    d = FormulaDefinition.model_validate({"rate_schedule": {"mode": "none"}, "fixed_amount": "2500"})
    assert calculate(d, D(0)).amount == D(2500) and calculate(d, D(99999)).amount == D(2500)


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"rate_schedule": {"mode": "linear_curve", "points": []}}, "definition.rate_schedule"),
        (
            {
                "rate_schedule": {
                    "mode": "linear_curve",
                    "points": [{"revenue": "5", "rate": "0.1"}, {"revenue": "1", "rate": "0.2"}],
                }
            },
            "definition.rate_schedule",
        ),
        ({"rate_schedule": {"mode": "flat_tiers", "tiers": [{"from_revenue": "0", "rate": "1.5"}]}}, "rate"),
        ({"rate_schedule": {"mode": "none"}, "min_payout": "10", "max_payout": "5"}, "definition"),
    ],
)
def test_invalid_definitions_are_rejected(raw: dict, field: str) -> None:
    from app.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as exc:
        parse_definition(raw)
    assert any(e["field"].startswith(field) or field in e["field"] for e in exc.value.errors)


# ---- periods ---------------------------------------------------------------------------------------


def test_25th_cycle_labels_and_boundaries() -> None:
    nov = cycle.regular(25, date(2026, 11, 10))
    assert (nov.start, nov.end, nov.label) == (date(2026, 10, 25), date(2026, 11, 24), "Nov 2026")
    assert cycle.regular(25, date(2026, 11, 24)) == nov
    assert cycle.regular(25, date(2026, 11, 25)).label == "Dec 2026"
    jan = cycle.regular(25, date(2027, 1, 3))  # across the year end
    assert (jan.start, jan.end) == (date(2026, 12, 25), date(2027, 1, 24))
    assert cycle.regular(1, date(2028, 2, 15)).end == date(2028, 2, 29)  # leap year


@pytest.mark.parametrize("day", range(1, 29))
def test_every_start_day_gives_contiguous_regular_periods(day: int) -> None:
    span = cycle.regular(day, date(2027, 1, 1))
    for s in cycle.upcoming(span.end, day, 30):
        assert s.start == span.end + timedelta(days=1)
        assert not s.is_transition and s.start.day == day
        assert 28 <= (s.end - s.start).days + 1 <= 31
        span = s


def test_changing_the_day_creates_one_transition_period() -> None:
    # From calendar months to the 25th, after November: Dec 1 - Dec 24, then Dec 25 - Jan 24.
    t, nxt = cycle.upcoming(date(2026, 11, 30), 25, 2)
    assert (t.start, t.end, t.is_transition) == (date(2026, 12, 1), date(2026, 12, 24), True)
    assert t.label == "Dec 2026 (transition)"
    assert (nxt.start, nxt.end, nxt.is_transition) == (date(2026, 12, 25), date(2027, 1, 24), False)
    # From the 25th back to the 1st: Nov 25 - Nov 30, then December.
    t, nxt = cycle.upcoming(date(2026, 11, 24), 1, 2)
    assert (t.start, t.end) == (date(2026, 11, 25), date(2026, 11, 30))
    assert (nxt.start, nxt.end) == (date(2026, 12, 1), date(2026, 12, 31))


def test_previous_period_lines_up_with_the_first() -> None:
    p = cycle.previous_before(date(2026, 10, 25), 25)
    assert (p.start, p.end, p.is_transition) == (date(2026, 9, 25), date(2026, 10, 24), False)
    odd = cycle.previous_before(date(2026, 12, 1), 25)  # first period started off-cycle
    assert (odd.start, odd.end, odd.is_transition) == (date(2026, 11, 25), date(2026, 11, 30), True)
