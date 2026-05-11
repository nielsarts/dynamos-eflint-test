"""Oracle: derive the expected ValidationResponse for a scenario.

The oracle does NOT read the SUT. It loads the Layer-1 interface, Layer-2
shared rules, and per-steward agreements into a fresh eflint-repl, plants the
Layer-3 facts derived from the manifest's ``request`` block, and then asks
``Invariant q_X When pred(...).`` for every predicate it needs to project.

The result is shaped exactly like the JSON ``ValidationResponse`` returned by
``POST /api/v1/policy-enforcer/validate``.
"""
from __future__ import annotations

import itertools
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.eflint_flatten import flatten_files
from harness.eflint_repl import EflintRepl
from harness.manifest import Manifest


# Used to confirm an invariant holds (eflint-repl emits a "+q_X()" effect
# line). Its absence — combined with a "violated invariant!: q_X" line —
# tells us the predicate is false.
VIOLATED_RE = re.compile(r"violated invariant!: (?P<name>\w+)")


@dataclass(frozen=True)
class StewardOutcome:
    permitted_at_steward: bool
    archetypes: tuple[str, ...]
    compute_providers: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedValidationResponse:
    """Canonical projection of the eFLINT reasoner result.

    Matches the subset of ``pb.ValidationResponse`` we compare against.
    """
    request_approved: bool
    user_id: str
    user_name: str
    valid_dataproviders: dict[str, StewardOutcome]
    invalid_dataproviders: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        """Round-trippable dict shaped like the SUT's ValidationResponse."""
        valid: dict[str, dict[str, list[str]]] = {}
        for steward, outcome in self.valid_dataproviders.items():
            valid[steward] = {
                "archetypes": sorted(outcome.archetypes),
                "compute_providers": sorted(outcome.compute_providers),
            }
        return {
            "request_approved": self.request_approved,
            "user": {"id": self.user_id, "user_name": self.user_name},
            "valid_dataproviders": valid,
            "invalid_dataproviders": sorted(self.invalid_dataproviders),
        }


def derive_expected(manifest: Manifest) -> ExpectedValidationResponse:
    """Run the oracle for the given manifest and return the expected response."""
    archetypes, providers = _candidate_universe(manifest)

    fixture_phrases = flatten_files(manifest.fixture_eflint_files())
    layer3_phrases = _layer3_phrases(manifest.requester, manifest.stewards)

    # We submit each query Invariant individually and inspect its OWN output
    # for the matching "violated invariant!: <name>" line. The per-submit
    # output reliably contains this line at declaration time; relying on
    # ``:display`` is unsafe because ``:display`` is a REPL meta-command
    # that bypasses the sentinel-trigger protocol.
    holds_results: dict[str, bool] = {}

    def query(qname: str, phrase: str, repl: EflintRepl) -> None:
        out = repl.submit(phrase)
        # An invariant DOES NOT hold iff the SAME-submission output
        # contains "violated invariant!: <qname>".
        holds_results[qname] = not _violated_in(out, qname)

    with EflintRepl(include_dirs=[manifest.scenarios_dir]) as repl:
        repl.submit_many(fixture_phrases)
        repl.submit_many(layer3_phrases)

        gen = _NameGen()
        permitted_request_q = gen.next("perm_req")
        per_steward_perm: dict[str, str] = {}
        per_steward_archetypes: dict[str, dict[str, str]] = {}
        per_steward_providers: dict[str, dict[str, str]] = {}

        query(
            permitted_request_q,
            f"Invariant {permitted_request_q} When permitted-request({_quote(manifest.requester)}).",
            repl,
        )
        for steward in manifest.stewards:
            qname = gen.next(f"perm_{_sanitize(steward)}")
            per_steward_perm[steward] = qname
            query(
                qname,
                f"Invariant {qname} When permitted-at-steward({_quote(manifest.requester)}, {_quote(steward)}).",
                repl,
            )

        for steward in manifest.stewards:
            per_steward_archetypes[steward] = {}
            for arch in archetypes:
                qname = gen.next(f"arch_{_sanitize(steward)}_{_sanitize(arch)}")
                per_steward_archetypes[steward][arch] = qname
                query(
                    qname,
                    f"Invariant {qname} When valid-archetype({_quote(manifest.requester)}, {_quote(steward)}, {_quote(arch)}).",
                    repl,
                )

        for steward in manifest.stewards:
            per_steward_providers[steward] = {}
            for prov in providers:
                qname = gen.next(f"cp_{_sanitize(steward)}_{_sanitize(prov)}")
                per_steward_providers[steward][prov] = qname
                query(
                    qname,
                    f"Invariant {qname} When valid-compute-provider({_quote(manifest.requester)}, {_quote(steward)}, {_quote(prov)}).",
                    repl,
                )

    def holds(qname: str) -> bool:
        if qname not in holds_results:
            raise RuntimeError(f"oracle never queried invariant {qname!r}")
        return holds_results[qname]

    request_approved = holds(permitted_request_q)
    valid_dp: dict[str, StewardOutcome] = {}
    invalid_dp: list[str] = []
    for steward in manifest.stewards:
        permitted_here = holds(per_steward_perm[steward])
        if not permitted_here:
            invalid_dp.append(steward)
            continue
        arch_names = tuple(
            a for a, q in per_steward_archetypes[steward].items() if holds(q)
        )
        prov_names = tuple(
            p for p, q in per_steward_providers[steward].items() if holds(q)
        )
        valid_dp[steward] = StewardOutcome(
            permitted_at_steward=True,
            archetypes=arch_names,
            compute_providers=prov_names,
        )

    return ExpectedValidationResponse(
        request_approved=request_approved,
        user_id=manifest.request.user.id,
        user_name=manifest.request.user.user_name,
        valid_dataproviders=valid_dp,
        invalid_dataproviders=tuple(invalid_dp),
    )


