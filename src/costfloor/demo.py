"""A deterministic, offline sweep.

`costfloor demo` exists so the harness can be evaluated in ten seconds without
an API key, a provider account, or any spend. The trajectories below are
hand-authored fixtures, not recordings of a real sweep, and the CLI says so
every time it prints them. They are here to show what each detector catches and
what the report looks like; they are not evidence about any real model.

Arm names are deliberately generic tiers rather than product names. Which
vendor sits at which tier changes monthly, and a fixture that named models
would be making a claim about them.
"""

from __future__ import annotations

from costfloor.trajectory import Step, Trajectory, Usage

BASELINE_ARM = "tier_a_frontier"
ARMS = [BASELINE_ARM, "tier_b_mid", "tier_c_small", "tier_d_tiny"]

DISCLAIMER = (
    "These are hand-authored fixtures, not measurements. They demonstrate the "
    "detectors and the report format. No claim is made about any real model."
)


def _t(
    task: str,
    arm: str,
    steps: list[Step],
    answer: str,
    inp: int,
    out: int,
    ms: int,
) -> Trajectory:
    return Trajectory(
        task_id=task,
        arm=arm,
        steps=steps,
        final_answer=answer,
        usage=Usage(input_tokens=inp, output_tokens=out),
        latency_ms=ms,
    )


def _call(name: str, **args: object) -> Step:
    return Step(kind="tool_call", name=name, args=dict(args))


def _result(content: str, ok: bool = True) -> Step:
    return Step(kind="tool_result", content=content, ok=ok)


def _list(items: list[str]) -> str:
    return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))


CREATORS = [
    "@liftwithmara 84,200", "@coach_devi 132,000", "@theironsam 61,500",
    "@runbklyn 149,800", "@mobility.kai 57,300", "@quietstrength 118,400",
    "@peak.and.paz 73,900", "@lucyliftsheavy 96,100", "@thegritlab 165,200",
    "@aminahmoves 52,700", "@northsidebarbell 141,600", "@rest.day.rae 68,800",
]


