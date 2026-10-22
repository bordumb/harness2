"""Strict native-policy configuration normalization shared with Mac Agent schema 3.

These fields select compiled Swift policies. They grant no tools or source access.
"""

from __future__ import annotations

import re
from typing import Any


def normalize_policies(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "results",
        "context",
        "discovery",
        "observations",
    }:
        raise ValueError("policies must contain only supported native policy fields")
    specifications = {
        "results": (
            "retained-results",
            {"bounded_preview", "stop"},
            {
                "spill_bytes": (2048, 1_048_576),
                "preview_bytes": (2048, 60_000),
                "page_bytes": (2048, 32_768),
                "page_rows": (1, 200),
                "retained_bytes_per_run": (4096, 67_108_864),
                "retention_seconds": (60, 31_536_000),
            },
        ),
        "context": (
            "deterministic-context",
            {"stop"},
            {
                "request_bytes": (8192, 240_000),
                "recent_groups": (1, 100),
            },
        ),
        "discovery": (
            "deferred-tools",
            {"stop"},
            {
                "catalog_bytes": (2048, 32_000),
                "maximum_loaded_tools": (1, 64),
                "maximum_transitions": (1, 4),
            },
        ),
    }
    normalized: dict[str, Any] = {}
    for family, (policy_id, failure_modes, bounds) in specifications.items():
        entry = value.get(family)
        if entry is None:
            normalized[family] = None
            continue
        fields = {"id", "version", "failure_mode", *bounds}
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ValueError("Use all and only the declared native policy fields")
        if (
            entry["id"] != policy_id
            or type(entry["version"]) is not int
            or entry["version"] != 1
            or not isinstance(entry["failure_mode"], str)
            or entry["failure_mode"] not in failure_modes
        ):
            raise ValueError("Unsupported native policy identity, version or failure mode")
        for name, (minimum, maximum) in bounds.items():
            item = entry[name]
            if type(item) is not int or not minimum <= item <= maximum:
                raise ValueError("Native policy limits must be bounded whole numbers: " + name)
        if (
            family == "results"
            and not entry["preview_bytes"]
            <= entry["spill_bytes"]
            <= entry["retained_bytes_per_run"]
        ):
            raise ValueError("Preview must fit spill threshold and retained quota")
        normalized[family] = dict(entry)
    observations = normalize_observations(value.get("observations"))
    # Keep existing schema-3 canonical fingerprints unchanged when omitted.
    if observations:
        normalized["observations"] = observations
    return normalized


def normalize_observations(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("Use at most eight compiled outcome observers")
    normalized = []
    seen = set()

    def valid_id(item):
        return isinstance(item, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", item))

    for entry in value:
        if not isinstance(entry, dict) or set(entry) - {"id", "version", "dependencies"}:
            raise ValueError("Use only declared observer identity fields")
        name = entry.get("id")
        if (
            not valid_id(name)
            or name in seen
            or type(entry.get("version")) is not int
            or entry["version"] != 1
        ):
            raise ValueError("Unsupported or duplicate outcome observer identity")
        dependencies = entry.get("dependencies")
        if dependencies is None:
            dependencies = []
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > 16
            or any(not valid_id(item) for item in dependencies)
            or len(set(dependencies)) != len(dependencies)
        ):
            raise ValueError("Use unique bounded observer dependency identities")
        seen.add(name)
        normalized.append({"id": name, "version": 1, "dependencies": sorted(dependencies)})
    return normalized
