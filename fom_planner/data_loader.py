"""
data_loader.py

Loaders for game databases, item metadata, item locations, and NPC preferences:
- load_item_locations
- load_item_seasons
- load_recipe_sources
- load_alt_sources
- load_quest_data
- load_npc_preferences_from_fiddle
- load_npc_preferences_from_json
- load_item_metadata
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fom_planner.constants import DEFAULT_QUEST_DATA_PATH

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None


def load_item_locations(locations_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    """
    Loads item location hints from JSON database file.
    If locations_path is not specified, defaults to 'data/item_locations.json'
    relative to the repository root.
    """
    if locations_path is None:
        root_path = Path(__file__).resolve().parent.parent / "data" / "item_locations.json"
        script_path = Path(__file__).resolve().parent / "data" / "item_locations.json"
        if root_path.exists():
            target = root_path
        elif script_path.exists():
            target = script_path
        else:
            target = Path("data/item_locations.json")
    else:
        target = Path(locations_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}
    except Exception:
        return {}
    return {}


def load_recipe_sources(sources_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    """
    Loads cooking recipe unlock sources from JSON database file.
    If sources_path is not specified, defaults to 'data/recipe_sources.json'
    relative to the repository root.
    Gracefully returns {} if path is None, file does not exist, or parsing fails.
    """
    if sources_path is None:
        root_path = Path(__file__).resolve().parent.parent / "data" / "recipe_sources.json"
        script_path = Path(__file__).resolve().parent / "data" / "recipe_sources.json"
        if root_path.exists():
            target = root_path
        elif script_path.exists():
            target = script_path
        else:
            target = Path("data/recipe_sources.json")
    else:
        target = Path(sources_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}
    except Exception:
        return {}
    return {}


def load_item_seasons(seasons_path: Optional[Union[str, Path]] = None) -> Dict[str, List[str]]:
    """
    Loads item seasonal availability from JSON database file.
    Maps item_id -> list of lowercased season names (e.g. ['spring'], ['summer', 'fall']).
    If seasons_path is not specified, defaults to 'data/item_seasons.json'
    relative to the repository root.
    Gracefully returns {} if path is None, file does not exist, or parsing fails.
    """
    if seasons_path is None:
        root_path = Path(__file__).resolve().parent.parent / "data" / "item_seasons.json"
        script_path = Path(__file__).resolve().parent / "data" / "item_seasons.json"
        if root_path.exists():
            target = root_path
        elif script_path.exists():
            target = script_path
        else:
            target = Path("data/item_seasons.json")
    else:
        target = Path(seasons_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            res: Dict[str, List[str]] = {}
            for k, v in data.items():
                if not k:
                    continue
                k_clean = str(k).strip().lower()
                if isinstance(v, list):
                    res[k_clean] = [str(s).strip().lower() for s in v if s]
                elif isinstance(v, str) and v.strip():
                    res[k_clean] = [str(v).strip().lower()]
            return res
    except Exception:
        return {}
    return {}


def load_alt_sources(
    sources_path: Optional[Union[str, Path]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Loads alternate acquisition sources from JSON database file.
    Maps item_id -> list of source dicts, each with keys:
      type, vendor/location, cost, currency, note, icon
    If sources_path is not specified, defaults to 'data/alt_sources.json'
    relative to the repository root.
    Gracefully returns {} if path is None, file does not exist, or parsing fails.
    """
    if sources_path is None:
        root_path = Path(__file__).resolve().parent.parent / "data" / "alt_sources.json"
        script_path = Path(__file__).resolve().parent / "data" / "alt_sources.json"
        if root_path.exists():
            target = root_path
        elif script_path.exists():
            target = script_path
        else:
            target = Path("data/alt_sources.json")
    else:
        target = Path(sources_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            res: Dict[str, List[Dict[str, Any]]] = {}
            for k, v in data.items():
                if not k:
                    continue
                k_clean = str(k).strip().lower()
                if isinstance(v, list):
                    valid_sources = [s for s in v if isinstance(s, dict) and s.get("type")]
                    if valid_sources:
                        res[k_clean] = valid_sources
            return res
    except Exception:
        return {}
    return {}


GENERIC_QUEST_PLACEHOLDERS: Set[str] = {
    "crop",
    "berry",
    "fish",
    "flower",
    "soup",
    "mine_forageable",
    "monster_part",
    "baked_dishes",
    "wool",
    "copper_tool",
    "dining_tables",
    "dining_chairs",
    "stone_path",
    "feather",
}

QUEST_ITEM_ALIASES: Dict[str, str] = {
    # Baseline tree aliases
    "milk": "cow_milk",
    "golden_milk": "golden_cow_milk",
    "wood": "basic_wood",
    "stone": "ore_stone",
    "rice_ball": "riceball",
    "tea": "cup_of_tea",
    # Quest dataset Wiki naming mismatches
    "breath_of_flame": "breath_of_fire",
    "archeology_shard": "shards",
    "chicken_egg": "egg",
    "rooster_feather": "feather",
    "clod_bomb": "bomb",
    "hay_bale": "spooky_haybale",
    "scarecrow": "starter_scarecrow",
    "potted_plant": "starter_potted_plant",
    "birdhouse": "starter_bird_house_red",
    "shipping_bin": "starter_shipping_box",
    "wooden_fence": "starter_wood_fence",
    "ultimate_large_animal_feed": "ultimate_hay",
    "silver_sword": "sword_silver",
    "corrupted_mistril_sword": "sword_corrupted_mistril",
    "silver_axe": "axe_silver",
    "copper_shovel": "shovel_copper",
    "iron_shovel": "shovel_iron",
    "copper_net": "net_copper",
    "iron_watering_can": "watering_can_iron",
    "common_bug_pheromones": "bug_pheromone_common",
    "uncommon_bug_pheromones": "bug_pheromone_uncommon",
    "rare_bug_pheromones": "bug_pheromone_rare",
    "common_fish_bait": "fish_bait_common",
    "uncommon_fish_bait": "fish_bait_uncommon",
    "rare_fish_bait": "fish_bait_rare",
    "grass_starter": "small_grass_starter",
}


def load_quest_data(
    quest_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Loads quest item requirements from quest_data.json.
    - Resolves item aliases to canonical IDs with bidirectional lookup.
    - Excludes Mission Quest entries (monster hunting kill quotas).
    - Excludes generic category placeholders (crop, berry, fish, etc.).
    - Recalculates total_required and quest_types per item.
    - Gracefully returns {} if file is missing or invalid.
    """
    if quest_path is None:
        if DEFAULT_QUEST_DATA_PATH.exists():
            target = DEFAULT_QUEST_DATA_PATH
        else:
            root_path = Path(__file__).resolve().parent.parent / "data" / "quest_data.json"
            script_path = Path(__file__).resolve().parent / "data" / "quest_data.json"
            if root_path.exists():
                target = root_path
            elif script_path.exists():
                target = script_path
            else:
                target = Path("data/quest_data.json")
    else:
        target = Path(quest_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        if not isinstance(raw_data, dict):
            return {}

        details = raw_data.get("item_quest_details", {})
        if not isinstance(details, dict):
            return {}

        canonical_items: Dict[str, Dict[str, Any]] = {}
        alias_map: Dict[str, str] = {}

        for raw_id, item_info in details.items():
            if not isinstance(item_info, dict):
                continue
            raw_id_clean = str(raw_id).strip().lower()
            if raw_id_clean in GENERIC_QUEST_PLACEHOLDERS:
                continue

            canonical_id = QUEST_ITEM_ALIASES.get(raw_id_clean, raw_id_clean)
            alias_map[raw_id_clean] = canonical_id

            raw_quests = item_info.get("quests", [])
            if not isinstance(raw_quests, list):
                continue

            valid_quests = [
                q for q in raw_quests
                if isinstance(q, dict)
                and q.get("category") != "Mission Quest"
                and q.get("quest_type") != "Mission Quest"
            ]
            if not valid_quests:
                continue

            if canonical_id not in canonical_items:
                display_name = item_info.get("name") or canonical_id.replace("_", " ").title()
                canonical_items[canonical_id] = {
                    "name": display_name,
                    "quests": list(valid_quests),
                }
            else:
                existing_quests = canonical_items[canonical_id]["quests"]
                for q in valid_quests:
                    if q not in existing_quests:
                        existing_quests.append(q)
                if not canonical_items[canonical_id].get("name") and item_info.get("name"):
                    canonical_items[canonical_id]["name"] = item_info["name"]

        res: Dict[str, Dict[str, Any]] = {}
        for cid, data in canonical_items.items():
            quests = data["quests"]
            if not quests:
                continue
            cleaned_types = sorted(list({str(q.get("quest_type", "Request")) for q in quests}))
            cleaned_total = sum(int(q.get("amount", 0)) for q in quests)
            res[cid] = {
                "name": data["name"],
                "total_required": cleaned_total,
                "quest_types": cleaned_types,
                "quests": quests,
            }

        # Populate bidirectional aliases
        for alias, canonical in QUEST_ITEM_ALIASES.items():
            if canonical in res and alias not in res:
                res[alias] = res[canonical]
            elif alias in res and canonical not in res:
                res[canonical] = res[alias]

        for raw_k, canon_k in alias_map.items():
            if canon_k in res and raw_k not in res:
                res[raw_k] = res[canon_k]
            elif raw_k in res and canon_k not in res:
                res[canon_k] = res[raw_k]

        return res
    except Exception:
        return {}


def load_npc_preferences_from_fiddle(fiddle_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parses NPC TOML files from assets/fiddle/npcs/*.toml.
    Returns:
        npcs: dict of npc_id -> {"name": display_name, "loved": set(), "liked": set()}
        items: dict of item_id -> {"loved_by": set(npc_names), "liked_by": set(npc_names),
                                   "loved_by_ids": set(npc_ids), "liked_by_ids": set(npc_ids)}
    """
    npcs_dir = fiddle_dir / "npcs"
    if not npcs_dir.exists() or tomllib is None:
        return {}, {}

    npcs = {}
    items = {}

    for file_path in sorted(npcs_dir.glob("*.toml")):
        npc_id = file_path.stem
        try:
            with open(file_path, "rb") as fp:
                data = tomllib.load(fp)

            npc_name = data.get("name", npc_id.capitalize())
            loved_gifts = data.get("loved_gifts", [])
            liked_gifts = data.get("liked_gifts", [])

            npcs[npc_id] = {
                "name": npc_name,
                "loved": set(loved_gifts),
                "liked": set(liked_gifts)
            }

            for item_id in loved_gifts:
                if item_id not in items:
                    items[item_id] = {
                        "loved_by": set(), "liked_by": set(),
                        "loved_by_ids": set(), "liked_by_ids": set()
                    }
                items[item_id]["loved_by"].add(npc_name)
                items[item_id]["loved_by_ids"].add(npc_id)

            for item_id in liked_gifts:
                if item_id not in items:
                    items[item_id] = {
                        "loved_by": set(), "liked_by": set(),
                        "loved_by_ids": set(), "liked_by_ids": set()
                    }
                items[item_id]["liked_by"].add(npc_name)
                items[item_id]["liked_by_ids"].add(npc_id)

        except Exception as e:
            print(f"Warning: Failed to parse NPC TOML '{file_path}': {e}", file=sys.stderr)

    return npcs, items


def load_npc_preferences_from_json(json_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fallback loader from gift_indicator/data/item_data.json."""
    if not json_path.exists():
        return {}, {}

    with open(json_path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    npc_names_map = data.get("npcs", {})
    npcs = {}
    items = {}

    for npc_id, npc_name in npc_names_map.items():
        npcs[npc_id] = {"name": npc_name, "loved": set(), "liked": set()}

    for item_id, item_info in data.get("items", {}).items():
        loved_ids = set(item_info.get("loved_by", []))
        liked_ids = set(item_info.get("liked_by", []))

        if not loved_ids and not liked_ids:
            continue

        loved_names = {npc_names_map.get(nid, nid.capitalize()) for nid in loved_ids}
        liked_names = {npc_names_map.get(nid, nid.capitalize()) for nid in liked_ids}

        for nid in loved_ids:
            if nid in npcs:
                npcs[nid]["loved"].add(item_id)
        for nid in liked_ids:
            if nid in npcs:
                npcs[nid]["liked"].add(item_id)

        items[item_id] = {
            "loved_by": loved_names,
            "liked_by": liked_names,
            "loved_by_ids": loved_ids,
            "liked_by_ids": liked_ids,
        }

    return npcs, items


def load_item_metadata(
    fiddle_dir: Path,
    item_data_json_path: Optional[Path] = None,
    tracker_files_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Loads comprehensive item metadata: display name, description, sell price (bin & store),
    tags, and recipe/quest usage counts.
    """
    metadata: Dict[str, Any] = {}

    # 1. Load from fiddle TOML files if available
    items_dir = fiddle_dir / "items" if fiddle_dir else None
    if items_dir and items_dir.exists() and tomllib is not None:
        for toml_path in items_dir.glob("**/*.toml"):
            try:
                with open(toml_path, "rb") as fp:
                    data = tomllib.load(fp)
                for item_id, item_info in data.items():
                    if not isinstance(item_info, dict):
                        continue
                    bin_price = None
                    store_price = None
                    if "value" in item_info and isinstance(item_info["value"], dict):
                        bin_price = item_info["value"].get("bin")
                        store_price = item_info["value"].get("store")

                    metadata[item_id] = {
                        "display_name": item_info.get("name", item_id.replace("_", " ").title()),
                        "description": item_info.get("description", ""),
                        "bin_price": bin_price if bin_price is not None else "",
                        "store_price": store_price if store_price is not None else "",
                        "tags": item_info.get("tags", []),
                        "cooking_recipes_count": 0,
                        "crafting_recipes_count": 0,
                        "quests_count": 0,
                    }
            except Exception as e:
                print(f"Warning: Failed to parse item TOML '{toml_path}': {e}", file=sys.stderr)

    # 2. Enrich from tracker items.json.js if available
    if tracker_files_dir and tracker_files_dir.exists():
        tracker_json_path = tracker_files_dir / "items.json.js.download"
        if not tracker_json_path.exists():
            tracker_json_path = tracker_files_dir / "items.json.js"
        if tracker_json_path.exists():
            try:
                with open(tracker_json_path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                json_str = re.sub(r'^\s*var\s+objItems\s*=\s*', '', content).rstrip(';\n ')
                t_items = json.loads(json_str)
                for iid, info in t_items.items():
                    if not isinstance(info, dict):
                        continue
                    if iid not in metadata:
                        metadata[iid] = {
                            "display_name": info.get("name", iid.replace("_", " ").title()),
                            "description": "",
                            "bin_price": "",
                            "store_price": "",
                            "tags": info.get("tags", []),
                            "cooking_recipes_count": 0,
                            "crafting_recipes_count": 0,
                            "quests_count": 0,
                        }
                    else:
                        if not metadata[iid]["tags"] and info.get("tags"):
                            metadata[iid]["tags"] = info.get("tags")
                        if not metadata[iid]["display_name"] and info.get("name"):
                            metadata[iid]["display_name"] = info.get("name")
            except Exception as e:
                print(f"Warning: Failed to parse tracker items JS: {e}", file=sys.stderr)

    # 3. Enrich from item_data.json if available
    if item_data_json_path and item_data_json_path.exists():
        try:
            with open(item_data_json_path, "r", encoding="utf-8") as fp:
                json_data = json.load(fp)
            for item_id, item_info in json_data.get("items", {}).items():
                if item_id not in metadata:
                    metadata[item_id] = {
                        "display_name": item_info.get("display_name", item_id.replace("_", " ").title()),
                        "description": "",
                        "bin_price": "",
                        "store_price": "",
                        "tags": item_info.get("tags", []),
                        "cooking_recipes_count": 0,
                        "crafting_recipes_count": 0,
                        "quests_count": 0,
                    }
                else:
                    if item_info.get("display_name"):
                        metadata[item_id]["display_name"] = item_info["display_name"]
                    if not metadata[item_id]["tags"] and item_info.get("tags"):
                        metadata[item_id]["tags"] = item_info["tags"]

                metadata[item_id]["cooking_recipes_count"] = len(item_info.get("cooking_recipes", []))
                metadata[item_id]["crafting_recipes_count"] = len(item_info.get("crafting_recipes", []))
                metadata[item_id]["quests_count"] = len(item_info.get("quests", []))
        except Exception as e:
            print(f"Warning: Failed to read item_data.json: {e}", file=sys.stderr)

    return metadata
