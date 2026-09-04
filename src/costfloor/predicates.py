"""The fixed registry of constraint predicates.

A predicate takes the trajectory and the constraint's arguments and returns
True when the requirement was honoured. The registry is deliberately small and
closed: every predicate here is something a desktop agent can observably do or
fail to do, and adding one is a decision about what the harness can measure,
not a convenience.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from costfloor.trajectory import Trajectory

Predicate = Callable[[Trajectory, dict[str, Any]], bool]


def _text(traj: Trajectory) -> str:
    parts = [traj.final_answer]
    parts.extend(s.content for s in traj.steps if s.kind == "message")
    return "\n".join(parts).lower()


def called_tool(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The named tool was called at least `min_times` times."""
    name = args["name"]
    minimum = int(args.get("min_times", 1))
    return traj.tool_names().count(name) >= minimum


def never_called_tool(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The named tool was never called. Used for destructive-action guards."""
    return args["name"] not in traj.tool_names()


def tool_arg_equals(traj: Trajectory, args: dict[str, Any]) -> bool:
    """Some call to `name` passed `arg` equal to `value`."""
    name, arg, value = args["name"], args["arg"], args["value"]
    return any(
        step.name == name and step.args.get(arg) == value for step in traj.tool_calls()
    )


def tool_call_count_at_most(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The agent stayed inside a step budget.

    This is the constraint that separates 'got there' from 'got there without
    burning the user's quota', which is the whole point of the harness.
    """
    return len(traj.tool_calls()) <= int(args["limit"])


def mentions_all(traj: Trajectory, args: dict[str, Any]) -> bool:
    """Every required term appears somewhere in the agent's own output."""
    body = _text(traj)
    return all(str(term).lower() in body for term in args["terms"])


def mentions_none(traj: Trajectory, args: dict[str, Any]) -> bool:
    """No forbidden term appears. Used for scope and privacy limits."""
    body = _text(traj)
    return not any(str(term).lower() in body for term in args["terms"])


def matches_pattern(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The final answer matches a regex. Used for required output shapes."""
    return re.search(args["pattern"], traj.final_answer, re.IGNORECASE) is not None


def output_item_count(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The final answer contains exactly / at least N lines matching a pattern.

    Silent truncation is the most common way a cheap model fails a 'give me 20
    of X' task: it returns a well-formed list of 7 and never says so.
    """
    pattern = args.get("pattern", r"^\s*(?:[-*•]|\d+[.)])\s+\S")
    found = len(re.findall(pattern, traj.final_answer, re.MULTILINE))
    if "exactly" in args:
        return found == int(args["exactly"])
    return found >= int(args.get("at_least", 1))


def no_failed_tool_results(traj: Trajectory, args: dict[str, Any]) -> bool:
    """The run contains no unrecovered tool errors."""
    return not traj.failed_results()


REGISTRY: dict[str, Predicate] = {
    "called_tool": called_tool,
    "never_called_tool": never_called_tool,
    "tool_arg_equals": tool_arg_equals,
    "tool_call_count_at_most": tool_call_count_at_most,
    "mentions_all": mentions_all,
    "mentions_none": mentions_none,
    "matches_pattern": matches_pattern,
    "output_item_count": output_item_count,
    "no_failed_tool_results": no_failed_tool_results,
}


class UnknownPredicate(KeyError):
    """Raised at suite-load time, not at scoring time.

    A typo in a predicate name must fail loudly before a paid sweep starts,
    never silently score as a passing constraint.
    """


def evaluate(name: str, traj: Trajectory, args: dict[str, Any]) -> bool:
    try:
        predicate = REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY))
        raise UnknownPredicate(f"unknown predicate '{name}'. known: {known}") from exc
    return predicate(traj, args)


__all__ = ["REGISTRY", "Predicate", "UnknownPredicate", "evaluate"]
