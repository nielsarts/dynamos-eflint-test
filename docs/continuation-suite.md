# Continuation suite — design notes (deferred)

This document captures the design of a follow-up harness for the
`scenario_05*.eflint` family. It is intentionally NOT implemented in
Phase 1/2/3 of the approval suite; we record the design here so the
deferral is precise rather than vague.

## Why the approval harness can't host these scenarios

The approval suite calls `POST /api/v1/policy-enforcer/validate`. That
endpoint runs a single layered evaluation on one pool entry and then
releases it; the entry's eFLINT process is restarted on release, so any
in-session state mutations (`-steward-supports-archetype(VU, ComputeToData).`,
`+relation-allows-archetype(Alice, UVA, ComputeToData).`) are erased before
the next call. The 05x scenarios depend on those mutations being visible
to a follow-up query in the same session.

See
[/Users/nielsarts/projects/school/masterproject/DYNAMOS/docs/development_guide/policy_enforcer.md](/Users/nielsarts/projects/school/masterproject/DYNAMOS/docs/development_guide/policy_enforcer.md)
sections 3.4 and 7.2 ("After Evaluation: Restart eFLINT process") for the
underlying reason.

## What the 05x scenarios actually exercise

| Scenario file                                              | UCON trigger                                                       |
|------------------------------------------------------------|--------------------------------------------------------------------|
| `scenario_05a_continuation_policy_change.eflint`           | F3 — agreement policy changes (`-steward-supports-archetype(VU, ComputeToData)`) |
| `scenario_05b_continuation_subject_change.eflint`          | Subject attribute change (`-/+ relation-allows-archetype(R, S, A)`) |
| `scenario_05c_continuation_object_change.eflint`           | F4 — object attribute change (`-steward-supports-compute-provider(VU, SURF)`) |

All three use:

- `permitted-continuation(R, S, A)` as the per-session decision predicate,
- `submit-data-request(R, S)` to enter the in-flight state,
- a follow-up minus-phrase to mutate the policy/relation/agreement,
- a second query of `permitted-continuation` (or `valid-archetype`,
  `valid-compute-provider`) to verify the runtime would now revoke the
  session.

## Two implementation options

Both keep the *oracle* identical to the approval suite (programmatic
`Invariant q_X When pred(...).` queries gated by the existing `//#violated`
self-tests). They differ in how the SUT is driven.

### Option A — second oracle, no SUT comparison

Run the existing scenario files through a long-lived `eflint-repl`
instance, projecting predicate outcomes at each "checkpoint" the manifest
declares. The harness compares oracle-vs-oracle: the eflint-test.py
self-test result vs the programmatic projection. This is *not* a
differential test against DYNAMOS — it only protects against accidental
regressions in the eFLINT specification, which the existing
`eflint-test.py` already does. **Recommendation: skip this option.**

### Option B — drive DYNAMOS via the policy-update path (preferred)

The Policy Enforcer accepts `pb.PolicyUpdate` messages over RabbitMQ
(`policyEnforcer-in` queue) which re-validate active jobs after a policy
change. This is the production code path for runtime mutability.

Concretely the continuation harness would:

1. Seed etcd with the baseline agreements (same as the approval harness).
2. Call `POST /api/v1/policy-enforcer/validate` to obtain the baseline
   `ValidationResponse` and confirm it matches the oracle baseline.
3. Mutate the etcd agreement (e.g. drop a
   `+steward-supports-archetype(VU, ComputeToData).` line and write back
   the modified text).
4. Trigger the policy-update flow. There are two viable triggers:
   - publish a `pb.PolicyUpdate` to RabbitMQ via the existing API Gateway
     (requires Gateway support; check
     [/Users/nielsarts/projects/school/masterproject/DYNAMOS/docs/openapi/api-gateway-openapi.yaml](/Users/nielsarts/projects/school/masterproject/DYNAMOS/docs/openapi/api-gateway-openapi.yaml)),
     or
   - call `POST /api/v1/policy-enforcer/validate` a second time with the
     same request body. The eFLINT pool restart between calls means the
     second call sees the mutated etcd state, which is the cheapest proxy
     for "policy update arrived".
5. Compare the second `ValidationResponse` against the post-mutation
   oracle projection.

This makes 05a/05c straightforward: both mutate etcd-side facts, and a
second `/validate` call will pick them up. 05b mutates Layer-3 (a
`+relation-allows-archetype(...)` line owned by the Layer-2 per-steward
agreement), so it is also etcd-side.

The continuation harness reuses every module in `src/harness/` except:

- a new `runner_continuation.py` that orchestrates the
  baseline-mutate-revalidate cycle and accepts a *list* of checkpoints
  per scenario, not just one.
- a new manifest schema (`suite: continuation`) that lists ordered
  checkpoints, each with its own request and assertions.

## Out of scope even for Option B

- **Stateful job revocation logic** lives in the Orchestrator (see
  `ReevaluateJob` references in
  [/Users/nielsarts/projects/school/masterproject/DYNAMOS/go/cmd/orchestrator/](/Users/nielsarts/projects/school/masterproject/DYNAMOS/go/cmd/orchestrator/)).
  Verifying that an in-flight job is actually killed is out of scope for
  the eFLINT-as-oracle approach — it would require driving the
  Orchestrator and observing its outbound RabbitMQ traffic. That belongs
  in the "Correctness of Continuous Authorisation" thesis section, not
  this harness.

## Estimated effort

- **Option B for 05a and 05c**: ~half a day. Both scenarios reduce to two
  oracle projections + two `/validate` calls per scenario, with an etcd
  mutation in between.
- **Option B for 05b**: same shape; requires modifying a
  `+relation-allows-archetype(...)` line in the per-steward agreement
  text, which the seeder already supports (it writes the agreement file
  verbatim).
- A working set of `manifests/scenario_05*.yaml` would close the loop.

## What to do until then

The 05x scenarios still pass their `//#violated` self-tests; the harness
exposes that via `harness consistency scenario_05a_continuation_policy_change`
once a manifest for them is authored. That gives partial coverage:
"the eFLINT specification of continuous authorisation is internally
consistent", which is weaker than the differential test but useful.
