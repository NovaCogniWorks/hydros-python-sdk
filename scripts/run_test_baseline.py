#!/usr/bin/env python3
"""Run Hydros Python SDK test baselines."""

from __future__ import annotations

import argparse
import compileall
import importlib
import inspect
import os
import pathlib
import sys
import unittest
from typing import Iterable, List, Sequence


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"

OPTIONAL_DEPENDENCY_TEST_MODULES = {
    "test_hydrosim_demo",
    "test_power_outflowplan_power_agent",
    "test_pump_dynamic_demand_plan",
    "test_pump_scheduling_agent",
}

CENTRAL_EVENT_TESTS = [
    "tests.test_central_scheduling_event_injection",
]

CENTRAL_DIRECT_TESTS = [
    "tests.test_agent_commands_refactor.AgentCommandsRefactorTest."
    "test_central_scheduling_agent_activates_mpc_on_time_series_update",
    "tests.test_agent_commands_refactor.AgentCommandsRefactorTest."
    "test_central_scheduling_agent_fails_without_rolling_config",
]

RELATED_ROUTER_TESTS = [
    "tests.test_coordination_client_dispatch",
    "tests.test_multi_agent_callback",
]


def discover_test_module_names(excluded_modules: Iterable[str] = ()) -> List[str]:
    excluded = set(excluded_modules)
    return [
        f"tests.{path.stem}"
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if path.stem not in excluded
    ]


def names_for_mode(mode: str) -> List[str]:
    if mode == "central-events":
        return list(CENTRAL_EVENT_TESTS)
    if mode == "central":
        return [*CENTRAL_EVENT_TESTS, *CENTRAL_DIRECT_TESTS]
    if mode == "central-router":
        return [*CENTRAL_EVENT_TESTS, *CENTRAL_DIRECT_TESTS, *RELATED_ROUTER_TESTS]
    if mode == "sdk":
        return discover_test_module_names(OPTIONAL_DEPENDENCY_TEST_MODULES)
    if mode == "full":
        return discover_test_module_names()
    raise ValueError(f"Unsupported unittest baseline mode: {mode}")


def run_unittest_names(
    names: Sequence[str],
    verbosity: int,
    function_test_modules: Iterable[str] = (),
) -> int:
    suite = load_unittest_suite(names, function_test_modules=function_test_modules)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


def load_unittest_suite(
    names: Sequence[str],
    function_test_modules: Iterable[str] = (),
) -> unittest.TestSuite:
    function_modules = set(function_test_modules)
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
        if name in function_modules:
            suite.addTests(load_module_level_function_tests(name))
    return suite


def load_module_level_function_tests(name: str) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    try:
        module = importlib.import_module(name)
    except Exception:
        return suite

    for attr_name in sorted(dir(module)):
        if not attr_name.startswith("test_"):
            continue
        test_func = getattr(module, attr_name)
        if not inspect.isfunction(test_func):
            continue
        if inspect.signature(test_func).parameters:
            continue
        suite.addTest(unittest.FunctionTestCase(test_func))
    return suite


def run_compile_baseline() -> int:
    ok = True
    for path in (PROJECT_ROOT / "hydros_agent_sdk", TESTS_DIR):
        ok = compileall.compile_dir(str(path), quiet=1) and ok
    return 0 if ok else 1


def print_baseline_list() -> None:
    modes = [
        ("central-events", names_for_mode("central-events")),
        ("central", names_for_mode("central")),
        ("central-router", names_for_mode("central-router")),
        ("sdk", names_for_mode("sdk")),
        ("full", names_for_mode("full")),
    ]
    print("Hydros Python SDK test baselines")
    print()
    for mode, names in modes:
        print(f"{mode}: {len(names)} target(s)")
        for name in names:
            print(f"  {name}")
        print()
    print("compile:")
    print("  hydros_agent_sdk")
    print("  tests")
    print()
    print("sdk excludes optional dependency tests:")
    for name in sorted(OPTIONAL_DEPENDENCY_TEST_MODULES):
        print(f"  tests.{name}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Hydros Python SDK test baseline.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="sdk",
        choices=[
            "central-events",
            "central",
            "central-router",
            "sdk",
            "full",
            "compile",
            "list",
        ],
        help="Baseline mode to run. Defaults to sdk.",
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=1,
        help="unittest verbosity for test-running modes.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    if args.mode == "list":
        print_baseline_list()
        return 0
    if args.mode == "compile":
        return run_compile_baseline()
    function_test_modules = RELATED_ROUTER_TESTS if args.mode == "central-router" else ()
    return run_unittest_names(
        names_for_mode(args.mode),
        verbosity=args.verbosity,
        function_test_modules=function_test_modules,
    )


if __name__ == "__main__":
    raise SystemExit(main())
