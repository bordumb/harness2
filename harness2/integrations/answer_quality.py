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
Never copy source-data facts into guidance: no merchant/customer names, record IDs,
task-specific dates, measured totals, intermediate calculations or task answers.
Guidance must describe a reusable procedure; do not copy source schemas, filenames,
business definitions, formulas or field-to-meaning mappings into runtime guidance.
Tell the analyst how to establish the current definition from authorized evidence.
Do not turn missing evidence in one case into a universal missing-record or default-value rule.
Current sources can define explicit exemptions, exclusions or defaults; preserve those contracts.
The analyst must read current source facts itself. Reading source files as proposer does not authorize embedding their
contents into runtime instructions. Task-specific examples must be generalized.
Preserve existing reusable procedures from earlier tasks unless current evidence
shows they conflict. A procedure need not be relevant to this single task to be
valuable across the workload. Use the experience library for that context.
Editing these text files requires no Git, build, dependency or test commands.
Return concise <notes> explaining observed evidence and the proposed change.
"""

CALLER_CONTRACT_CHECKS = (
    "Assess source support and caller-contract fidelity separately for every original case. "
    "Correct reasoning does not excuse a final answer that violates required fields, types, "
    "precision or permitted fallback forms. Read the original request and verbatim deliverable; "
    "do not apply answer-format requirements to host evidence wrappers. "
    "Preserve the caller's stated conditions for a fallback. Do not silently narrow or expand "
    "them, invent a new uncertainty label, or confuse availability of a supported answer with "
    "whether the question's topic is relevant. Prefer a supported result where one is available; "
    "when none is established, express that limitation through the caller's permitted contract. "
    "If no permitted form can truthfully represent the available evidence and no fallback exists, "
    "identify that contract conflict rather than inventing a value for conformance."
)


DECISION_EVIDENCE_CHECKS = (
    "Distinguish a supported positive decision, a supported negative decision, and unresolved applicability. "
    "Missing evidence for a claim does not prove its opposite. A negative decision needs an applicable "
    "criterion or an explicit complete-rule contract that warrants it; a measured condition alone "
    "does not establish a different consequence. Reject unsupported affirmation and unsupported denial "
    "equally. Prefer a decisive answer when the evidence establishes it, and preserve uncertainty "
    "when neither decision is established. A conditional calculation under an explicitly labelled, "
    "source-derived working hypothesis can be useful without establishing the hypothesis as fact. "
    "Check its observable support, plausible alternatives, sensitivity and falsifying evidence. "
    "Reject silent defaults and claims of certainty unsupported by those checks; do not prefer "
    "blanket abstention over a sound conditional analysis merely because documentation is incomplete."
)


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

    def __init__(self, root: Path, backend: AnswerQualityBackend, *, model: str, initial_tree: tree.Tree | None = None):
        if getattr(backend, "partition", "development") != "development":
            raise ValueError("A frozen holdout backend cannot enter proposer recursion")
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
        fixed_profile = getattr(backend, "fixed_profile_runtime", False) is True
        self.spec = BenchSpec(
            name="mac-agent-answer-quality",
            runs_root=root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="answer a colleague's data and knowledge question using authorized original evidence",
                domain_word="workload",
                inv_levers=(
                    "Edit systemprompt.md and tool_guidance.md only. Preserve retrieval.json, skills, company profile, source grants, provider and task."
                    if fixed_profile else
                    "Edit systemprompt.md, tool_guidance.md and retrieval.json only. Keep source grants, provider and task unchanged."
                ),
                dom_levers="Improve source discovery, date/scope interpretation, numerical reasoning and warranted uncertainty.",
                yardstick=("A useful answer is supported by original evidence, preserves units and scope, and identifies unresolved questions honestly. " + CALLER_CONTRACT_CHECKS),
                domain_guidance=(
                    "Use observed trajectories to distinguish retrieval, context, reasoning and tool limitations. Do not prescribe a particular SQL implementation."
                    + (" This comparison fixes company knowledge, capabilities and retrieval. Only reusable prompt/tool guidance may change; do not edit retrieval.json or invent company facts."
                       if fixed_profile else "")
                ),
                selection_checks=(
                    "Inspect each candidate's authorized tool observations and calculations, not just its final answer. "
                    "Check source definitions, rule populations, units, coverage and arithmetic. "
                    "A short source projection may omit data available to the analyst; absence from that projection "
                    "is not proof the data does not exist. Neither confident wording nor abstention establishes correctness. "
                    "Name unresolved evidence rather than inventing support for a choice. "
                    + DECISION_EVIDENCE_CHECKS + " " + CALLER_CONTRACT_CHECKS
                ),
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("**/evaluation/**", "**/contract.json", "**/seed.json", "**/judgment.json"),
            allow_subagents=False,
        )
        baseline = dict(initial_tree) if initial_tree is not None else {
            "systemprompt.md": "", "tool_guidance.md": "", "retrieval.json": "{}"}
        self.validate_tree(baseline)
        from ..core.context import assert_tree_has_no_grader_verdicts
        assert_tree_has_no_grader_verdicts(baseline)
        self._base = root / "base"
        if not self._base.exists():
            tree.write_tree(SURFACE, baseline, self._base)
        # Selection/reflection must inspect the same effective initial tree used
        # by baseline execution, including a deliberately seeded incumbent.
        if candidate_from_tree(tree.read_tree(SURFACE, self._base)) != candidate_from_tree(baseline):
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

    def validate_run(self, task_id, run_dir):
        case = self._development(task_id)
        inspected = self.backend.inspect(run_dir)
        if inspected.get("task_id") != task_id or inspected.get("question") != case["question"]:
            raise ValueError("Execution evidence belongs to a different task or question")

    def validate_baseline(self, task_id, view):
        self.validate_run(task_id, view.run_dir)
        expected = candidate_from_tree(tree.read_tree(SURFACE, self._base)).as_dict()
        if self.backend.inspect(view.run_dir).get("candidate") != expected:
            raise ValueError("Baseline execution used a different harness configuration")

    def validate_tree(self, value):
        candidate = candidate_from_tree(value)
        validate = getattr(self.backend, "validate_candidate", None)
        if validate is not None:
            validate(candidate.as_dict())

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
        # Preserve the exact authored output for conformance and reflection.
        return "\n\n".join(self.backend.inspect(run_dir)["deliverables"].values())

    def selection_evidence(self, run_dir):
        # Separate observer-supplied calculations from the authored final answer.
        # The core labels this appendix explicitly; private judgments stay out.
        return self.backend.inspect(run_dir)["trajectory"]

    def score(self, run_dir, task_id):
        self._development(task_id)
        return self.backend.judge(run_dir, task_id)


def finalize_development(task_id, rollouts, trees, *, adapter, proposer, work_dir, library, depth=1):
    """Use core selection/reflection/library only after candidate validity checks.

    This function never calls an independent grader. A development library is not
    adoption into the user's application or permission to evaluate holdout.
    """
    from ..core import selection

    if type(depth) is not int or depth < 1:
        raise ValueError("Declare the original recursion depth")
    adapter._development(task_id)
    eligible, rejected = {}, {}
    for label, view in rollouts.items():
        try:
            adapter.validate_run(task_id, view.run_dir)
            adapter.validate_tree(trees.get(label, {}))
            verify = getattr(adapter.backend, "validate_configuration_run", None)
            if verify is not None:
                verify(view.run_dir, candidate_from_tree(trees.get(label, {})).as_dict())
        except ValueError as error:
            rejected[label] = str(error)
            continue
        eligible[label] = view
    if len(eligible) <= 1:
        chosen = selection.trivial_selection(task_id, depth, "seq", eligible,
                                             adapter=adapter, work_dir=work_dir)
    else:
        chosen = selection.run_selection(task_id, depth, "seq", eligible, adapter=adapter,
                                        prop=proposer, work_dir=work_dir)
    entry = None
    selected_tree = trees.get(chosen.chosen_label, {})
    if chosen.ok and candidate_from_tree(selected_tree).id != "builtin":
        adapter.validate_tree(selected_tree)
        experience = selection.reflect_adoption(task_id, chosen, eligible, adapter=adapter,
                                                prop=proposer, work_dir=work_dir)
        # Reflection also stays data-free; source facts may not be cached as rules.
        try:
            validate = getattr(adapter.backend, "validate_candidate", None)
            if validate is not None:
                validate({"prompt_guidance": "", "tool_guidance": json.dumps(experience), "skills": []})
            entry = library.add(task_id, selected_tree, why=chosen.why, label=chosen.chosen_label,
                                run_id=chosen.chosen_run_id, experience=experience)
        except ValueError as error:
            rejected["reflection"] = str(error)
    return {"selection": chosen.to_dict(), "rejected": rejected,
            "library_entry": str(entry) if entry else None, "application_adopted": False}
