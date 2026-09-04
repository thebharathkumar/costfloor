"""Cost accounting and the report that reads it.

The property that matters most here is negative: the report must never quote a
dollar saving it cannot source. A harness whose own output overstates the win
is the exact failure it was built to detect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from costfloor import demo as demo_module
from costfloor.cost import RateCard, cost_multiple, total_usage
from costfloor.report import render, score
from costfloor.spec import load_suite
from costfloor.trajectory import Usage

SUITE = Path(__file__).resolve().parents[1] / "src" / "costfloor" / "suite"
RATES = Path("/tmp/_costfloor_rates.yaml")
RATES.write_text(
    "source: test fixture\nas_of: '2026-09-04'\nrates:\n"
    "  tier_a_frontier: {input_per_mtok: 15.0, output_per_mtok: 75.0}\n"
    "  tier_b_mid: {input_per_mtok: 3.0, output_per_mtok: 15.0}\n"
)


class TestUsage:
    def test_cached_input_is_not_billed_twice(self) -> None:
        u = Usage(input_tokens=1000, cached_input_tokens=900, output_tokens=100)
        assert u.billable_input == 100
        assert u.total == 1100

    def test_totals_add_up(self) -> None:
        t = total_usage([Usage(input_tokens=10, output_tokens=1)] * 3)
        assert (t.input_tokens, t.output_tokens) == (30, 3)

    def test_zero_baseline_is_not_an_infinite_saving(self) -> None:
        assert cost_multiple(Usage(input_tokens=10), Usage()) is None


class TestRateCard:
    def test_unknown_arm_returns_none_rather_than_zero(self) -> None:
        card = RateCard.load(RATES)
        assert card.dollars("tier_d_tiny", Usage(input_tokens=1000)) is None

    def test_price_is_per_million_tokens(self) -> None:
        card = RateCard.load(RATES)
        got = card.dollars("tier_b_mid", Usage(input_tokens=1_000_000, output_tokens=0))
        assert got == pytest.approx(3.0)

    def test_provenance_is_required(self) -> None:
        bad = Path("/tmp/_costfloor_bad_rates.yaml")
        bad.write_text("rates: {}\n")
        with pytest.raises(Exception):
            RateCard.load(bad)


class TestReport:
    def setup_method(self) -> None:
        self.suite = load_suite(SUITE)
        self.floors = score(self.suite, demo_module.build(),
                            baseline_arm=demo_module.BASELINE_ARM)

    def test_every_family_is_scored(self) -> None:
        assert {f.family for f in self.floors} == set(self.suite.families())

    def test_baseline_cost_multiple_is_one(self) -> None:
        for floor in self.floors:
            base = next(r for r in floor.results if r.arm == floor.baseline_arm)
            assert base.cost_multiple == pytest.approx(1.0)

    def test_code_edit_has_no_safe_downgrade(self) -> None:
        """No arm below the baseline runs the tests, so the floor is the baseline."""
        floor = next(f for f in self.floors if f.family == "code_edit")
        assert floor.floor_arm == floor.baseline_arm

    def test_a_family_with_a_clean_cheaper_arm_reports_one(self) -> None:
        floor = next(f for f in self.floors if f.family == "file_organisation")
        assert floor.floor_arm == "tier_b_mid"

    def test_render_without_rates_never_prints_a_dollar_figure(self) -> None:
        out = render(self.floors, None)
        assert "$" not in out
        assert "tokens only" in out

    def test_render_with_rates_cites_its_source(self) -> None:
        out = render(self.floors, RateCard.load(RATES))
        assert "test fixture" in out and "2026-09-04" in out

    def test_verdict_never_quotes_a_saving_without_prices(self) -> None:
        """Token ratios are ~1.00x even when dollars differ 20x. Never imply otherwise."""
        for floor in self.floors:
            assert "%" not in floor.verdict
