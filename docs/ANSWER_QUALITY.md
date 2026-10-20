# Mac Agent recall and answer quality

Status (2026-10-20): real shared-runtime execution, read-only Trino/Airflow,
restricted proposer sessions and actual model-backed recursion are implemented.
Mac Agent's complete twelve-case development cohort passes independent
factual/source checks and calibrated narrative review. A sealed 96-run unseen
comparison is collecting; no unseen improvement or promotion result exists yet.

`harness2.integrations.answer_quality.AnswerQualityAdapter` implements the existing
core `BenchmarkAdapter` contract. Use existing recursion, selection and library
machinery rather than another optimizer. Mac Agent owns the data/knowledge/history
fixtures, independent source-to-answer contracts and concrete execution/judging.
Its `lab/answer_quality/` and `docs/testing/plans/answer-quality.md` are authoritative;
this fork contains no duplicated business definitions or hidden expected values.

The adapter's backend port supplies describe/execute/inspect/judge. Only public
project sources, actual trajectories and delivered artifacts enter proposer context.
The independent judge is called separately. All/train list development only;
holdout access through recursion fails closed. Holdout must run through a separate
frozen comparison gate and never enter reflection or the improvement library.
An entirely held-out backend is also rejected before any proposer context is
constructed. No instruction candidate can be chosen using those answers.

The Mac Agent surface supports only `systemprompt.md`, `tool_guidance.md` and
`retrieval.json`, mapped through the schema-2 host-owned runtime contract. Candidates
cannot modify authentication, model, tool grants, task text, scripts or executable
skills. A generic `core.prompts.register_surface_text` port registers the adapter's
instructions while refusing replacement of an existing different surface.

```sh
# Use the repository's supported Python 3.12 interpreter.
python3 -m unittest discover -s tests -p test_answer_quality.py -v
```

The controlled backend/proposer test exercises existing propose/probe/compose code
with four rollouts and no judge feedback. Separately, the actual subscribed
`run_sequential(k=1)` pipeline investigation completed invariant, domain and
compose proposals and all three real Mac Agent rollouts. This establishes the
integration; it does not establish generalization or justify promotion. The
schema-2 HTTP preflight/binding checks remain authoritative; do not replace the
production analyst with a direct model call.

The Codex proposer channel uses a unique process-local permission profile, not
workspace-write's default broad read access. Minimal platform reads and workspace
writes are allowed; sibling private data and command network access are denied.
The installed protocol is checked against
[official permission profiles](https://learn.chatgpt.com/docs/permissions).
Native direct/symlink canary denials and approved read/write controls passed on
Codex 0.157.1 without inference. Older unsupported permission transports fail
closed; do not fall back to unrestricted execution or edit global settings.

Context isolation: every proposer session is ephemeral and receives only its
constructed evidence workspace/mission. Host instruction discovery and inherited
Codex memories are explicitly disabled; no current orchestrator conversation is
passed. The installed CLI's memories default was already false when audited; this
change removes reliance on that default, not a claim of detected contamination.
The analyst runs in a separate fresh Mac Agent profile; the reviewer runs in
another ephemeral evidence workspace. Neither receives the orchestrator's chat.
Reviewers receive independent reference facts/original enabled API observations
for grading, explicitly separated from what the analyst actually read. Those
references never enter analyst or proposer context. Schema-constrained reviewer
responses use packet-local reference keys while preserving original identities;
verdicts are unconstrained.

## Frozen comparison ownership

Mac Agent's `lab/answer_quality/frozen.py` seals the development-selected harness,
source/evaluator bytes, binaries/resources, fixtures and verified service images.
Its collection controller runs twelve static holdouts and four difficult pipeline
controls, two repetitions across prior-product builtin, updated builtin and the
selected harness: 96 original samples. Private controller mappings stay outside
the linked project, and analyst case/run paths are opaque. Every original sample
must finish before factual or narrative assessment is authorized. Terminal errors
remain in the denominator; unresolved work is never silently resubmitted.

Use the Mac Agent `lab/answer_quality/README.md` for executable collection and
assessment commands. Generated profiles, private contracts, raw traces and service
state remain ignored there; only reviewed summaries are committed. Docker is owned
by each live service phase and shut down afterward. Do not route the holdout through
Harness² recursion or use the older declarative transport lab's phrase checks as
business-answer evidence.

The development record includes authentic citation-normalization and evaluator
repairs, all retained alongside original failures. They are not agent improvements.
The new product's denied-tool filtering and SQL alias support are measured
separately from the instruction candidate. If the frozen candidate supplies no
incremental supported-answer gain, retain the builtin harness. Same-model reviewer
bias and fixture-author bias remain limitations despite session isolation.
