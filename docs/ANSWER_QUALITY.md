# Mac Agent recall and answer quality

Status: benchmark adapter, controlled recursion checks and restricted proposer
reads implemented. The Mac Agent backend has two actual development recall
baselines; warehouse cases, actual model-backed recursion and frozen promotion
remain in progress.

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
with four rollouts and no judge feedback. It is not a live inference or improvement
claim. The previous Mac Agent HTTP adapter and schema-2 preflight/binding checks
remain authoritative; do not replace them with a direct model call.

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
The actual model-backed answer-quality recursion campaign remains unverified.
