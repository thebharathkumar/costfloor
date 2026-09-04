"""What one agent run looks like, once the provider details are stripped out.

A Trajectory is deliberately provider-agnostic. Anything that can emit a list
of steps and a token count can be scored, which is what lets the same detectors
run over a recorded fixture and over a live provider call without a second
code path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StepKind = Literal["tool_call", "tool_result", "message", "error"]


class Step(BaseModel):
    """One observable event in an agent run."""

    kind: StepKind
    name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    ok: bool = True


class Usage(BaseModel):
    """Token accounting for one run.

    Cost lives here as tokens, not dollars. Prices change weekly and differ per
    account; token counts are the thing actually measured, so they are the
    thing stored. Dollars are derived at report time from a rate file the
    operator supplies.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def billable_input(self) -> int:
        return max(self.input_tokens - self.cached_input_tokens, 0)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class Trajectory(BaseModel):
    """One task, run once, on one model."""

    task_id: str
    arm: str
    steps: list[Step] = Field(default_factory=list)
    final_answer: str = ""
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0

    def tool_calls(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "tool_call"]

    def tool_names(self) -> list[str]:
        return [s.name for s in self.tool_calls()]

    def failed_results(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "tool_result" and not s.ok]


__all__ = ["Step", "StepKind", "Trajectory", "Usage"]
