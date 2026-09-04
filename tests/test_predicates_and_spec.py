"""Suite loading and the predicate registry.

The theme: everything that can be wrong with a suite must fail loudly at load
or verify time. A typo that silently scores as a passing constraint is worse
than a crash, because it produces a confident green report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from costfloor import predicates
from costfloor.predicates import UnknownPredicate
from costfloor.spec import load_suite
from costfloor.trajectory import Step, Trajectory

SUITE = Path(__file__).resolve().parents[1] / "src" / "costfloor" / "suite"


def traj(steps: list[Step] | None = None, answer: str = "") -> Trajectory:
    return Trajectory(task_id="t", arm="a", steps=steps or [], final_answer=answer)


class TestSuite:
    def test_shipped_suite_loads(self) -> None:
        suite = load_suite(SUITE)
        assert len(suite) == 6

    def test_every_task_has_at_least_one_constraint(self) -> None:
        for task in load_suite(SUITE).tasks:
            assert task.constraints, f"{task.task_id} has nothing to detect"

    def test_every_predicate_in_the_suite_is_registered(self) -> None:
        for task in load_suite(SUITE).tasks:
            for constraint in task.constraints:
                assert constraint.predicate in predicates.REGISTRY

    def test_duplicate_task_ids_are_rejected(self, tmp_path: Path = Path("/tmp")) -> None:
        path = Path("/tmp/_costfloor_dupe.yaml")
        path.write_text(
            "- {task_id: a, family: screen_qa, prompt: x}\n"
            "- {task_id: a, family: screen_qa, prompt: y}\n"
        )
        with pytest.raises(ValueError, match="duplicate"):
            load_suite(path)


class TestPredicates:
    def test_unknown_predicate_raises_rather_than_passing(self) -> None:
        with pytest.raises(UnknownPredicate):
            predicates.evaluate("no_such_predicate", traj(), {})

    def test_called_tool_counts_repeats(self) -> None:
        t = traj([Step(kind="tool_call", name="stat_file")] * 2)
        assert predicates.evaluate("called_tool", t, {"name": "stat_file", "min_times": 2})
        assert not predicates.evaluate("called_tool", t, {"name": "stat_file", "min_times": 3})

    def test_never_called_tool(self) -> None:
        t = traj([Step(kind="tool_call", name="send_invite")])
        assert not predicates.evaluate("never_called_tool", t, {"name": "send_invite"})
        assert predicates.evaluate("never_called_tool", t, {"name": "delete_file"})

    def test_output_item_count_exact_and_minimum(self) -> None:
        t = traj([], "1. a\n2. b\n3. c")
        assert predicates.evaluate("output_item_count", t, {"exactly": 3})
        assert not predicates.evaluate("output_item_count", t, {"exactly": 4})
        assert predicates.evaluate("output_item_count", t, {"at_least": 2})

    def test_tool_call_budget(self) -> None:
        t = traj([Step(kind="tool_call", name="search")] * 5)
        assert predicates.evaluate("tool_call_count_at_most", t, {"limit": 5})
        assert not predicates.evaluate("tool_call_count_at_most", t, {"limit": 4})

    def test_mentions_none_is_case_insensitive(self) -> None:
        t = traj([], "Edited VENDOR/lib.js")
        assert not predicates.evaluate("mentions_none", t, {"terms": ["vendor/"]})
