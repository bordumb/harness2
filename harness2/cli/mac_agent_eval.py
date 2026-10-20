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

"""Run one bounded task against the configured Mac Agent shared runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from ..integrations.mac_agent import Candidate, MacAgentClient, MacAgentError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path, help="Versioned candidate contract JSON")
    parser.add_argument("--task", required=True, type=Path, help="One synthetic evaluation task as UTF-8 text")
    parser.add_argument("--stable-run-key", required=True, help="Stable key for safe lookup after an uncertain submit")
    parser.add_argument("--output", required=True, type=Path, help="Path for bounded redacted evidence JSON")
    parser.add_argument("--timeout", type=float, default=900, help="Maximum poll time in seconds (default: 900)")
    args = parser.parse_args(argv)
    try:
        candidate = Candidate.load(json.loads(args.candidate.read_text(encoding="utf-8")))
        task = args.task.read_text(encoding="utf-8")
        result = MacAgentClient().run(
            task=task,
            candidate=candidate,
            stable_run_key=args.stable_run_key,
            timeout=args.timeout,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(result.as_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".mac-agent-eval-", dir=args.output.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, args.output)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print(f"Saved bounded run evidence to {args.output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, MacAgentError) as exc:
        print(f"harness2-mac-agent-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
