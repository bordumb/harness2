"""Scoped Mac Agent profile learning through the unchanged recursion core.

The host validates source provenance and imports native stores. This adapter never
turns company facts into runtime instructions or imports a private assessor.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..core import prompts, selection, tree
from ..core.context import assert_tree_has_no_grader_verdicts
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .answer_quality import AnswerQualityAdapter, DECISION_EVIDENCE_CHECKS
from .mac_agent import Candidate

SURFACE = tree.SurfaceSpec(
    name="mac_agent_profile",
    always_on=("profile.json",),
    always_on_max=1_000_000,
    always_on_cap_reason="Bounded company Knowledge and Capability assets, validated by the host",
    skill_dir="unsupported_skills",
    skill_name_rule="Only profile.json is supported",
    trigger_hint="Edit native profile assets in profile.json only",
    autotrigger_file="profile.json",
    trigger_line="{name}: {desc}",
    subagent_requires_mode=True,
    plugin_dir=None,
    hooks_file=None,
)

HOST_SURFACE = """# EDITABLE COMPANY PROFILE

Edit context/harness/profile.json in place. This is saved company knowledge and
capabilities, not global instructions. Keep schema_version, id and project_id.
Only notes, packages and their review/provenance may change. The host validates
and imports these assets through native project-scoped stores. Runtime prompts,
model, permissions, source files and provider remain fixed.

Before editing, identify an observable causal weakness in the original calculations
or source use. Adding a fact the analyst already used correctly is not evidence
of improvement. State the operation the new asset should change and the source
check that could falsify it. If a missing source contract cannot be resolved, keep
that uncertainty instead of inventing a convenient default. A different candidate
answer alone does not prove the original answer wrong.

Notes have id, title, statement, kind (businessRule, datasetNote, analysisLesson),
optional datasets/applicability, and evidence. Each evidence reference contains
path (relative public original file), sha256 (exact original bytes), and excerpt
(a literal original-source excerpt, at most 8000 UTF-8 bytes). Do not invent source
hashes. Read original files with Python hashlib if necessary. No foreign scope.
Company-specific names, schema definitions and procedures are allowed when
supported by original evidence. Record uncertainty when a source is ambiguous.
Do not memorize a question's answer, record a computed task result, or derive a
business rule from an expected answer. No private answers or assessment artifacts
are available or legitimate learning inputs.