def _quote(value: str) -> str:
    """Wrap a runtime value in eFLINT quoted-string syntax.

    eFLINT treats bare atoms as variables and silently discards them; every
    concrete fact instance value must be a quoted string literal so the server
    registers it as a ground term rather than a free variable.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _layer3_phrases(requester: str, stewards: tuple[str, ...]) -> list[str]:
    """Build the Layer-3 facts the Policy Enforcer would build from the HTTP body."""
    phrases = [f"+requester({_quote(requester)})."]
    phrases.extend(f"+requested-steward({_quote(s)})." for s in stewards)
    return phrases


def _candidate_universe(manifest: Manifest) -> tuple[list[str], list[str]]:
    """Return ``(archetypes, compute_providers)`` candidates to probe.

    If the manifest doesn't list them, auto-discover by scanning all agreement
    files for ``+archetype(...)`` and ``+compute-provider(...)`` declarations.
    """
    archetypes = list(manifest.candidates.archetypes)
    providers = list(manifest.candidates.compute_providers)
    if archetypes and providers:
        return archetypes, providers

    arch_re = re.compile(r'\+archetype\(\s*"([^"]+)"\s*\)\s*\.')
    cp_re = re.compile(r'\+compute-provider\(\s*"([^"]+)"\s*\)\s*\.')

    discovered_arch: list[str] = []
    discovered_cp: list[str] = []
    seen_arch: set[str] = set()
    seen_cp: set[str] = set()

    for path in manifest.agreement_files.values():
        text = Path(path).read_text()
        for m in arch_re.finditer(text):
            name = m.group(1)
            if name not in seen_arch:
                seen_arch.add(name)
                discovered_arch.append(name)
        for m in cp_re.finditer(text):
            name = m.group(1)
            if name not in seen_cp:
                seen_cp.add(name)
                discovered_cp.append(name)

    return archetypes or discovered_arch, providers or discovered_cp


def _collect_violated(repl_output: str) -> set[str]:
    return {m.group("name") for m in VIOLATED_RE.finditer(repl_output)}


def _violated_in(repl_output: str, name: str) -> bool:
    """Whether ``repl_output`` reports the invariant ``name`` as violated."""
    return any(m.group("name") == name for m in VIOLATED_RE.finditer(repl_output))


_SANITIZE_RE = re.compile(r"[^A-Za-z]")


def _sanitize(name: str) -> str:
    """Project an arbitrary identifier into ``[a-z]+`` for use in q-names.

    eflint-repl's tokeniser rejects uppercase letters and digits inside bare
    identifiers (``q_x_c2d`` and ``qABCdef`` both fail to parse), so we use
    lowercase ASCII letters only for the generated invariant names.
    Collisions are prevented by a global counter in ``_NameGen``.
    """
    return _SANITIZE_RE.sub("", name).lower() or "x"


class _NameGen:
    """Generates unique bare-letter identifiers like ``q_perm_req_a``.

    The trailing letter sequence cycles through ``a..z, aa..zz, ...`` so that
    sanitising stewards/archetypes into letters cannot collide.
    """

    def __init__(self) -> None:
        self._counter = _letter_counter()

    def next(self, hint: str) -> str:
        suffix = next(self._counter)
        return f"q_{_sanitize(hint)}_{suffix}"


def _letter_counter():
    for n in itertools.count(1):
        for combo in itertools.product(string.ascii_lowercase, repeat=n):
            yield "".join(combo)
