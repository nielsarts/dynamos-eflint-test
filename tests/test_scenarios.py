"""Scenario-level tests.

Two layers:

1. Tests that exercise just the **oracle** (no DYNAMOS needed). These run in
   every environment that has ``eflint-repl`` available. They confirm:
     - each scenario's eFLINT file is internally consistent;
     - each scenario's oracle projection matches its documented hypothesis;
     - a forced regression in the agreement files flips the oracle's output.

2. An **integration** test (marked ``integration``) that drives the full
   pipeline against a running local DYNAMOS environment. Skipped unless the
   etcd and Policy Enforcer endpoints respond on the configured URLs.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harness.comparator import compare
from harness.etcd_seeder import EtcdSeeder
from harness.manifest import (
    Manifest,
    default_scenarios_dir,
    discover_manifests,
    load_manifest,
)
from harness.oracle import derive_expected
from harness.runner import run_scenario, RunOptions
from harness.scenario_consistency import check_scenario_consistency
from harness.sut_client import PolicyEnforcerClient


# ---------------------------------------------------------------------------
# Discovery / fixtures
# ---------------------------------------------------------------------------


def _manifests() -> list[Manifest]:
    return discover_manifests(default_scenarios_dir())


def _ids(manifests: list[Manifest]) -> list[str]:
    return [m.id for m in manifests]


@pytest.fixture(scope="session")
def manifests() -> list[Manifest]:
    ms = _manifests()
    if not ms:
        pytest.skip("no scenario manifests discovered")
    return ms


# ---------------------------------------------------------------------------
# Oracle-only tests (no DYNAMOS dependency)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "manifest",
    _manifests(),
    ids=_ids(_manifests()),
)
def test_scenario_is_self_consistent(manifest: Manifest) -> None:
    result = check_scenario_consistency(manifest)
    assert result.consistent, result.render()


# Hand-derived from the hypothesis table in
HYPOTHESIS_TABLE: dict[str, dict[str, object]] = {
    "scenario_01_approved": {
        "request_approved": True,
        "invalid": set(),
        "valid": {
            "VU": {"archetypes": {"ComputeToData"}, "compute_providers": {"SURF"}},
            "UVA": {"archetypes": {"ComputeToData", "DataThroughTtp"}, "compute_providers": {"SURF"}},
        },
    },
    "scenario_02a_approved_alice_uva": {
        "request_approved": True,
        "invalid": set(),
        "valid": {
            "UVA": {"archetypes": {"DataThroughTtp"}, "compute_providers": {"SURF"}},
        },
    },
    "scenario_02b_approved_alice_partial": {
        "request_approved": True,
        "invalid": {"VU"},
        "valid": {
            "UVA": {"archetypes": {"DataThroughTtp"}, "compute_providers": {"SURF"}},
        },
    },
    "scenario_03a_denied_bob_no_agreement": {
        "request_approved": False,
        "invalid": {"SURF_org"},
        "valid": {},
    },
    "scenario_03b_denied_bob_no_relation": {
        "request_approved": False,
        "invalid": {"VU", "UVA"},
        "valid": {},
    },
    "scenario_04a_denied_alice_wrong_steward": {
        "request_approved": False,
        "invalid": {"VU"},
        "valid": {},
    },
    "scenario_04b_denied_alice_restricted_archetype": {
        "request_approved": True,
        "invalid": set(),
        "valid": {
            "UVA": {"archetypes": {"DataThroughTtp"}, "compute_providers": {"SURF"}},
        },
    },
}


@pytest.mark.parametrize(
    "manifest",
    _manifests(),
    ids=_ids(_manifests()),
)
def test_oracle_matches_hypothesis(manifest: Manifest) -> None:
    expected_hypothesis = HYPOTHESIS_TABLE.get(manifest.id)
    if expected_hypothesis is None:
        pytest.skip(f"no hand-coded hypothesis for {manifest.id}")

    expected = derive_expected(manifest)

    assert expected.request_approved == expected_hypothesis["request_approved"], (
        f"{manifest.id}: oracle request_approved={expected.request_approved}, "
        f"hypothesis={expected_hypothesis['request_approved']}"
    )
    assert set(expected.invalid_dataproviders) == expected_hypothesis["invalid"], (
        f"{manifest.id}: invalid_dataproviders mismatch"
    )
    expected_valid_keys = set(expected_hypothesis["valid"].keys())  # type: ignore[union-attr]
    actual_valid_keys = set(expected.valid_dataproviders.keys())
    assert actual_valid_keys == expected_valid_keys, (
        f"{manifest.id}: valid_dataproviders keys mismatch "
        f"oracle={actual_valid_keys} hypothesis={expected_valid_keys}"
    )
    for steward, body in expected_hypothesis["valid"].items():  # type: ignore[union-attr]
        outcome = expected.valid_dataproviders[steward]
        assert set(outcome.archetypes) == body["archetypes"], (  # type: ignore[index]
            f"{manifest.id}/{steward}: archetypes mismatch"
        )
        assert set(outcome.compute_providers) == body["compute_providers"], (  # type: ignore[index]
            f"{manifest.id}/{steward}: compute_providers mismatch"
        )


def test_regression_in_agreement_flips_oracle(tmp_path: Path) -> None:
    """Phase-1 regression guard.

    Mutate ``agreement_UVA.eflint`` so Niels can no longer use DataThroughTtp,
    and confirm the oracle for ``scenario_01_approved`` reflects that change
    (UVA archetypes lose ``DataThroughTtp``).
    """
    src_scenarios = default_scenarios_dir()
    work = tmp_path / "scenarios"
    shutil.copytree(src_scenarios, work)

    uva = work / "agreement_UVA.eflint"
    text = uva.read_text()
    target = "+relation-allows-archetype(\"Niels\", \"UVA\", \"DataThroughTtp\")."
    assert target in text, "test fixture must contain the line we mutate"
    uva.write_text(text.replace(target, f"// REGRESSED: {target}"))

    # Re-load the manifest from the mutated tree.
    manifest = load_manifest(work / "manifests" / "scenario_01_approved.yaml")
    expected = derive_expected(manifest)

    uva_outcome = expected.valid_dataproviders["UVA"]
    assert "DataThroughTtp" not in uva_outcome.archetypes, (
        "regression should have removed DataThroughTtp from UVA's archetype set"
    )
    assert "ComputeToData" in uva_outcome.archetypes, (
        "ComputeToData should still hold after the targeted regression"
    )


# ---------------------------------------------------------------------------
# Integration: requires a live DYNAMOS environment
# ---------------------------------------------------------------------------


def _integration_available() -> tuple[bool, str]:
    seeder = EtcdSeeder()
    client = PolicyEnforcerClient()
    try:
        etcd_ok = seeder.health()
        sut_ok = client.health()
    finally:
        seeder.close()
        client.close()
    if not etcd_ok:
        return False, f"etcd not reachable at {seeder.base_url}"
    if not sut_ok:
        return False, f"Policy Enforcer not reachable at {client.base_url}"
    return True, ""


@pytest.fixture(scope="session")
def integration_env() -> None:
    ok, reason = _integration_available()
    if not ok:
        pytest.skip(reason)


@pytest.mark.integration
@pytest.mark.parametrize(
    "manifest",
    _manifests(),
    ids=_ids(_manifests()),
)
def test_scenario_end_to_end(manifest: Manifest, integration_env: None) -> None:
    result = run_scenario(manifest)
    assert result.ok, f"\n{result.render()}"
