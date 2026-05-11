"""Idempotent etcd seeder for the DYNAMOS Policy Enforcer test fixtures.

The Policy Enforcer reads its Layer-2 inputs fresh on every evaluation from
these etcd keys (see DYNAMOS/docs/development_guide/policy_enforcer.md §8.3):

    /policyEnforcer/eflintRules/shared        ← Layer-2 shared rules
    /policyEnforcer/eflintModels/{steward}    ← per-steward Layer-2 eFLINT
    /policyEnforcer/configs/{steward}         ← validationStrategy=eflint

Layer-1 is embedded in the binary and the eFLINT pool restarts each entry on
release, so the seeder only needs to overwrite these three groups of keys;
the next ``/api/v1/policy-enforcer/validate`` call picks them up.

We talk to etcd through its HTTP JSON gateway (``/v3/kv/put``) so the harness
only depends on httpx, not on a server-version-specific etcd client.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from harness.manifest import Manifest


SHARED_RULES_KEY = "/policyEnforcer/eflintRules/shared"
EFLINT_MODEL_KEY_PREFIX = "/policyEnforcer/eflintModels/"
PROVIDER_CONFIG_KEY_PREFIX = "/policyEnforcer/configs/"

DEFAULT_ETCD_URL = "http://localhost:30005"


@dataclass(frozen=True)
class SeedResult:
    shared_rules_key: str
    model_keys: tuple[str, ...]
    config_keys: tuple[str, ...]

    def keys(self) -> list[str]:
        return [self.shared_rules_key, *self.model_keys, *self.config_keys]


class EtcdSeederError(RuntimeError):
    pass


class EtcdSeeder:
    """Writes Layer-2 fixtures into the running DYNAMOS etcd over HTTP.

    The base URL defaults to ``http://localhost:30005`` (the local DYNAMOS
    config in DYNAMOS/go/cmd/policy-enforcer/config_local.go); override via
    ``DYNAMOS_ETCD_URL`` or the constructor argument.
    """

    def __init__(self, base_url: str | None = None, *, timeout_s: float = 5.0) -> None:
        self.base_url = (base_url or os.environ.get("DYNAMOS_ETCD_URL") or DEFAULT_ETCD_URL).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def __enter__(self) -> "EtcdSeeder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> bool:
        """Probe ``/v3/maintenance/status``; True if etcd answers."""
        try:
            r = self._client.post("/v3/maintenance/status", json={})
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def put(self, key: str, value: str) -> None:
        body = {
            "key": _b64(key),
            "value": _b64(value),
        }
        r = self._client.post("/v3/kv/put", json=body)
        if r.status_code != 200:
            raise EtcdSeederError(
                f"etcd PUT {key} failed: status={r.status_code} body={r.text[:300]}"
            )

    def get(self, key: str) -> str | None:
        body = {"key": _b64(key)}
        r = self._client.post("/v3/kv/range", json=body)
        if r.status_code != 200:
            raise EtcdSeederError(
                f"etcd RANGE {key} failed: status={r.status_code} body={r.text[:300]}"
            )
        data = r.json()
        kvs = data.get("kvs")
        if not kvs:
            return None
        # v3 JSON gateway base64-encodes both keys and values.
        return _b64_decode(kvs[0]["value"])

    def delete(self, key: str) -> None:
        body = {"key": _b64(key)}
        r = self._client.post("/v3/kv/deleterange", json=body)
        if r.status_code != 200:
            raise EtcdSeederError(
                f"etcd DELETE {key} failed: status={r.status_code} body={r.text[:300]}"
            )

    def seed_manifest(self, manifest: Manifest) -> SeedResult:
        """Write the manifest's fixtures into etcd. Overwrites idempotently."""
        shared_text = Path(manifest.shared_rules_file).read_text()
        self.put(SHARED_RULES_KEY, shared_text)

        model_keys: list[str] = []
        config_keys: list[str] = []
        for steward, path in manifest.agreement_files.items():
            model_key = f"{EFLINT_MODEL_KEY_PREFIX}{steward}"
            self.put(model_key, Path(path).read_text())
            model_keys.append(model_key)

            cfg_key = f"{PROVIDER_CONFIG_KEY_PREFIX}{steward}"
            cfg = {
                "name": steward,
                "validationStrategy": "eflint",
                "agreementLocation": f"/app/eflint-models/{steward}.eflint",
            }
            self.put(cfg_key, json.dumps(cfg))
            config_keys.append(cfg_key)

        # Stewards in the request but without a per-manifest agreement should
        # NOT have a leftover config from a previous run, otherwise the
        # Policy Enforcer would treat them as eFLINT-format and fail to load
        # an agreement they were supposed to be missing.
        for steward in manifest.stewards:
            if steward in manifest.agreement_files:
                continue
            cfg_key = f"{PROVIDER_CONFIG_KEY_PREFIX}{steward}"
            model_key = f"{EFLINT_MODEL_KEY_PREFIX}{steward}"
            self.delete(cfg_key)
            self.delete(model_key)

        return SeedResult(
            shared_rules_key=SHARED_RULES_KEY,
            model_keys=tuple(model_keys),
            config_keys=tuple(config_keys),
        )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_decode(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")
