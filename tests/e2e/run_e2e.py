#!/usr/bin/env python3
"""
tests/e2e/run_e2e.py

Standalone CLI Test Runner for the FoM Gift Planner 4-Tier E2E Test Suite.
Usage:
    python tests/e2e/run_e2e.py            # Runs all tiers
    python tests/e2e/run_e2e.py --tier=1   # Runs Tier 1 only
    python tests/e2e/run_e2e.py --tier=2   # Runs Tier 2 only
    python tests/e2e/run_e2e.py --tier=3   # Runs Tier 3 only
    python tests/e2e/run_e2e.py --tier=4   # Runs Tier 4 only
    python tests/e2e/run_e2e.py -v         # Verbose output
"""

import argparse
from pathlib import Path
import sys

import pytest

E2E_DIR = Path(__file__).resolve().parent

TIER_FILES = {
    1: E2E_DIR / "test_tier1_features.py",
    2: E2E_DIR / "test_tier2_boundaries.py",
    3: E2E_DIR / "test_tier3_pairwise.py",
    4: E2E_DIR / "test_tier4_scenarios.py",
}


def main():
    parser = argparse.ArgumentParser(
        description="Run FoM Gift Planner 4-Tier End-to-End Test Suite"
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Specify which tier to run (1, 2, 3, or 4). Defaults to all tiers.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="Run all tiers (default).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test execution output.",
    )
    parser.add_argument(
        "-k",
        "--expression",
        type=str,
        default="",
        help="Pytest keyword expression filter.",
    )

    args = parser.parse_args()

    pytest_args = []
    if args.verbose:
        pytest_args.append("-v")
    else:
        pytest_args.append("-q")

    if args.expression:
        pytest_args.extend(["-k", args.expression])

    if args.tier:
        target_file = TIER_FILES[args.tier]
        pytest_args.append(str(target_file))
        print(f"=== Running FoM Planner E2E Tier {args.tier} ===")
    else:
        pytest_args.append(str(E2E_DIR))
        print("=== Running Full FoM Planner 4-Tier E2E Test Suite ===")

    exit_code = pytest.main(pytest_args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
