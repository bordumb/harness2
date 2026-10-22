import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from harness2.core import context, tree
from harness2.core.proposer import Proposer, Reply
from harness2.core.recursion import run_sequential
from harness2.core.spec import BenchmarkAdapter, RunView
from harness2.integrations.mac_agent import Candidate
from harness2.integrations.mac_agent_profile import (
    SURFACE,
    ProfileLearningAdapter,
    finalize_profile,
    profile_fingerprint,
    profile_from_tree,
)


def initial():
    return {
        "schema_version": 1,
        "id": "company",
        "project_id": "project-identity",
        "review": "Source-backed fixture",
        "notes": [],
        "packages": [],
    }


def as_tree(profile):
    return {"profile.json": json.dumps(profile)}


class Backend:
    partition = "development"
    comparison_identity = {"model": "gpt-6-sol", "product": "fixed", "grants": "fixed"}

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.judgments = 0
        (root / "sources").mkdir()
        (root / "sources/manual.md").write_text("Null stock means unknown, not zero.")

    def describe(self):
        return [
            {
                "id": k,
                "question": "Explain inventory stock",
                "family": "inventory",
                "partition": p,
                "project": str(self.root / "sources"),
            }
            for k, p in [("dev", "development"), ("hidden", "holdout")]
        ]

    def validate_profile(self, value):
        if set(value) != set(initial()):
            raise ValueError("Unsupported profile fields")
        if any("answer-cache" in n["statement"] for n in value["notes"]):
            raise ValueError("Rejected unsupported answer cache")

    def execute_profile(self, task, profile, run_id, timeout):
        folder = self.root / "executions" / run_id
        folder.mkdir(parents=True)
        self.calls.append((task, copy.deepcopy(profile), folder))
        return folder

    def inspect(self, path):
        task, profile, _ = next(c for c in self.calls if c[2] == path)
        return {
            "task_id": task,
            "question": "Explain inventory stock",
            "candidate": Candidate("builtin").as_dict(),
            "profile_spec_sha256": profile_fingerprint(profile),
            "comparison": self.comparison_identity,
            "delivered": True,
            "trajectory": "[OBSERVATION] Native project knowledge: null stock is unknown",
            "deliverables": {"answer.md": "Unknown, not zero."},
        }

    def judge(self, path, task):
        self.judgments += 1
        return {"passed": True}


class ProfileProposer(Proposer):
    def call(self, mission, context_dir, label, **kwargs):
        workspace = Path(context_dir) / "harness"
        value = json.loads((workspace / "profile.json").read_text())
        value["notes"] = [
            {
                "id": "null-stock",
                "title": "Inventory stock semantics",
                "statement": "Null stock means unknown, not zero.",
                "kind": "datasetNote",
                "evidence": [
                    {
                        "path": "manual.md",
                        "sha256": "actual-host-validates-this",
                        "excerpt": "Null stock means unknown, not zero.",
                    }
                ],
            }
        ]
        (workspace / "profile.json").write_text(json.dumps(value))
        reply = Reply(
            label=label,
            text="<notes>Preserve original missing-data meaning.</notes>",
            ok=True,
            attempts=1,
            workspace=workspace,
        )
        self._calls.append(reply)
        return reply


class ProfileAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.backend = Backend(self.root)
        self.adapter = ProfileLearningAdapter(
            self.root / "adapter", self.backend, model="gpt-6-sol", initial_tree=as_tree(initial())
        )

    def test_actual_recursion_core_edits_company_assets_without_changing_global_runtime(self):
        self.assertIsInstance(self.adapter, BenchmarkAdapter)
        path = self.adapter.execute("dev", None, "base")
        result = run_sequential(
            "dev",
            1,
            [RunView("base", "base", path, True, True)],
            adapter=self.adapter,
            prop=ProfileProposer(self.adapter.spec.channels["proposer"]),
            work_dir=self.root / "recursion",
            run_id_of=lambda s: "recursion-" + s,
            base_tree=as_tree(initial()),
            propose_workers=1,
            rollout_workers=1,
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.finals, ["c1"])
        self.assertEqual(len(self.backend.calls), 4)
        self.assertTrue(all(c[1]["notes"] for c in self.backend.calls[1:]))
        self.assertEqual(self.backend.judgments, 0)
        self.assertEqual(set(result.trees["c1"]), {"profile.json"})

    def test_wrong_baseline_profile_and_changed_product_rejected_before_proposal(self):
        other = initial()
        other["notes"] = [{"statement": "Company fact"}]
        path = self.backend.execute_profile("dev", other, "other-profile", 1)
        prop = Mock()
        with self.assertRaisesRegex(ValueError, "different saved profile"):
            run_sequential(
                "dev",
                1,
                [RunView("base", "other", path, True, True)],
                adapter=self.adapter,
                prop=prop,
                work_dir=self.root / "invalid",
                run_id_of=lambda s: s,
                base_tree=as_tree(initial()),
            )
        original = self.backend.inspect
        self.backend.inspect = lambda p: {**original(p), "comparison": {"product": "changed"}}
        with self.assertRaisesRegex(ValueError, "product, grants"):
            self.adapter.validate_run("dev", path)
        prop.call.assert_not_called()
        self.assertFalse((self.root / "invalid").exists())

    def test_prompt_overlays_foreign_scope_identity_changes_and_unsupported_assets_rejected(self):
        for change in (
            {"project_id": "different"},
            {"prompt_guidance": "Domain policy"},
            {"notes": [{"scope": "foreign"}]},
        ):
            with self.assertRaises(ValueError):
                self.adapter.validate_tree(as_tree({**initial(), **change}))
        with self.assertRaisesRegex(ValueError, "only profile.json"):
            profile_from_tree({**as_tree(initial()), "systemprompt.md": "Hidden business rules"})
        for text in ("[]", "invalid json"):
            with self.assertRaises(ValueError):
                profile_from_tree({"profile.json": text})
        self.assertEqual(self.backend.calls, [])

    def test_context_and_selection_use_original_observations_without_private_grades(self):
        path = self.adapter.execute("dev", None, "base")
        (path / "judgment.json").write_text('{"private":"DO_NOT_COPY"}')
        built = context.build(
            self.root / "context",
            self.adapter,
            "dev",
            [RunView("base", "base", path, True, True)],
            harness_dir=self.adapter.base_harness(),
        )
        rendered = "\n".join(p.read_text() for p in built.root.rglob("*") if p.is_file())
        self.assertIn("null stock is unknown", rendered)
        self.assertNotIn("DO_NOT_COPY", rendered)
        self.assertIn("authorized", self.adapter.deliverable_text(path).lower())
        value = as_tree({**initial(), "review": "Wrong profile"})
        result = finalize_profile(
            "dev",
            {"bad": RunView("bad", "base", path, True, True)},
            {"bad": value},
            adapter=self.adapter,
            proposer=Mock(),
            work_dir=self.root / "selection",
        )
        self.assertIn("different saved profile", result["rejected"]["bad"])
        self.assertFalse(result["application_adopted"])
        self.assertEqual(self.backend.judgments, 0)

    def test_holdout_and_changed_native_harness_cannot_enter_profile_recursion(self):
        with self.assertRaises(ValueError):
            self.adapter.execute("hidden", None, "no")
        self.backend.partition = "holdout"
        with self.assertRaisesRegex(ValueError, "holdout"):
            ProfileLearningAdapter(
                self.root / "forbidden",
                self.backend,
                model="gpt-6-sol",
                initial_tree=as_tree(initial()),
            )
        self.assertFalse((self.root / "forbidden").exists())
        self.backend.partition = "development"
        path = self.adapter.execute("dev", None, "base")
        original = self.backend.inspect
        self.backend.inspect = lambda p: {
            **original(p),
            "candidate": {"id": "builtin", "prompt_guidance": "Hidden"},
        }
        with self.assertRaisesRegex(ValueError, "runtime instructions"):
            self.adapter.validate_run("dev", path)

    def test_malformed_note_collections_fail_as_actionable_validation_errors(self):
        for notes in (None, "not a list", ["not a record"], [None]):
            with self.assertRaisesRegex(ValueError, "native record objects"):
                self.adapter.validate_tree(as_tree({**initial(), "notes": notes}))
        self.assertEqual(self.backend.calls, [])

    def test_seeded_profile_is_preserved_as_the_actual_baseline(self):
        value = initial()
        value["notes"] = [{"statement": "Original company fact"}]
        adapter = ProfileLearningAdapter(
            self.root / "seeded", self.backend, model="gpt-6-sol", initial_tree=as_tree(value)
        )
        path = adapter.execute("dev", None, "seeded")
        adapter.validate_baseline("dev", RunView("base", "seeded", path, True, True))
        self.assertEqual(profile_from_tree(tree.read_tree(SURFACE, adapter.base_harness())), value)
        with self.assertRaisesRegex(ValueError, "baseline profile changed"):
            ProfileLearningAdapter(
                self.root / "seeded",
                self.backend,
                model="gpt-6-sol",
                initial_tree=as_tree(initial()),
            )


if __name__ == "__main__":
    unittest.main()
