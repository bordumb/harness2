import json
import tempfile
import unittest
from pathlib import Path

from harness2.core import context, tree
from harness2.core.proposer import Proposer, Reply
from harness2.core.recursion import run_sequential
from harness2.core.spec import BenchmarkAdapter, RunView
from harness2.integrations.answer_quality import SURFACE, AnswerQualityAdapter, candidate_from_tree


class Backend:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.judgments = 0
        (root / "sources").mkdir()
        (root / "sources/catalog.json").write_text('{"source":"original-note"}')

    def describe(self):
        return [
            dict(
                id=key,
                family="recall",
                partition=partition,
                question="Recall the team's decision",
                project=str(self.root / "sources"),
            )
            for key, partition in [("dev", "development"), ("hidden", "holdout")]
        ]

    def execute(self, task_id, candidate, run_id, timeout):
        self.calls.append((task_id, candidate, run_id, timeout))
        path = self.root / "executions" / run_id
        path.mkdir(parents=True)
        return path

    def inspect(self, run_dir):
        return {
            "delivered": True,
            "trajectory": "[ACTION] Read original note\n[OBSERVATION] Team chose UTC",
            "deliverables": {"answer.md": "The team chose UTC."},
        }

    def judge(self, run_dir, task_id):
        self.judgments += 1
        return {"passed": True}


class ControlledProposer(Proposer):
    def call(self, mission, context_dir, label, **kwargs):
        workspace = Path(context_dir) / "harness"
        (workspace / "tool_guidance.md").write_text(
            "Verify original source revisions before answering."
        )
        reply = Reply(
            label=label,
            text="<notes>Use original source evidence.</notes>",
            ok=True,
            attempts=1,
            workspace=workspace,
        )
        self._calls.append(reply)
        return reply


class AnswerQualityTests(unittest.TestCase):
    def test_frozen_holdout_backend_is_rejected_before_proposer_context_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = Backend(root)
            backend.partition = "holdout"
            with self.assertRaisesRegex(ValueError, "cannot enter proposer recursion"):
                AnswerQualityAdapter(root / "adapter", backend, model="gpt-6-sol")
            self.assertFalse((root / "adapter").exists())
            self.assertEqual(backend.calls, [])

    def test_existing_recursion_core_proposes_probes_and_composes_without_judge_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = Backend(root)
            adapter = AnswerQualityAdapter(root, backend, model="gpt-6-sol")
            base_dir = adapter.execute("dev", None, "base")
            base = RunView("base", "base", base_dir, True, True)
            result = run_sequential(
                "dev",
                1,
                [base],
                adapter=adapter,
                prop=ControlledProposer(adapter.spec.channels["proposer"]),
                work_dir=root / "recursion",
                run_id_of=lambda label: "recursion-" + label,
                base_tree=tree.read_tree(SURFACE, adapter.base_harness()),
                propose_workers=1,
                rollout_workers=1,
            )
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.finals, ["c1"])
            self.assertEqual(len(backend.calls), 4)
            self.assertEqual(backend.judgments, 0)
            self.assertTrue(all(call[1]["tool_guidance"] for call in backend.calls[1:]))

    def test_candidates_are_runtime_effective_and_unsupported_surfaces_fail(self):
        self.assertEqual(candidate_from_tree({}).id, "builtin")
        candidate = candidate_from_tree(
            {
                "systemprompt.md": "Check original decisions.",
                "retrieval.json": '{"maximum_notes":12}',
            }
        )
        self.assertEqual(candidate.retrieval_settings["maximum_notes"], 12)
        self.assertNotEqual(candidate.id, "builtin")
        self.assertEqual(
            candidate.fingerprint,
            candidate_from_tree(
                {
                    "retrieval.json": '{"maximum_notes":12}',
                    "systemprompt.md": "Check original decisions.",
                }
            ).fingerprint,
        )
        for value in [
            {"scripts/replace_auth.py": "pass"},
            {"retrieval.json": '{"tool_permissions":"allow"}'},
            {"retrieval.json": '{"maximum_notes":true}'},
        ]:
            with self.assertRaises(ValueError):
                candidate_from_tree(value)

    def test_core_context_gets_actual_observations_without_judgments_or_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = Backend(root)
            adapter = AnswerQualityAdapter(root, backend, model="gpt-6-sol")
            self.assertIsInstance(adapter, BenchmarkAdapter)
            self.assertEqual(adapter.tasks(), ["dev"])
            self.assertEqual(adapter.tasks("train"), ["dev"])
            with self.assertRaises(ValueError):
                adapter.tasks("test")
            for fn in [adapter.task_prompt, adapter.task_files, adapter.domain_of]:
                with self.assertRaises(ValueError):
                    fn("hidden")
            with self.assertRaises(ValueError):
                adapter.execute("hidden", None, "forbidden")
            path = adapter.execute("dev", None, "baseline")
            view = RunView("base", "baseline", path, True, True)
            built = context.build(
                root / "context", adapter, "dev", [view], harness_dir=adapter.base_harness()
            )
            self.assertEqual(built.rollouts, ["base"])
            self.assertEqual(backend.judgments, 0)
            text = "\n".join(p.read_text() for p in built.root.rglob("*") if p.is_file())
            self.assertIn("Team chose UTC", text)
            self.assertNotIn("hidden", text)
            self.assertNotIn("passed", text)
            adapter.score(path, "dev")
            self.assertEqual(backend.judgments, 1)
            changed = root / "candidate"
            tree.write_tree(
                SURFACE,
                {
                    "systemprompt.md": "Inspect original evidence.",
                    "retrieval.json": json.dumps({"maximum_notes": 4}),
                },
                changed,
            )
            adapter.execute("dev", changed, "candidate")
            self.assertEqual(backend.calls[-1][1]["retrieval_settings"]["maximum_notes"], 4)
            self.assertEqual(backend.calls[0][1]["id"], "builtin")


if __name__ == "__main__":
    unittest.main()
