# dynamos-eflint-harness

Black-box differential test harness for the [DYNAMOS](https://github.com/nielsarts/DYNAMOS) Policy Enforcer.

> **Note:** This harness targets a [forked version of DYNAMOS](https://github.com/nielsarts/DYNAMOS) that integrates the eFLINT reasoner into the Policy Enforcer. The upstream DYNAMOS project does not include eFLINT-based policy evaluation.

## Primary goal

**The primary goal of this project is to test the full chain: oracle projection vs. the live DYNAMOS Policy Enforcer (the SUT).** Every other capability in this repository — the eFLINT unit-tester integration, the oracle-only dry-run mode, the consistency gate — exists to support and validate the inputs to that end-to-end comparison. They are useful in isolation (e.g. when the DYNAMOS stack is unavailable), but they are not the end goal.

The harness uses the **eFLINT reasoner as an oracle** — projected programmatically and gated by `//#violated` / `//#assert` self-tests embedded in the scenario files — and the **live Policy Enforcer's `/api/v1/policy-enforcer/validate` endpoint as the system under test (SUT)**. Before each scenario the harness seeds the steward fixtures into the live DYNAMOS etcd so the oracle and the SUT evaluate against identical agreements.

## How it works

A full scenario run — which is the primary mode — proceeds in five phases. Phases 1–3 are preparatory and ensure the oracle and SUT operate on identical, self-consistent inputs; phases 4–5 are the core test against the SUT.

1. **Consistency gate** *(supporting)* — runs `eflint-test.py` (the [eFLINT unit-tester](https://gitlab.com/eflint/tools/unit-tester)) against the scenario's eFLINT file. If any `//#violated` / `//#assert` assertions fail, the scenario is reported as inconsistent and the SUT is never consulted. This guards against a broken oracle producing a false-pass result against the SUT.
2. **Oracle projection** *(supporting)* — flattens Layer 1 + shared rules + per-steward agreements, plants Layer-3 request facts from the manifest, and queries the eFLINT reasoner. Results are projected into the canonical `ValidationResponse` shape.
3. **Etcd seeding** *(supporting)* — writes the shared rules and per-steward agreement/config keys directly into etcd so the SUT sees the same input as the oracle.
4. **SUT call** *(primary)* — `POST /api/v1/policy-enforcer/validate` with the manifest's request body.
5. **Comparison** *(primary)* — per-steward diff with set equality on archetypes and compute-provider lists. A pass here is what this project is ultimately measuring.

## Project layout

```
dynamos-eflint-test/
  dynamos-test-scenarios/
    01_interface_policy.eflint      ← Layer-1 baseline interface policy
    02_agreement_rules.eflint       ← Layer-2 shared agreement rules
    agreement_VU.eflint             ← per-steward agreement (VU)
    agreement_UVA.eflint            ← per-steward agreement (UVA)
    scenario_*.eflint               ← scenario files with //#assert and //#violated guards
    manifests/
      scenario_*.yaml               ← per-scenario manifest (HTTP body + queries)
  src/harness/
    manifest.py                     ← YAML manifest model + discovery
    eflint_repl.py                  ← minimal eflint-repl driver
    eflint_flatten.py               ← in-process eFLINT line flattener
    oracle.py                       ← projects query results into ValidationResponse
    scenario_consistency.py         ← subprocess wrapper around eflint-test.py
    etcd_seeder.py                  ← writes Layer-2 fixtures via etcd HTTP gateway
    sut_client.py                   ← HTTP client for the Policy Enforcer endpoint
    comparator.py                   ← per-steward oracle vs actual diff
    runner.py                       ← per-scenario orchestration
    cli.py                          ← `harness` CLI entry point
  tests/
    test_scenarios.py               ← pytest suite parametrized over manifests
  eflint-test.py                    ← upstream eFLINT unit-tester (kept as-is)
  flatten.py                        ← upstream eFLINT flattener (kept as-is)
```

## Prerequisites

- **Python ≥ 3.10** (CI uses 3.12)
- **`eflint-repl`** on `PATH` (or set `EFLINT_REPL_EXE`). The binary is built from the [eFLINT Haskell implementation](https://gitlab.com/eflint/haskell-implementation); full installation instructions are available in that repository. The quick path using Cabal:

  ```bash
  git clone https://gitlab.com/eflint/haskell-implementation.git eflint-impl
  cd eflint-impl
  cabal install --installdir="$HOME/.local/bin" exe:eflint-repl
  ```

- **Running DYNAMOS stack** (etcd + Policy Enforcer) — only required for the integration tests.

## Install

**Option A — editable install (recommended)**

Installs the `harness` CLI and makes `import harness` available without setting `PYTHONPATH`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Option B — dependencies only (no CLI install)**

Useful for running tests in CI or without touching site-packages. The `PYTHONPATH=src` prefix is required so Python can locate the `harness` package:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/pytest tests/
```

## CLI

```bash
# Primary — full chain (oracle + seed + SUT call + comparison)
harness run scenario_01_approved                                # single scenario against the SUT
harness run                                                     # all discovered scenarios against the SUT

# Supporting — sub-steps useful for authoring and debugging
harness list                                                    # discover all scenario manifests
harness consistency scenario_01_approved                        # self-consistency (eFLINT unit-test) only
harness oracle scenario_01_approved                             # oracle projection only (no SUT)
harness seed scenario_01_approved                               # seed etcd only
harness run --no-seed --no-sut scenario_01_approved             # oracle-only dry run (no SUT)
```

Without the editable install:

```bash
PYTHONPATH=src .venv/bin/python -m harness.cli list
```

## Configuration

All values default to the DYNAMOS local configuration. Override via environment variable or the matching CLI flag.

| Variable                      | Default                   | Purpose                                    |
| ----------------------------- | ------------------------- | ------------------------------------------ |
| `EFLINT_REPL_EXE`             | `eflint-repl`             | Path to the eFLINT REPL binary             |
| `EFLINT_TEST_PY`              | `<repo>/eflint-test.py`   | Path to the upstream eFLINT unit-tester    |
| `DYNAMOS_ETCD_URL`            | `http://localhost:30005`  | etcd v3 JSON gateway used by the seeder    |
| `DYNAMOS_POLICY_ENFORCER_URL` | `http://policy-enforcer.orchestrator.svc.cluster.local` | Policy Enforcer HTTP base URL |

## Accessing cluster services from your local machine

The integration tests require two DYNAMOS services to be reachable from your local machine.

**etcd v3 JSON gateway** (default `localhost:30005`):

etcd is a `NodePort` service in the `core` namespace already mapped to host port `30005`. It is reachable at `localhost:30005` without any extra steps in most local cluster setups (minikube, k3s, kind with host networking). If it is not, forward it manually:

```bash
kubectl port-forward -n core svc/etcd 30005:2379
```

**Policy Enforcer** (default `http://policy-enforcer.orchestrator.svc.cluster.local`):

The Policy Enforcer sits behind the nginx ingress controller, which is a `LoadBalancer` already bound to `localhost:80`. The ingress routes on the hostname `policy-enforcer.orchestrator.svc.cluster.local`. This `/etc/hosts` entry is part of the standard DYNAMOS installation, so it may already be present. If not, add it manually:

```bash
echo "127.0.0.1 policy-enforcer.orchestrator.svc.cluster.local" | sudo tee -a /etc/hosts
```

Then export the URL:

```bash
export DYNAMOS_POLICY_ENFORCER_URL=http://policy-enforcer.orchestrator.svc.cluster.local
```

No port-forward is needed. If you prefer a plain `localhost` URL, you can still port-forward directly to the service (its service port is `8080`):

```bash
kubectl port-forward -n orchestrator svc/policy-enforcer 8082:8080
# export DYNAMOS_POLICY_ENFORCER_URL=http://localhost:8082
```

## Running the tests

**End-to-end against the SUT** (primary — requires a running DYNAMOS stack):

```bash
DYNAMOS_ETCD_URL=http://localhost:30005 \
DYNAMOS_POLICY_ENFORCER_URL=http://policy-enforcer.orchestrator.svc.cluster.local \
.venv/bin/pytest -m integration tests/
```

This is the authoritative test run. It seeds etcd, calls the live Policy Enforcer, and compares the SUT response against the oracle projection for every scenario.

**Oracle-only** (no DYNAMOS stack required, just `eflint-repl`):

```bash
.venv/bin/pytest -m "not integration" tests/
```

Useful for validating scenario authoring and oracle correctness when the DYNAMOS stack is unavailable, but does not test the SUT.

Integration tests skip cleanly when etcd or the Policy Enforcer is unreachable, so `pytest tests/` is also safe to run without a live DYNAMOS stack.

## Scenarios covered

| ID  | Manifest                                         | Hypothesis                                              |
| --- | ------------------------------------------------ | ------------------------------------------------------- |
| H1  | `scenario_01_approved`                           | Niels at {VU, UVA} approved; VU=[C2D]; UVA=[C2D, DTT]  |
| H2a | `scenario_02a_approved_alice_uva`                | Alice at {UVA} approved; UVA=[DTT]                      |
| H2b | `scenario_02b_approved_alice_partial`            | Alice at {VU, UVA} approved; VU invalid; UVA=[DTT]      |
| H3a | `scenario_03a_denied_bob_no_agreement`           | Bob at {SURF_org} denied (no agreement)                 |
| H3b | `scenario_03b_denied_bob_no_relation`            | Bob at {VU, UVA} denied (no relation)                   |
| H4a | `scenario_04a_denied_alice_wrong_steward`        | Alice at {VU} denied (no relation at VU)                |
| H4b | `scenario_04b_denied_alice_restricted_archetype` | Alice at {UVA} approved, restricted to DataThroughTtp   |

Continuation scenarios (`scenario_05*.eflint`) are intentionally out of scope for the approval suite. They exercise in-session state mutations that `/api/v1/policy-enforcer/validate` resets between calls and require a separate stateful runner.

## Authoring a new scenario

1. Add `dynamos-test-scenarios/scenario_<id>.eflint` with the request facts and `//#violated` / `//#assert` assertions.
2. Add `dynamos-test-scenarios/manifests/scenario_<id>.yaml` with the eFLINT file list, HTTP request body, and candidate/assertion declarations.
3. Add a row to `HYPOTHESIS_TABLE` in `tests/test_scenarios.py` so the hand-derived expected outcome stays an independent check on the oracle's projection.
