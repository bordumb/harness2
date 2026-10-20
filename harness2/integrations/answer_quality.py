"""Mac Agent answer-quality adapter for the existing Harness² recursion core.

The backend is owned by Mac Agent. It supplies actual execution and independent
judging; this module contains no business definitions or expected answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..core import prompts, tree
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .mac_agent import Candidate

SURFACE = tree.SurfaceSpec(
    name="mac_agent",
    always_on=("systemprompt.md", "tool_guidance.md", "retrieval.json"),
    always_on_max=20_000,
    always_on_cap_reason="Mac Agent accepts bounded host instructions and retrieval limits",
    skill_dir="skills",
    skill_name_rule="No executable skills are supported by this host surface",
    trigger_hint="Only edit the three declared always-on files",
    autotrigger_file="systemprompt.md",
    trigger_line="{name}: {desc}",
    subagent_requires_mode=True,
    plugin_dir=None,
    hooks_file=None,
)

HOST_SURFACE = """# EDITABLE MAC AGENT HOST SURFACE

Edit the actual files inside context/harness/, not a JSON description of changes.
systemprompt.md supplements the host's main instructions, up to 8000 UTF-8 bytes.
tool_guidance.md supplements tool-use instructions, up to 8000 UTF-8 bytes.
retrieval.json is a JSON object with only these optional whole-number settings:
context_byte_budget (0..32000, default 16000), maximum_notes (0..16, default 8),
maximum_recipe_hints (0..8, default 4). They change actual authorized retrieval.

No other files, scripts, plugins, executable skills or subagents are supported.
Do not change the question, evidence, provider, authentication, source grants,
permissions or completion policy. Make reusable changes grounded in observed
behavior; do not put this task's answer into the harness. Leave valid JSON behind.
Return concise <notes> explaining observed evidence and the proposed change.
"""


class AnswerQualityBackend(Protocol):
    def describe(self) -> list[dict]: ...

    def execute(self, task_id: str, candidate: dict, run_id: str, timeout: int) -> Path: ...

    def inspect(self, run_dir: Path) -> dict: ...

    def judge(self, run_dir: Path, task_id: str) -> dict | None: ...


class MacAgentSurface:
    name = "mac_agent"

    def surface(self):
        return SURFACE


def candidate_from_tree(value: tree.Tree) -> Candidate:
    unsupported = set(value) - set(SURFACE.always_on)
    if unsupported:
        raise ValueError("Unsupported Mac Agent harness paths: " + ", ".join(sorted(unsupported)))
    try:
        retrieval = json.loads(value.get("retrieval.json", "{}") or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("retrieval.json must contain a JSON object") from error
    fields = {
        "schema_version": 2,
        "id": "builtin",
        "prompt_guidance": value.get("systemprompt.md", ""),
        "tool_guidance": value.get("tool_guidance.md", ""),
        "skills": [],
        "retrieval_settings": retrieval,
    }
    candidate = Candidate.load(fields)
    if candidate.as_dict() != Candidate("builtin").as_dict():
        fields["id"] = "aq-" + candidate.fingerprint[:24]
        candidate = Candidate.load(fields)
    return candidate


class AnswerQualityAdapter:
    """Development-only recursion. Holdout is a separate frozen comparison gate."""

    def __init__(self, root: Path, backend: AnswerQualityBackend, *, model: str):
        prompts.register_surface_text(
            "mac_agent",
            surface_md=HOST_SURFACE,
            invariant="Improve the general evidence-use procedure. {levers}",
            domain="Improve reusable reasoning for this {domain} without memorizing its answer. {levers}",
            tts_surface=HOST_SURFACE,
        )
        self.root = root
        self.backend = backend
        self.substrate = MacAgentSurface()
        self.cases = {case["id"]: case for case in backend.describe()}
        channel = ChannelSpec("codex_app_server", model)
        self.spec = BenchSpec(
            name="mac-agent-answer-quality",
            runs_root=root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="answer a colleague's data and knowledge question using authorized original evidence",
                domain_word="workload",
                inv_levers="Edit systemprompt.md, tool_guidance.md and retrieval.json only. Keep source grants, provider and task unchanged.",
                dom_levers="Improve source discovery, date/scope interpretation, numerical reasoning and warranted uncertainty.",
                yardstick="A useful answer is supported by original evidence, preserves units and scope, and identifies unresolved questions honestly.",
                domain_guidance="Use observed trajectories to distinguish retrieval, context, reasoning and tool limitations. Do not prescribe a particular SQL implementation.",
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("**/evaluation/**", "**/contract.json", "**/seed.json", "**/judgment.json"),
            allow_subagents=False,
        )
        self._base = root / "base"
        if not self._base.exists():
            tree.write_tree(
                SURFACE,
                {"systemprompt.md": "", "tool_guidance.md": "", "retrieval.json": "{}"},
                self._base,
            )
        # A caller cannot silently relabel a changed harness as builtin.
        if candidate_from_tree(tree.read_tree(SURFACE, self._base)).id != "builtin":
            raise ValueError("The baseline harness changed")

    def tasks(self, split="all"):
        if split not in ("all", "train"):
            raise ValueError("Holdout cannot enter recursion; use the frozen comparison gate")
        return sorted(key for key, case in self.cases.items() if case["partition"] == "development")

    def _development(self, task_id):
        case = self.cases[task_id]
        if case["partition"] != "development":
            raise ValueError("Held-out cases cannot enter proposer context or reflection")
        return case

    def domain_of(self, task_id):
        return self._development(task_id)["family"]

    def task_prompt(self, task_id):
        return self._development(task_id)["question"]

    def task_files(self, task_id):
        return Path(self._development(task_id)["project"])

    def base_harness(self):
        return self._base

    def validate_tree(self, value):
        candidate_from_tree(value)

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        self._development(task_id)
        candidate = candidate_from_tree(tree.read_tree(SURFACE, harness_dir or self._base))
        return self.backend.execute(task_id, candidate.as_dict(), run_id, timeout or 600)

    def delivered(self, run_dir):
        return self.backend.inspect(run_dir)["delivered"]

    def trajectory(self, run_dir, *, obs_trunc):
        # The backend returns original authorized observations, never judgments.
        return self.backend.inspect(run_dir)["trajectory"]

    def deliverable_files(self, run_dir):
        return self.backend.inspect(run_dir)["deliverables"]

    def deliverable_text(self, run_dir):
        return "\n\n".join(self.deliverable_files(run_dir).values())

    def score(self, run_dir, task_id):
        self._development(task_id)
        return self.backend.judge(run_dir, task_id)
