"""Explicit source-code proposals, separate from runtime instruction candidates.

This prepares a bounded evidence workspace for the existing Proposer. It never
applies code, runs builds, changes permissions or promotes a candidate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..core.proposer import Proposer


def _path(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or not path.parts or any(part in ("..", ".git") for part in path.parts):
        raise ValueError("Use explicit repository-relative source paths")
    if path.parts[0] not in {"Sources", "Tests", "Server"} or path.suffix not in {".swift", ".py"}:
        raise ValueError("Only allowlisted product source/tests can enter a code candidate")
    return path.as_posix()


def propose_product(*, proposer: Proposer, repository: Path, context: Path,
                    source_paths: list[str], trajectory: str, task: str, mission: str,
                    label: str = "product-candidate") -> dict:
    repository, context = repository.resolve(), context.resolve()
    paths = [_path(name) for name in source_paths]
    if not paths or len(paths) > 20 or len(set(paths)) != len(paths):
        raise ValueError("Supply one to twenty distinct source paths")
    context.mkdir(parents=True, exist_ok=False)
    originals = {}
    for name in paths:
        source = repository / name
        if source.is_symlink() or not source.resolve().is_relative_to(repository):
            raise ValueError("Source path escapes repository")
        body = source.read_text() if source.exists() else ""
        originals[name] = hashlib.sha256(body.encode()).hexdigest()
        target = context / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    if sum(path.stat().st_size for path in (context / "source").rglob("*") if path.is_file()) > 1_000_000:
        raise ValueError("Source proposal exceeds one MB")
    (context / "observed-trajectory.txt").write_text(trajectory)
    (context / "task.txt").write_text(task)
    reply = proposer.call(
        mission,
        context,
        label,
        system=("Improve general production tooling from the observed execution. "
                "Edit only the supplied files under context/source. Empty files are explicitly allowed additions. "
                "Preserve authentication, permission enforcement, source isolation, receipts and historical compatibility. "
                "Do not put task answers, task-specific branches or reference SQL into product code. "
                "No benchmark graders or expected answers are available. Add focused regression tests when applicable. "
                "You cannot build or run the app here. Explain the defect, change and remaining validation."),
        harvest="context/source",
    )
    if reply.workspace is None:
        raise ValueError("Proposer returned no source tree")
    changed = {}
    for path in reply.workspace.rglob("*"):
        if path.is_symlink():
            raise ValueError("Code proposals cannot contain symlinks")
        if not path.is_file():
            continue
        name = path.relative_to(reply.workspace).as_posix()
        if name not in paths or path.stat().st_size > 524_288:
            raise ValueError("Proposer changed an unsupported source path")
        body = path.read_text()
        if hashlib.sha256(body.encode()).hexdigest() != originals[name]:
            changed[name] = body
    manifest = {"kind": "product-source", "original_sha256": originals,
                "changed_sha256": {name: hashlib.sha256(body.encode()).hexdigest() for name, body in changed.items()},
                "workspace": str(reply.workspace), "notes": reply.text, "usage": reply.usage,
                "wall_seconds": reply.wall_s, "applied": False}
    (context / "proposal.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
