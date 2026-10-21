from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from harness2.integrations.product_candidate import _path, propose_product
from harness2.core.proposer import Proposer, ProposerError
from harness2.core.spec import ChannelSpec


class ProductCandidateTests(unittest.TestCase):
    def test_harvest_rejects_symlinks_before_copying_private_host_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "session/context/source"
            source.mkdir(parents=True)
            (root / "private.txt").write_text("secret")
            (source / "Tool.swift").symlink_to(root / "private.txt")
            proposer = Proposer(ChannelSpec("codex_app_server", "gpt-6-sol"), audit_dir=root / "audit")
            with self.assertRaisesRegex(ProposerError, "symlinks"):
                proposer._harvest(root / "session", "context/source", "patch")
            self.assertFalse((root / "audit").exists())

    def test_private_and_escaping_paths_are_rejected(self):
        for path in ("/tmp/code.swift", "Sources/../private.py", "lab/answers.py", "Sources/.git/hook.py"):
            with self.assertRaises(ValueError):
                _path(path)

    def test_existing_proposer_receives_only_explicit_sources_and_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "Sources").mkdir(parents=True)
            (repo / "Sources/Tool.swift").write_text("old")
            (repo / "private-answer.json").write_text("secret")
            output = root / "proposal"
            (output / "Sources").mkdir(parents=True)
            (output / "Sources/Tool.swift").write_text("improved")
            proposer = Mock()
            proposer.call.return_value = Mock(workspace=output, text="notes", usage={}, wall_s=1)
            manifest = propose_product(proposer=proposer, repository=repo, context=root / "context",
                                       source_paths=["Sources/Tool.swift"], trajectory="observed error",
                                       task="original question", mission="Fix the tool")
            self.assertFalse((root / "context/private-answer.json").exists())
            self.assertEqual(list(manifest["changed_sha256"]), ["Sources/Tool.swift"])
            self.assertFalse(manifest["applied"])
            self.assertEqual((repo / "Sources/Tool.swift").read_text(), "old")


if __name__ == "__main__":
    unittest.main()
