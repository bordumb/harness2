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

"""Narrow, durable client for Mac Agent's authenticated shared-runtime API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class MacAgentError(RuntimeError):
    """The Mac Agent runtime rejected or could not resolve an evaluation run."""


class MacAgentResponseLimitExceeded(MacAgentError):
    """Observation exceeded the transport cap; this does not classify the native run."""


class MacAgentObservationPending(MacAgentError):
    """An accepted run is still owned by its original host, not a failed task."""

    def __init__(self, run_id: str, key: str, message: str):
        super().__init__(message)
        self.run_id = run_id
        self.idempotency_key = key


_MAX_BODY = 2_000_000
_SECRET = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*|sk-[A-Za-z0-9_-]{12,}")


def _redact(value: str) -> str:
    return _SECRET.sub(
        lambda match: match.group(1) + "[REDACTED]" if match.group(1) else "[REDACTED]", value
    )


@dataclass(frozen=True)
class Candidate:
    """Versioned host configuration, never text appended to an evaluation task."""

    id: str
    prompt_guidance: str = ""
    tool_guidance: str = ""
    skills: tuple[str, ...] = ()
    retrieval_settings: dict[str, int] | None = None
    schema_version: int = 2
    policies: dict[str, Any] | None = None

    @classmethod
    def load(cls, value: dict[str, Any]) -> Candidate:
        if not isinstance(value, dict):
            raise ValueError("candidate JSON must have an object at the top level")
        allowed = {
            "schema_version",
            "id",
            "prompt_guidance",
            "tool_guidance",
            "skills",
            "retrieval_settings",
            "policies",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                f"candidate contains non-allowlisted fields: {', '.join(sorted(unknown))}"
            )
        if type(value.get("schema_version")) is not int or value["schema_version"] not in (2, 3):
            raise ValueError(
                "candidate schema_version must be 2 or 3; task-augmentation schema 1 is unsupported"
            )
        candidate_id = value.get("id")
        if not isinstance(candidate_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", candidate_id
        ):
            raise ValueError(
                "candidate id must use 1 to 100 ASCII letters, digits, underscores or hyphens"
            )
        prompt = value.get("prompt_guidance", "")
        tools = value.get("tool_guidance", "")
        skills = value.get("skills", [])
        for field, text in (("prompt_guidance", prompt), ("tool_guidance", tools)):
            if not isinstance(text, str) or len(text.encode("utf-8")) > 8_000:
                raise ValueError(f"{field} must be text no longer than 8,000 UTF-8 bytes")
        if (
            not isinstance(skills, list)
            or len(skills) > 32
            or any(not isinstance(item, str) for item in skills)
        ):
            raise ValueError("skills must be a list of at most 32 text entries")
        if sum(len(item.encode("utf-8")) for item in skills) > 8_000:
            raise ValueError("combined skill guidance must not exceed 8,000 UTF-8 bytes")
        retrieval = value.get("retrieval_settings", {})
        bounds = {"context_byte_budget": 32_000, "maximum_notes": 16, "maximum_recipe_hints": 8}
        if not isinstance(retrieval, dict) or set(retrieval) - set(bounds):
            raise ValueError("retrieval_settings contains unsupported fields")
        if any(
            type(item) is not int or not 0 <= item <= bounds[key] for key, item in retrieval.items()
        ):
            raise ValueError("retrieval_settings values must be bounded whole numbers")
        if value["schema_version"] == 2 and "policies" in value:
            raise ValueError("Native policies require schema 3")
        from .native_policy import normalize_policies

        policies = (
            normalize_policies(value.get("policies", {})) if value["schema_version"] == 3 else None
        )
        return cls(
            candidate_id,
            prompt,
            tools,
            tuple(skills),
            dict(retrieval),
            value["schema_version"],
            policies,
        )

    def as_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "id": self.id,
            "prompt_guidance": self.prompt_guidance,
            "tool_guidance": self.tool_guidance,
            "skills": list(self.skills),
            "retrieval_settings": {
                **{"context_byte_budget": 16_000, "maximum_notes": 8, "maximum_recipe_hints": 4},
                **(self.retrieval_settings or {}),
            },
        }
        if self.schema_version == 3:
            from .native_policy import normalize_policies

            result["policies"] = normalize_policies(
                self.policies if self.policies is not None else {}
            )
        return result

    @property
    def fingerprint(self) -> str:
        # Mirrors RuntimeHarnessConfiguration's canonical compact UTF-8 encoding.
        payload = json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunEvidence:
    run_id: str
    state: str
    answer: str
    created_at: str | None
    updated_at: str | None
    elapsed_seconds: float
    event_count: int | None
    candidate_fingerprint: str
    idempotency_key: str
    artifacts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "answer": _redact(self.answer),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "event_count": self.event_count,
            "candidate_fingerprint": self.candidate_fingerprint,
            "idempotency_key": self.idempotency_key,
            "artifacts": list(self.artifacts),
            "usage": self.usage,
        }


class MacAgentClient:
    """Uses bearer auth without persisting it, and never retries an ambiguous POST."""

    def __init__(
        self,
        endpoint: str | None = None,
        token: str | None = None,
        *,
        poll_interval: float = 0.5,
        request_timeout: float = 20,
        targets: dict[str, dict[str, str]] | None = None,
    ):
        self.targets = targets
        if self.targets is None:
            target_path = os.environ.get("HARNESS2_MAC_AGENT_TARGETS")
            if target_path:
                from pathlib import Path

                self.targets = json.loads(Path(target_path).read_text(encoding="utf-8"))
        if self.targets is not None:
            if not isinstance(self.targets, dict):
                raise ValueError("candidate targets must be a nonempty fingerprint-to-host map")
            for fingerprint, target in self.targets.items():
                if not isinstance(fingerprint, str) or not re.fullmatch(
                    r"[a-f0-9]{64}", fingerprint
                ):
                    raise ValueError("candidate target keys must be SHA-256 fingerprints")
                if not isinstance(target, dict) or set(target) != {"endpoint", "token_environment"}:
                    raise ValueError(
                        "candidate targets require only endpoint and token_environment"
                    )
                if any(not isinstance(value, str) or not value for value in target.values()):
                    raise ValueError("candidate target fields must be nonempty strings")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target["token_environment"]):
                    raise ValueError("target token_environment must name an environment variable")
        self.endpoint = (endpoint or os.environ.get("HARNESS2_MAC_AGENT_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get("HARNESS2_MAC_AGENT_TOKEN", "")
        self.poll_interval = max(0.05, poll_interval)
        self.request_timeout = max(1, request_timeout)
        parsed = urlsplit(self.endpoint)
        if self.targets:
            return  # Each selected host is validated again before any network request.
        if not self.endpoint or parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ValueError(
                "Set HARNESS2_MAC_AGENT_URL to an HTTPS origin, or localhost HTTP for a lab"
            )
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "HARNESS2_MAC_AGENT_URL must be an origin without credentials, path, or query"
            )
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("HTTP is allowed only for a loopback Mac Agent lab server")
        if not self.token:
            raise ValueError(
                "Set HARNESS2_MAC_AGENT_TOKEN; it is read from the environment and never saved"
            )

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        key: str | None = None,
    ):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":")).encode()
        if key:
            headers["Idempotency-Key"] = key
        request = Request(self.endpoint + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                raw = response.read(_MAX_BODY + 1)
        except HTTPError as exc:
            # Never include headers or echoed request bodies in diagnostics.
            raise MacAgentError(
                f"Mac Agent API returned HTTP {exc.code} for {method} {path}"
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise MacAgentError(
                f"Mac Agent API transport error ({type(exc).__name__}) for {method} {path}"
            ) from None
        if len(raw) > _MAX_BODY:
            raise MacAgentResponseLimitExceeded(
                "Mac Agent API response exceeded the 2 MB evaluation limit"
            )
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MacAgentError("Mac Agent API returned invalid JSON") from None

    @staticmethod
    def idempotency_key(stable_run_key: str) -> str:
        if not stable_run_key or len(stable_run_key) > 200:
            raise ValueError("stable_run_key must contain 1 to 200 characters")
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "harness2:" + stable_run_key))

    def cancel(self, run_id: str) -> dict[str, Any]:
        """Request cancellation through the runtime's durable cancellation route."""
        if not re.fullmatch(r"[A-Fa-f0-9-]{36}", run_id):
            raise ValueError("run_id must be a UUID returned by Mac Agent")
        result = self._request(f"/v1/runs/{run_id}/cancel", method="POST", body={})
        if not isinstance(result, dict):
            raise MacAgentError("Mac Agent returned an invalid cancellation receipt")
        return {key: result[key] for key in ("id", "state", "updatedAt") if key in result}

    @staticmethod
    def _verify_binding(record: Any, candidate: Candidate) -> None:
        request = record.get("request") if isinstance(record, dict) else None
        if (
            not isinstance(request, dict)
            or request.get("runtime_harness_fingerprint") != candidate.fingerprint
            or request.get("runtime_harness") != candidate.as_dict()
        ):
            raise MacAgentError(
                "Run evidence does not match the actual expected runtime harness; retain the submission key"
            )

    def run(
        self,
        *,
        task: str,
        candidate: Candidate,
        stable_run_key: str,
        timeout: float = 900,
    ) -> RunEvidence:
        if self.targets:
            target = self.targets.get(candidate.fingerprint)
            if target is None:
                raise ValueError("No explicitly configured host for this candidate fingerprint")
            runtime = MacAgentClient(
                target["endpoint"],
                os.environ.get(target["token_environment"], ""),
                poll_interval=self.poll_interval,
                request_timeout=self.request_timeout,
                targets={},
            )
            return runtime.run(
                task=task, candidate=candidate, stable_run_key=stable_run_key, timeout=timeout
            )
        if not task.strip() or len(task.encode()) > 300_000:
            raise ValueError("task must be nonempty and at most 300 KB")
        key = self.idempotency_key(stable_run_key)
        # Reject older/nonmatching hosts before giving them a task to execute.
        configured = self._request("/v1/runtime/harness")
        if (
            not isinstance(configured, dict)
            or configured.get("schema_version") != candidate.schema_version
            or configured.get("fingerprint") != candidate.fingerprint
        ):
            raise MacAgentError(
                "The selected host does not expose this versioned runtime candidate"
            )
        payload = {
            "text": task,
            "user_initiated": True,
            "expected_harness_fingerprint": candidate.fingerprint,
        }
        started = time.monotonic()
        try:
            record = self._request("/v1/runs", method="POST", body=payload, key=key)
        except MacAgentError:
            # An accepted POST can lose its response. Resolve the same durable key;
            # never submit it again with a new key or repeat uncertain effects.
            try:
                record = self._request("/v1/submissions/" + key)
            except MacAgentError as lookup_error:
                raise MacAgentError(
                    "submission outcome is uncertain; preserve idempotency key "
                    + key
                    + " and resolve it with GET /v1/submissions before retrying"
                ) from lookup_error
            if not isinstance(record, dict) or not record.get("id"):
                raise MacAgentError(
                    "submission outcome is uncertain; no record was found yet. Preserve idempotency key "
                    + key
                )
        return self._observe(record, candidate, key, started, timeout)

    def resume(
        self, *, candidate: Candidate, stable_run_key: str, timeout: float = 900
    ) -> RunEvidence:
        """Observe the exact original submission; this method never issues POST."""
        if self.targets:
            target = self.targets.get(candidate.fingerprint)
            if target is None:
                raise ValueError("No explicitly configured host for this candidate fingerprint")
            return MacAgentClient(
                target["endpoint"],
                os.environ.get(target["token_environment"], ""),
                poll_interval=self.poll_interval,
                request_timeout=self.request_timeout,
                targets={},
            ).resume(candidate=candidate, stable_run_key=stable_run_key, timeout=timeout)
        key = self.idempotency_key(stable_run_key)
        started = time.monotonic()
        record = self._request("/v1/submissions/" + key)
        if not isinstance(record, dict) or not record.get("id"):
            raise MacAgentError(
                "The original durable submission is unavailable; do not dispatch a replacement"
            )
        return self._observe(record, candidate, key, started, timeout)

    def _observe(self, record, candidate, key, started, timeout):
        self._verify_binding(record, candidate)
        run_id = str(record.get("id") or "")
        if not run_id:
            raise MacAgentError("Mac Agent accepted no identifiable durable run")
        deadline = started + min(3600, max(1, timeout))
        try:
            while True:
                state = str(record.get("state", "unknown"))
                if state in {"succeeded", "failed", "cancelled", "interrupted", "requiresInput"}:
                    break
                if time.monotonic() >= deadline:
                    raise MacAgentObservationPending(
                        run_id,
                        key,
                        f"run {run_id} remains {state}; it was left durable and was not resubmitted or cancelled. "
                        f"Resume with idempotency key {key}.",
                    )
                # Grading uses the durable record, not repeated full-state event
                # snapshots. Server event pages can legitimately exceed this
                # adapter's bounded record budget; downloading unused pages can
                # abort otherwise healthy data work.
                try:
                    record = self._request(f"/v1/runs/{run_id}")
                except MacAgentError as error:
                    raise MacAgentObservationPending(run_id, key, str(error)) from error
                if not isinstance(record, dict):
                    raise MacAgentObservationPending(
                        run_id, key, f"Mac Agent returned an invalid record for run {run_id}"
                    )
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            try:
                self.cancel(run_id)
            except MacAgentError:
                pass
            raise
        self._verify_binding(record, candidate)
        conversation = (
            record.get("conversation") if isinstance(record.get("conversation"), dict) else {}
        )
        messages = conversation.get("messages", [])
        answer = "\n\n".join(
            str(message.get("text", ""))
            for message in messages
            if isinstance(message, dict)
            and message.get("role") == "assistant"
            and message.get("isFinal") is True
        )
        if state != "succeeded":
            raise MacAgentError(
                f"Mac Agent run {run_id} ended in state {state}; inspect its retained run in the lab"
            )
        if not answer:
            raise MacAgentError(
                f"Mac Agent run {run_id} succeeded without a final assistant message"
            )
        invocations = conversation.get("invocations", [])
        artifacts = []
        if isinstance(invocations, list):
            for invocation in invocations:
                result = invocation.get("result") if isinstance(invocation, dict) else None
                refs = result.get("artifacts", []) if isinstance(result, dict) else []
                if not isinstance(refs, list):
                    continue
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    summary = {
                        key: _redact(str(ref[key])[:256]) if isinstance(ref[key], str) else ref[key]
                        for key in ("id", "name", "mediaType", "digest", "byteCount")
                        if isinstance(ref.get(key), (str, int))
                    }
                    if summary:
                        artifacts.append(summary)
                    if len(artifacts) >= 100:
                        break
                if len(artifacts) >= 100:
                    break
        raw_usage = record.get("usage")
        usage = None
        if isinstance(raw_usage, dict):
            usage = {
                name: int(raw_usage[name])
                for name in ("input_tokens", "output_tokens")
                if isinstance(raw_usage.get(name), int)
            }
        return RunEvidence(
            run_id=run_id,
            state=state,
            answer=_redact(answer[:100_000]),
            created_at=record.get("createdAt"),
            updated_at=record.get("updatedAt"),
            elapsed_seconds=time.monotonic() - started,
            event_count=None,
            candidate_fingerprint=candidate.fingerprint,
            idempotency_key=key,
            artifacts=tuple(artifacts),
            usage=usage,
        )
