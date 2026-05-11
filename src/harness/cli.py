"""CLI entry point for the harness.

Usage:

    harness run [<scenario-id>...]            Run scenarios end-to-end.
    harness oracle <scenario-id>              Print the oracle's expected JSON.
    harness consistency <scenario-id>         Run only the self-test gate.
    harness seed <scenario-id>                Only seed etcd with the scenario fixtures.
    harness list                              List discovered manifests.

If no scenario IDs are given to ``run``, all discovered manifests run.
Configuration:

- ``EFLINT_REPL_EXE``           path to eflint-repl (default: "eflint-repl")
- ``EFLINT_TEST_PY``            path to eflint-test.py (default: <root>/eflint-test.py)
- ``DYNAMOS_ETCD_URL``          base URL for etcd (default: http://localhost:30005)
- ``DYNAMOS_POLICY_ENFORCER_URL`` base URL for the SUT (default: http://localhost:8082)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable

from harness.etcd_seeder import EtcdSeeder
from harness.manifest import (
    Manifest,
    default_scenarios_dir,
    discover_manifests,
    load_manifest,
)
from harness.oracle import derive_expected
from harness.runner import RunOptions, run_scenario
from harness.scenario_consistency import check_scenario_consistency


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness", description=__doc__)
    p.add_argument(
        "--scenarios-dir",
        default=str(default_scenarios_dir()),
        help="Override the scenarios directory (default: %(default)s)",
    )
    p.add_argument("--etcd-url", default=None, help="Override DYNAMOS_ETCD_URL.")
    p.add_argument("--sut-url", default=None, help="Override DYNAMOS_POLICY_ENFORCER_URL.")

    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List discovered scenario manifests.")

    p_oracle = sub.add_parser("oracle", help="Print the oracle's expected response.")
    p_oracle.add_argument("scenario_id")

    p_cons = sub.add_parser("consistency", help="Run the eflint-test.py self-test gate.")
    p_cons.add_argument("scenario_id")

    p_seed = sub.add_parser("seed", help="Seed etcd with the scenario's fixtures.")
    p_seed.add_argument("scenario_id")

    p_run = sub.add_parser("run", help="End-to-end run of one or more scenarios.")
    p_run.add_argument("scenario_ids", nargs="*", help="Scenario IDs (default: all discovered).")
    p_run.add_argument("--no-consistency", action="store_true", help="Skip the self-test gate.")
    p_run.add_argument("--no-seed", action="store_true", help="Skip etcd seeding.")
    p_run.add_argument("--no-sut", action="store_true", help="Stop after seeding; do not call SUT.")

    args = p.parse_args(argv)
    scenarios_dir = args.scenarios_dir
    manifests = {m.id: m for m in discover_manifests(scenarios_dir)}

    if args.command == "list":
        return _cmd_list(manifests.values())
    if args.command == "oracle":
        return _cmd_oracle(_resolve_one(manifests, args.scenario_id))
    if args.command == "consistency":
        return _cmd_consistency(_resolve_one(manifests, args.scenario_id))
    if args.command == "seed":
        return _cmd_seed(_resolve_one(manifests, args.scenario_id), args.etcd_url)
    if args.command == "run":
        chosen = (
            [_resolve_one(manifests, sid) for sid in args.scenario_ids]
            if args.scenario_ids
            else list(manifests.values())
        )
        opts = RunOptions(
            skip_consistency_gate=args.no_consistency,
            skip_seeding=args.no_seed,
            skip_sut=args.no_sut,
            etcd_base_url=args.etcd_url,
            sut_base_url=args.sut_url,
        )
        return _cmd_run(chosen, opts)

    p.error(f"unknown command: {args.command}")
    return 2  # unreachable


def _resolve_one(manifests: dict[str, Manifest], scenario_id: str) -> Manifest:
    if scenario_id in manifests:
        return manifests[scenario_id]
    raise SystemExit(
        f"unknown scenario id: {scenario_id!r}; known: {sorted(manifests)}"
    )


def _cmd_list(manifests: Iterable[Manifest]) -> int:
    for m in sorted(manifests, key=lambda x: x.id):
        flag = m.hypothesis or "-"
        print(f"{m.id:50} [{m.suite:12} {flag}] {m.description}")
    return 0


def _cmd_oracle(m: Manifest) -> int:
    expected = derive_expected(m)
    print(json.dumps(expected.to_json(), indent=2, sort_keys=True))
    return 0


def _cmd_consistency(m: Manifest) -> int:
    r = check_scenario_consistency(m)
    print(r.render())
    return 0 if r.consistent else 1


def _cmd_seed(m: Manifest, etcd_url: str | None) -> int:
    with EtcdSeeder(base_url=etcd_url) as seeder:
        if not seeder.health():
            print(f"etcd not reachable at {seeder.base_url}", file=sys.stderr)
            return 1
        seed = seeder.seed_manifest(m)
    for k in seed.keys():
        print(f"PUT {k}")
    return 0


def _cmd_run(manifests: list[Manifest], options: RunOptions) -> int:
    overall_ok = True
    for i, m in enumerate(manifests):
        result = run_scenario(m, options=options)
        if i > 0:
            print()
        print(result.render())
        if not result.ok:
            overall_ok = False
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