Packages are objects with package (native CapabilityPackage JSON) and evidence
(the same source-reference format). Package schemaVersion 1/hostContract 1 supports
id, version, name, purpose, tools. Each tool has name, description, inputSchema and
steps with id/tool/arguments. Compose only currently granted host operations.
Installation never grants extra actions. A guidance-only package does not apply
itself automatically. Prefer source-backed notes unless a concrete workflow is
justified; preserve useful existing assets. Maximum 32 notes, 8 packages, one MB.
Do not edit code, global prompts, grants, model settings, sources or other files.
Return concise <notes> describing the observed weakness and source-grounded fix.
"""


def profile_from_tree(value):
    if set(value) != {"profile.json"}:
        raise ValueError("Edit only profile.json; global runtime guidance is a separate surface")
    raw = value["profile.json"]
    if not isinstance(raw, str) or len(raw.encode()) > SURFACE.always_on_max:
        raise ValueError("Profile exceeds its bounded JSON surface")
    try:
        profile = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("profile.json must be valid JSON") from error
    if not isinstance(profile, dict):
        raise ValueError("profile.json must contain an object")
    return profile


def profile_fingerprint(profile):
    return hashlib.sha256(
        json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class ProfileSurface:
    name = "mac_agent_profile"

    def surface(self):
        return SURFACE


class ProfileLearningAdapter(AnswerQualityAdapter):
    """Reuse evidence/task plumbing while replacing only the editable host surface.

    Backend port: validate_profile(spec), execute_profile(task, spec, run, timeout),
    inspect(path), judge(path, task), describe(), and comparison_identity. inspect
    exports profile_spec_sha256 and comparison alongside the original native trace.
    """

    def __init__(self, root: Path, backend, *, model: str, initial_tree):
        if getattr(backend, "partition", "development") != "development":
            raise ValueError("A frozen holdout backend cannot enter profile recursion")
        prompts.register_surface_text(
            "mac_agent_profile",
            surface_md=HOST_SURFACE,
            invariant="Improve source-grounded company knowledge and procedures. {levers}",
            domain="Improve this company's saved knowledge and capabilities. {levers}",
            tts_surface=HOST_SURFACE,
        )
        self.root, self.backend = Path(root), backend
        self.substrate = ProfileSurface()
        self.cases = {case["id"]: case for case in backend.describe()}
        self.initial_profile = profile_from_tree(initial_tree)
        self.validate_tree(initial_tree)
        assert_tree_has_no_grader_verdicts(initial_tree)
        channel = ChannelSpec("codex_app_server", model)
        self.spec = BenchSpec(
            name="mac-agent-profile-learning",
            runs_root=self.root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="answer a colleague's business question using original company evidence",
                domain_word="workload",
                inv_levers="Improve saved notes and native workflows in profile.json only.",
                dom_levers="Capture source-supported definitions, missing-data semantics and reusable procedures.",
                yardstick="Answers must preserve population, grain, units, joins and uncertainty, with auditable calculations.",
                domain_guidance="Distinguish missing company knowledge from general tool defects. Do not disguise a tool fix as a business fact.",
                selection_checks=(
                    "Inspect original calculations and evidence. Reject answer caches, invented source conventions "
                    "and unsupported facts. Preserve valid uncertainty; confidence or abstention alone does not "
                    "establish correctness. " + DECISION_EVIDENCE_CHECKS
                ),
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=(
                "**/evaluation/**",
                "**/contract.json",
                "**/seed.json",
                "**/judgment.json",
                "**/private/**",
            ),
            allow_subagents=False,
        )
        self._base = self.root / "base"
        if not self._base.exists():
            tree.write_tree(SURFACE, initial_tree, self._base)
        if profile_from_tree(tree.read_tree(SURFACE, self._base)) != self.initial_profile:
            raise ValueError("The baseline profile changed")

    def validate_tree(self, value):
        profile = profile_from_tree(value)
        for key in ("schema_version", "id", "project_id"):
            if profile.get(key) != self.initial_profile.get(key):
                raise ValueError("Preserve the profile identity and native schema")
        notes = profile.get("notes")
        if not isinstance(notes, list) or any(not isinstance(note, dict) for note in notes):
            raise ValueError("Knowledge notes must be native record objects in a list")
        if any(note.get("scope", "selected") != "selected" for note in notes):
            raise ValueError("Learning can modify only the selected company profile")
        self.backend.validate_profile(profile)

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        self._development(task_id)
        value = tree.read_tree(SURFACE, harness_dir or self._base)
        self.validate_tree(value)
        return self.backend.execute_profile(
            task_id, profile_from_tree(value), run_id, timeout or 900
        )

    def validate_run(self, task_id, run_dir):
        super().validate_run(task_id, run_dir)
        inspected = self.backend.inspect(run_dir)
        if inspected.get("candidate") != Candidate("builtin").as_dict():
            raise ValueError(
                "Profile learning cannot change runtime instructions or retrieval settings"
            )
        if inspected.get("comparison") != self.backend.comparison_identity:
            raise ValueError("Execution product, grants, model or source bank changed")
        if not inspected.get("profile_spec_sha256"):
            raise ValueError("Original execution has no frozen profile binding")

    def validate_baseline(self, task_id, view):
        self.validate_profile_run(task_id, view.run_dir, tree.read_tree(SURFACE, self._base))

    def validate_profile_run(self, task_id, run_dir, value):
        self.validate_run(task_id, run_dir)
        self.validate_tree(value)
        if self.backend.inspect(run_dir)["profile_spec_sha256"] != profile_fingerprint(
            profile_from_tree(value)
        ):
            raise ValueError("Execution used a different saved profile")


def finalize_profile(
    task_id, rollouts, trees, *, adapter, proposer, work_dir, library=None, depth=1
):
    """Select using native evidence, never grades; return a proposal for host review."""
    if type(depth) is not int or depth < 1:
        raise ValueError("Declare the original recursion depth")
    eligible, rejected = {}, {}
    for label, view in rollouts.items():
        try:
            adapter.validate_profile_run(task_id, view.run_dir, trees[label])
            # Reflection expects task-local harnesses next to its work directory.
            # Materialize only trees verified against the original native profile.
            harnesses = (Path(work_dir) / "harnesses").resolve()
            target = (harnesses / label).resolve()
            if not target.is_relative_to(harnesses):
                raise ValueError("Candidate label escapes its reflection harness directory")
            if target.exists():
                if profile_from_tree(tree.read_tree(SURFACE, target)) != profile_from_tree(
                    trees[label]
                ):
                    raise ValueError(
                        "Retained reflection harness differs from the original profile"
                    )
            else:
                tree.write_tree(SURFACE, trees[label], target)
        except (KeyError, ValueError) as error:
            rejected[label] = str(error)
            continue
        eligible[label] = view
    if len(eligible) <= 1:
        chosen = selection.trivial_selection(
            task_id, depth, "seq", eligible, adapter=adapter, work_dir=work_dir
        )
    else:
        chosen = selection.run_selection(
            task_id, depth, "seq", eligible, adapter=adapter, prop=proposer, work_dir=work_dir
        )
    entry = None
    if (
        chosen.ok
        and library is not None
        and trees[chosen.chosen_label] != tree.read_tree(SURFACE, adapter.base_harness())
    ):
        experience = selection.reflect_adoption(
            task_id, chosen, eligible, adapter=adapter, prop=proposer, work_dir=work_dir
        )
        entry = library.add(
            task_id,
            trees[chosen.chosen_label],
            why=chosen.why,
            label=chosen.chosen_label,
            run_id=chosen.chosen_run_id,
            experience=experience,
        )
    return {
        "selection": chosen.to_dict(),
        "rejected": rejected,
        "library_entry": str(entry) if entry else None,
        "application_adopted": False,
    }
