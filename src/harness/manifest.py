"""Scenario manifest schema and loader.

Each scenario has a YAML manifest under ``dynamos-test-scenarios/manifests/``
describing the eFLINT files to load, the HTTP request to send to the Policy
Enforcer, the queries the oracle should ask, and which fields of the
ValidationResponse to compare.

The manifest is the only place identifiers are restated; the oracle does NOT
hand-code the expected archetypes/compute-providers, it projects them from
``?Holds(...)`` results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


SCENARIOS_DIR_NAME = "dynamos-test-scenarios"
MANIFESTS_SUBDIR = "manifests"

DEFAULT_INTERFACE_FILE = "01_interface_policy.eflint"
DEFAULT_SHARED_RULES_FILE = "02_agreement_rules.eflint"

VALID_ASSERTIONS = {
    "request_approved",
    "valid_dataproviders",
    "invalid_dataproviders",
    "auth_present_when_approved",
}


class ManifestError(ValueError):
    """Raised when a manifest fails to load or validate."""


@dataclass(frozen=True)
class RequestUser:
    id: str
    user_name: str


@dataclass(frozen=True)
class Request:
    """The body of POST /api/v1/policy-enforcer/validate for this scenario."""
    user: RequestUser
    data_providers: tuple[str, ...]
    type: str | None = None
    options: dict[str, bool] | None = None

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user": {"id": self.user.id, "user_name": self.user.user_name},
            "data_providers": list(self.data_providers),
        }
        if self.type is not None:
            body["type"] = self.type
        if self.options is not None:
            body["options"] = dict(self.options)
        return body


@dataclass(frozen=True)
class Candidates:
    """Universe of archetypes / compute providers the oracle will probe.

    If empty, the oracle auto-discovers candidates by scanning the loaded
    agreement files for ``+archetype(...)`` and ``+compute-provider(...)``
    declarations.
    """
    archetypes: tuple[str, ...] = ()
    compute_providers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Manifest:
    """A fully-parsed scenario manifest, with all paths resolved to absolute
    locations under the scenarios directory.
    """
    id: str
    description: str
    suite: str
    hypothesis: str | None

    scenario_file: Path
    interface_file: Path
    shared_rules_file: Path
    agreement_files: dict[str, Path]

    request: Request
    candidates: Candidates
    assertions: frozenset[str]

    scenarios_dir: Path
    manifest_path: Path

    @property
    def requester(self) -> str:
        """Convenience: the eFLINT identifier used as ``+requester(...)``."""
        return self.request.user.user_name

    @property
    def stewards(self) -> tuple[str, ...]:
        return self.request.data_providers

    def all_eflint_files(self) -> list[Path]:
        """All eFLINT files in load order, suitable for eflint-test.py."""
        files = [self.interface_file, self.shared_rules_file]
        files.extend(self.agreement_files[s] for s in sorted(self.agreement_files))
        files.append(self.scenario_file)
        return files

    def fixture_eflint_files(self) -> list[Path]:
        """eFLINT files the oracle loads (no scenario file, no #require
        directives). The oracle builds Layer-3 facts itself from the request.
        """
        return [
            self.interface_file,
            self.shared_rules_file,
            *(self.agreement_files[s] for s in sorted(self.agreement_files)),
        ]


def _require(d: dict[str, Any], key: str, *, where: str) -> Any:
    if key not in d:
        raise ManifestError(f"{where}: missing required field '{key}'")
    return d[key]


def _resolve(scenarios_dir: Path, relpath: str, *, where: str) -> Path:
    p = (scenarios_dir / relpath).resolve()
    if not p.is_file():
        raise ManifestError(f"{where}: file not found: {p}")
    return p


def load_manifest(path: str | Path) -> Manifest:
    """Load and validate a scenario manifest from a YAML file."""
    manifest_path = Path(path).resolve()
    if not manifest_path.is_file():
        raise ManifestError(f"manifest file not found: {manifest_path}")

    scenarios_dir = manifest_path.parent
    if scenarios_dir.name == MANIFESTS_SUBDIR:
        scenarios_dir = scenarios_dir.parent

    with manifest_path.open() as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: top-level YAML must be a mapping")

    where = str(manifest_path)
    mid = _require(raw, "id", where=where)
    description = raw.get("description", "")
    suite = _require(raw, "suite", where=where)
    if suite not in {"approval", "continuation"}:
        raise ManifestError(f"{where}: suite must be 'approval' or 'continuation', got {suite!r}")
    hypothesis = raw.get("hypothesis")

    scenario_rel = _require(raw, "scenario_file", where=where)
    interface_rel = raw.get("interface_file", DEFAULT_INTERFACE_FILE)
    shared_rules_rel = raw.get("shared_rules_file", DEFAULT_SHARED_RULES_FILE)

    scenario_file = _resolve(scenarios_dir, scenario_rel, where=where)
    interface_file = _resolve(scenarios_dir, interface_rel, where=where)
    shared_rules_file = _resolve(scenarios_dir, shared_rules_rel, where=where)

    raw_agreements = raw.get("agreement_files", {}) or {}
    if not isinstance(raw_agreements, dict):
        raise ManifestError(f"{where}: agreement_files must be a mapping {{steward: file}}")
    agreement_files: dict[str, Path] = {}
    for steward, rel in raw_agreements.items():
        agreement_files[str(steward)] = _resolve(scenarios_dir, rel, where=where)

    raw_request = _require(raw, "request", where=where)
    if not isinstance(raw_request, dict):
        raise ManifestError(f"{where}: request must be a mapping")
    raw_user = _require(raw_request, "user", where=where)
    if not isinstance(raw_user, dict):
        raise ManifestError(f"{where}: request.user must be a mapping")
    raw_dataproviders = _require(raw_request, "data_providers", where=where)
    if not isinstance(raw_dataproviders, list) or not raw_dataproviders:
        raise ManifestError(f"{where}: request.data_providers must be a non-empty list")

    request = Request(
        user=RequestUser(
            id=str(_require(raw_user, "id", where=where)),
            user_name=str(_require(raw_user, "user_name", where=where)),
        ),
        data_providers=tuple(str(s) for s in raw_dataproviders),
        type=str(raw_request["type"]) if raw_request.get("type") is not None else None,
        options=dict(raw_request["options"]) if isinstance(raw_request.get("options"), dict) else None,
    )

    raw_candidates = raw.get("candidates", {}) or {}
    candidates = Candidates(
        archetypes=tuple(str(a) for a in raw_candidates.get("archetypes", []) or []),
        compute_providers=tuple(str(c) for c in raw_candidates.get("compute_providers", []) or []),
    )

    raw_assertions = raw.get("assertions") or list(VALID_ASSERTIONS)
    if not isinstance(raw_assertions, list):
        raise ManifestError(f"{where}: assertions must be a list")
    assertions = frozenset(str(a) for a in raw_assertions)
    unknown = assertions - VALID_ASSERTIONS
    if unknown:
        raise ManifestError(
            f"{where}: unknown assertion(s): {sorted(unknown)}; valid: {sorted(VALID_ASSERTIONS)}"
        )

    return Manifest(
        id=str(mid),
        description=str(description),
        suite=str(suite),
        hypothesis=str(hypothesis) if hypothesis is not None else None,
        scenario_file=scenario_file,
        interface_file=interface_file,
        shared_rules_file=shared_rules_file,
        agreement_files=agreement_files,
        request=request,
        candidates=candidates,
        assertions=assertions,
        scenarios_dir=scenarios_dir.resolve(),
        manifest_path=manifest_path,
    )


def discover_manifests(scenarios_dir: str | Path) -> list[Manifest]:
    """Find all manifests under ``<scenarios_dir>/manifests/*.yaml``."""
    base = Path(scenarios_dir).resolve()
    manifests_dir = base / MANIFESTS_SUBDIR
    if not manifests_dir.is_dir():
        return []
    out: list[Manifest] = []
    for path in sorted(manifests_dir.glob("*.yaml")):
        out.append(load_manifest(path))
    return out


def default_scenarios_dir() -> Path:
    """Return ``<repo_root>/dynamos-test-scenarios`` based on this file's location."""
    return Path(__file__).resolve().parents[2] / SCENARIOS_DIR_NAME
