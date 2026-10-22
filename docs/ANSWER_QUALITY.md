# Mac Agent recall and answer quality

## DABstep and product-source development

Mac Agent's `lab/benchmarks/README.md` owns the plugin runner, pinned DABstep
development inputs/scorer, executable commands and evidence retention. Its
`RuntimeBackend` implements this adapter's existing backend port. No second
optimizer or direct analyst model client is introduced.

The optional backend `validate_candidate` port runs during proposal validation and
before selection/library retention. Mac Agent's DABstep implementation rejects
guidance containing public source entities; semantic review remains necessary for
other task-specific facts. Private reference answers are never used by this guard.
`finalize_development` uses core selection, reflection and `Library`, excluding
rejected trees and source facts in reflection before independent grading. Library
retention is development context, not adoption into the user's app.

`harness2.integrations.product_candidate.propose_product` supplies a separate,
explicitly allowlisted product-source proposal workspace to the existing
`Proposer`. It returns reviewed source hashes and a proposal manifest; it cannot
apply code, build, modify credentials/grants or promote a product. Harvest uses
bounded descriptor-based copies without following symlinks. The operator validates
and builds an isolated product, then Mac Agent records product revision and binary
resource hashes separately from instruction configuration and runner revision.

The 2026-10-21 Mac Agent report records one actual three-stage instruction cycle,
rejection of all task-specific instruction candidates, an actual source proposal,
an isolated rebuilt runtime and a four-task development comparison. These are
development observations, not a hidden-set leaderboard result. See Mac Agent's
`docs/testing/reports/2026-10-21-dabstep-tooling.md` for the measured outcomes.

## Existing recall and pipeline program

Status (2026-10-20): real shared-runtime execution, read-only Trino/Airflow,
restricted proposer sessions and actual model-backed recursion are implemented.
Mac Agent's complete twelve-case development cohort passes independent
factual/source checks and calibrated narrative review. A sealed 96-run unseen
comparison and all 96 anonymous assessments are complete. Updated builtin passes
5/8 difficult pipeline answers versus the prior product's 2/8 under the original
strict gates. Static source regressions are retained; the instruction candidate
fails the paired no-regression gate and is not adopted. The Mac Agent-owned
`docs/testing/reports/2026-10-20-answer-quality-unseen.md` and reviewed aggregate
retain every original outcome.

The additional mature-cohort bank has four independently checked worlds and two
actual development answers with all 24 requested values correct. An explicit
source-dependency correction, with unchanged answers/data/expected values, gives
24/24 supported facts; eleven fresh calibration controls and both narratives
pass. That is evaluator repair/development evidence, not agent gain. The separate
12-run frozen comparison and all anonymous assessments are complete. Every arm
has 48/48 correct values and 4/4 passing narratives; strict source/full gates are
prior 2/4, updated builtin 4/4 and C1 3/4. These differences are per-fact citation
attachment completeness, not new arithmetic or business-conclusion gains. Keep
builtin. The Mac Agent report `docs/testing/reports/2026-10-20-cohort-unseen.md`
and its reviewed aggregate/audit preserve every original result. Across both
comparisons, 108 analyst conversations and 108 reviewer threads are distinct;
recorded initial models and scoped context/path checks pass. Docker is fully off.
The original 96 are not rerun or retrospectively regraded.

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

### Seeded recursive baselines

Pass `initial_tree` to `AnswerQualityAdapter` when continuing from a reviewed
incumbent. Execute baselines from `adapter.base_harness()` and give that same tree
to recursion. Selection/reflection then inspect the actual baseline rather than
an empty builtin surface. Reopening the adapter with a different baseline fails.
Both recursion modes require `k` distinct baseline samples for `k` units; an
incorrect count or duplicate identity is rejected before any proposal or rollout.
Keep source definitions in current evidence, preserve prior reusable procedures,
and use the per-domain experience library across tasks. Independent transfer
checks remain necessary before any application-default change.

Numeric-answer selection includes the candidate's original authorized tool
observations alongside its final answer. A final number or abstention alone is
insufficient evidence of correct scope, rule eligibility or arithmetic. The
selector must inspect those observations; a documentation-only source projection
is not proof that omitted source data was unavailable to the analyst. Native
journals and independent judgments are never copied into candidate evidence.

A retained baseline must belong to the current task and exact question and must
have executed the adapter's initial harness configuration. The backend's
`inspect()` supplies `task_id`, `question` and canonical `candidate` metadata;
the native backend validates these against its retained execution pin. Sequential
and parallel recursion reject mismatches before creating proposer context or
starting inference. Final selection also excludes evidence from another task.
Reusing an original terminal baseline is supported; relabeling unrelated evidence
is not.
