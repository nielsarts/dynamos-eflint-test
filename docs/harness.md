# DYNAMOS Policy Enforcer scenario harness

Black-box differential test harness for the DYNAMOS Policy Enforcer.

The harness uses the **eFLINT reasoner as the oracle** (projected
programmatically and gated by the existing `//#violated` / `//#assert`
self-tests) and the **running Policy Enforcer's `/api/v1/policy-enforcer/validate`
HTTP endpoint as the system under test (SUT)**. Before each scenario the
harness seeds the steward fixtures into the live DYNAMOS etcd so the SUT
and the oracle evaluate against the same agreements.

## Layout

```
dynamos-eflint-test/
  dynamos-test-scenarios/
    01_interface_policy.eflint
    02_agreement_rules.eflint
    agreement_VU.eflint
    agreement_UVA.eflint
    scenario_*.eflint             ← already vetted with //#violated / //#assert
    manifests/
      scenario_*.yaml             ← per-scenario manifest (HTTP body + queries)
  src/harness/
    manifest.py                   ← YAML manifest model + loader
    eflint_repl.py                ← minimal eflint-repl driver (sentinel-trigger protocol)
    eflint_flatten.py             ← in-process clone of flatten.py
    oracle.py                     ← projects ?Holds(...) queries into ValidationResponse
    scenario_consistency.py       ← subprocess wrapper around eflint-test.py
    etcd_seeder.py                ← writes Layer-2 fixtures via etcd's HTTP gateway
    sut_client.py                 ← POST /api/v1/policy-enforcer/validate
    comparator.py                 ← per-steward diff
    runner.py                     ← per-scenario orchestration
    cli.py                        ← `harness <command>` entry point
  tests/
    test_scenarios.py             ← pytest parametrized over manifests
  eflint-test.py                  ← upstream eFLINT unit-tester (kept as-is)
  flatten.py                      ← upstream flattener (kept as-is)
```

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Or, if you just want to run the tests without installing the package:

```bash
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/pytest tests/
```

