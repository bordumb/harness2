# Mac Agent native policies

The Mac Agent transport accepts host configuration schema 3 in addition to the
unchanged schema 2. Schema 3 selects separately versioned, compiled Swift result,
context and discovery policies. It does not execute Python in Mac Agent, install
code, grant sources or add permissions.

Policy entries have explicit byte/row/transition limits and failure modes.
Unknown fields, unsupported identities/versions, fractional or Boolean limits and
inconsistent result budgets are rejected. Omitted policy families normalize to
null. Legacy candidates keep their original canonical JSON and fingerprints.

The host must advertise the exact candidate schema version and fingerprint
before a task is submitted. A mismatch never falls back to another host or
configuration. The configured and final native requests remain bound by the
existing evidence checks. Authoring or tuning native policy parameters requires
an explicitly scoped evaluation backend; accepting schema 3 in the transport does
not expand existing prompt/profile proposal surfaces.

`tests/test_native_policy.py` covers normalization, authority rejection,
version mismatch before submission and fingerprint compatibility. Mac Agent's
Swift tests independently check the same complete schema-3 configuration digest
`ead62d0c0256c93e216b50e1899ff572afbeef1f122430f5f2c3b2eba0c58e88`.