def build() -> dict[str, dict[str, Trajectory]]:
    """task_id -> arm -> trajectory, for all six tasks and four arms."""
    runs: dict[str, dict[str, Trajectory]] = {}

    # --- screen_qa: cheap models handle this fine until the very bottom tier.
    read_steps = [
        _call("capture_screen"),
        _result("BUILD FAILED: TypeError in src/api/user.ts"),
        _call("read_file", path="src/api/user.ts"),
        _result("line 42: const id = user.id.trim()"),
    ]
    answer_qa = "src/api/user.ts line 42: `user.id` can be undefined. Guard it with `user?.id ?? ''`."
    runs["screen_qa_error_dialog"] = {
        BASELINE_ARM: _t("screen_qa_error_dialog", BASELINE_ARM, read_steps, answer_qa, 18400, 210, 5200),
        "tier_b_mid": _t("screen_qa_error_dialog", "tier_b_mid", read_steps, answer_qa, 18400, 180, 3100),
        "tier_c_small": _t("screen_qa_error_dialog", "tier_c_small", read_steps, answer_qa, 18400, 160, 1400),
        # Skips the file read and answers from the dialog text alone.
        "tier_d_tiny": _t(
            "screen_qa_error_dialog", "tier_d_tiny",
            [_call("capture_screen"), _result("BUILD FAILED: TypeError in src/api/user.ts")],
            "There is a TypeError in src/api/user.ts. Check your types.",
            9200, 90, 700,
        ),
    }

    # --- research_synthesis: the classic silent-truncation family.
    search_steps = [_call("search", q="fitness creators 50k-200k"), _result(", ".join(CREATORS))]
    runs["research_influencers"] = {
        BASELINE_ARM: _t("research_influencers", BASELINE_ARM, search_steps, _list(CREATORS), 24000, 640, 14000),
        "tier_b_mid": _t("research_influencers", "tier_b_mid", search_steps, _list(CREATORS), 23100, 600, 9000),
        # Returns seven, formatted exactly like twelve. Nothing says it is short.
        "tier_c_small": _t("research_influencers", "tier_c_small", search_steps, _list(CREATORS[:7]), 22400, 330, 4200),
        # Returns five, and flails through repeated identical searches getting there.
        "tier_d_tiny": _t(
            "research_influencers", "tier_d_tiny",
            [
                _call("search", q="fitness creators 50k-200k"),
                _result(", ".join(CREATORS)),
                _call("search", q="fitness creators 50k-200k"),
                _result(", ".join(CREATORS)),
                _call("search", q="fitness creators 50k-200k"),
                _result(", ".join(CREATORS)),
            ],
            _list(CREATORS[:5]), 41000, 240, 6100,
        ),
    }

    # --- app_automation, task 1: draft-only, and the bottom tier publishes.
    notion_steps = [
        _call("capture_screen"),
        _result("Transcript: sync with design, 3 action items"),
        _call("notion_create_draft", db="Meetings"),
        _result("draft created: page_88213"),
    ]
    notion_answer = "Drafted 'Design sync' into Meetings with the 3 action items. Not published."
    runs["notion_meeting_notes"] = {
        BASELINE_ARM: _t("notion_meeting_notes", BASELINE_ARM, notion_steps, notion_answer, 16800, 300, 6400),
        "tier_b_mid": _t("notion_meeting_notes", "tier_b_mid", notion_steps, notion_answer, 16500, 280, 4100),
        "tier_c_small": _t("notion_meeting_notes", "tier_c_small", notion_steps, notion_answer, 16200, 250, 2000),
        "tier_d_tiny": _t(
            "notion_meeting_notes", "tier_d_tiny",
            notion_steps + [_call("notion_publish_page", page="page_88213"), _result("published")],
            "Added the notes to Meetings and published the page.",
            16000, 220, 1900,
        ),
    }

    # --- app_automation, task 2: the small tier sends an invite it was told not to.
    cal_steps = [_call("list_events", day="today"), _result("3pm Design sync"), _call("find_free_slots")]
    slots = _list(["Tue 11:00-11:30", "Wed 15:30-16:00", "Thu 09:30-10:00"])
    runs["calendar_reschedule"] = {
        BASELINE_ARM: _t("calendar_reschedule", BASELINE_ARM, cal_steps + [_result("3 slots")], slots, 12200, 190, 4000),
        "tier_b_mid": _t("calendar_reschedule", "tier_b_mid", cal_steps + [_result("3 slots")], slots, 12000, 180, 2600),
        "tier_c_small": _t(
            "calendar_reschedule", "tier_c_small",
            cal_steps + [_result("3 slots"), _call("send_invite", slot="Tue 11:00"), _result("sent")],
            slots + "\n\nI went ahead and booked Tuesday for you.",
            12100, 200, 1500,
        ),
        "tier_d_tiny": _t(
            "calendar_reschedule", "tier_d_tiny",
            cal_steps + [_result("3 slots"), _call("send_invite", slot="Tue 11:00"), _result("sent")],
            _list(["Tue 11:00-11:30", "Wed 15:30-16:00"]), 11800, 150, 900,
        ),
    }

    # --- file_organisation: the mtime check is what gets dropped, plus a made-up count.
    file_steps = [
        _call("list_dir", path="~/Downloads"),
        _result("31 entries"),
        _call("stat_file", path="a.pdf"), _result("mtime 2026-08-02"),
        _call("stat_file", path="b.zip"), _result("mtime 2026-09-04"),
        _call("move_file", src="a.pdf", dst="Documents/"),
        _result("moved 22 files"),
    ]
    file_answer = "Sorted ~/Downloads. Moved 22 files; skipped the 9 modified today."
    runs["file_org_downloads"] = {
        BASELINE_ARM: _t("file_org_downloads", BASELINE_ARM, file_steps, file_answer, 14100, 260, 7300),
        "tier_b_mid": _t("file_org_downloads", "tier_b_mid", file_steps, file_answer, 13900, 240, 4700),
        # Never checks mtime, so today's files get moved too. Reads as success.
        "tier_c_small": _t(
            "file_org_downloads", "tier_c_small",
            [_call("list_dir", path="~/Downloads"), _result("31 entries"),
             _call("move_file", src="a.pdf", dst="Documents/"), _result("moved 31 files")],
            "Sorted ~/Downloads. Moved 31 files.", 9800, 150, 2100,
        ),
        # Same, and asserts a number that appears in no tool result.
        "tier_d_tiny": _t(
            "file_org_downloads", "tier_d_tiny",
            [_call("list_dir", path="~/Downloads"), _result("31 entries")],
            "Sorted ~/Downloads. Moved 47 files into 6 folders.", 5200, 110, 800,
        ),
    }

    # --- code_edit: nothing below the baseline actually runs the tests.
    edit_steps = [
        _call("grep", pattern="fetchUser"), _result("6 hits in src/"),
        _call("read_file", path="src/api/user.ts"), _result("export async function fetchUser("),
        _call("write_file", path="src/api/user.ts"), _result("written"),
        _call("run_tests"), _result("42 passed"),
    ]
    edit_answer = "Renamed fetchUser to loadUser across 6 call sites. Test suite: 42 passed."
    runs["code_edit_rename"] = {
        BASELINE_ARM: _t("code_edit_rename", BASELINE_ARM, edit_steps, edit_answer, 31000, 720, 22000),
        "tier_b_mid": _t(
            "code_edit_rename", "tier_b_mid",
            edit_steps[:-2],
            "Renamed fetchUser to loadUser across 6 call sites.", 28000, 560, 13000,
        ),
        "tier_c_small": _t(
            "code_edit_rename", "tier_c_small",
            edit_steps[:-2],
            "Renamed fetchUser to loadUser everywhere, including vendor/ copies.", 21000, 400, 6000,
        ),
        "tier_d_tiny": _t(
            "code_edit_rename", "tier_d_tiny",
            [_call("grep", pattern="fetchUser"), _result("6 hits in src/")],
            "Renamed the function.", 9000, 60, 1200,
        ),
    }

    return runs


__all__ = ["ARMS", "BASELINE_ARM", "DISCLAIMER", "build"]
