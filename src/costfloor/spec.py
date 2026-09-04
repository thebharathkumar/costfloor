"""Task specifications for desktop-agent work, loaded from YAML.

The design constraint carried over from `downgrade`: every requirement a task
states in prose must also exist as a machine-checkable predicate. "Did the
cheaper model quietly drop a requirement?" then becomes a computation over the
trajectory instead of a second model's opinion about it. A requirement that
cannot be written as a predicate means the task is badly authored, and the
task gets rewritten rather than handed to a judge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# The families a screen-aware desktop agent actually spends its budget on.
TaskFamily = Literal[
    "screen_qa",           # look at what is on screen, answer about it
    "app_automation",      # drive a GUI or an app integration to a target state
    "file_organisation",   # read, classify and move things on disk
    "research_synthesis",  # gather from several sources, write one artefact
    "code_edit",           # change a file and leave it valid
]

AnswerCheckKind = Literal["exact", "regex", "set", "numeric", "none"]


class Constraint(BaseModel):
    """One machine-checkable requirement stated in the task prompt."""

    id: str
    predicate: str
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""

    @field_validator("id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("constraint id must be non-empty")
        return value


class AnswerCheck(BaseModel):
    """How to decide whether the final answer is correct."""

    kind: AnswerCheckKind = "none"
    value: Any = None
    tolerance: float = 0.01
    pattern: str | None = None


class TaskSpec(BaseModel):
    task_id: str
    family: TaskFamily
    prompt: str
    answer_check: AnswerCheck = Field(default_factory=AnswerCheck)
    constraints: list[Constraint] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("constraints")
    @classmethod
    def _unique_ids(cls, value: list[Constraint]) -> list[Constraint]:
        seen = [c.id for c in value]
        if len(seen) != len(set(seen)):
            raise ValueError(f"duplicate constraint ids: {seen}")
        return value


class Suite(BaseModel):
    tasks: list[TaskSpec] = Field(default_factory=list)

    def by_id(self) -> dict[str, TaskSpec]:
        return {t.task_id: t for t in self.tasks}

    def families(self) -> list[str]:
        return sorted({t.family for t in self.tasks})

    def __len__(self) -> int:
        return len(self.tasks)


def load_suite(path: Path) -> Suite:
    """Load every .yaml under `path` (or a single file) into a Suite.

    Task ids must be unique across the whole suite; a duplicate would silently
    merge two tasks' results into one row of the cost-floor table.
    """
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    tasks: list[TaskSpec] = []
    for file in files:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        if raw is None:
            continue
        entries = raw if isinstance(raw, list) else [raw]
        for entry in entries:
            tasks.append(TaskSpec.model_validate(entry))

    ids = [t.task_id for t in tasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate task ids in suite: {', '.join(duplicates)}")
    return Suite(tasks=tasks)


__all__ = ["AnswerCheck", "Constraint", "Suite", "TaskFamily", "TaskSpec", "load_suite"]
