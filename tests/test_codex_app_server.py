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

"""Protocol-level checks for the signed-in Codex app-server channel."""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from harness2.core.codex_app_server import CodexAppServerClient, CodexAppServerError
from harness2.core.spec import resolve_channel_model

FAKE_SERVER = """#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(sys.argv[0]).parent
(root / "launch-arguments.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
record = root / "requests.jsonl"
auth_mode = (root / "auth-mode").read_text(encoding="utf-8")
for line in sys.stdin:
    request = json.loads(line)
    with open(record, "a", encoding="utf-8") as file:
        file.write(json.dumps(request) + "\\n")
    method = request.get("method")
    if method == "initialize":
        response = {"id": request["id"], "result": {"protocolVersion": "2"}}
    elif method == "account/read":
        response = {"id": request["id"], "result": {"account": {"type": auth_mode}}}
    elif method == "model/list":
        response = {"id": request["id"], "result": {"data": [{"model": "gpt-6.1"}], "nextCursor": None}}
    elif method == "thread/start":
        response = {"id": request["id"], "result": {"thread": {"id": "thread-1"}, "model": "gpt-6.1", "modelProvider": "openai"}}
    elif method == "turn/start":
        response = {"id": request["id"], "result": {"turn": {"id": "turn-1"}}}
        if (root / "early-notification").exists():
            print(json.dumps({"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "delta": "early-"}}), flush=True)
        print(json.dumps(response), flush=True)
        if (root / "auth-changed").exists():
            print(json.dumps({"method": "account/updated", "params": {"authMode": "api"}}), flush=True)
        print(json.dumps({"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "delta": "report ready"}}), flush=True)
        print(json.dumps({"method": "thread/tokenUsage/updated", "params": {"threadId": "thread-1", "tokenUsage": {"total": {"inputTokens": 19, "outputTokens": 7}}}}), flush=True)
        print(json.dumps({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}}}), flush=True)
        break
    else:
        response = {"id": request.get("id"), "result": {}}
    print(json.dumps(response), flush=True)
"""


class CodexAppServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.executable = self.root / "fake-codex"
        self.executable.write_text(FAKE_SERVER, encoding="utf-8")
        self.executable.chmod(0o700)
        self.record = self.root / "requests.jsonl"

    def client(self, *, auth_mode="chatgpt", event_log=None):
        (self.root / "auth-mode").write_text(auth_mode, encoding="utf-8")
        return CodexAppServerClient(
            executable=str(self.executable), model="gpt-6.1", timeout=5, event_log=event_log
        )

    def test_early_notifications_survive_request_assembly_and_raw_events_exclude_auth_responses(
        self,
    ):
        (self.root / "early-notification").touch()
        path = self.root / "events.jsonl"
        client = self.client(event_log=path)
        try:
            answer, _ = client.run(cwd=self.root, mission="produce the report")
        finally:
            client.close()
        self.assertEqual(answer, "early-report ready")
        events = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertTrue(any(event["method"] == "turn/completed" for event in events))
        self.assertTrue(all(event["method"].startswith(("item/", "turn/")) for event in events))
        self.assertNotIn('"account"', path.read_text())
        with self.assertRaises(FileExistsError):
            self.client(event_log=path)

    def test_turn_is_chatgpt_only_bounded_and_captures_usage(self):
        client = self.client()
        try:
            answer, usage = client.run(
                cwd=self.root, mission="write the report", system="work only in cwd"
            )
        finally:
            client.close()
        self.assertEqual(answer, "report ready")
        self.assertEqual(usage, {"input_tokens": 19, "output_tokens": 7})
        requests = [json.loads(line) for line in self.record.read_text().splitlines()]
        thread = next(row["params"] for row in requests if row.get("method") == "thread/start")
        turn = next(row["params"] for row in requests if row.get("method") == "turn/start")
        self.assertEqual(thread["approvalPolicy"], "never")
        self.assertEqual(thread["permissions"], client.permission_profile)
        self.assertNotIn("sandbox", thread)
        self.assertNotIn("environments", thread)
        self.assertFalse(thread["allowProviderModelFallback"])
        self.assertEqual(turn["permissions"], client.permission_profile)
        self.assertNotIn("sandboxPolicy", turn)
        self.assertNotIn("environments", turn)
        policy = tomllib.loads("policy=" + client.permission_profile_toml())["policy"]
        self.assertEqual(policy["extends"], ":workspace")
        self.assertFalse(policy["network"]["enabled"])
        self.assertEqual(policy["filesystem"][":root"], "deny")
        self.assertEqual(policy["filesystem"][":minimal"], "read")
        self.assertEqual(policy["filesystem"][":workspace_roots"], "write")
        launch = json.loads((self.root / "launch-arguments.json").read_text())
        self.assertIn("features.memories=false", launch)
        self.assertIn("project_doc_max_bytes=0", launch)
        self.assertIn("features.skip_host_skill_discovery=true", launch)

    def test_non_chatgpt_account_is_rejected_without_fallback(self):
        client = self.client(auth_mode="api")
        try:
            with self.assertRaisesRegex(CodexAppServerError, "API-key authentication"):
                client.run(cwd=self.root, mission="must not run")
        finally:
            client.close()
        methods = [json.loads(line).get("method") for line in self.record.read_text().splitlines()]
        self.assertNotIn("thread/start", methods)
        self.assertNotIn("turn/start", methods)

    def test_global_auth_mode_change_is_not_discarded_by_thread_filter(self):
        (self.root / "auth-changed").touch()
        client = self.client()
        try:
            with self.assertRaisesRegex(CodexAppServerError, "sign-in changed"):
                client.run(cwd=self.root, mission="must not accept an auth fallback")
        finally:
            client.close()

    def test_channel_requires_bare_model_id(self):
        with self.assertRaisesRegex(ValueError, "bare Codex model id"):
            resolve_channel_model("codex_app_server", "openai/gpt-6.1")


if __name__ == "__main__":
    unittest.main()
