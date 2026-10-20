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

"""Serial, bounded baseline/candidate campaigns against the Mac Agent runtime."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .mac_agent import Candidate, MacAgentClient, MacAgentError, RunEvidence

_MANIFEST_KEYS = {
    "schema_version",
    "campaign_id",
    "fixture_fingerprint",
    "baseline",
    "candidate",
    "development",
    "holdout",
}
_TASK_KEYS = {
    "id",
    "file",
    "required_phrases",
    "forbidden_phrases",
    "expected_metrics",
    "expected_artifacts",
}
CAMPAIGN_ADAPTER_VERSION = 2


def _is_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def validate_manifest(value: dict[str, Any]) -> None:
    unknown = set(value) - _MANIFEST_KEYS
    if unknown:
        raise ValueError(f"campaign manifest contains unknown fields: {', '.join(sorted(unknown))}")
    if value.get("schema_version") != 1:
        raise ValueError("campaign schema_version must be 1")
    if not isinstance(value.get("campaign_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,80}", value["campaign_id"]
    ):
        raise ValueError(
            "campaign_id must be 1 to 80 letters, digits, dots, underscores, or hyphens"
        )
    fixture = value.get("fixture_fingerprint")
    if not isinstance(fixture, str) or not fixture.strip() or len(fixture) > 200:
        raise ValueError(
            "fixture_fingerprint must identify the exact data bundle, ideally by SHA-256"
        )
    for key in ("baseline", "candidate"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"{key} must name a candidate JSON file")
    for partition in ("development", "holdout"):
        tasks = value.get(partition, [])
        if not isinstance(tasks, list) or len(tasks) > 50:
            raise ValueError(f"{partition} must contain no more than 50 tasks")
        ids = set()
        for task in tasks:
            if not isinstance(task, dict):
                raise ValueError(f"{partition} entries must be objects")
            extra = set(task) - _TASK_KEYS
            if extra:
                raise ValueError(f"task contains unknown fields: {', '.join(sorted(extra))}")
            task_id = task.get("id")
            if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", task_id):
                raise ValueError(
                    "task id must be 1 to 100 letters, digits, dots, underscores, or hyphens"
                )
            if task_id in ids:
                raise ValueError(f"duplicate task id in {partition}: {task_id}")
            ids.add(task_id)
            if not isinstance(task.get("file"), str) or not task["file"]:
                raise ValueError(f"task {task_id} must name a UTF-8 task file")
            for key in ("required_phrases", "forbidden_phrases", "expected_artifacts"):
                if key in task and (
                    not isinstance(task[key], list)
                    or any(not isinstance(x, str) or not x.strip() for x in task[key])
                ):
                    raise ValueError(f"task {task_id} {key} must be a list of strings")
            metrics = task.get("expected_metrics", {})
            if not isinstance(metrics, dict):
                raise ValueError(f"task {task_id} expected_metrics must be an object")
            for name, check in metrics.items():
                if (
                    not isinstance(name, str)
                    or not isinstance(check, dict)
                    or set(check) != {"value", "tolerance"}
                ):
                    raise ValueError(f"task {task_id} metric {name!r} needs value and tolerance")
                if (
                    not _is_number(check["value"])
                    or not _is_number(check["tolerance"])
                    or check["tolerance"] < 0
                ):
                    raise ValueError(
                        f"task {task_id} metric {name!r} must use numeric value/tolerance"
                    )
            if not any(
                task.get(field)
                for field in (
                    "required_phrases",
                    "forbidden_phrases",
                    "expected_metrics",
                    "expected_artifacts",
                )
            ):
                raise ValueError(
                    f"task {task_id} needs at least one independent deterministic check"
                )
    overlap = {task["id"] for task in value.get("development", [])} & {
        task["id"] for task in value.get("holdout", [])
    }
    if overlap:
        raise ValueError(
            f"development and holdout task IDs must be distinct: {', '.join(sorted(overlap))}"
        )


def _answer_metrics(answer: str) -> dict[str, float]:
    text = answer.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    metrics = parsed.get("metrics") if isinstance(parsed, dict) else None
    if not isinstance(metrics, dict):
        return {}
    return {
        key: float(value)
        for key, value in metrics.items()
        if isinstance(key, str) and _is_number(value)
    }


def score(task: dict[str, Any], evidence: RunEvidence) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    answer = evidence.answer
    for phrase in task.get("required_phrases", []):
        checks.append(
            {
                "check": "required_phrase",
                "target": phrase,
                "pass": phrase.casefold() in answer.casefold(),
            }
        )
    for phrase in task.get("forbidden_phrases", []):
        checks.append(
            {
                "check": "forbidden_phrase",
                "target": phrase,
                "pass": phrase.casefold() not in answer.casefold(),
            }
        )
    if task.get("expected_metrics"):
        actual = _answer_metrics(answer)
        for name, expected in task["expected_metrics"].items():
            got = actual.get(name)
            checks.append(
                {
                    "check": "numeric_tolerance",
                    "target": name,
                    "expected": expected["value"],
                    "actual": got,
                    "tolerance": expected["tolerance"],
                    "pass": got is not None
                    and abs(got - expected["value"]) <= expected["tolerance"],
                }
            )
    names = {item.get("name", "") for item in evidence.artifacts}
    for name in task.get("expected_artifacts", []):
        checks.append({"check": "artifact_reference", "target": name, "pass": name in names})
    return {"passed": all(item["pass"] for item in checks), "checks": checks}


def _evidence(evidence: RunEvidence, task: dict[str, Any]) -> dict[str, Any]:
    return {**evidence.as_dict(), "score": score(task, evidence)}


def run_campaign(
    manifest_path: Path,
    output_path: Path,
    *,
    include_holdout: bool = False,
    max_runs: int = 100,
    timeout: int = 900,
    client: MacAgentClient | None = None,
) -> dict[str, Any]:
    """Run serially and atomically checkpoint after each arm/task result."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("campaign manifest root must be an object")
    validate_manifest(manifest)
    tasks = list(manifest.get("development", []))
    if include_holdout:
        tasks.extend(manifest.get("holdout", []))
    if not tasks:
        raise ValueError("the selected campaign partition has no tasks")
    if not isinstance(max_runs, int) or not 2 <= max_runs <= 100:
        raise ValueError("max_runs must be between 2 and 100")
    if len(tasks) * 2 > max_runs:
        raise ValueError(
            f"selected tasks require {len(tasks) * 2} runs, exceeding --max-runs {max_runs}"
        )
    if not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    candidate_paths = {}
    for label in ("baseline", "candidate"):
        path = (manifest_path.parent / manifest[label]).resolve()
        if manifest_path.parent not in path.parents or not path.is_file():
            raise ValueError(f"{label} candidate file must exist under the manifest directory")
        candidate_paths[label] = path
    baseline = Candidate.load(json.loads(candidate_paths["baseline"].read_text(encoding="utf-8")))
    candidate = Candidate.load(json.loads(candidate_paths["candidate"].read_text(encoding="utf-8")))
    runtime = client or MacAgentClient()
    report: dict[str, Any] = {
        "schema_version": 1,
        "campaign_adapter_version": CAMPAIGN_ADAPTER_VERSION,
        "campaign_id": manifest["campaign_id"],
        "fixture_fingerprint": manifest["fixture_fingerprint"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "candidate_fingerprints": {
            "baseline": baseline.fingerprint,
            "candidate": candidate.fingerprint,
        },
        "partition": "development+holdout" if include_holdout else "development",
        "max_runs": max_runs,
        "permission_invariants": {
            "candidate_contract_allowlisted": True,
            "request_did_not_override_runtime_identity_scope_or_permissions": True,
        },
        "tasks": {},
    }
    for task in tasks:
        task_file = (manifest_path.parent / task["file"]).resolve()
        if manifest_path.parent not in task_file.parents or not task_file.is_file():
            raise ValueError(f"task file for {task['id']} must exist under the manifest directory")
        task_text = task_file.read_text(encoding="utf-8")
        task_digest = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
        entry: dict[str, Any] = {
            "task_id": task["id"],
            "partition": "holdout" if task in manifest.get("holdout", []) else "development",
            "task_sha256": task_digest,
        }
        for label, harness in (("baseline", baseline), ("candidate", candidate)):
            stable_material = "/".join(
                (
                    manifest["campaign_id"],
                    manifest["fixture_fingerprint"],
                    str(CAMPAIGN_ADAPTER_VERSION),
                    entry["partition"],
                    label,
                    task["id"],
                    "replica-1",
                    task_digest,
                    harness.fingerprint,
                )
            )
            stable_key = "campaign/" + str(uuid.uuid5(uuid.NAMESPACE_URL, stable_material))
            run_text = task_text
            if task.get("expected_metrics"):
                metric_names = ", ".join(sorted(task["expected_metrics"]))
                run_text += (
                    "\n\nFor verifiable outputs, return the final response as JSON with a numeric "
                    f"'metrics' object containing these exact keys: {metric_names}. You may include "
                    "other explanatory fields, but do not put the JSON inside a code fence."
                )
            try:
                evidence = runtime.run(
                    task=run_text, candidate=harness, stable_run_key=stable_key, timeout=timeout
                )
                entry[label] = _evidence(evidence, task)
            except MacAgentError as exc:
                entry[label] = {"error": str(exc), "score": {"passed": False, "checks": []}}
            report["tasks"][task["id"]] = entry
            _summarize(report)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            data = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            fd, temporary = tempfile.mkstemp(prefix=".campaign-", dir=output_path.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, output_path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return report


def _summarize(report: dict[str, Any]) -> None:
    partitions = {}
    for name in ("development", "holdout"):
        rows = [entry for entry in report["tasks"].values() if entry["partition"] == name]
        if not rows:
            continue
        arms = {}
        for arm in ("baseline", "candidate"):
            complete = [
                row[arm]
                for row in rows
                if "error" not in row.get(arm, {}) and "score" in row.get(arm, {})
            ]
            passed = sum(bool(row["score"]["passed"]) for row in complete)
            arms[arm] = {
                "tasks": len(rows),
                "completed": len(complete),
                "passed": passed,
                "pass_rate": passed / len(complete) if complete else None,
            }
        partitions[name] = arms
    report["summary"] = partitions
    holdout = partitions.get("holdout")
    if holdout and all(
        holdout[arm]["completed"] == holdout[arm]["tasks"] for arm in ("baseline", "candidate")
    ):
        before, after = holdout["baseline"]["passed"], holdout["candidate"]["passed"]
        report["holdout_outcome"] = (
            "candidate_better"
            if after > before
            else "baseline_better"
            if after < before
            else "equal"
        )
        report["recommendation"] = (
            "review_candidate_for_limited_adoption"
            if after > before and re.fullmatch(r"[a-f0-9]{64}", report["fixture_fingerprint"])
            else "do_not_adopt_unpinned_fixture"
            if after > before
            else "retain_baseline"
            if after < before
            else "no_evidence_for_change"
        )
    else:
        report["holdout_outcome"] = "not_run_or_incomplete"
        report["recommendation"] = "insufficient_holdout_evidence"