You also need `eflint-repl` on `PATH` (or set `EFLINT_REPL_EXE`). See
the upstream [Haskell implementation](https://gitlab.com/eflint/haskell-implementation).

## CLI

After `pip install -e .`:

```bash
harness list
harness consistency scenario_01_approved
harness oracle scenario_01_approved
harness seed scenario_01_approved
harness run scenario_01_approved
harness run                                 # all discovered scenarios
harness run --no-seed --no-sut scenario_01_approved   # oracle-only dry run
```

Without the install:

```bash
PYTHONPATH=src .venv/bin/python -m harness.cli list
```

## Configuration

All knobs default to the DYNAMOS *local* configuration
(`go/cmd/policy-enforcer/config_local.go` in the DYNAMOS repo).

| Variable                          | Default                  | Purpose                                              |
| --------------------------------- | ------------------------ | ---------------------------------------------------- |
| `EFLINT_REPL_EXE`                 | `eflint-repl`            | Path to the eFLINT REPL binary.                      |
| `EFLINT_TEST_PY`                  | `<repo>/eflint-test.py`  | Path to the upstream unit-tester.                    |
| `DYNAMOS_ETCD_URL`                | `http://localhost:30005` | etcd v3 JSON gateway used by the seeder.             |
| `DYNAMOS_POLICY_ENFORCER_URL`     | `http://localhost:8082`  | Policy Enforcer HTTP base URL.                       |

Each can also be passed as a CLI flag (`--etcd-url`, `--sut-url`).

## What the harness does, end to end

1. **Consistency gate** — runs `eflint-test.py` against the scenario's eFLINT
   file. If `//#violated` / `//#assert` comments fail, the scenario is
   reported as `inconsistent`; the harness does not consult the SUT in that
   case because the oracle is broken.
2. **Oracle projection** — flattens Layer 1 + shared rules + per-steward
   agreements, plants the Layer-3 facts derived from the manifest's
   `request` block, and asks `Invariant q_<id> When pred(...).` for every
   predicate it needs. A violation report identifies "does not hold"; the
   absence of one identifies "holds". Results are projected into the
   canonical `ValidationResponse` shape.
3. **Etcd seeding** — writes
   - `/policyEnforcer/eflintRules/shared` ← Layer-2 shared rules
   - `/policyEnforcer/eflintModels/{steward}` ← per-steward agreement text
   - `/policyEnforcer/configs/{steward}` ← `{"validationStrategy":"eflint", ...}`
   via etcd's v3 HTTP/JSON gateway. Stewards in the request without a
   manifest-side agreement get their config + model deleted, which is what
   the "no agreement registered" scenarios need.
4. **SUT call** — `POST /api/v1/policy-enforcer/validate` with the manifest's
   `request` body. Returns the parsed `ValidationResponse`.
5. **Comparison** — per-steward diff, with set equality on archetypes and
   compute-provider lists. Token values are never compared; on approved
   requests the comparator only checks that `auth.access_token` /
   `auth.refresh_token` are present and non-empty.

## Hypotheses covered

| ID  | Scenario manifest                                  | One-line hypothesis                                            |
| --- | -------------------------------------------------- | -------------------------------------------------------------- |
| H1  | `scenario_01_approved`                             | Niels at {VU, UVA} approved; VU=[C2D]; UVA=[C2D, DTT]          |
| H2a | `scenario_02a_approved_alice_uva`                  | Alice at {UVA} approved; UVA=[DTT]                             |
| H2b | `scenario_02b_approved_alice_partial`              | Alice at {VU, UVA} approved; VU invalid; UVA=[DTT]             |
| H3a | `scenario_03a_denied_bob_no_agreement`             | Bob at {SURF_org} denied (no agreement)                        |
| H3b | `scenario_03b_denied_bob_no_relation`              | Bob at {VU, UVA} denied (no relation)                          |
| H4a | `scenario_04a_denied_alice_wrong_steward`          | Alice at {VU} denied (no relation at VU)                       |
| H4b | `scenario_04b_denied_alice_restricted_archetype`   | Alice at {UVA} approved, restricted to DataThroughTtp          |

Continuation scenarios (`scenario_05*.eflint`) are intentionally out of scope
for the approval suite. They exercise in-session mutations that
`/api/v1/policy-enforcer/validate` deliberately resets between calls, so they
need a different runner and a different (stateful) endpoint.

## Running the tests

Oracle-only (no DYNAMOS dependency, just `eflint-repl`):

```bash
.venv/bin/pytest -m "not integration" tests/
```

End-to-end against a running local DYNAMOS:

```bash
DYNAMOS_ETCD_URL=http://localhost:30005 \
DYNAMOS_POLICY_ENFORCER_URL=http://localhost:8082 \
.venv/bin/pytest -m integration tests/
```

Integration tests skip cleanly when etcd or the Policy Enforcer is
unreachable, so they are safe to leave in `pytest tests/`.

## Authoring a new scenario

1. Add `dynamos-test-scenarios/scenario_<id>.eflint` with the request facts
   and the `//#violated` / `//#assert` assertions for the hypothesis.
2. Add `dynamos-test-scenarios/manifests/scenario_<id>.yaml` listing the
   eFLINT files, the HTTP request body, and the candidates/assertions.
3. Add a row to `HYPOTHESIS_TABLE` in
   [tests/test_scenarios.py](../tests/test_scenarios.py) so the hand-derived
   hypothesis stays an independent check on the oracle's projection.

## Why direct etcd writes (not HTTP)

DYNAMOS exposes no HTTP endpoint to insert a steward's agreement; the
runtime policy-update flow is RabbitMQ-only and writes etcd internally.
The Policy Enforcer reads Layer 2 fresh on every evaluation, so direct
writes to the three etcd keys above are picked up immediately by the next
`/validate` call (the eFLINT pool restarts each instance on release, so
the Layer-1 baseline is preserved). See
[DYNAMOS/docs/development_guide/policy_enforcer.md §8.3](../../DYNAMOS/docs/development_guide/policy_enforcer.md)
for the contract.
