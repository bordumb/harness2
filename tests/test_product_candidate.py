from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from harness2.integrations.product_candidate import _path, propose_product


class ProductCandidateTests(unittest.TestCase):
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
