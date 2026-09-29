"""
companion/planner_bridge.py

Bridge layer between the companion server and the core fom_planner engine.
Handles safe path resolution, Windows file lock retries, and data conversion.
"""

import json
from pathlib import Path
import re
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


def parse_date_override(
    date_override: Optional[str],
    default_date: Optional[InGameDate] = None,
) -> Optional[InGameDate]:
    """
    Parses a user-defined date override string into an InGameDate object.
    Supports:
      - 'saturday', 'sat': Jumps to upcoming Saturday relative to default_date (or Spring 6).
      - 'Spring 14', 'Year 2, Summer 6', 'Fall 10', 'Winter 28'
      - Festivals: 'animal festival' (Winter 10), 'spring festival' (Spring 17),
                   'shooting star' (Summer 28), 'harvest festival' (Fall 10)
      - Numbers: '6', '13', '20', '27'
      - JSON format: '{"season": "spring", "day": 14, "year": 1}'
      - Empty / None / 'auto' / 'save' / 'default': Returns None (no override).
    """
    if not date_override:
        return None
    raw = str(date_override).strip()
    if not raw or raw.lower() in ("none", "auto", "save", "default", "null", "false", "0"):
        return None

    # Try JSON format
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            season = str(data.get("season", "spring")).strip().lower()
            if season == "autumn":
                season = "fall"
            day = int(data.get("day", 1))
            day = max(1, min(28, day))
            yr = int(data.get("year", default_date.year if default_date else 1))
            yr = max(1, yr)
            return InGameDate(year=yr, season=season, day=day, time_str="10:00")
        except Exception:
            pass

    text = raw.lower()

    # 1. Festival keywords
    if "animal" in text or text in ("winter 10", "winter_10", "10 winter"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="winter", day=10, time_str="10:00")
    if "shooting" in text or text in ("summer 28", "summer_28", "28 summer"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="summer", day=28, time_str="10:00")
    if "harvest" in text:
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="fall", day=10, time_str="10:00")
    if "spring fest" in text or text in ("spring 17", "spring_17", "17 spring"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="spring", day=17, time_str="10:00")

    # 2. "saturday" or "sat" keyword
    if text.startswith("sat"):
        if default_date is not None:
            yr = default_date.year
            season = default_date.season.lower()
            if season == "autumn":
                season = "fall"
            next_day = default_date.next_saturday_day
            if next_day <= 28:
                return InGameDate(year=yr, season=season, day=next_day, time_str="10:00")
            else:
                seasons_cycle = ["spring", "summer", "fall", "winter"]
                curr_idx = seasons_cycle.index(season) if season in seasons_cycle else 0
                next_idx = (curr_idx + 1) % 4
                next_season = seasons_cycle[next_idx]
                next_yr = yr + 1 if next_idx == 0 else yr
                return InGameDate(year=next_yr, season=next_season, day=6, time_str="10:00")
        else:
            return InGameDate(year=1, season="spring", day=6, time_str="10:00")

    # 3. Year, season, and day extraction
    yr = default_date.year if default_date else 1
    yr_match = re.search(r"(?:year|y)\s*[:=]?\s*(\d+)", text)
    if yr_match:
        try:
            yr = int(yr_match.group(1))
            text = text[:yr_match.start()] + " " + text[yr_match.end():]
        except Exception:
            pass

    season = default_date.season.lower() if default_date else "spring"
    if season == "autumn":
        season = "fall"
    if "spring" in text:
        season = "spring"
    elif "summer" in text:
        season = "summer"
    elif "fall" in text or "autumn" in text:
        season = "fall"
    elif "winter" in text:
        season = "winter"

    # Search for day number (1..28)
    day_match = re.search(r"\b([1-9]|[12][0-9])\b", text)
    if day_match:
        day = int(day_match.group(1))
        if 1 <= day <= 28:
            return InGameDate(year=max(1, yr), season=season, day=day, time_str="10:00")

    digits = re.findall(r"\d+", text)
    if digits:
        val = int(digits[0])
        day = max(1, min(28, val))
        return InGameDate(year=max(1, yr), season=season, day=day, time_str="10:00")

    return None


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
    current_ingame_date = save.in_game_date if (save and hasattr(save, "in_game_date")) else None
    override_date = parse_date_override(config.date_override, current_ingame_date)

    if override_date is not None:
        yr = override_date.year
        s_name = override_date.season.lower()
        if s_name == "autumn":
            s_name = "fall"
        d_num = override_date.day

        if save is None:
            seasons_order = ["spring", "summer", "fall", "winter"]
            s_idx = seasons_order.index(s_name) if s_name in seasons_order else 0
            cal_days = (yr - 1) * 112 + s_idx * 28 + (d_num - 1)
            dummy_entries = {
                "header": json.dumps({"name": "Player", "calendar_time": cal_days * 86400, "clock_time": 36000}),
                "player": json.dumps({"name": "Player", "inventory": []}),
                "npcs": json.dumps({}),
            }
            save = SaveData(Path("simulated.sav"), dummy_entries)

        save.in_game_date = InGameDate(year=yr, season=s_name, day=d_num, time_str="10:00")

        # Saturday Market behavior:
        # If effective_mode is "auto" and the effective date is a Saturday, activate Saturday mode!
        if effective_mode == "auto" and save.in_game_date.is_saturday:
            effective_mode = "saturday"

    # 6. Exclude NPCs
    excluded: Set[str] = set()
    if config.exclude_npcs:
        excluded = {x.strip().lower() for x in config.exclude_npcs.split(",") if x.strip()}

    focus_mode_enabled = bool(getattr(config, "focus_mode_enabled", False))
    focus_npcs: Set[str] = set()
    raw_focus_npcs = getattr(config, "focus_npcs", "")
    if raw_focus_npcs:
        if isinstance(raw_focus_npcs, (list, set, tuple)):
            focus_npcs = {str(x).strip().lower() for x in raw_focus_npcs if str(x).strip()}
        elif isinstance(raw_focus_npcs, str):
            focus_npcs = {x.strip().lower() for x in raw_focus_npcs.split(",") if x.strip()}

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
            focus_mode_enabled=focus_mode_enabled,
            focus_npcs=focus_npcs,
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
            focus_mode_enabled=focus_mode_enabled,
            focus_npcs=focus_npcs,
        )

    return save, plan_results, metadata, save_path
