"""Each detector gets a case it must catch and a case it must not.

The near-miss cases matter more than the hits. A detector that flags list
numbering as a fabricated value is one an operator learns to ignore within a
day, at which point the harness is worse than nothing.
"""

from __future__ import annotations


from costfloor.detect import (
    fabricated_value,
    missing_tool_call,
    redundant_retry,
    scope_creep,
    silent_truncation,
)
from costfloor.spec import Constraint, TaskSpec
from costfloor.trajectory import Step, Trajectory


def traj(arm: str, steps: list[Step] | None = None, answer: str = "") -> Trajectory:
    return Trajectory(task_id="t", arm=arm, steps=steps or [], final_answer=answer)


def call(name: str, **args: object) -> Step:
    return Step(kind="tool_call", name=name, args=dict(args))


def result(content: str) -> Step:
    return Step(kind="tool_result", content=content)


class TestMissingToolCall:
    def test_flags_a_tool_the_baseline_used(self) -> None:
        base = traj("base", [call("run_tests")])
        cand = traj("cheap", [])
        assert [f.type for f in missing_tool_call(base, cand)] == ["missing_tool_call"]

    def test_extra_tools_are_not_a_regression(self) -> None:
        base = traj("base", [call("grep")])
        cand = traj("cheap", [call("grep"), call("read_file")])
        assert missing_tool_call(base, cand) == []


class TestFabricatedValue:
    def test_flags_a_number_with_no_evidence(self) -> None:
        base = traj("base")
        cand = traj("cheap", [result("31 entries")], "Moved 47 files.")
        assert [f.type for f in fabricated_value(base, cand)] == ["fabricated_value"]

    def test_supported_number_is_clean(self) -> None:
        base = traj("base")
        cand = traj("cheap", [result("moved 22 files")], "Moved 22 files.")
        assert fabricated_value(base, cand) == []

    def test_list_numbering_is_not_a_claim(self) -> None:
        """Regression: numbering a list 1..12 flagged 10, 11 and 12."""
        base = traj("base")
        answer = "\n".join(f"{i}. @creator{i}" for i in range(1, 13))
        assert fabricated_value(base, traj("cheap", [], answer)) == []

    def test_clock_times_are_not_claims(self) -> None:
        """Regression: '11:00-11:30' was parsed as the number -11."""
        base = traj("base")
        cand = traj("cheap", [], "Free at 11:00-11:30 and 15:30-16:00.")
        assert fabricated_value(base, cand) == []

    def test_small_integers_are_ignored(self) -> None:
        base = traj("base")
        assert fabricated_value(base, traj("cheap", [], "I found 3 things.")) == []


class TestSilentTruncation:
    def test_flags_a_short_list_that_does_not_say_so(self) -> None:
        base = traj("base", [], "\n".join(f"{i}. x" for i in range(1, 13)))
        cand = traj("cheap", [], "\n".join(f"{i}. x" for i in range(1, 6)))
        assert [f.type for f in silent_truncation(base, cand)] == ["silent_truncation"]

    def test_admitting_partiality_is_not_silent(self) -> None:
        base = traj("base", [], "\n".join(f"{i}. x" for i in range(1, 13)))
        cand = traj("cheap", [], "I only found 5 that matched:\n" +
                    "\n".join(f"{i}. x" for i in range(1, 6)))
        assert silent_truncation(base, cand) == []

    def test_short_baselines_are_not_scored(self) -> None:
        base = traj("base", [], "1. x\n2. y")
        assert silent_truncation(base, traj("cheap", [], "1. x")) == []


class TestRedundantRetry:
    def test_flags_repeated_identical_calls(self) -> None:
        base = traj("base", [call("search", q="a")])
        cand = traj("cheap", [call("search", q="a")] * 4)
        assert [f.type for f in redundant_retry(base, cand)] == ["redundant_retry"]

    def test_one_extra_call_is_within_slack(self) -> None:
        base = traj("base", [call("search", q="a")])
        cand = traj("cheap", [call("search", q="a")] * 2)
        assert redundant_retry(base, cand) == []

    def test_different_args_are_different_calls(self) -> None:
        base = traj("base", [call("search", q="a")])
        cand = traj("cheap", [call("search", q=str(i)) for i in range(5)])
        assert redundant_retry(base, cand) == []


class TestScopeCreep:
    spec = TaskSpec(task_id="t", family="app_automation", prompt="draft it")

    def test_flags_a_state_change_the_baseline_avoided(self) -> None:
        base = traj("base", [call("list_events")])
        cand = traj("cheap", [call("list_events"), call("send_invite")])
        found = scope_creep(self.spec, base, cand)
        assert [f.type for f in found] == ["scope_creep"]

    def test_read_only_divergence_is_not_scope_creep(self) -> None:
        base = traj("base", [call("list_events")])
        cand = traj("cheap", [call("list_events"), call("search")])
        assert scope_creep(self.spec, base, cand) == []
