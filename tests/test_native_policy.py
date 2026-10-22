import unittest
from unittest.mock import patch

from harness2.integrations.mac_agent import Candidate, MacAgentClient, MacAgentError


def configuration():
    return {
        "schema_version": 3,
        "id": "retained-test",
        "policies": {
            "results": {
                "id": "retained-results",
                "version": 1,
                "failure_mode": "bounded_preview",
                "spill_bytes": 4096,
                "preview_bytes": 2048,
                "page_bytes": 8192,
                "page_rows": 3,
                "retained_bytes_per_run": 1_048_576,
                "retention_seconds": 3600,
            }
        },
    }


class NativePolicyTests(unittest.TestCase):
    def test_legacy_fingerprint_is_unchanged_and_native_configuration_is_stable(self):
        legacy = Candidate.load(
            {
                "schema_version": 2,
                "id": "oracle",
                "prompt_guidance": "Verify / µ",
                "skills": ["units"],
            }
        )
        self.assertEqual(
            legacy.fingerprint, "29eb24cea9e21bc20435e253192f8b4984c3928317b52f3f562260ad7b606899"
        )
        value = configuration()
        candidate = Candidate.load(value)
        frozen = candidate.as_dict()
        value["policies"]["results"]["preview_bytes"] = 9999
        self.assertEqual(candidate.as_dict(), frozen)
        frozen["policies"]["results"]["preview_bytes"] = 9999
        self.assertEqual(candidate.as_dict()["policies"]["results"]["preview_bytes"], 2048)
        self.assertEqual(candidate.as_dict()["policies"]["context"], None)
        self.assertEqual(Candidate.load(candidate.as_dict()).fingerprint, candidate.fingerprint)

    def test_policy_fields_do_not_accept_authority_unknown_versions_or_invalid_limits(self):
        for field, value in [
            ("version", True),
            ("version", 2),
            ("preview_bytes", 2048.5),
            ("page_rows", True),
            ("retention_seconds", 0),
            ("failure_mode", "silently_continue"),
            ("failure_mode", []),
            ("grant", "all"),
            ("spill_bytes", 1024),
            ("id", "downloaded-code"),
        ]:
            config = configuration()
            config["policies"]["results"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Candidate.load(config)
        config = configuration()
        config["schema_version"] = 2
        with self.assertRaises(ValueError):
            Candidate.load(config)

    def test_observers_are_pinned_without_changing_omitted_policy_fingerprints(self):
        original = configuration()
        baseline = Candidate.load(original)
        for value in (None, []):
            config = configuration()
            config["policies"]["observations"] = value
            self.assertEqual(Candidate.load(config).fingerprint, baseline.fingerprint)
        config = {
            "schema_version": 3,
            "id": "observed-turn",
            "policies": {
                "observations": [
                    {"id": "base", "version": 1},
                    {"id": "dependent", "version": 1, "dependencies": ["base"]},
                ]
            },
        }
        candidate = Candidate.load(config)
        self.assertEqual(
            candidate.fingerprint,
            "18ab557c456eae1c3f5fef01ce1cd7643c3ec187a74f235f4c1b3ce5ab60fe45",
        )
        self.assertNotEqual(candidate.fingerprint, baseline.fingerprint)
        self.assertEqual(Candidate.load(candidate.as_dict()).fingerprint, candidate.fingerprint)
        config["policies"]["observations"][0]["id"] = "changed"
        self.assertEqual(candidate.as_dict()["policies"]["observations"][0]["id"], "base")

    def test_observer_identity_limits_reject_authority_and_ambiguous_dependencies(self):
        for value in (
            "observer",
            [{}],
            [{"id": "x", "version": True}],
            [{"id": "x", "version": 2}],
            [{"id": "../x", "version": 1}],
            [{"id": "x", "version": 1, "grant": "all"}],
            [{"id": "x", "version": 1, "dependencies": ["a", "a"]}],
            [{"id": "x", "version": 1}] * 2,
            [{"id": "x", "version": 1, "dependencies": [True]}],
        ):
            config = configuration()
            config["policies"]["observations"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                Candidate.load(config)

    def test_native_host_version_mismatch_is_rejected_before_submission(self):
        client = MacAgentClient(
            "http://127.0.0.1:1", "synthetic-token-value-1234567890", targets={}
        )
        candidate = Candidate.load(configuration())
        with patch.object(
            client,
            "_request",
            return_value={"schema_version": 2, "fingerprint": candidate.fingerprint},
        ) as request:
            with self.assertRaises(MacAgentError):
                client.run(
                    task="Inspect source evidence",
                    candidate=candidate,
                    stable_run_key="native-check",
                    timeout=1,
                )
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[0], "/v1/runtime/harness")
