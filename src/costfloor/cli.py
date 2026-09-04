"""Command line interface.

    costfloor demo      run the offline fixture sweep and print the report
    costfloor verify    check the suite loads and every predicate resolves
    costfloor score     score a directory of recorded trajectories

There is no `run` command that calls a provider yet, and that is a deliberate
gap rather than an oversight: the scoring half is the part worth reviewing, and
shipping a spend-money command before the scoring is trusted gets the order
backwards. `score` accepts trajectories from any runner, so wiring a live one
in is an integration, not a rewrite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from costfloor import demo as demo_module
from costfloor import predicates
from costfloor.cost import RateCard
from costfloor.report import render, score
from costfloor.spec import load_suite
from costfloor.trajectory import Trajectory

DEFAULT_SUITE = Path(__file__).parent / "suite"


@click.group()
@click.version_option(package_name="costfloor")
def main() -> None:
    """Find the cheapest model that does not silently break your agent."""


@main.command()
@click.option("--suite", "suite_path", type=click.Path(path_type=Path), default=DEFAULT_SUITE)
@click.option("--rates", type=click.Path(path_type=Path), default=None,
              help="YAML rate card. Without it, costs are reported in tokens only.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def demo(suite_path: Path, rates: Path | None, as_json: bool) -> None:
    """Run the offline fixture sweep. No API key, no spend, deterministic."""
    suite = load_suite(suite_path)
    runs = demo_module.build()
    floors = score(suite, runs, baseline_arm=demo_module.BASELINE_ARM)

    if as_json:
        click.echo(json.dumps({
            "disclaimer": demo_module.DISCLAIMER,
            "floors": [f.model_dump() for f in floors],
        }, indent=2))
        return

    card = RateCard.load(rates) if rates else None
    click.secho("costfloor demo", bold=True)
    click.secho(demo_module.DISCLAIMER, fg="yellow")
    click.echo(f"\n{len(suite)} tasks x {len(demo_module.ARMS)} arms, "
               f"baseline = {demo_module.BASELINE_ARM}")
    click.echo(render(floors, card))
    click.echo("\nsummary")
    for floor in floors:
        click.echo(f"  {floor.family:<22} {floor.verdict}")


@main.command()
@click.option("--suite", "suite_path", type=click.Path(path_type=Path), default=DEFAULT_SUITE)
def verify(suite_path: Path) -> None:
    """Check the suite loads, ids are unique and every predicate exists."""
    suite = load_suite(suite_path)
    problems: list[str] = []
    for task in suite.tasks:
        for constraint in task.constraints:
            if constraint.predicate not in predicates.REGISTRY:
                problems.append(f"{task.task_id}/{constraint.id}: "
                                f"unknown predicate '{constraint.predicate}'")
        if not task.constraints:
            problems.append(f"{task.task_id}: no constraints, nothing to detect")

    for problem in problems:
        click.secho(f"  x {problem}", fg="red")
    if problems:
        sys.exit(1)
    click.secho(f"  ok  {len(suite)} tasks, {len(suite.families())} families, "
                f"all predicates resolve", fg="green")


@main.command()
@click.argument("runs_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--suite", "suite_path", type=click.Path(path_type=Path), default=DEFAULT_SUITE)
@click.option("--baseline", required=True, help="Arm name to score everything against.")
@click.option("--rates", type=click.Path(path_type=Path), default=None)
def score_cmd(runs_dir: Path, suite_path: Path, baseline: str, rates: Path | None) -> None:
    """Score recorded trajectories. One JSON file per run, any runner."""
    suite = load_suite(suite_path)
    runs: dict[str, dict[str, Trajectory]] = {}
    for file in sorted(runs_dir.glob("*.json")):
        traj = Trajectory.model_validate_json(file.read_text(encoding="utf-8"))
        runs.setdefault(traj.task_id, {})[traj.arm] = traj
    if not runs:
        raise click.ClickException(f"no .json trajectories found in {runs_dir}")

    floors = score(suite, runs, baseline_arm=baseline)
    click.echo(render(floors, RateCard.load(rates) if rates else None))


main.add_command(score_cmd, name="score")

if __name__ == "__main__":  # pragma: no cover
    main()
