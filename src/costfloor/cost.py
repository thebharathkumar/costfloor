"""Cost accounting.

Deliberately denominated in tokens by default. Provider prices change, differ
per account and per region, and a number baked into a repo is stale the week
after it is written. Tokens are what the harness actually observes, so tokens
are what it reports, and the decision-relevant figure -- how many times more
expensive is the safe arm than the cheap one -- needs no price at all.

Dollars are available, but only from a rate file the operator supplies. There
are no default prices in this package on purpose.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from costfloor.trajectory import Usage


class Rate(BaseModel):
    """Price per million tokens, as supplied by the operator."""

    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None


class RateCard(BaseModel):
    """A file of rates, keyed by arm name.

    `source` and `as_of` are required so a report can say where its dollar
    figures came from. A cost table without provenance is a number nobody can
    check later.
    """

    source: str
    as_of: str
    rates: dict[str, Rate] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "RateCard":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def dollars(self, arm: str, usage: Usage) -> float | None:
        """Cost of one run, or None when this arm has no rate on file."""
        rate = self.rates.get(arm)
        if rate is None:
            return None
        cached_rate = (
            rate.cached_input_per_mtok
            if rate.cached_input_per_mtok is not None
            else rate.input_per_mtok
        )
        return (
            usage.billable_input * rate.input_per_mtok
            + usage.cached_input_tokens * cached_rate
            + usage.output_tokens * rate.output_per_mtok
        ) / 1_000_000


def total_usage(usages: list[Usage]) -> Usage:
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cached_input_tokens=sum(u.cached_input_tokens for u in usages),
    )


def cost_multiple(candidate: Usage, baseline: Usage) -> float | None:
    """How many times the baseline's token spend this arm used.

    None when the baseline spent nothing, which is a broken run rather than a
    free one, and must not be reported as an infinite saving.
    """
    if baseline.total == 0:
        return None
    return candidate.total / baseline.total


__all__ = ["Rate", "RateCard", "cost_multiple", "total_usage"]
