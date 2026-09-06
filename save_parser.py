#!/usr/bin/env python3
"""
save_parser.py

Backward-compatible shim delegating to fom_planner.models and fom_planner.parser.
"""

import sys
from pathlib import Path

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    DAYS_OF_WEEK,
    DEFAULT_SAVE_DIRS,
    FESTIVAL_CALENDAR,
    NON_LOCATION_KEYS,
    SATURDAY_MARKET_VENDORS,
)
from fom_planner.models import (
    InGameDate,
    SaveData,
    _extract_slot_item_and_count,
)
from fom_planner.parser import (
    find_latest_save,
    find_save_files,
    parse_save_file,
)

__all__ = [
    "DEFAULT_SAVE_DIRS",
    "NON_LOCATION_KEYS",
    "SATURDAY_MARKET_VENDORS",
    "ANIMAL_FESTIVAL_ATTENDING_VENDORS",
    "FESTIVAL_CALENDAR",
    "DAYS_OF_WEEK",
    "InGameDate",
    "SaveData",
    "_extract_slot_item_and_count",
    "parse_save_file",
    "find_save_files",
    "find_latest_save",
]

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse and inspect Fields of Mistria save files.")
    parser.add_argument("save_file", nargs="?", help="Path to .sav file (optional; defaults to latest)")
    args = parser.parse_args()

    target_path = Path(args.save_file) if args.save_file else find_latest_save()
    if not target_path or not target_path.exists():
        print("No save file found. Please provide a path to a .sav file.", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing: {target_path}")
    save = parse_save_file(target_path)
    print("\n" + save.summary())
