"""Per-scenario orchestration.

The runner threads a single scenario manifest through:

    1. ``scenario_consistency``: gate on the scenario's own ``//#violated``
       and ``//#assert`` comments. If the scenario disagrees with itself,
       the harness reports ``inconsistent`` and does NOT consult the SUT.
    2. ``oracle``: derive the expected ValidationResponse from eflint-repl.
    3. ``etcd_seeder``: write Layer-2 fixtures into the live DYNAMOS etcd.
    4. ``sut_client``: call ``POST /api/v1/policy-enforcer/validate``.
    5. ``comparator``: compute a per-steward diff against the expected
       projection.

Each phase can be skipped via the ``RunOptions`` flags so the CLI can do
``oracle``-only or ``seed``-only runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from harness._fmt import bold_cyan, bold_green, bold_red, bold_yellow, dim, red
from harness.comparator import ComparisonResult, compare
from harness.etcd_seeder import EtcdSeeder, SeedResult
from harness.manifest import Manifest
from harness.oracle import ExpectedValidationResponse, derive_expected
from harness.scenario_consistency import ConsistencyResult, check_scenario_consistency
from harness.sut_client import ActualValidationResponse, PolicyEnforcerClient

_OUTCOME_COLOR = {
    "pass":         bold_green,
    "fail":         bold_red,
    "error":        bold_red,
    "inconsistent": bold_yellow,
}


Outcome = Literal["pass", "fail", "inconsistent", "error", "skipped"]


@dataclass
class RunOptions:
    skip_consistency_gate: bool = False
    skip_seeding: bool = False
    skip_sut: bool = False
    etcd_base_url: str | None = None
    sut_base_url: str | None = None


@dataclass
class ScenarioResult:
    scenario_id: str
    outcome: Outcome
    consistency: ConsistencyResult | None = None
    expected: ExpectedValidationResponse | None = None
    seed: SeedResult | None = None
    actual: ActualValidationResponse | None = None
    comparison: ComparisonResult | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "pass"

    def render(self) -> str:
        color_fn     = _OUTCOME_COLOR.get(self.outcome, dim)
        outcome_str  = color_fn(self.outcome.upper())
        title        = bold_cyan(self.scenario_id)
        lines        = [f"─── {title} ─── {outcome_str}"]

        if self.consistency is not None and not self.consistency.consistent:
            lines.append(self.consistency.render())
        if self.expected is not None:
            lines.append(dim(f"  oracle  {self.expected.to_json()}"))
        if self.seed is not None:
            lines.append(dim(f"  seeded  {', '.join(self.seed.keys())}"))
        if self.actual is not None:
            lines.append(dim(f"  sut     {self.actual.raw}"))
        if self.comparison is not None:
            lines.append(self.comparison.render())
        if self.error is not None:
            lines.append(f"  {red('error:')} {self.error}")
        return "\n".join(lines)


def run_scenario(
    manifest: Manifest,
    *,
    options: RunOptions | None = None,
) -> ScenarioResult:
    """Run one scenario end-to-end and return the structured result."""
    opts = options or RunOptions()
    result = ScenarioResult(scenario_id=manifest.id, outcome="skipped")

    try:
        if not opts.skip_consistency_gate:
            cr = check_scenario_consistency(manifest)
            result.consistency = cr
            if not cr.consistent:
                result.outcome = "inconsistent"
                return result

        result.expected = derive_expected(manifest)

        if not opts.skip_seeding:
            with EtcdSeeder(base_url=opts.etcd_base_url) as seeder:
                if not seeder.health():
                    result.outcome = "error"
                    result.error = (
                        f"etcd not reachable at {seeder.base_url}; "
                        "set DYNAMOS_ETCD_URL or pass --etcd-url"
                    )
                    return result
                result.seed = seeder.seed_manifest(manifest)

        if opts.skip_sut:
            result.outcome = "skipped"
            return result

        with PolicyEnforcerClient(base_url=opts.sut_base_url) as client:
            if not client.health():
                result.outcome = "error"
                result.error = (
                    f"Policy Enforcer not reachable at {client.base_url}; "
                    "set DYNAMOS_POLICY_ENFORCER_URL or pass --sut-url"
                )
                return result
            result.actual = client.validate(manifest)

        result.comparison = compare(manifest, result.expected, result.actual)
        result.outcome = "pass" if result.comparison.ok else "fail"
        return result
    except Exception as e:  # noqa: BLE001 - we deliberately catch broadly
        result.outcome = "error"
        result.error = f"{type(e).__name__}: {e}"
        return result
