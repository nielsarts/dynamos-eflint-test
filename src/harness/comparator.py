"""Compare an expected oracle projection against the SUT's response.

The comparator normalises both sides before comparing:

- ``request_approved``: bool equality
- ``valid_dataproviders``: keys treated as a set; per-steward
  ``archetypes`` / ``compute_providers`` treated as sets
- ``invalid_dataproviders``: set equality
- ``auth_present_when_approved`` (opt-in via the manifest): when the oracle
  says ``request_approved == true``, the SUT must include non-empty
  ``auth.access_token`` and/or ``auth.refresh_token``. Token VALUES are
  never compared.

Unspecified fields (``type``, ``request_type``, ``valid_archetypes``,
``options``, ``auth`` content beyond presence, ``user.id``) are ignored
unless explicitly enabled in the manifest's ``assertions`` list.

The diff renderer emits per-steward output so failures are easy to debug.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from harness._fmt import bold, dim, green, red
from harness.manifest import Manifest
from harness.oracle import ExpectedValidationResponse
from harness.sut_client import ActualValidationResponse


@dataclass(frozen=True)
class FieldDiff:
    field: str
    expected: object
    actual: object
    ok: bool
    note: str = ""

    def render(self, indent: str = "") -> str:
        tick   = green("✓") if self.ok else red("✗")
        status = green("OK") if self.ok else red("MISMATCH")
        note   = dim(f"  [{self.note}]") if self.note else ""
        return (
            f"{indent}{tick} {self.field:25}"
            f" expected={_fmt(self.expected):<40}"
            f" actual={_fmt(self.actual):<40}"
            f" {status}{note}"
        )


@dataclass
class StewardDiff:
    steward: str
    diffs: list[FieldDiff] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(d.ok for d in self.diffs)

    def render(self, indent: str = "  ") -> str:
        label  = bold(self.steward)
        suffix = f"  {red('[MISMATCH]')}" if not self.ok else ""
        lines  = [f"{indent}{label}:{suffix}"]
        for d in self.diffs:
            lines.append(d.render(indent + "  "))
        return "\n".join(lines)


@dataclass
class ComparisonResult:
    scenario_id: str
    ok: bool
    field_diffs: list[FieldDiff] = field(default_factory=list)
    steward_diffs: list[StewardDiff] = field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = []
        for d in self.field_diffs:
            lines.append(d.render("  "))
        if self.steward_diffs:
            lines.append(dim("  valid_dataproviders (per steward):"))
            for sd in self.steward_diffs:
                lines.append(sd.render("    "))
        return "\n".join(lines)


def compare(
    manifest: Manifest,
    expected: ExpectedValidationResponse,
    actual: ActualValidationResponse,
) -> ComparisonResult:
    """Apply the manifest's selected assertions to expected vs actual."""
    asserts = manifest.assertions
    field_diffs: list[FieldDiff] = []
    steward_diffs: list[StewardDiff] = []

    if "request_approved" in asserts:
        field_diffs.append(
            FieldDiff(
                field="request_approved",
                expected=expected.request_approved,
                actual=actual.request_approved,
                ok=expected.request_approved == actual.request_approved,
            )
        )

    if "invalid_dataproviders" in asserts:
        exp_set = set(expected.invalid_dataproviders)
        act_set = set(actual.invalid_dataproviders)
        field_diffs.append(
            FieldDiff(
                field="invalid_dataproviders",
                expected=sorted(exp_set),
                actual=sorted(act_set),
                ok=exp_set == act_set,
                note="set equality",
            )
        )

    if "valid_dataproviders" in asserts:
        exp_keys = set(expected.valid_dataproviders.keys())
        act_keys = set(actual.valid_dataproviders.keys())
        keys_ok = exp_keys == act_keys
        field_diffs.append(
            FieldDiff(
                field="valid_dataproviders.keys",
                expected=sorted(exp_keys),
                actual=sorted(act_keys),
                ok=keys_ok,
                note="set equality on stewards",
            )
        )
        for steward in sorted(exp_keys | act_keys):
            sd = StewardDiff(steward=steward)
            exp = expected.valid_dataproviders.get(steward)
            act = actual.valid_dataproviders.get(steward)
            exp_arch = set(exp.archetypes) if exp else set()
            act_arch = set((act or {}).get("archetypes", []))
            sd.diffs.append(
                FieldDiff(
                    field="archetypes",
                    expected=sorted(exp_arch),
                    actual=sorted(act_arch),
                    ok=exp_arch == act_arch,
                    note="set equality",
                )
            )
            exp_cp = set(exp.compute_providers) if exp else set()
            act_cp = set((act or {}).get("compute_providers", []))
            sd.diffs.append(
                FieldDiff(
                    field="compute_providers",
                    expected=sorted(exp_cp),
                    actual=sorted(act_cp),
                    ok=exp_cp == act_cp,
                    note="set equality",
                )
            )
            steward_diffs.append(sd)

    if "auth_present_when_approved" in asserts and expected.request_approved:
        ok = actual.request_approved and actual.has_nonempty_auth
        field_diffs.append(
            FieldDiff(
                field="auth_present",
                expected="non-empty when approved",
                actual="present" if actual.has_nonempty_auth else "missing/empty",
                ok=ok,
                note="masked: token values not compared",
            )
        )

    overall_ok = all(d.ok for d in field_diffs) and all(sd.ok for sd in steward_diffs)
    return ComparisonResult(
        scenario_id=manifest.id,
        ok=overall_ok,
        field_diffs=field_diffs,
        steward_diffs=steward_diffs,
    )


def _fmt(v: object) -> str:
    if isinstance(v, set):
        return repr(sorted(v))
    if isinstance(v, list):
        return repr(v)
    return repr(v)
