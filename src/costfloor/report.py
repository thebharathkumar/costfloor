"""Turning per-run findings into the one table the operator needs.

The output answers a single question: for each task family, what is the
cheapest arm that shows no silent regression? That arm is the family's cost
floor. Anything cheaper is a saving the product cannot take without degrading
quietly; anything more expensive is margin being left on the table.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from costfloor.cost import RateCard, cost_multiple, total_usage
from costfloor.detect import Finding, detect_all
from costfloor.spec import Suite, TaskSpec
from costfloor.trajectory import Trajectory, Usage


class ArmResult(BaseModel):
    """One arm's aggregate performance over one family of tasks."""

    arm: str
    family: str
    tasks: int
    clean_tasks: int
    findings: list[Finding] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    cost_multiple: float | None = None

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def pass_rate(self) -> float:
        return self.clean_tasks / self.tasks if self.tasks else 0.0


class FamilyFloor(BaseModel):
    """The cheapest clean arm for one family, if there is one."""

    family: str
    baseline_arm: str
    floor_arm: str | None
    saving_vs_baseline: float | None
    results: list[ArmResult]

    @property
    def verdict(self) -> str:
        """What the operator should actually do about this family.

        Deliberately does NOT quote a saving. Cheaper models do not use fewer
        tokens, they cost less per token, so a token ratio is close to 1.00x
        even when the dollar difference is 20x. Quoting the token ratio as a
        saving would be the harness telling its own operator a comfortable
        lie. The dollar figure appears only when a rate card is supplied.
        """
        if self.floor_arm is None:
            return "nothing below the baseline is clean; stay on the baseline"
        if self.floor_arm == self.baseline_arm:
            return "baseline is already the floor; no safe downgrade here"
        return f"safe to downgrade to {self.floor_arm} (price it with --rates)"


def score(
    suite: Suite,
    runs: dict[str, dict[str, Trajectory]],
    *,
    baseline_arm: str,
) -> list[FamilyFloor]:
    """Score every arm against the baseline, grouped by task family.

    `runs` is task_id -> arm -> trajectory. Arms are ordered by observed token
    spend rather than by a hard-coded model ranking, so 'cheapest clean arm' is
    read off what the sweep measured, not off an assumption about which model
    ought to be cheaper.
    """
    specs = suite.by_id()
    by_family: dict[str, list[TaskSpec]] = defaultdict(list)
    for spec in suite.tasks:
        by_family[spec.family].append(spec)

    floors: list[FamilyFloor] = []
    for family, specs_in_family in sorted(by_family.items()):
        arms = sorted({arm for s in specs_in_family for arm in runs.get(s.task_id, {})})
        results: list[ArmResult] = []
        for arm in arms:
            findings: list[Finding] = []
            usages: list[Usage] = []
            latency = 0
            clean_tasks = 0
            counted = 0
            for spec in specs_in_family:
                per_arm = runs.get(spec.task_id, {})
                base = per_arm.get(baseline_arm)
                cand = per_arm.get(arm)
                if base is None or cand is None:
                    continue
                counted += 1
                usages.append(cand.usage)
                latency += cand.latency_ms
                task_findings = detect_all(specs[spec.task_id], base, cand)
                if not task_findings:
                    clean_tasks += 1
                findings.extend(task_findings)
            results.append(
                ArmResult(
                    arm=arm,
                    family=family,
                    tasks=counted,
                    clean_tasks=clean_tasks,
                    findings=findings,
                    usage=total_usage(usages),
                    latency_ms=latency,
                )
            )

        base_result = next((r for r in results if r.arm == baseline_arm), None)
        if base_result is not None:
            for result in results:
                result.cost_multiple = cost_multiple(result.usage, base_result.usage)

        cheaper_clean = sorted(
            (r for r in results if r.clean and r.usage.total > 0),
            key=lambda r: r.usage.total,
        )
        floor = cheaper_clean[0] if cheaper_clean else None
        floors.append(
            FamilyFloor(
                family=family,
                baseline_arm=baseline_arm,
                floor_arm=floor.arm if floor else None,
                saving_vs_baseline=floor.cost_multiple if floor else None,
                results=results,
            )
        )
    return floors


def render(floors: list[FamilyFloor], rates: RateCard | None = None) -> str:
    """Plain-text report. Deliberately narrow enough to paste into a DM."""
    lines: list[str] = []
    for floor in floors:
        lines.append(f"\n{floor.family}")
        lines.append("-" * len(floor.family))
        header = f"  {'arm':<22}{'clean':>8}{'tokens':>12}{'tok vs base':>13}"
        if rates is not None:
            header += f"{'$ / task':>12}"
        lines.append(header)
        for result in sorted(floor.results, key=lambda r: r.usage.total):
            mult = "-" if result.cost_multiple is None else f"{result.cost_multiple:.2f}x"
            row = (
                f"  {result.arm:<22}"
                f"{result.clean_tasks}/{result.tasks:<6}"
                f"{result.usage.total:>12,}"
                f"{mult:>13}"
            )
            if rates is not None:
                dollars = rates.dollars(result.arm, result.usage)
                per_task = (
                    "-" if dollars is None or not result.tasks
                    else f"${dollars / result.tasks:.4f}"
                )
                row += f"{per_task:>12}"
            lines.append(row)
            for finding in result.findings[:3]:
                lines.append(f"      ! {finding.type}: {finding.detail}")
            if len(result.findings) > 3:
                lines.append(f"      ! ... {len(result.findings) - 3} more")
        lines.append(f"  => {floor.verdict}")
    if rates is not None:
        lines.append(f"\ndollar figures from rate file: {rates.source}, as of {rates.as_of}")
    else:
        lines.append("\nno rate file supplied; costs shown in tokens only")
    return "\n".join(lines)


__all__ = ["ArmResult", "FamilyFloor", "render", "score"]
