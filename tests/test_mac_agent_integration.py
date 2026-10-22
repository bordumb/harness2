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

"""Contract tests for Mac Agent's durable runtime adapter."""

import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from harness2.integrations.mac_agent import (
    Candidate,
    MacAgentClient,
    MacAgentError,
    MacAgentObservationPending,
    MacAgentResponseLimitExceeded,
)


class MacAgentIntegrationTests(unittest.TestCase):
    def test_response_cap_is_an_observation_error_without_repeating_the_request(self):
        token = "synthetic-token-value-1234567890"
        client = MacAgentClient("http://127.0.0.1:1", token, targets={})
        with patch(
            "harness2.integrations.mac_agent.urlopen", return_value=io.BytesIO(b"x" * 2_000_001)
        ) as request:
            with self.assertRaises(MacAgentResponseLimitExceeded) as raised:
                client._request("/v1/runs/original")
        self.assertEqual(request.call_count, 1)
        self.assertNotIn(token, str(raised.exception))

    def test_observer_deadline_resumes_original_key_without_post_or_cancellation(self):
        client = MacAgentClient(
            "http://127.0.0.1:1", "synthetic-token-value-1234567890", targets={}
        )
        candidate = Candidate("builtin")
        request = {
            "runtime_harness": candidate.as_dict(),
            "runtime_harness_fingerprint": candidate.fingerprint,
        }
        pending = {"id": "run-1", "state": "running", "request": request}
        finished = {
            **pending,
            "state": "succeeded",
            "conversation": {
                "messages": [{"role": "assistant", "isFinal": True, "text": "Verified answer"}]
            },
        }
        calls = []
        with patch("harness2.integrations.mac_agent.time.monotonic", return_value=0) as clock:

            def respond(path, *, method="GET", body=None, key=None):
                calls.append((method, path, key))
                if path == "/v1/runtime/harness":
                    return {"schema_version": 2, "fingerprint": candidate.fingerprint}
                if method == "POST":
                    clock.return_value = 5
                    return pending
                if path.startswith("/v1/submissions/"):
                    return pending
                if path == "/v1/runs/run-1":
                    return finished
                raise AssertionError("Unexpected request: " + path)

            with patch.object(client, "_request", side_effect=respond):
                with self.assertRaises(MacAgentObservationPending) as caught:
                    client.run(
                        task="Answer from original evidence",
                        candidate=candidate,
                        stable_run_key="retained",
                        timeout=1,
                    )
                self.assertEqual(caught.exception.run_id, "run-1")
                self.assertEqual(
                    caught.exception.idempotency_key, client.idempotency_key("retained")
                )
                clock.return_value = 0
                result = client.resume(candidate=candidate, stable_run_key="retained", timeout=1)
        self.assertEqual(result.answer, "Verified answer")
        self.assertEqual(sum(method == "POST" for method, _, _ in calls), 1)
        self.assertIn(("GET", "/v1/submissions/" + client.idempotency_key("retained"), None), calls)
        self.assertFalse(any("cancel" in path for _, path, _ in calls))

    def setUp(self):
        self.requests = []
        self.candidate = Candidate.load({"schema_version": 2, "id": "baseline"})
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, value, status=200):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(
                    (self.command, self.path, body, self.headers.get("Idempotency-Key"))
                )
                self._send(
                    {
                        "id": "run-1",
                        "state": "queued",
                        "request": {
                            "runtime_harness": owner.candidate.as_dict(),
                            "runtime_harness_fingerprint": owner.candidate.fingerprint,
                        },
                    },
                    202,
                )

            def do_GET(self):
                owner.requests.append((self.command, self.path, None, None))
                if self.path == "/v1/runtime/harness":
                    self._send({"schema_version": 2, "fingerprint": owner.candidate.fingerprint})
                elif self.path.endswith("/events?after=0"):
                    self._send([{"cursor": 2, "value": {"unretained": "not written to evidence"}}])
                elif self.path == "/v1/runs/run-1":
                    self._send(
                        {
                            "id": "run-1",
                            "state": "succeeded",
                            "request": {
                                "runtime_harness": owner.candidate.as_dict(),
                                "runtime_harness_fingerprint": owner.candidate.fingerprint,
                            },
                            "createdAt": "2026-10-20T00:00:00Z",
                            "updatedAt": "2026-10-20T00:00:03Z",
                            "conversation": {
                                "messages": [
                                    {
                                        "role": "assistant",
                                        "isFinal": True,
                                        "text": "Done. Bearer secret-token-value",
                                    }
                                ],
                                "invocations": [
                                    {
                                        "result": {
                                            "artifacts": [
                                                {
                                                    "id": "a1",
                                                    "name": "chart.png",
                                                    "digest": "abc",
                                                    "byteCount": 3,
                                                }
                                            ]
                                        }
                                    }
                                ],
                            },
                        }
                    )
                else:
                    self._send({}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_candidate_allowlist_fingerprint_and_runtime_evidence(self):
        with self.assertRaisesRegex(ValueError, "non-allowlisted"):
            Candidate.load({"schema_version": 2, "id": "unsafe", "auth": "override"})
        candidate = Candidate.load(
            {
                "schema_version": 2,
                "id": "baseline",
                "prompt_guidance": "Check definitions before aggregating.",
                "skills": ["verify units"],
                "retrieval_settings": {"maximum_notes": 4},
            }
        )
        self.candidate = candidate
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        client = MacAgentClient(endpoint, "lab-secret", poll_interval=0.05)
        evidence = client.run(
            task="Analyze the synthetic metrics", candidate=candidate, stable_run_key="eval/1"
        )
        self.assertEqual(evidence.state, "succeeded")
        self.assertIn("[REDACTED]", evidence.answer)
        self.assertIsNone(evidence.event_count)
        self.assertFalse(any("/events" in request[1] for request in self.requests))
        self.assertEqual(evidence.artifacts[0]["name"], "chart.png")
        self.assertIsNone(evidence.usage)
        self.assertEqual(evidence.candidate_fingerprint, candidate.fingerprint)
        post = next(request for request in self.requests if request[0] == "POST")
        self.assertEqual(post[1], "/v1/runs")
        self.assertEqual(post[3], evidence.idempotency_key)
        self.assertEqual("Analyze the synthetic metrics", post[2]["text"])
        self.assertEqual(candidate.fingerprint, post[2]["expected_harness_fingerprint"])
        self.assertNotIn("lab-secret", json.dumps(evidence.as_dict()))

    def test_url_rejects_non_loopback_plain_http(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            MacAgentClient("http://example.com", "token")

    def test_ambiguous_submit_resolves_same_key_without_reposting(self):
        from harness2.integrations.mac_agent import MacAgentError

        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        candidate = Candidate.load({"schema_version": 2, "id": "baseline"})
        client = MacAgentClient(endpoint, "lab-secret", poll_interval=0.05)
        original_request = client._request
        calls = []

        def ambiguous_request(path, *, method="GET", body=None, key=None):
            if method == "POST":
                calls.append((method, path, key))
                raise MacAgentError("simulated lost POST response")
            if path.startswith("/v1/submissions/"):
                calls.append((method, path, None))
                return {
                    "id": "run-1",
                    "state": "queued",
                    "request": {
                        "runtime_harness": candidate.as_dict(),
                        "runtime_harness_fingerprint": candidate.fingerprint,
                    },
                }
            return original_request(path, method=method, body=body, key=key)

        client._request = ambiguous_request
        evidence = client.run(
            task="Check one metric", candidate=candidate, stable_run_key="eval/uncertain"
        )
        self.assertEqual(evidence.run_id, "run-1")
        posts = [request for request in calls if request[0] == "POST"]
        lookups = [request for request in calls if request[1].startswith("/v1/submissions/")]
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(lookups), 1)
        self.assertEqual(posts[0][2], lookups[0][1].rsplit("/", 1)[-1])

    def test_schema_two_matches_the_independent_swift_utf8_fingerprint_oracle(self):
        candidate = Candidate.load(
            {
                "schema_version": 2,
                "id": "oracle",
                "prompt_guidance": "Verify / µ",
                "skills": ["units"],
            }
        )
        self.assertEqual(
            candidate.fingerprint,
            "29eb24cea9e21bc20435e253192f8b4984c3928317b52f3f562260ad7b606899",
        )
        for fields in (
            {"schema_version": 1},
            {"retrieval_settings": {"max_sources": 2}},
            {"retrieval_settings": {"maximum_notes": True}},
            {"retrieval_settings": {"maximum_notes": 1.5}},
            {"prompt_guidance": "µ" * 4001},
        ):
            with self.assertRaises(ValueError):
                Candidate.load({"schema_version": 2, "id": "bad", **fields})

    def test_mismatched_preflight_never_submits_a_task(self):
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        client = MacAgentClient(endpoint, "lab-secret", poll_interval=0.05)
        candidate = Candidate.load({"schema_version": 2, "id": "another-candidate"})
        with self.assertRaisesRegex(MacAgentError, "does not expose"):
            client.run(task="Must not execute", candidate=candidate, stable_run_key="mismatch")
        self.assertFalse(any(item[0] == "POST" for item in self.requests))

    def test_host_targets_require_explicit_fingerprint_and_environment_token(self):
        candidate = self.candidate
        target = {
            candidate.fingerprint: {
                "endpoint": f"http://127.0.0.1:{self.server.server_port}",
                "token_environment": "SYNTHETIC_HARNESS_TOKEN",
            }
        }
        client = MacAgentClient(targets=target)
        with patch.dict("os.environ", {"SYNTHETIC_HARNESS_TOKEN": "lab-secret"}):
            evidence = client.run(
                task="Read the fixture", candidate=candidate, stable_run_key="targets"
            )
        self.assertEqual(evidence.candidate_fingerprint, candidate.fingerprint)
        with patch.dict("os.environ", {"HARNESS2_MAC_AGENT_TOKEN": "must-not-fallback"}):
            with self.assertRaisesRegex(ValueError, "TOKEN"):
                client.run(
                    task="Must not execute",
                    candidate=candidate,
                    stable_run_key="missing-target-token",
                )
        with self.assertRaisesRegex(ValueError, "No explicitly configured host"):
            client.run(
                task="Read the fixture",
                candidate=Candidate.load({"schema_version": 2, "id": "other"}),
                stable_run_key="unknown",
            )

    def test_final_evidence_must_retain_the_original_runtime_binding(self):
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        client = MacAgentClient(endpoint, "lab-secret", poll_interval=0.05)
        original = client._request

        def changed(path, **kwargs):
            result = original(path, **kwargs)
            if path == "/v1/runs/run-1":
                result["request"]["runtime_harness_fingerprint"] = "changed"
            return result

        client._request = changed
        with self.assertRaisesRegex(MacAgentError, "does not match"):
            client.run(
                task="Read the fixture", candidate=self.candidate, stable_run_key="changed-evidence"
            )


if __name__ == "__main__":
    unittest.main()
