"""End-to-end CLI behaviour.

`demo` is the command a stranger runs first, so it carries the most weight
here: it must work with no key, no network and no arguments, and it must never
print the fixtures without also printing that they are fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from costfloor.cli import main

RUNS = Path("/tmp/_costfloor_runs")


class TestDemo:
    def test_runs_with_no_arguments(self) -> None:
        result = CliRunner().invoke(main, ["demo"])
        assert result.exit_code == 0, result.output

    def test_always_labels_the_fixtures_as_fixtures(self) -> None:
        """The disclaimer is load-bearing: without it this output looks measured."""
        result = CliRunner().invoke(main, ["demo"])
        assert "not measurements" in result.output

    def test_reports_every_family(self) -> None:
        result = CliRunner().invoke(main, ["demo"])
        for family in ("screen_qa", "app_automation", "code_edit",
                       "file_organisation", "research_synthesis"):
            assert family in result.output

    def test_json_output_is_parseable_and_carries_the_disclaimer(self) -> None:
        result = CliRunner().invoke(main, ["demo", "--json"])
        payload = json.loads(result.output)
        assert "not measurements" in payload["disclaimer"]
        assert len(payload["floors"]) == 5

    def test_no_dollar_figures_without_a_rate_file(self) -> None:
        result = CliRunner().invoke(main, ["demo"])
        assert "$" not in result.output


class TestVerify:
    def test_shipped_suite_verifies(self) -> None:
        result = CliRunner().invoke(main, ["verify"])
        assert result.exit_code == 0
        assert "all predicates resolve" in result.output

    def test_unknown_predicate_exits_non_zero(self) -> None:
        bad = Path("/tmp/_costfloor_bad_suite")
        bad.mkdir(exist_ok=True)
        (bad / "t.yaml").write_text(
            "- task_id: t\n  family: screen_qa\n  prompt: x\n"
            "  constraints:\n    - {id: c, predicate: not_a_real_predicate}\n"
        )
        result = CliRunner().invoke(main, ["verify", "--suite", str(bad)])
        assert result.exit_code == 1
        assert "unknown predicate" in result.output


class TestScore:
    def test_empty_directory_is_an_error_not_an_empty_report(self) -> None:
        RUNS.mkdir(exist_ok=True)
        for stale in RUNS.glob("*.json"):
            stale.unlink()
        result = CliRunner().invoke(
            main, ["score", str(RUNS), "--baseline", "tier_a_frontier"]
        )
        assert result.exit_code != 0
        assert "no .json trajectories" in result.output

    def test_scores_recorded_trajectories(self) -> None:
        from costfloor import demo as demo_module

        RUNS.mkdir(exist_ok=True)
        for task_id, arms in demo_module.build().items():
            for arm, traj in arms.items():
                (RUNS / f"{task_id}__{arm}.json").write_text(traj.model_dump_json())
        result = CliRunner().invoke(
            main, ["score", str(RUNS), "--baseline", demo_module.BASELINE_ARM]
        )
        assert result.exit_code == 0, result.output
        assert "code_edit" in result.output
