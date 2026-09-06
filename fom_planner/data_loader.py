"""
data_loader.py

Loaders for game databases, item metadata, item locations, and NPC preferences:
- load_item_locations
- load_npc_preferences_from_fiddle
- load_npc_preferences_from_json
- load_item_metadata
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

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
