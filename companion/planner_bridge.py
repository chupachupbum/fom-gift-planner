"""
companion/planner_bridge.py

Bridge layer between the companion server and the core fom_planner engine.
Handles safe path resolution, Windows file lock retries, and data conversion.
"""

import json
from pathlib import Path
import time
from typing import Any, Dict, Optional, Set, Tuple

from companion.config import CompanionConfig, get_repo_root
from fom_planner.crafting import filter_recipes_by_unlocks, load_recipes
from fom_planner.data_loader import (
    load_item_locations,
    load_item_metadata,
    load_item_seasons,
    load_npc_preferences_from_fiddle,
    load_npc_preferences_from_json,
    load_recipe_sources,
)
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import plan_daily_gift_bag, plan_max_relationship
from fom_planner.parser import find_latest_save, parse_save_file


def resolve_path(path_str: Optional[str], repo_root: Path) -> Optional[Path]:
    """
    Safely resolves a path across Windows and Linux.
    Expands environment variables and user home, and resolves relative paths against repo_root.
    """
    if not path_str or not str(path_str).strip():
        return None
    raw = str(path_str).strip()
    expanded = Path(raw).expanduser()
    if expanded.is_absolute() and expanded.exists():
        return expanded.resolve()
    rel = (repo_root / raw).resolve()
    if rel.exists():
        return rel
    return expanded.resolve()


def read_save_with_retry(save_path: Path, max_attempts: int = 5) -> SaveData:
    """
    Parses a Fields of Mistria .sav file with exponential backoff retry.
    Crucial on Windows where the game process may momentarily lock the file during saving.
    """
    last_err = None
    for attempt in range(max_attempts):
        try:
            return parse_save_file(save_path)
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(0.1 * (2 ** attempt))
            else:
                raise ValueError(f"Save file locked or inaccessible on attempt {attempt+1}: {e}") from e
        except Exception as e:
            raise e
    if last_err:
        raise last_err


def execute_plan(
    config: CompanionConfig,
    repo_root: Optional[Path] = None,
) -> Tuple[Optional[SaveData], Dict[str, Any], Dict[str, Any], Optional[Path]]:
    """
    Runs the planner engine with the given CompanionConfig.
    Returns:
        (save, plan_results, item_metadata, resolved_save_path)
    """
    root = repo_root or get_repo_root()

    # 1. Resolve save file
    save_path: Optional[Path] = None
    if config.save_file:
        resolved = resolve_path(config.save_file, root)
        if resolved and resolved.exists():
            save_path = resolved
        else:
            raise FileNotFoundError(f"Specified save file '{config.save_file}' was not found.")
    else:
        latest = find_latest_save()
        if latest and latest.exists():
            save_path = latest
        else:
            # Fallback to sample saves if available
            sample_candidates = [
                root / "samples" / "sample_save.sav",
                root / "game-2026225748-autosave.sav",
            ]
            for candidate in sample_candidates:
                if candidate.exists():
                    save_path = candidate.resolve()
                    break

    save: Optional[SaveData] = None
    if save_path and save_path.exists():
        save = read_save_with_retry(save_path)

    # 2. Resolve database and asset paths
    fiddle_path = resolve_path(config.fiddle, root) or (root / "assets" / "fiddle")
    item_data_path = resolve_path(config.item_data, root) or (root / "data" / "item_data.json")
    recipes_path = resolve_path(config.recipes, root) or (root / "data" / "recipes.json")
    item_locations_path = resolve_path(config.item_locations, root) or (root / "data" / "item_locations.json")
    recipe_sources_path = resolve_path(config.recipe_sources, root) or (root / "data" / "recipe_sources.json")
    item_seasons_path = resolve_path(config.item_seasons, root) or (root / "data" / "item_seasons.json")

    # 3. Load databases
    all_recipes = load_recipes(str(recipes_path)) if recipes_path.exists() else {}
    recipes = all_recipes
    if save is not None and hasattr(save, "get_unlocked_recipe_ids"):
        unlocked = save.get_unlocked_recipe_ids()
        if unlocked is not None:
            recipes = filter_recipes_by_unlocks(all_recipes, unlocked)

    item_locations = load_item_locations(str(item_locations_path)) if item_locations_path.exists() else {}
    recipe_sources = load_recipe_sources(str(recipe_sources_path)) if recipe_sources_path.exists() else {}
    item_seasons = load_item_seasons(str(item_seasons_path)) if item_seasons_path.exists() else {}

    # 4. Load NPC gift preferences & metadata
    npcs_def = None
    if fiddle_path.exists():
        npcs_def, _ = load_npc_preferences_from_fiddle(fiddle_path)
    if not npcs_def and item_data_path.exists():
        npcs_def, _ = load_npc_preferences_from_json(item_data_path)

    if not npcs_def:
        raise ValueError("Failed to load NPC gift preferences from fiddle or item_data.json.")

    tracker_files_path = root / "Fields of Mistria Progress Tracker_files"
    if not tracker_files_path.exists():
        tracker_files_path = None
    metadata = load_item_metadata(fiddle_path, item_data_path, tracker_files_path)

    # 5. Handle date override
    effective_mode = config.mode
    if config.date_override:
        d_lower = config.date_override.strip().lower()
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

    # 6. Exclude NPCs
    excluded: Set[str] = set()
    if config.exclude_npcs:
        excluded = {x.strip().lower() for x in config.exclude_npcs.split(",") if x.strip()}

    # 7. Run optimization strategy
    focus_sort = config.focus_sort or "impact"
    all_seasons_flag = bool(config.all_seasons)
    seasonal_boost_val = float(config.seasonal_boost)

    if config.strategy == "max-relationship":
        infused_items = save.get_infused_items() if (save is not None and hasattr(save, "get_infused_items")) else None
        plan_results = plan_max_relationship(
            save=save,
            npc_gift_definitions=npcs_def,
            item_metadata=metadata,
            mode=effective_mode,
            max_slots=config.slots,
            exclude_npcs=excluded,
            force_all_npcs=config.force_all_npcs,
            infused_items=infused_items,
            recipes=recipes,
            all_recipes=all_recipes,
            item_locations=item_locations,
            max_relationship_points=config.max_relationship_points,
            exclude_max_relationship=not config.no_exclude_max_relationship,
            focus_sort=focus_sort,
            recipe_sources=recipe_sources,
            item_seasons=item_seasons,
            all_seasons=all_seasons_flag,
            seasonal_boost=seasonal_boost_val,
        )
    else:
        plan_results = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=npcs_def,
            item_metadata=metadata,
            mode=effective_mode,
            max_slots=config.slots,
            loved_weight=config.loved_weight,
            liked_weight=config.liked_weight,
            vendor_boost=config.vendor_boost,
            exclude_npcs=excluded,
            force_all_npcs=config.force_all_npcs,
            recipes=recipes,
            all_recipes=all_recipes,
            item_locations=item_locations,
            focus_sort=focus_sort,
            recipe_sources=recipe_sources,
            item_seasons=item_seasons,
            all_seasons=all_seasons_flag,
            seasonal_boost=seasonal_boost_val,
        )

    return save, plan_results, metadata, save_path
