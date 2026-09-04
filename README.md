![ci](https://github.com/thebharathkumar/costfloor/actions/workflows/ci.yml/badge.svg)

# costfloor

**Find the cheapest model that does not silently break your agent.**

A desktop agent is an economics problem before it is an AI problem. Every task
a user fires off costs real money, so every product built on one ends up
rationing: *150 agent messages a month*. The obvious lever is to route cheap
tasks to cheap models. The obvious risk is that a cheap model does not fail
loudly, it fails *politely* — it returns 7 items where the expensive one
returned 12, formatted identically, with no indication that anything is
missing. The user does not file a bug. They just quietly trust the product a
little less.

`costfloor` measures that. For each family of tasks it finds the **cost
floor**: the cheapest arm that shows no silent regression against the
expensive baseline. Anything cheaper is a saving you cannot take. Anything
more expensive is margin you are leaving on the table.

```
pip install -e . && costfloor demo
```

No API key. No network. No spend. Runs in under a second.

## What it catches

Six structural detectors, all comparing a candidate run against a baseline run
of the same task. None of them asks a model for an opinion, which is what makes
the result reproducible, free, and safe to gate a deploy on.

| detector | the failure it catches |
| --- | --- |
| `dropped_constraint` | a requirement stated in the prompt, checked as a predicate over the trajectory |
| `missing_tool_call` | the baseline opened the file; the cheap model guessed from the dialog |
| `fabricated_value` | a figure in the answer that appears in no tool result the run actually saw |
| `redundant_retry` | got there, but flailed, and you paid for the flailing |
| `silent_truncation` | returned 7 of 12 items and did not say so |
| `scope_creep` | asked to draft, it sent |

`scope_creep` is the one worth staring at. Every other failure is fixed by
retrying. A cheap model that books the meeting instead of listing the slots has
done something that a retry cannot undo, on the user's calendar, in the user's
name.

## Sample output

```
code_edit
---------
  arm                      clean      tokens  tok vs base
  tier_d_tiny           0/1            9,060        0.29x
      ! dropped_constraint: runs_tests: must verify, not just edit
      ! missing_tool_call: baseline called read_file, run_tests, write_file; candidate did not
  tier_c_small          0/1           21,400        0.67x
      ! dropped_constraint: no_vendor: must not report edits under vendor/
  tier_b_mid            0/1           28,560        0.90x
      ! dropped_constraint: runs_tests: must verify, not just edit
  tier_a_frontier       1/1           31,720        1.00x
  => baseline is already the floor; no safe downgrade here

summary
  app_automation         safe to downgrade to tier_b_mid
  code_edit              baseline is already the floor; no safe downgrade here
  file_organisation      safe to downgrade to tier_b_mid
  research_synthesis     safe to downgrade to tier_b_mid
  screen_qa              safe to downgrade to tier_c_small
```

The useful result there is `code_edit`. Everything below the baseline edits the
files and skips running the tests, which reads as success and is not. That is
one family you cannot route cheaply, and knowing which one is the entire point.

## Two things this repo refuses to do

**It ships no prices.** Provider rates change, differ per account and per
region, and a number committed to a repo is stale the week after. The report
is denominated in tokens. Dollars appear only when you supply a rate card, and
then the report prints your `source` and `as_of` next to every figure. See
`rates.example.yaml`.

**It never quotes a saving it cannot source.** Cheaper models do not use fewer
tokens, they cost less *per* token, so the token ratio between arms sits near
1.00x even when the dollar difference is 20x. Reporting that ratio as a
"saving" would be this harness telling its own operator a comfortable lie,
which is the exact failure mode it exists to detect. So the verdict says *safe
to downgrade*, and stays silent about the size of the win until you price it.

The demo fixtures are hand-authored, not recorded, and the CLI says so on every
run. They exist to show what the detectors catch and what the report looks
like. **They are not evidence about any real model, and no model is named.**

## Writing a task

Every requirement stated in the prompt must also exist as a machine-checkable
predicate. If a requirement cannot be written as one, the task is badly
authored and gets rewritten. There is no LLM-judge fallback.

```yaml
- task_id: notion_meeting_notes
  family: app_automation
  prompt: >
    Summarise the meeting transcript on screen into my Notion "Meetings"
    database. Draft it only. Do not publish or share it.
  constraints:
    - id: draft_not_published
      predicate: never_called_tool
      args: { name: notion_publish_page }
      description: draft only; publishing is a side effect the user did not ask for
```

`costfloor verify` fails loudly on a typo'd predicate name. A misspelling that
silently scored as a passing constraint would produce a confident green report,
which is worse than a crash.

## Commands

```
costfloor demo                          offline fixture sweep, no key, deterministic
costfloor demo --rates rates.yaml       same, priced with your own rate card
costfloor verify                        suite loads, ids unique, predicates resolve
costfloor score runs/ --baseline <arm>  score trajectories from any runner
```

There is no `run` command that calls a provider yet, and that is a deliberate
gap rather than an oversight. The scoring half is the part worth reviewing, and
shipping a spend-money command before the scoring is trusted gets the order
backwards. `score` reads plain JSON trajectories, so wiring in a live runner is
an integration, not a rewrite.

## Tests

```
pip install -e ".[dev]" && pytest
```

47 tests. Roughly half of them are negative cases, which is where the value is:
a detector that flags list numbering as a fabricated value is one an operator
learns to ignore inside a day, at which point the harness is worse than
nothing. Two such false positives were found by running the demo during
development and are now pinned by
`test_list_numbering_is_not_a_claim` and `test_clock_times_are_not_claims`.

## Prior work

The taxonomy comes from [`downgrade`](https://github.com/thebharathkumar/downgrade),
which asks the same question about model *routers* rather than desktop agents:
when a router silently downgrades your request, does quality drop, and can you
tell? `costfloor` reuses its central rule — every constraint is a predicate, never
a judge — and swaps `unsupported_citation` for `silent_truncation`, because
desktop tasks rarely cite and very often return a short list without admitting
it is short.

MIT.
