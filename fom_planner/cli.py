"""
cli.py

Unified Command-Line Interface for Fields of Mistria tools:
- run_planner: Daily Bag Loadout Optimizer
- run_rankings: Item Gift Rankings & Matrix Exporter
- main: Unified entry point dispatcher
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

# Ensure stdout supports UTF-8 on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fom_planner.constants import ANIMAL_FESTIVAL_ATTENDING_VENDORS
from fom_planner.crafting import load_recipes
from fom_planner.data_loader import (
    load_item_locations,
    load_item_metadata,
    load_npc_preferences_from_fiddle,
    load_npc_preferences_from_json,
)
from fom_planner.exporters.csv_export import export_plan_to_csv, export_to_csv
from fom_planner.exporters.excel_export import export_plan_to_excel, export_to_excel
from fom_planner.exporters.terminal import print_terminal_plan
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import plan_daily_gift_bag
from fom_planner.parser import find_latest_save, parse_save_file
from fom_planner.rankings import build_ranked_rows


def get_repo_root() -> Path:
    """Finds repository root containing the data/ folder."""
    curr = Path.cwd()
    if (curr / "data").exists():
        return curr
    parent = Path(__file__).resolve().parent.parent
    if (parent / "data").exists():
        return parent
    return curr


def build_planner_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py" if Path(sys.argv[0]).name == "main.py" else Path(sys.argv[0]).name,
        description="Daily Bag Loadout Optimizer for Fields of Mistria gift giving, with inventory awareness and Saturday Market support."
    )
    parser.add_argument(
        "--save-file",
        default=None,
        help="Path to .sav file. If omitted, auto-detects the latest save in your FoM saves folder."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override simulation date/day (e.g. 'saturday', '6', 'winter 6')"
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "today", "saturday", "market-only", "townsfolk", "weekday", "all"],
        default="auto",
        help="Planning mode: 'auto' (use save day), 'saturday' (simulate Saturday Market), 'market-only' (8 vendors only), 'townsfolk' (26 townsfolk only), 'weekday' (26 townsfolk only), 'all' (all 34 NPCs). Default: auto"
    )
    parser.add_argument(
        "--slots",
        type=int,
        default=20,
        help="Maximum bag slots budgeted for gifts (default: 20)"
    )
    parser.add_argument(
        "--recipes",
        default="data/recipes.json",
        help="Path to recipes.json database (default: data/recipes.json)"
    )
    parser.add_argument(
        "--fiddle",
        default="assets/fiddle",
        help="Path to assets/fiddle directory (default: assets/fiddle)"
    )
    parser.add_argument(
        "--item-data",
        default="data/item_data.json",
        help="Path to item_data.json (default: data/item_data.json)"
    )
    parser.add_argument(
        "--item-locations",
        default="data/item_locations.json",
        help="Path to item_locations.json database (default: data/item_locations.json)"
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory for generated CSV and Excel plans (default: exports)"
    )
    parser.add_argument(
        "--format",
        choices=["all", "terminal", "csv", "excel", "both"],
        default="all",
        help="Output format: all, terminal, csv, excel, or both (default: all)"
    )
    parser.add_argument(
        "--loved-weight",
        type=int,
        default=3,
        help="Weight multiplier for loved gifts in optimization scoring (default: 3)"
    )
    parser.add_argument(
        "--liked-weight",
        type=int,
        default=1,
        help="Weight multiplier for liked gifts in optimization scoring (default: 1)"
    )
    parser.add_argument(
        "--vendor-boost",
        type=float,
        default=1.5,
        help="Priority boost multiplier for Saturday Market vendors on market day (default: 1.5)"
    )
    parser.add_argument(
        "--exclude-npcs",
        default="",
        help="Comma-separated list of NPC IDs to exclude from planning"
    )
    parser.add_argument(
        "--force-all-npcs",
        action="store_true",
        help="Force planning for all NPCs, even if save indicates they were already gifted today"
    )
    parser.add_argument(
        "--csv-name",
        default="daily_gift_bag_plan.csv",
        help="Filename for CSV export (default: daily_gift_bag_plan.csv)"
    )
    parser.add_argument(
        "--excel-name",
        default="daily_gift_bag_plan.xlsx",
        help="Filename for Excel export (default: daily_gift_bag_plan.xlsx)"
    )
    return parser


def run_planner(args=None):
    if args is None:
        parser = build_planner_parser()
        args = parser.parse_args()

    repo_root = get_repo_root()
    fiddle_path = (repo_root / args.fiddle).resolve() if not Path(args.fiddle).is_absolute() else Path(args.fiddle)
    item_data_path = (repo_root / args.item_data).resolve() if not Path(args.item_data).is_absolute() else Path(args.item_data)
    output_dir = (repo_root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    recipes_path = (repo_root / args.recipes).resolve() if not Path(args.recipes).is_absolute() else Path(args.recipes)
    item_locations_path = (repo_root / args.item_locations).resolve() if not Path(args.item_locations).is_absolute() else Path(args.item_locations)

    # 1. Resolve save file
    save_path = None
    if args.save_file:
        p = Path(args.save_file)
        if p.exists():
            save_path = p.resolve()
        elif (repo_root / args.save_file).exists():
            save_path = (repo_root / args.save_file).resolve()
        else:
            print(f"Error: Specified save file '{args.save_file}' not found.", file=sys.stderr)
            sys.exit(1)
    else:
        latest = find_latest_save()
        local_sample = repo_root / "game-2026225748-autosave.sav"
        if latest and latest.exists():
            save_path = latest
        elif local_sample.exists():
            save_path = local_sample

    save = None
    if save_path and save_path.exists():
        print(f"Loading save file: {save_path}...")
        try:
            save = parse_save_file(save_path)
        except Exception as e:
            print(f"Warning: Failed to parse save file '{save_path}': {e}", file=sys.stderr)
            save = None
    else:
        print("Note: No save file found or specified. Planning with empty starting inventory.")

    # 2. Load recipes and locations database
    recipes = load_recipes(str(recipes_path))
    item_locations = load_item_locations(str(item_locations_path))

    # 3. Load gift definitions & metadata
    npcs_def = None
    if fiddle_path.exists():
        print(f"Loading NPC preferences from: {fiddle_path}...")
        npcs_def, _ = load_npc_preferences_from_fiddle(fiddle_path)
    if not npcs_def and item_data_path.exists():
        print("Falling back to item_data.json...")
        npcs_def, _ = load_npc_preferences_from_json(item_data_path)

    if not npcs_def:
        print("Error: Failed to load NPC gift definitions.", file=sys.stderr)
        sys.exit(1)

    tracker_files_path = repo_root / "Fields of Mistria Progress Tracker_files"
    if not tracker_files_path.exists():
        tracker_files_path = None
    metadata = load_item_metadata(fiddle_path, item_data_path, tracker_files_path)

    # 4. Handle date override
    effective_mode = args.mode
    if args.date:
        d_lower = args.date.strip().lower()
        if "sat" in d_lower or d_lower in ("6", "13", "20", "27"):
            if effective_mode == "auto":
                effective_mode = "saturday"
        elif "animal" in d_lower or "winter 10" in d_lower or "10 winter" in d_lower or d_lower in ("winter_10", "animal_festival"):
            yr = 1
            if save is not None and hasattr(save, "in_game_date") and save.in_game_date:
                yr = save.in_game_date.year
            elif save is None:
                cal_days = (yr - 1) * 112 + 3 * 28 + 9
                dummy_entries = {
                    "header": json.dumps({"name": "Player", "calendar_time": cal_days * 86400, "clock_time": 36000}),
                    "player": json.dumps({"name": "Player", "inventory": []}),
                    "npcs": json.dumps({}),
                }
                save = SaveData(Path("simulated.sav"), dummy_entries)
            save.in_game_date = InGameDate(year=yr, season="winter", day=10, time_str="10:00")

    # 5. Exclude NPCs if requested
    excluded = set([x.strip().lower() for x in args.exclude_npcs.split(",") if x.strip()])

    # 6. Plan daily gift bag
    plan_results = plan_daily_gift_bag(
        save=save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode=effective_mode,
        max_slots=args.slots,
        loved_weight=args.loved_weight,
        liked_weight=args.liked_weight,
        vendor_boost=args.vendor_boost,
        exclude_npcs=excluded,
        force_all_npcs=args.force_all_npcs,
        recipes=recipes,
        item_locations=item_locations,
    )

    # 7. Output
    if args.format in ("all", "terminal"):
        print_terminal_plan(save, plan_results)

    if args.format in ("all", "csv", "both"):
        export_plan_to_csv(plan_results, output_dir, args.csv_name)

    if args.format in ("all", "excel", "both"):
        excel_path = output_dir / args.excel_name
        export_plan_to_excel(save, plan_results, npcs_def, metadata, excel_path)


def build_rankings_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract and export ranked love/like gift items table to CSV and Excel."
    )
    parser.add_argument(
        "--fiddle",
        default="assets/fiddle",
        help="Path to assets/fiddle directory (default: assets/fiddle)"
    )
    parser.add_argument(
        "--item-data",
        default="data/item_data.json",
        help="Path to item_data.json (default: data/item_data.json)"
    )
    parser.add_argument(
        "--tracker-files",
        default=None,
        help="Path to tracker files directory (default: Fields of Mistria Progress Tracker_files)"
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory for generated CSV and Excel files (default: exports)"
    )
    parser.add_argument(
        "--csv-name",
        default="item_gift_rankings.csv",
        help="Filename for CSV export (default: item_gift_rankings.csv)"
    )
    parser.add_argument(
        "--excel-name",
        default="item_gift_rankings.xlsx",
        help="Filename for Excel export (default: item_gift_rankings.xlsx)"
    )
    parser.add_argument(
        "--format",
        choices=["both", "csv", "excel", "terminal"],
        default="both",
        help="Export format: csv, excel, terminal, or both (default: both)"
    )
    parser.add_argument(
        "--sort-by",
        choices=["total", "loved", "liked"],
        default="total",
        help="Primary sorting criterion: total, loved, or liked (default: total)"
    )
    parser.add_argument(
        "--min-npcs",
        type=int,
        default=1,
        help="Minimum number of NPCs who must love/like an item to include it (default: 1)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Limit output rows to top N items"
    )
    return parser


def run_rankings(args=None):
    if args is None:
        parser = build_rankings_parser()
        args = parser.parse_args()

    repo_root = get_repo_root()
    fiddle_path = (repo_root / args.fiddle).resolve() if not Path(args.fiddle).is_absolute() else Path(args.fiddle)
    item_data_path = (repo_root / args.item_data).resolve() if not Path(args.item_data).is_absolute() else Path(args.item_data)
    output_dir = (repo_root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    if args.tracker_files:
        tracker_files_path = Path(args.tracker_files).resolve()
    else:
        default_tracker = repo_root / "Fields of Mistria Progress Tracker_files"
        tracker_files_path = default_tracker if default_tracker.exists() else None

    # 1. Load preferences
    npcs = None
    items = None
    if fiddle_path.exists():
        print(f"Loading NPC preferences from fiddle: {fiddle_path}...")
        npcs, items = load_npc_preferences_from_fiddle(fiddle_path)

    if not npcs and item_data_path.exists():
        print("Falling back to item_data.json...")
        npcs, items = load_npc_preferences_from_json(item_data_path)

    if not npcs or not items:
        print("Error: Could not load NPC gift preferences from fiddle or item_data.json", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded preferences for {len(npcs)} NPCs and {len(items)} unique items.")

    # 2. Enrich metadata
    metadata = load_item_metadata(fiddle_path, item_data_path, tracker_files_path)

    # 3. Build ranked rows
    rows = build_ranked_rows(items, metadata, sort_by=args.sort_by, min_npcs=args.min_npcs)

    if args.top:
        rows = rows[:args.top]
        print(f"Limiting to top {args.top} items.")

    # 4. Export
    if args.format == "terminal":
        print(f"\nTop {len(rows)} Gift Items (Sorted by {args.sort_by.upper()}):")
        print("=" * 80)
        print(f"{'Rank':<5} {'Item Name':<28} {'Total':<7} {'Loved':<7} {'Liked':<7}")
        print("-" * 80)
        for r in rows[:30]:
            print(f"{r['rank']:<5} {r['item_name']:<28} {r['total_count']:<7} {r['loved_count']:<7} {r['liked_count']:<7}")
        if len(rows) > 30:
            print(f"... and {len(rows) - 30} more items.")
        print("=" * 80)
    else:
        if args.format in ("csv", "both"):
            csv_path = output_dir / args.csv_name
            export_to_csv(rows, csv_path)

        if args.format in ("excel", "both"):
            excel_path = output_dir / args.excel_name
            export_to_excel(rows, npcs, excel_path)


def main(argv: Optional[List[str]] = None):
    """
    Unified CLI dispatcher:
    - python main.py rankings [...] -> runs gift rankings
    - python main.py --rankings [...] -> runs gift rankings
    - python main.py [...] -> runs daily gift planner
    """
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("rankings", "--rankings"):
        parser = build_rankings_parser()
        args = parser.parse_args(argv[1:])
        run_rankings(args)
    elif argv and argv[0] == "plan":
        parser = build_planner_parser()
        args = parser.parse_args(argv[1:])
        run_planner(args)
    else:
        parser = build_planner_parser()
        args = parser.parse_args(argv)
        run_planner(args)


if __name__ == "__main__":
    main()
