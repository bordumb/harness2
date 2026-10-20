# Mac Agent runtime evaluation lab

This lab connects Harness² evaluation tasks to Mac Agent's authenticated durable
run API. The Mac Agent server owns the real `AgentRuntime`, Codex app-server
account, tool authorization, project namespace, context, and run persistence.
Harness² supplies an allowlisted candidate and a stable evaluation identity;
it does not emulate the runtime or call a separate model endpoint for execution.

## First vertical slice

The `harness2-mac-agent-eval` command runs one task at a time against a running
Mac Agent server. It requires an HTTPS server origin, except for an HTTP
loopback lab, and a lab-specific bearer token supplied only through the
environment. It submits through `POST /v1/runs`, polls durable state,
and retains a small evidence record. On uncertain POST outcomes, it queries
`GET /v1/submissions/{idempotency-key}` and never repeats the POST under a new
key. A timeout leaves the run intact and reports its stable key so the operator
can investigate/resume it.

The current candidate contract is **schema 2**. Schema 1's task augmentation is
rejected. Candidates use Mac Agent's host-owned `RuntimeHarnessConfiguration`:

| Field | Runtime effect |
|---|---|
| `id` | Part of the normalized configuration fingerprint |
| `prompt_guidance` | Supplements the actual runtime instructions |
| `tool_guidance` | Supplements tool-use instructions without changing tool grants |
| `skills` | Bounded behavioral guidance; installs no executable skills |
| `retrieval_settings.context_byte_budget` | Actual automatic context limit, 0–32000 UTF-8 bytes |
| `retrieval_settings.maximum_notes` | Actual authorized knowledge limit, 0–16 |
| `retrieval_settings.maximum_recipe_hints` | Actual recipe hint limit, 0–8 |

Defaults are 16000 bytes, eight notes and four hints. Unknown keys, fractional or
boolean limits and oversized UTF-8 guidance fail closed. Candidate fingerprints
match the Swift implementation's normalized compact UTF-8 JSON; tests share an
independent Unicode/slash oracle.

Configure `harnessConfiguration` in each isolated Mac Agent server identity. Use
separate workspaces and bearer identities for baseline and candidate. Omit the
field for the builtin baseline (candidate JSON ID `builtin`). Configuration is
fixed at host startup; adoption/rollback require an explicit host config change
and restart. No run can install a candidate, change authentication, scope, tool
permissions or the configured subscription model. Queued runs and continuations
remain bound to the exact original configuration.

Before submission the adapter checks authenticated `GET /v1/runtime/harness`.
It sends the task **unchanged**, with `expected_harness_fingerprint`, and verifies
both accepted and completed run bindings. Older hosts cannot silently grade the
wrong configuration. A preflight mismatch submits no task.

For a two-arm campaign, set `HARNESS2_MAC_AGENT_TARGETS` to a JSON file mapping
configuration fingerprints to explicit host identities:

```json
{
  "<64-character candidate fingerprint>": {
    "endpoint": "http://127.0.0.1:18080",
    "token_environment": "SYNTHETIC_CANDIDATE_TOKEN"
  }
}
```

Add the baseline fingerprint as a separate entry. Token **values** stay in the
environment, outside manifests and reports. Every selected fingerprint requires
an explicit entry; there is no fallback to a different candidate. For an
individual run, the original `HARNESS2_MAC_AGENT_URL` and
`HARNESS2_MAC_AGENT_TOKEN` remain supported. The adapter still validates HTTPS or
loopback HTTP, and never resubmits an uncertain effect under a new key.

The persisted report contains the final answer (bounded and credential-redacted),
state, timing, candidate fingerprint, idempotency key, and up to
100 artifact references containing identity metadata only. `event_count` is `null`: the adapter does not download unused event pages, which
contain repeated run snapshots and can exceed its bounded response limit. Raw events,
provider traces, auth headers, and artifact bytes are omitted. Mac Agent's server
does not expose model token usage in `RunRecord`, so `usage` is `null` until the
runtime API provides a supported usage field.

## Reproducible comparison procedure

1. Use a disposable Mac Agent server identity configured with the synthetic
   product campaign workspace from the Mac Agent repository's
   `lab/stress/PRODUCT-CAMPAIGN.md`. Do not point this lab at personal history.
2. Pin the candidate JSON, task text, fixture revision, Mac Agent server build,
   and the configured signed-in Codex model in a campaign manifest. Set
   `fixture_fingerprint` to the exact product fixture's `manifest_sha256`
   (printed by `product_campaign.py prepare` and saved in `identity.json`). A
   non-SHA smoke label may run, but the report will not recommend adoption from
   that comparison.
3. Run an unchanged baseline and candidate against the same development task
   set. The runner derives a stable idempotency key from campaign, fixture,
   arm, partition, task, candidate and task fingerprints, and adapter version.
   Never reuse a key for different input.
4. Keep development and holdout task files in separate directories and do not
   use holdout results while tuning. The campaign command runs development by
   default; review the candidate and freeze it before using `--include-holdout`.
5. Compare answers, artifacts, correctness, metric semantics, numeric
   tolerances, and permission/namespace invariants with deterministic checks.
   Record unavailable checks as unavailable rather than as passes.
6. Retain only aggregate campaign reports and small redacted run manifests.
   Keep raw payloads, synthetic databases, and copied workspaces outside Git.

Example candidate and task fixtures are under `docs/mac-agent-lab/`.
The checked-in `campaign.json` is only a connectivity smoke test with a
phrase-presence oracle; it does not establish analysis correctness. Replace its
checks with values independently audited against the synthetic fixture
ground-truth before using a report to assess a candidate.

## Implemented boundaries and remaining issue scope

Implemented in this slice: signed-in Codex app-server calls for Harness²'s
proposer/selector channel; the Mac Agent durable-run adapter; host-configured runtime candidates,
preflight and durable binding verification, strict allowlisting and fingerprints; bounded serial baseline/candidate campaign
runs; development/holdout partitioning; declarative phrase, artifact-reference
and numeric-tolerance checks; aggregate comparisons; transport-failure and
idempotency tests; and cancellation through the durable runtime API.

Still required for the full issue: wire the manifest to the Mac Agent
repository's product campaign fixtures; add independent checks for the
fixture's data correctness, permission/namespace invariants and artifact
contents; add an app-server model-judge adapter where deterministic judges are
insufficient; propagate available usage from Mac Agent; and run the end-to-end
campaign against a disposable server profile. Current tests use mocked
protocol responses and are not proof that the live workflow works. Do not
adopt a candidate based on the small declarative check set alone.
