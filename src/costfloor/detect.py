"""Silent-regression detectors.

'Silent' is the load-bearing word. A cheaper model that errors out is not the
problem: the user sees it and retries. The problem is the run that returns a
confident, well-formatted answer that is quietly worse than the expensive
model's, because nothing in the product surfaces it and the user's trust is
spent before anyone notices.

Every detector here is structural. It compares a candidate trajectory against
a baseline trajectory for the same task, or against the task's own declared
constraints. None of them asks a model for an opinion, which is what makes the
result reproducible and free to run in CI.

The taxonomy is carried over from `downgrade`, adapted to desktop-agent work:
`unsupported_citation` becomes `silent_truncation`, because desktop tasks
rarely cite and very often return a short list without admitting it was short.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from costfloor import predicates
from costfloor.spec import TaskSpec
from costfloor.trajectory import Trajectory

RegressionType = Literal[
    "dropped_constraint",
    "missing_tool_call",
    "fabricated_value",
    "redundant_retry",
    "silent_truncation",
    "scope_creep",
]

# A number must not be glued to a word character or a digit on its left. That
# excludes the 12 inside "@creator12" and the -11 inside "11:00-11:30", both of
# which are formatting or identity rather than a figure the model is asserting.
NUMBER = re.compile(r"(?<![\w:.-])-?\d[\d,]*(?:\.\d+)?")

# List ordinals and clock times are formatting, not claims. Stripping them
# before extraction is the difference between a detector an operator trusts
# and one they learn to ignore.
LIST_ORDINAL = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\s*(?:[ap]m)?", re.IGNORECASE)


class Finding(BaseModel):
    """One detected regression, with the evidence that produced it."""

    type: RegressionType
    task_id: str
    arm: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"[{self.type}] {self.task_id}/{self.arm}: {self.detail}"


def _numbers(text: str, *, strip_formatting: bool = False) -> set[str]:
    """Every number asserted in `text`.

    `strip_formatting` is used on the final answer only. Numbering a list
    1..12 is not a claim that the number twelve appeared in the evidence, and
    neither is writing down a meeting time, so both are removed before the
    numbers that remain are treated as assertions.
    """
    if strip_formatting:
        text = CLOCK.sub(" ", LIST_ORDINAL.sub("", text))
    return {m.group().replace(",", "") for m in NUMBER.finditer(text)}


def dropped_constraint(spec: TaskSpec, cand: Trajectory) -> list[Finding]:
    """A requirement the task stated in prose was not honoured.

    Scored against the spec rather than the baseline: a constraint the
    expensive model also drops is a broken task, and `costfloor verify`
    reports that separately instead of letting it inflate the regression count.
    """
    out: list[Finding] = []
    for constraint in spec.constraints:
        if not predicates.evaluate(constraint.predicate, cand, constraint.args):
            detail = constraint.description or constraint.predicate
            out.append(
                Finding(
                    type="dropped_constraint",
                    task_id=spec.task_id,
                    arm=cand.arm,
                    detail=f"{constraint.id}: {detail}",
                )
            )
    return out


def missing_tool_call(base: Trajectory, cand: Trajectory) -> list[Finding]:
    """The baseline used a tool the candidate skipped.

    Read from what the baseline actually did, not from the task author's
    `expected_tools` list. A baseline that never calls a tool the author
    expected means the task is wrong; a baseline that reliably calls something
    unanticipated is still a real expectation.
    """
    base_tools = set(base.tool_names())
    cand_tools = set(cand.tool_names())
    skipped = sorted(base_tools - cand_tools)
    if not skipped:
        return []
    return [
        Finding(
            type="missing_tool_call",
            task_id=cand.task_id,
            arm=cand.arm,
            detail=f"baseline called {', '.join(skipped)}; candidate did not",
        )
    ]


def fabricated_value(base: Trajectory, cand: Trajectory) -> list[Finding]:
    """The candidate asserts a figure that never appeared in its own evidence.

    Only numbers are checked. Prose can be paraphrased without being wrong, but
    a number in the answer that is in no tool result the run actually saw was
    invented, whatever it is a paraphrase of.
    """
    seen: set[str] = set()
    for step in cand.steps:
        if step.kind in {"tool_result", "message"}:
            seen |= _numbers(step.content)
    # Small integers are counters and list indices, not claims.
    asserted = {
        n for n in _numbers(cand.final_answer, strip_formatting=True)
        if abs(float(n)) >= 10
    }
    invented = sorted(asserted - seen)
    if not invented:
        return []
    return [
        Finding(
            type="fabricated_value",
            task_id=cand.task_id,
            arm=cand.arm,
            detail=f"answer asserts {', '.join(invented)} with no supporting tool result",
        )
    ]


def redundant_retry(base: Trajectory, cand: Trajectory, *, slack: int = 1) -> list[Finding]:
    """The candidate repeated an identical call more than the baseline did.

    This is the failure that costs money without showing up as a wrong answer:
    the cheap model gets there, but it flails on the way, and the operator pays
    for the flailing.
    """
    def repeats(traj: Trajectory) -> Counter[str]:
        keys = [f"{s.name}({sorted(s.args.items())})" for s in traj.tool_calls()]
        return Counter(keys)

    base_counts, cand_counts = repeats(base), repeats(cand)
    out: list[Finding] = []
    for key, count in cand_counts.items():
        excess = count - max(base_counts.get(key, 0), 1)
        if excess > slack:
            out.append(
                Finding(
                    type="redundant_retry",
                    task_id=cand.task_id,
                    arm=cand.arm,
                    detail=f"{key.split('(')[0]} called {count}x vs baseline {base_counts.get(key, 0)}x",
                )
            )
    return out


def silent_truncation(base: Trajectory, cand: Trajectory, *, ratio: float = 0.7) -> list[Finding]:
    """The candidate returned a materially shorter list without saying so.

    Length alone is not a defect: a tighter answer can be a better one. The
    defect is a shorter enumeration with no acknowledgement, which reads to the
    user as a complete answer. So an answer that says it is partial is exempt.
    """
    item = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.MULTILINE)
    base_n = len(item.findall(base.final_answer))
    cand_n = len(item.findall(cand.final_answer))
    if base_n < 3 or cand_n >= base_n * ratio:
        return []
    admits = re.search(
        r"\b(partial|incomplete|truncat|only found|first \d+|couldn't find all|some of)\b",
        cand.final_answer,
        re.IGNORECASE,
    )
    if admits:
        return []
    return [
        Finding(
            type="silent_truncation",
            task_id=cand.task_id,
            arm=cand.arm,
            detail=f"returned {cand_n} items vs baseline {base_n}, with no note that it is partial",
        )
    ]


def scope_creep(spec: TaskSpec, base: Trajectory, cand: Trajectory) -> list[Finding]:
    """The candidate took a state-changing action the baseline did not.

    Cheap models over-act on desktop tasks: asked to draft, they send. This is
    the one detector whose findings are worse than a wrong answer, because the
    side effect is not undoable by retrying.
    """
    mutating = {"send", "delete", "move", "write", "create", "post", "purchase", "trash"}

    def acts(traj: Trajectory) -> set[str]:
        return {
            s.name
            for s in traj.tool_calls()
            if any(verb in s.name.lower() for verb in mutating)
        }

    extra = sorted(acts(cand) - acts(base))
    if not extra:
        return []
    return [
        Finding(
            type="scope_creep",
            task_id=spec.task_id,
            arm=cand.arm,
            detail=f"took state-changing action(s) the baseline did not: {', '.join(extra)}",
        )
    ]


def detect_all(spec: TaskSpec, base: Trajectory, cand: Trajectory) -> list[Finding]:
    """Run every detector for one candidate against one baseline."""
    return [
        *dropped_constraint(spec, cand),
        *missing_tool_call(base, cand),
        *fabricated_value(base, cand),
        *redundant_retry(base, cand),
        *silent_truncation(base, cand),
        *scope_creep(spec, base, cand),
    ]


__all__ = [
    "Finding",
    "RegressionType",
    "detect_all",
    "dropped_constraint",
    "fabricated_value",
    "missing_tool_call",
    "redundant_retry",
    "scope_creep",
    "silent_truncation",
]
