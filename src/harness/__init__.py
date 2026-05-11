"""DYNAMOS Policy Enforcer black-box scenario harness.

The harness uses the eFLINT reasoner as the oracle (programmatic projection
plus self-test sanity gate) and the running Policy Enforcer /validate
endpoint as the SUT. The harness seeds steward fixtures into the running
DYNAMOS etcd before each scenario.

Public modules:
- ``harness.manifest``: load and validate scenario manifests.
- ``harness.oracle``: derive the expected ValidationResponse from eflint-repl.
- ``harness.scenario_consistency``: run eflint-test.py against the scenario file.
- ``harness.etcd_seeder``: write Layer-2 fixtures into the DYNAMOS etcd.
- ``harness.sut_client``: call POST /api/v1/policy-enforcer/validate.
- ``harness.comparator``: normalised diff of expected vs actual.
- ``harness.runner``: per-scenario orchestration.
- ``harness.cli``: command-line entry point.
"""

__version__ = "0.1.0"
