# Setup guide

Start with the [quick start](../README.md#install). This guide covers benchmark
dependencies, model credentials, and the optional Codex executor. For individual
benchmarks, see the [benchmark guides](BENCHMARKS.md).

## Requirements

Use Linux and Python 3.12 for benchmark runs; the Python package also supports
3.13. On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git curl unzip ca-certificates pandoc poppler-utils
```

Pandoc and Poppler are needed by LAB. Also install:

- [Node.js](https://nodejs.org/en/download) 20 or newer.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install).
- [Docker Engine](https://docs.docker.com/engine/install/) for WorkBuddy-Bench,
  with permission to run `docker info`.

Benchmark setup installs its own pinned Bun runtime under `dependencies/`.
Keep the main Harness² environment active when running the commands below.

## Models and credentials

Copy `.env.example` to `.env` if you have not already done so. Set your Vertex AI
project and model IDs, then authenticate:

```bash
gcloud auth application-default login
```

Shell environment variables take precedence over `.env`.
`GOOGLE_CLOUD_PROJECT` identifies your project; `GOOGLE_CLOUD_LOCATION` defaults
to `global`. Your account must have access to each configured model.

| Setting | Meaning |
|---|---|
| `HARNESS2_SOLVER_MODEL` | Executor model in OpenCode's `provider/model` format |
| `HARNESS2_IMPROVER_MODEL` | Improver model in the same format; defaults to the executor |
| `HARNESS2_JUDGE_MODEL` | Bare judge model ID; the adapter supplies the Vertex prefix |
| `HARNESS2_RUNS_DIR` | Output root; defaults to `runs/` |

The provided configuration uses Vertex Gemini executors and judges, and supports
either Vertex Claude or Gemini as the improver. LAB also supports the upstream
judge's direct providers when their credentials are configured. For WorkBuddy,
setup generates the Gemini solver and judge routes from these settings; rerun
setup after changing either model.

### Signed-in Codex for Harness²'s improver and selector

The existing benchmark executor and judge routes remain configured separately.
To route Harness² proposal/selection model calls through the Codex CLI already
signed in with ChatGPT, set:

```text
HARNESS2_PROPOSER_CHANNEL=codex_app_server
HARNESS2_PROPOSER_MODEL=<bare model ID shown by Codex>
```

`HARNESS2_CODEX_EXECUTABLE` and `HARNESS2_CODEX_HOME` are optional when the
signed-in `codex` binary and home are already discoverable. The app-server
adapter verifies `account/read` reports a ChatGPT account, checks that the
model is available, pins the OpenAI provider, disables provider fallback,
network access, MCP, plugins and integrations, and rejects unapproved RPC
requests. It records reported token usage without inventing a subscription
cost. It never reads or exports auth files or tokens.

This channel currently covers Harness² proposer/selector calls. It does not
replace the benchmark-specific executor or the benchmark's external judge. Use
the separate Mac Agent lab adapter below to exercise Mac Agent's actual shared
runtime. No API-key fallback is involved in either signed-in path.

### Mac Agent shared-runtime evaluation

For one bounded synthetic task against a running Mac Agent server, define the
server origin and the lab identity's bearer token in the process environment:

```text
HARNESS2_MAC_AGENT_URL=http://127.0.0.1:<port>
HARNESS2_MAC_AGENT_TOKEN=<lab identity token>
```

Use HTTPS for non-loopback servers. Keep the token out of files, command-line
arguments, and retained evidence. A candidate JSON has this versioned shape:

```json
{
  "schema_version": 2,
  "id": "baseline-v2",
  "prompt_guidance": "Check metric definitions before aggregating.",
  "tool_guidance": "",
  "skills": [],
  "retrieval_settings": {
    "context_byte_budget": 16000,
    "maximum_notes": 8,
    "maximum_recipe_hints": 4
  }
}
```

Only those candidate keys are accepted; schema 1 and unknown retrieval fields
are rejected. Schema-2 guidance and retrieval limits configure the host-owned
runtime harness, with preflight and durable fingerprint binding. Task text stays
unchanged. Authentication, model, namespace, history, cancellation behavior and
tool permissions cannot be changed by a candidate. Run one transport task with a
durable, stable key:

```bash
harness2-mac-agent-eval \
  --candidate docs/mac-agent-lab/baseline.json \
  --task docs/mac-agent-lab/tasks/metric-check.txt \
  --stable-run-key campaign-2026-01/baseline/metric-check/replica-1 \
  --output runs/mac-agent/campaign-2026-01/baseline/metric-check.json
```

The output stores the run identity/state, timestamps, elapsed time, event count,
candidate fingerprint, stable idempotency key, and final answer. It omits raw
events, credentials, and provider traces. On an ambiguous submit, the adapter
looks up the same idempotency key; it does not replay the submission. A timed
out active run stays durable so a later process can inspect its key/run ID.
For bounded baseline/candidate comparisons, see the
[Mac Agent runtime evaluation lab](MAC_AGENT_LAB.md). This is the earlier bounded
declarative transport benchmark. It runs development by default;
`--include-holdout` selects its separately declared transport holdout. That flag
does not seal production sources or implement the independent business-answer
comparison. For recall/analysis selection, use the canonical frozen collection and
independent grading described in [ANSWER_QUALITY.md](ANSWER_QUALITY.md).

```bash
harness2-mac-agent-campaign \
  --manifest docs/mac-agent-lab/campaign.json \
  --output runs/mac-agent/campaign-2026-01/report.json \
  --max-runs 20
# Optional separate transport holdout; not business-answer grading:
harness2-mac-agent-campaign \
  --manifest docs/mac-agent-lab/campaign.json \
  --output runs/mac-agent/campaign-2026-01/holdout-report.json \
  --max-runs 20 --include-holdout
```

### Authentication alternatives

On a machine with a configured attached service account, Application Default
Credentials can use that account. Other options include:

- `gcloud auth application-default login --no-browser`, which prints a command
  to run on another machine that has a browser.
- `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service account key file.
- `gcloud auth application-default login --impersonate-service-account=<account>`.

Keep `gcloud` on `PATH` for these Vertex configurations, including the key-file
route: the installation check runs
`gcloud auth application-default print-access-token`.

## Benchmark installation

Install only the benchmark you intend to run:

```bash
harness2-setup lab
harness2-check --bench lab
```

Use `jb` for JobBench or `wb` for WorkBuddy-Bench. See the
[benchmark guides](BENCHMARKS.md) for subset selection and licensing.

The runner overlays and compatibility patches are included in
[`third_party/`](../third_party/README.md). Setup clones supported upstream
revisions under `dependencies/`, applies the patches, creates the benchmark
environments, and downloads task data.

Each benchmark environment lives inside its upstream checkout:

- `dependencies/harvey-labs/.venv`
- `dependencies/job-bench-eval/.venv`
- `dependencies/workbuddy-bench/.venv`

Harness² selects these interpreters automatically; do not activate them for the
main commands.

### Installation checks

`harness2-setup <bench> --dry-run` previews setup without making changes.
`harness2-check` checks installed dependencies, credentials, and configuration
without calling a model. Refinement runs perform the same checks, including
judge configuration, before starting.

These checks do not test model availability. Access to an executor, improver, or
judge model is tested when that model is first called. Refinement and judging
return a nonzero exit status when incomplete.

## Codex executor

The Codex executor connects to a Responses API endpoint. For Gemini on Vertex
AI, the included `harness2-bridge` provides this interface through a local
LiteLLM server, using the same Application Default Credentials and
`GOOGLE_CLOUD_PROJECT`.

Install the optional dependencies and start the bridge in a separate session:

```bash
uv pip install -e '.[render,bridge]'
harness2-bridge                 # for WorkBuddy: harness2-bridge --host 0.0.0.0
```

The bridge prints the `HARNESS2_CODEX_*` settings to add to `.env`. Its port and
generated access key are stored under `dependencies/codex/` and reused on
restart. Pass `--substrate cx` to setup, checks, refinement, judging, and
reporting:

```bash
harness2-setup lab --substrate cx
harness2-check --bench lab --substrate cx
harness2 --bench lab --substrate cx --k 1 --mode parallel \
  --only-domains antitrust-competition --max-tasks 1
```

WorkBuddy executes Codex inside Docker containers, so the bridge must listen on
`--host 0.0.0.0`; it also prints `HARNESS2_CODEX_CONTAINER_URL`. This binds the
bridge to all network interfaces; restrict access to the intended clients.

To use another Responses API endpoint, set `HARNESS2_CODEX_BASE_URL`,
`HARNESS2_CODEX_API_KEY`, and `HARNESS2_CODEX_MODEL` directly. Setup records the
endpoint and model in `dependencies/codex/home/config.toml`; rerun setup after
changing either. `harness2-check` reports stale configuration until then.

Codex runs with its sandbox disabled. Review the
[executor network restrictions](EXPERIMENTS.md#web-access) before evaluation.

## Network access during setup

Setup downloads dependencies from the following hosts:

| Host | Used for |
|---|---|
| `github.com` | Pinned upstream checkouts |
| `registry.npmjs.org` | Pinned Bun runtime and Codex CLI, plus dependencies resolved by `bun install` |
| `huggingface.co` and its CDN | JobBench data and WorkBuddy subset archives |
| A Docker registry | WorkBuddy container image |
| `astral.sh` | CPython 3.12 when the host has no system Python 3.12 |

Use `harness2-setup <bench> --dry-run` to review setup commands when configuring
network access. Experiments also access the model endpoints configured in
`.env`. Setup downloads and executor web access have different requirements;
see [web access during evaluation](EXPERIMENTS.md#web-access).

## Wheel installations

A wheel ships the `harness2` package only. The task partitioner,
`python scripts/split_tasks.py`, requires this source tree. For a wheel
installation, work from a dedicated directory: `.env`, `dependencies/`, and
`runs/` are resolved there.
