"""HTTP client for the DYNAMOS Policy Enforcer ``validate`` endpoint.

Calls ``POST /api/v1/policy-enforcer/validate`` and returns the parsed
``ValidationResponse`` JSON. The schema lives in
DYNAMOS/docs/openapi/policy-enforcer-openapi.yaml.

The client treats opaque fields (``auth.access_token``, ``auth.refresh_token``)
as opaque — the harness only asserts presence on approved requests, see
``harness.comparator``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from harness.manifest import Manifest


DEFAULT_BASE_URL = "http://policy-enforcer.orchestrator.svc.cluster.local"
VALIDATE_PATH = "/api/v1/policy-enforcer/validate"
HEALTH_PATH = "/api/v1/health"


@dataclass(frozen=True)
class ActualValidationResponse:
    """The Policy Enforcer's response, normalised for comparison.

    Keys match the openapi schema; missing keys default to safe values so
    the comparator can rely on them.
    """
    raw: dict[str, Any]

    @property
    def request_approved(self) -> bool:
        return bool(self.raw.get("request_approved", False))

    @property
    def user_id(self) -> str:
        u = self.raw.get("user") or {}
        return str(u.get("id", ""))

    @property
    def user_name(self) -> str:
        u = self.raw.get("user") or {}
        return str(u.get("user_name", ""))

    @property
    def valid_dataproviders(self) -> dict[str, dict[str, list[str]]]:
        v = self.raw.get("valid_dataproviders") or {}
        out: dict[str, dict[str, list[str]]] = {}
        for steward, body in v.items():
            body = body or {}
            out[steward] = {
                "archetypes": list(body.get("archetypes") or []),
                "compute_providers": list(body.get("compute_providers") or []),
            }
        return out

    @property
    def invalid_dataproviders(self) -> list[str]:
        return list(self.raw.get("invalid_dataproviders") or [])

    @property
    def has_nonempty_auth(self) -> bool:
        auth = self.raw.get("auth") or {}
        return bool(auth.get("access_token")) or bool(auth.get("refresh_token"))


class SutError(RuntimeError):
    pass


class PolicyEnforcerClient:
    """Minimal HTTP client for the Policy Enforcer's policy-engineer endpoints."""

    def __init__(self, base_url: str | None = None, *, timeout_s: float = 10.0) -> None:
        self.base_url = (base_url or os.environ.get("DYNAMOS_POLICY_ENFORCER_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def __enter__(self) -> "PolicyEnforcerClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> bool:
        try:
            r = self._client.get(HEALTH_PATH)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def validate(self, manifest: Manifest) -> ActualValidationResponse:
        return self.validate_payload(manifest.request.to_payload())

    def validate_payload(self, body: dict[str, Any]) -> ActualValidationResponse:
        try:
            r = self._client.post(VALIDATE_PATH, json=body)
        except httpx.HTTPError as e:
            raise SutError(f"validate request failed at the network layer: {e}") from e
        if r.status_code != 200:
            raise SutError(
                f"validate returned status={r.status_code}: {r.text[:500]}"
            )
        try:
            data = r.json()
        except ValueError as e:
            raise SutError(f"validate returned non-JSON body: {r.text[:500]}") from e
        if not isinstance(data, dict):
            raise SutError(f"validate returned non-object body: {data!r}")
        return ActualValidationResponse(raw=data)
