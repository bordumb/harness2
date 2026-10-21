import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from harness2.core.proposer import Proposer, ProposerError, _copy_harvest_tree
from harness2.core.spec import ChannelSpec
from harness2.integrations.product_candidate import _path, propose_product


class ProductCandidateTests(unittest.TestCase):
    def test_harvest_opens_each_file_without_following_a_raced_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "Tool.swift").write_text("original")
            (root / "private").write_text("secret")
            original_open = os.open
            def swap_before_open(path, flags, *args, **kwargs):
                if path == "Tool.swift":
                    (source / "Tool.swift").unlink()
                    (source / "Tool.swift").symlink_to(root / "private")
                return original_open(path, flags, *args, **kwargs)
            with patch("harness2.core.proposer.os.open", side_effect=swap_before_open):
                with self.assertRaises(OSError):
                    _copy_harvest_tree(source, root / "output")
            self.assertFalse((root / "output").exists())

    def test_harvest_retains_nested_regular_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source/Sources").mkdir(parents=True)
            (root / "source/Sources/Tool.swift").write_text("new source")
            _copy_harvest_tree(root / "source", root / "output")
            self.assertEqual((root / "output/Sources/Tool.swift").read_text(), "new source")

    def test_oversized_proposal_does_not_publish_a_partial_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source").mkdir()
            (root / "source/Tool.swift").write_bytes(b"x" * 1_000_001)
            with self.assertRaisesRegex(ProposerError, "bounded harvest"):
                _copy_harvest_tree(root / "source", root / "output")
            self.assertFalse((root / "output").exists())

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
