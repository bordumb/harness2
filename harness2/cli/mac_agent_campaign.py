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

"""Run a small, serial baseline/candidate campaign on Mac Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..integrations.campaign import run_campaign
from ..integrations.mac_agent import MacAgentError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Campaign manifest JSON")
    parser.add_argument("--output", type=Path, required=True, help="Aggregate report JSON path")
    parser.add_argument("--max-runs", type=int, default=20, help="Hard cap on runtime runs (default: 20, max: 100)")
    parser.add_argument("--timeout", type=int, default=900, help="Maximum seconds per run (default: 900, max: 3600)")
    parser.add_argument(
        "--include-holdout",
        action="store_true",
        help="Run the separately declared holdout set once; do this after development is frozen",
    )
    args = parser.parse_args(argv)
    try:
        report = run_campaign(
            args.manifest,
            args.output,
            include_holdout=args.include_holdout,
            max_runs=args.max_runs,
            timeout=args.timeout,
        )
        print(f"Wrote {args.output}; partitions: {', '.join(report.get('summary', {}))}")
        if report.get("holdout_outcome"):
            print(f"Holdout comparison: {report['holdout_outcome']}")
        return 0
    except (OSError, ValueError, MacAgentError) as exc:
        print(f"harness2-mac-agent-campaign: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
