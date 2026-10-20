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

"""Small, subscription-only Codex app-server client used by Harness² model stages."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class CodexAppServerError(RuntimeError):
    """Codex did not complete a ChatGPT-authenticated app-server turn."""


_EOF = object()


class CodexAppServerClient:
    """Run one isolated turn through the user's existing signed-in Codex CLI.

    Authentication remains inside Codex's configured home. The client never reads, copies,
    logs, or exports auth files or bearer tokens. Every turn verifies ChatGPT account mode,
    disables provider fallback, uses a workspace-write sandbox with network access disabled,
    and rejects app-server requests that this noninteractive harness cannot authorize.
    """

    def __init__(
        self,
        *,
        model: str,
        effort: str = "high",
        executable: str | None = None,
        codex_home: str | None = None,
        timeout: int = 3600,
    ):
        self.model = model
        self.effort = effort
        self.executable = executable or os.environ.get("HARNESS2_CODEX_EXECUTABLE") or shutil.which("codex")
        self.codex_home = codex_home or os.environ.get("HARNESS2_CODEX_HOME") or os.environ.get("CODEX_HOME")
        self.timeout = max(1, int(timeout))
        self.proc: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[Any] = queue.Queue()
        self._next_id = 0
        self._mcp_servers: dict[str, Any] = {}

    def _env(self) -> dict[str, str]:
        # Keep only the environment needed to locate Codex and its existing login. In
        # particular, do not pass cloud/database credentials into the model tool process.
        env = {
            "HOME": os.environ.get("HOME", str(Path.home())),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        for name in ("CODEX_CA_CERTIFICATE", "SSL_CERT_FILE"):
            if os.environ.get(name):
                env[name] = os.environ[name]
        if self.codex_home:
            env["CODEX_HOME"] = str(Path(self.codex_home).expanduser())
        return env

    def start(self, *, cwd: Path) -> None:
        if not self.executable:
            raise CodexAppServerError(
                "Codex CLI was not found; install it and sign in with ChatGPT, or set "
                "HARNESS2_CODEX_EXECUTABLE."
            )
        self.proc = subprocess.Popen(
            [
                self.executable,
                "app-server",
                "--listen",
                "stdio://",
                "-c",
                'model_provider="openai"',
                "-c",
                'web_search="disabled"',
                "-c",
                "mcp_servers={}",
                "-c",
                'history.persistence="none"',
                "-c",
                "project_doc_max_bytes=0",
                "-c",
                "notify=[]",
                "-c",
                "include_environment_context=false",
                "-c",
                "include_apps_instructions=false",
                "-c",
                "features.skip_host_skill_discovery=true",
                "-c",
                "features.plugins=false",
                "-c",
                "features.apps=false",
                "-c",
                "features.multi_agent=false",
                "-c",
                "features.browser_use=false",
                "-c",
                "features.computer_use=false",
                "-c",
                "features.image_generation=false",
            ],
            cwd=cwd,
            env=self._env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, name="harness2-codex-rpc", daemon=True).start()
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "harness2",
                    "title": "Harness²",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self._write({"method": "initialized"})
        account = self._request("account/read", {"refreshToken": False})
        if account.get("account", {}).get("type") != "chatgpt":
            raise CodexAppServerError(
                "Codex is not signed in with ChatGPT. Sign in through Codex first; API-key "
                "authentication and billing fallbacks are disabled."
            )
        models = self._request("model/list", {"limit": 100, "cursor": None})
        available = {row.get("model") for row in models.get("data", []) if isinstance(row, dict)}
        if self.model not in available:
            raise CodexAppServerError(
                f"Codex model {self.model!r} is not listed for this ChatGPT sign-in."
            )
        config = self._request("config/read", {"includeLayers": False}).get("config", {})
        servers = config.get("mcp_servers", {})
        if isinstance(servers, dict):
            self._mcp_servers = {name: {"enabled": False} for name in servers}

    def run(self, *, cwd: Path, mission: str, system: str = "") -> tuple[str, dict[str, int]]:
        self.start(cwd=cwd)
        started = self._request(
            "thread/start",
            {
                "model": self.model,
                "modelProvider": "openai",
                "allowProviderModelFallback": False,
                "ephemeral": True,
                "cwd": str(cwd.resolve()),
                "runtimeWorkspaceRoots": [str(cwd.resolve())],
                "approvalPolicy": "never",
                "approvalsReviewer": "user",
                "sandbox": "workspace-write",
                "environments": [],
                "baseInstructions": system,
                "config": {
                    "web_search": "disabled",
                    "mcp_servers": self._mcp_servers,
                    "features": {
                        "skip_host_skill_discovery": True,
                        "plugins": False,
                        "apps": False,
                        "multi_agent": False,
                        "browser_use": False,
                        "computer_use": False,
                        "image_generation": False,
                    },
                    "history": {"persistence": "none"},
                    "project_doc_max_bytes": 0,
                    "notify": [],
                    "include_environment_context": False,
                    "include_apps_instructions": False,
                },
            },
        )
        thread_id = started.get("thread", {}).get("id")
        if not thread_id or started.get("model") != self.model or started.get("modelProvider") != "openai":
            raise CodexAppServerError("Codex rejected the requested model or thread configuration.")

        turn_started = self._request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": mission}],
                "effort": self.effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": [str(cwd.resolve())], "networkAccess": False},
                "environments": [],
            },
        )
        turn_id = turn_started.get("turn", {}).get("id")
        if not turn_id:
            raise CodexAppServerError("Codex app-server did not start the requested turn.")

        deltas: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        deadline = time.monotonic() + self.timeout
        while True:
            message = self._receive(deadline)
            if message is _EOF:
                raise CodexAppServerError("Codex app-server exited before completing the turn.")
            method = message.get("method")
            params = message.get("params", {})
            if "id" in message and method:
                self._reject_request(message["id"])
                continue
            if params.get("threadId") != thread_id:
                continue
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if isinstance(delta, str):
                    deltas.append(delta)
            elif method == "thread/tokenUsage/updated":
                total = params.get("tokenUsage", {}).get("total", {})
                usage["input_tokens"] = int(total.get("inputTokens") or 0)
                usage["output_tokens"] = int(total.get("outputTokens") or 0)
            elif method == "account/updated":
                account = params.get("account", {})
                auth_mode = account.get("type") if isinstance(account, dict) else None
                auth_mode = auth_mode or params.get("authMode")
                if auth_mode and auth_mode != "chatgpt":
                    raise CodexAppServerError(
                        "Codex sign-in changed during the turn; no API fallback was used."
                    )
            elif method == "turn/completed" and params.get("turn", {}).get("id") == turn_id:
                status = params.get("turn", {}).get("status")
                if status != "completed":
                    raise CodexAppServerError(
                        f"Codex turn ended with status {status or 'unknown'}; no retry was attempted."
                    )
                text = "".join(deltas).strip()
                if not text:
                    raise CodexAppServerError("Codex completed without a final text response.")
                return text, usage

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + min(self.timeout, 300)
        while True:
            message = self._receive(deadline)
            if message is _EOF:
                raise CodexAppServerError(f"Codex exited before replying to {method}.")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                detail = message.get("error", {}).get("message", "request rejected")
                raise CodexAppServerError(f"Codex app-server {method} failed: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise CodexAppServerError(f"Codex app-server {method} returned an invalid response.")
            return result

    def _write(self, message: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise CodexAppServerError("Codex app-server is not running.")
        self.proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
                if isinstance(message, dict):
                    self.messages.put(message)
            except json.JSONDecodeError:
                self.messages.put({"_protocol_error": True})
        self.messages.put(_EOF)

    def _receive(self, deadline: float) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexAppServerError(f"Codex app-server timed out after {self.timeout}s.")
        try:
            message = self.messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise CodexAppServerError(f"Codex app-server timed out after {self.timeout}s.") from exc
        if isinstance(message, dict) and message.get("_protocol_error"):
            raise CodexAppServerError("Codex app-server returned malformed JSON.")
        return message

    def _reject_request(self, request_id: Any) -> None:
        self._write(
            {
                "id": request_id,
                "error": {"code": -32601, "message": "Harness² does not authorize this request."},
            }
        )

    def close(self) -> None:
        if not self.proc:
            return
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc = None
