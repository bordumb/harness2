# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Small deterministic checks for the Mac Agent campaign orchestrator."""

import json
import tempfile
import unittest
from pathlib import Path

from harness2.integrations.campaign import run_campaign, validate_manifest
from harness2.integrations.mac_agent import RunEvidence


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def run(self, *, task, candidate, stable_run_key, timeout):
        self.calls.append((task, candidate.id, stable_run_key, timeout))
        score = 0.95 if candidate.id == "candidate" else 0.5
        return RunEvidence(
            run_id=f"run-{len(self.calls)}",
            state="succeeded",
            answer=json.dumps({"metrics": {"subscriber_rate": score}, "notes": "verified"}),
            created_at="2026-10-20T00:00:00Z",
            updated_at="2026-10-20T00:00:01Z",
            elapsed_seconds=1,
            event_count=1,
            candidate_fingerprint=candidate.fingerprint,
            idempotency_key=stable_run_key,
            artifacts=({"name": "summary.csv"},),
        )


class MacAgentCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "baseline.json").write_text(
            json.dumps({"schema_version": 2, "id": "baseline"})
        )
        (self.root / "candidate.json").write_text(
            json.dumps({"schema_version": 2, "id": "candidate"})
        )
        (self.root / "dev.txt").write_text("measure subscriber_rate")
        (self.root / "holdout.txt").write_text("repeat subscriber_rate independently")
        self.manifest = {
            "schema_version": 1,
            "campaign_id": "tiny-test",
            "fixture_fingerprint": "a" * 64,
            "baseline": "baseline.json",
            "candidate": "candidate.json",
            "development": [
                {
                    "id": "dev-1",
                    "file": "dev.txt",
                    "required_phrases": ["verified"],
                    "expected_metrics": {"subscriber_rate": {"value": 0.95, "tolerance": 0.01}},
                    "expected_artifacts": ["summary.csv"],
                }
            ],
            "holdout": [
                {
                    "id": "holdout-1",
                    "file": "holdout.txt",
                    "expected_metrics": {"subscriber_rate": {"value": 0.95, "tolerance": 0.01}},
                }
            ],
        }
        self.manifest_path = self.root / "campaign.json"
        self.manifest_path.write_text(json.dumps(self.manifest))

    def test_development_is_default_and_holdout_comparison_is_separate(self):
        runtime = FakeRuntime()
        output = self.root / "report.json"
        first = run_campaign(self.manifest_path, output, max_runs=2, client=runtime)
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(first["partition"], "development")
        self.assertEqual(first["summary"]["development"]["candidate"]["passed"], 1)
        second = run_campaign(
            self.manifest_path, output, include_holdout=True, max_runs=4, client=runtime
        )
        self.assertEqual(len(runtime.calls), 6)
        self.assertEqual(second["holdout_outcome"], "candidate_better")
        self.assertEqual(second["recommendation"], "review_candidate_for_limited_adoption")
        self.assertEqual(second["summary"]["holdout"]["baseline"]["passed"], 0)

    def test_manifest_rejects_unchecked_and_cross_partition_reused_tasks(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["development"][0].pop("expected_metrics")
        bad["development"][0].pop("expected_artifacts")
        bad["development"][0].pop("required_phrases")
        with self.assertRaisesRegex(ValueError, "deterministic check"):
            validate_manifest(bad)
        bad = json.loads(json.dumps(self.manifest))
        bad["holdout"][0]["id"] = "dev-1"
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            validate_manifest(bad)

    def test_campaign_run_cap_is_enforced_before_runtime_calls(self):
        runtime = FakeRuntime()
        with self.assertRaisesRegex(ValueError, "exceeding"):
            run_campaign(
                self.manifest_path,
                self.root / "report.json",
                include_holdout=True,
                max_runs=2,
                client=runtime,
            )
        self.assertEqual(runtime.calls, [])


if __name__ == "__main__":
    unittest.main()
