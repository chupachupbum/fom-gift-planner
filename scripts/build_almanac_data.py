#!/usr/bin/env python3
"""
scripts/build_almanac_data.py

Extracts the canonical Almanac dataset covering all 12 in-game Almanac categories
from /home/tyrell/Downloads/assets/fiddle/ and project metadata.
Generates data/almanac_data.json and mirrors it to web/data/almanac_data.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Dict, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIDDLE_DIR = Path("/home/tyrell/Downloads/assets/fiddle")
DATA_DIR = PROJECT_ROOT / "data"
WEB_DATA_DIR = PROJECT_ROOT / "web" / "data"


def coerce_int(val: Any, default: int = 0) -> int:
    """Safely coerce values to integer >= 0. Non-numeric formula expressions coerce to default."""
    if isinstance(val, int) and not isinstance(val, bool):
        return max(0, val)
    if isinstance(val, float):
        return max(0, int(round(val)))
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            return int(s)
        if (s.startswith("-") or s.startswith("+")) and s[1:].isdigit():
            return max(0, int(s))
    return default

CATEGORY_METADATA: Dict[str, Dict[str, str]] = {
    "artifacts": {
        "name": "Artifacts",
        "description": "Historical relics, fossils, and treasures unearthed across Mistria.",
        "icon": "spr_ui_journal_almanac_icon_artifacts.png",
    },
    "blacksmithing": {
        "name": "Blacksmithing",
        "description": "Metal ingots, tools, weapons, and protective armor forged at the smithy.",
        "icon": "spr_ui_journal_almanac_icon_blacksmithing.png",
    },
    "bugs": {
        "name": "Bugs",
        "description": "Insects, butterflies, beetles, and critters caught across Mistria.",
        "icon": "spr_ui_journal_almanac_icon_bugs.png",
    },
    "cooked_dishes": {
        "name": "Cooked Dishes",
        "description": "Delicious meals, soups, pastries, and drinks prepared at the kitchen.",
        "icon": "spr_ui_journal_almanac_icon_cooked_dishes.png",
    },
    "crops": {
        "name": "Crops",
        "description": "Cultivated vegetables, fruits, flowers, and grains grown on the farm.",
        "icon": "spr_ui_journal_almanac_icon_crops.png",
    },
    "date_inspiration": {
        "name": "Date Inspiration",
        "description": "Special tokens, treats, and souvenirs from romantic dates.",
        "icon": "spr_ui_journal_almanac_icon_date_inspiration.png",
    },
    "fish": {
        "name": "Fishing and Diving",
        "description": "Freshwater fish, ocean catches, and underwater treasures from diving.",
        "icon": "spr_ui_journal_almanac_icon_fish.png",
    },
    "forageables": {
        "name": "Forageables",
        "description": "Wild plants, berries, nuts, shells, and mushrooms gathered from nature.",
        "icon": "spr_ui_journal_almanac_icon_forageables.png",
    },
    "furniture": {
        "name": "Furniture",
        "description": "Decorations, furniture, structures, and home furnishings crafted or bought.",
        "icon": "spr_ui_journal_almanac_icon_furniture.png",
    },
    "materials": {
        "name": "Materials",
        "description": "Raw resources, processed goods, ores, wood, stone, and animal products.",
        "icon": "spr_ui_journal_almanac_icon_materials.png",
    },
    "ranching": {
        "name": "Ranching",
        "description": "Milk, eggs, wool, feathers, feeds, and products from domestic animals.",
        "icon": "spr_ui_journal_almanac_icon_ranching.png",
    },
    "song_crystal": {
        "name": "Song Crystals",
        "description": "Mystical crystals holding ancient melodies scattered throughout the realm.",
        "icon": "spr_ui_journal_almanac_icon_song_crystals.png",
    },
}

ALL_SEASONS = ["spring", "summer", "fall", "winter"]

STORE_DISPLAY_NAMES = {
    "general": "General Store",
    "carpenter": "Eastern Woodworks",
    "terithia": "Tackle Shop",
    "blacksmith": "Blacksmith",
    "louis": "The Louis Shop",
    "vera": "Vera's Salon",
    "darcy": "Saturday Market - Darcy's Stall",
    "merri": "Saturday Market - Merri's Stall",
    "hayden": "Sweetwater Farm",
    "inn": "The Sleeping Dragon Inn",
}

STATION_LOCATIONS = {
    "cooking": "Kitchen",
    "milling": "The Mill",
    "woodcrafting": "Crafting Bench",
    "blacksmithing": "Blacksmith Forge",
    "refining": "Stone Refinery",
    "dragon_forging": "Summit Dragon Forge",
}


def classify_station(item_id: str, item_def: Dict[str, Any], file_rel_path: str) -> str:
    tags = item_def.get("tags", [])
    if item_id.startswith("dragon_forged_") or item_id == "sword_dragon_forged":
        return "dragon_forging"
    if "cooked_dishes" in file_rel_path or "food" in tags:
        return "cooking"
    if "mill" in file_rel_path or "milling" in tags or item_id in ("oil", "paper"):
        return "milling"
    if (
        "furniture" in tags
        or "items/furniture" in file_rel_path
        or item_id.startswith(("hero_shield_", "royal_chest_", "gemstone_bridge_", "forge_"))
    ):
        return "woodcrafting"
    recipe = item_def.get("recipe", [])
    has_ore_stone = any(isinstance(x, dict) and x.get("item") == "ore_stone" for x in recipe)
    if has_ore_stone or "essence_stone" in tags:
        return "refining"
    if (
        "blacksmithing" in file_rel_path
        or "armor" in file_rel_path
        or item_id == "engagement_ring"
        or "blacksmithing" in tags
    ):
        return "blacksmithing"
    return "woodcrafting"


def load_fish_toml() -> Dict[str, Dict[str, Any]]:
    path = FIDDLE_DIR / "fish.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    result = {}
    for k, v in data.items():
        if isinstance(v, dict):
            target = v.get("item", k)
            if target and target != "<..>":
                result[target] = v
    return result


def load_bugs_toml() -> Dict[str, Dict[str, Any]]:
    path = FIDDLE_DIR / "bugs.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    result = {}
    for k, v in data.items():
        if isinstance(v, dict):
            target = v.get("item", k)
            if target:
                result[target] = v
    return result


def load_forageables_toml() -> Dict[str, Set[str]]:
    path = FIDDLE_DIR / "forageables.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    result: Dict[str, Set[str]] = {}
    for s in ALL_SEASONS:
        s_data = data.get(s, {})
        if isinstance(s_data, dict):
            for rarity, items in s_data.items():
                if isinstance(items, list):
                    for item in items:
                        result.setdefault(item, set()).add(s)
    for s in data.get("sand_forageables", []):
        result.setdefault(s, set()).update(ALL_SEASONS)
    return result


def load_artifacts_toml() -> Dict[str, Set[str]]:
    path = FIDDLE_DIR / "artifacts.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    locations = data.get("locations", {})
    set_to_loc = {v: k for k, v in locations.items()}

    result: Dict[str, Set[str]] = {}
    loot = data.get("loot", {})
    for item in loot.keys():
        result.setdefault(item, set()).add("Digging")
    return result


def load_stores_toml() -> Dict[str, List[str]]:
    path = FIDDLE_DIR / "stores.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        stores = tomllib.load(f)
    item_to_stores: Dict[str, List[str]] = {}

    for store_key, store_data in stores.items():
        store_name = STORE_DISPLAY_NAMES.get(store_key, store_key.replace("_", " ").title())
        categories = store_data.get("categories", [])
        if isinstance(categories, list):
            for cat in categories:
                if not isinstance(cat, dict):
                    continue
                # check constant_stock
                for it in cat.get("constant_stock", []):
                    item_id = it.get("item") if isinstance(it, dict) else it
                    if item_id:
                        if store_name not in item_to_stores.setdefault(item_id, []):
                            item_to_stores[item_id].append(store_name)
                # check seasonal
                seasonal = cat.get("seasonal", {})
                if isinstance(seasonal, dict):
                    for s, items in seasonal.items():
                        for it in items:
                            item_id = it.get("item") if isinstance(it, dict) else it
                            if item_id:
                                if store_name not in item_to_stores.setdefault(item_id, []):
                                    item_to_stores[item_id].append(store_name)
    return item_to_stores


def build_almanac_dataset() -> Dict[str, Any]:
    # 1. Load Categories from sub_menus.toml
    sub_menus_path = FIDDLE_DIR / "ui" / "menus" / "sub_menus.toml"
    with open(sub_menus_path, "rb") as f:
        sub_menus = tomllib.load(f)
    raw_categories = sub_menus.get("almanac", {}).get("categories", [])

    categories: Dict[str, Dict[str, Any]] = {}
    for cat in raw_categories:
        k = cat["key"]
        meta = CATEGORY_METADATA.get(k, {})
        raw_icon = meta.get("icon") or cat.get("icon_sprite") or f"spr_ui_journal_almanac_icon_{k}.png"
        icon_name = raw_icon if raw_icon.endswith(".png") else f"{raw_icon}.png"
        categories[k] = {
            "key": k,
            "name": meta.get("name", cat.get("name", k.replace("_", " ").title())),
            "icon": icon_name,
            "description": meta.get("description", ""),
            "tags": cat.get("tags", []),
            "total_items": 0,
            "item_ids": [],
        }

    # 2. Auxiliary data sources
    fish_info = load_fish_toml()
    bugs_info = load_bugs_toml()
    forage_seasons = load_forageables_toml()
    artifact_locs = load_artifacts_toml()
    store_catalog = load_stores_toml()

    item_seasons_path = DATA_DIR / "item_seasons.json"
    cached_seasons = {}
    if item_seasons_path.exists():
        with open(item_seasons_path, "r", encoding="utf-8") as f:
            cached_seasons = json.load(f)

    item_locations_path = DATA_DIR / "item_locations.json"
    cached_locations = {}
    if item_locations_path.exists():
        with open(item_locations_path, "r", encoding="utf-8") as f:
            cached_locations = json.load(f)

    alt_sources_path = DATA_DIR / "alt_sources.json"
    cached_alt_sources = {}
    if alt_sources_path.exists():
        with open(alt_sources_path, "r", encoding="utf-8") as f:
            cached_alt_sources = json.load(f)

    # 3. Read items from fiddle/items/**/*.toml
    items_dir = FIDDLE_DIR / "items"
    raw_items: Dict[str, Tuple[Dict[str, Any], str]] = {}

    for p in sorted(items_dir.glob("**/*.toml")):
        with open(p, "rb") as f:
            data = tomllib.load(f)
        rel_path = str(p.relative_to(FIDDLE_DIR))
        for item_id, item_def in data.items():
            if not isinstance(item_def, dict) or item_id == "harvest_day_pie":
                continue
            raw_items[item_id] = (item_def, rel_path)

    items: Dict[str, Dict[str, Any]] = {}

    # Sort item IDs for deterministic output
    for item_id in sorted(raw_items.keys()):
        item_def, rel_path = raw_items[item_id]
        tags = item_def.get("tags", [])
        tags_set = set(tags)

        # Category membership
        matched_categories = []
        for cat_key, cat_data in categories.items():
            if set(cat_data["tags"]) & tags_set:
                matched_categories.append(cat_key)

        if not matched_categories:
            continue

        for m_cat in matched_categories:
            categories[m_cat]["item_ids"].append(item_id)

        # Primary category determination
        if "items/other/materials.toml" in rel_path or "refined_material" in tags:
            primary_category = "materials"
        elif "items/other/artifacts.toml" in rel_path or "archaeology" in tags:
            primary_category = "artifacts"
        elif "items/other/blacksmithing.toml" in rel_path or "blacksmithing" in tags:
            primary_category = "blacksmithing"
        elif "items/other/cooked_dishes.toml" in rel_path or "food" in tags:
            primary_category = "cooked_dishes"
        elif "items/crops/" in rel_path or "crops.toml" in rel_path or "crop" in tags:
            primary_category = "crops"
        elif "items/fish/" in rel_path or ("fishable" in tags or "dive" in tags):
            primary_category = "fish"
        elif "items/furniture/" in rel_path or "furniture" in tags:
            primary_category = "furniture"
        else:
            primary_category = matched_categories[0]

        # Recipe parsing
        recipe_data = None
        if "recipe" in item_def:
            st = classify_station(item_id, item_def, rel_path)
            is_default = bool(item_def.get("recipe_is_default", False))
            ingredients = []
            for entry in item_def.get("recipe", []):
                if isinstance(entry, dict):
                    if "item" in entry:
                        ingredients.append({
                            "item_id": entry["item"],
                            "count": max(1, int(entry.get("count", 1))),
                        })
                    elif "essence" in entry:
                        ingredients.append({
                            "item_id": "essence",
                            "count": max(1, int(entry["essence"])),
                        })
            recipe_data = {
                "station": st,
                "is_default": is_default,
                "ingredients": ingredients,
                "output_count": 1,
            }

        # Furniture swatch grouping
        recipe_key = item_def.get("recipe_key")
        swatch_name = None
        if "furniture" in matched_categories:
            if recipe_key:
                if item_id == recipe_key:
                    swatch_name = "Default"
                elif item_id.startswith(f"{recipe_key}_"):
                    suffix = item_id[len(recipe_key) + 1:]
                    swatch_name = suffix.replace("_", " ").title()
                else:
                    swatch_name = item_id.replace("_", " ").title()
            else:
                recipe_key = None
                swatch_name = None
        else:
            recipe_key = None
            swatch_name = None

        # Value (strictly integer sell/buy values >= 0)
        val = item_def.get("value")
        if isinstance(val, dict):
            value_dict = {
                "bin": coerce_int(val.get("bin"), 0),
                "store": coerce_int(val.get("store"), 0),
            }
        else:
            value_dict = {"bin": 0, "store": 0}

        # Sources & Acquisition Metadata
        sources: List[Dict[str, str]] = []
        seasons: List[str] = []
        weather: List[str] = []
        time_info: List[str] = []

        # Recipe source
        if recipe_data:
            sources.append({
                "type": recipe_data["station"],
                "location": STATION_LOCATIONS.get(recipe_data["station"], "Crafting Station"),
                "tier": "quick",
            })

        # Shop sources
        for store_name in store_catalog.get(item_id, []):
            sources.append({
                "type": "shop",
                "location": store_name,
                "tier": "quick",
            })

        # Cached alt sources
        for alt in cached_alt_sources.get(item_id, []):
            v_name = alt.get("vendor") or alt.get("location") or alt.get("type", "alternate")
            src_type = alt.get("type", "alternate")
            tier = "quick" if src_type in ("shop", "vendor", "mill") else "grind"
            entry = {"type": src_type, "location": v_name, "tier": tier}
            if entry not in sources:
                sources.append(entry)

        # Fish data
        if item_id in fish_info:
            f_entry = fish_info[item_id]
            f_seasons = f_entry.get("seasons")
            if isinstance(f_seasons, list):
                seasons.extend(f_seasons)
            elif f_seasons is False or f_seasons is None:
                seasons.extend(ALL_SEASONS)

            f_weather = f_entry.get("weather")
            if isinstance(f_weather, list):
                weather.extend(f_weather)

            f_hours = f_entry.get("hours")
            if isinstance(f_hours, list) and len(f_hours) == 2:
                time_info.append(f"{f_hours[0]}:00 - {f_hours[1]}:00")

            f_locs = f_entry.get("locations")
            loc_str = ", ".join(f_locs) if isinstance(f_locs, list) else (str(f_locs) if f_locs else "Waters")
            src_type = "dive" if "dive" in tags else "fishing"
            sources.append({
                "type": src_type,
                "location": f"Fishing / Diving ({loc_str})",
                "tier": "grind",
            })

        # Bug data
        if item_id in bugs_info:
            b_entry = bugs_info[item_id]
            b_seasons = b_entry.get("seasons")
            if isinstance(b_seasons, list):
                seasons.extend(b_seasons)
            elif b_seasons is False or b_seasons is None:
                seasons.extend(ALL_SEASONS)

            b_weather = b_entry.get("weather")
            if isinstance(b_weather, list):
                weather.extend(b_weather)

            b_hours = b_entry.get("hours")
            if isinstance(b_hours, list) and len(b_hours) == 2:
                time_info.append(f"{b_hours[0]}:00 - {b_hours[1]}:00")

            b_spawn = b_entry.get("spawn")
            spawn_str = ", ".join(b_spawn) if isinstance(b_spawn, list) else (str(b_spawn) if b_spawn else "Wild")
            sources.append({
                "type": "bug_catching",
                "location": f"Bug Catching ({spawn_str})",
                "tier": "grind",
            })

        # Forageables data
        if item_id in forage_seasons:
            seasons.extend(sorted(list(forage_seasons[item_id])))
            sources.append({
                "type": "foraging",
                "location": "Wild / Nature",
                "tier": "grind",
            })

        # Cached seasons
        if item_id in cached_seasons:
            for s in cached_seasons[item_id]:
                if s not in seasons:
                    seasons.append(s)

        # Cached locations
        if item_id in cached_locations:
            loc = cached_locations[item_id]
            tier = "farm" if "ranch" in loc.lower() or "farm" in loc.lower() else "grind"
            sources.append({
                "type": "gathering",
                "location": loc,
                "tier": tier,
            })

        # Fallback category-based sources & seasons
        if "crop" in tags:
            if not any(s["type"] == "farming" for s in sources):
                sources.append({"type": "farming", "location": "Farm Crops", "tier": "farm"})
        if "ranching" in tags:
            if not any(s["type"] == "ranching" for s in sources):
                sources.append({"type": "ranching", "location": "Animal Care / Ranch", "tier": "farm"})
        if "archaeology" in tags:
            if not any(s["type"] == "archaeology" for s in sources):
                sources.append({"type": "archaeology", "location": "Excavation / Dig Sites", "tier": "grind"})

        # Normalize seasons
        clean_seasons = []
        for s in seasons:
            s_norm = s.strip().lower()
            if s_norm == "autumn":
                s_norm = "fall"
            if s_norm in ALL_SEASONS and s_norm not in clean_seasons:
                clean_seasons.append(s_norm)
        # Order seasons spring -> summer -> fall -> winter
        ordered_seasons = [s for s in ALL_SEASONS if s in clean_seasons]

        # De-duplicate sources
        unique_sources = []
        seen_sources = set()
        for src in sources:
            key = (src.get("type"), src.get("location"), src.get("tier"))
            if key not in seen_sources:
                seen_sources.add(key)
                unique_sources.append(src)

        # De-duplicate weather & time
        weather = sorted(list(set(weather)))
        time_info = sorted(list(set(time_info)))

        # Item record
        items[item_id] = {
            "item_id": item_id,
            "name": item_def.get("name") or item_id.replace("_", " ").title(),
            "description": item_def.get("description", ""),
            "category": primary_category,
            "categories": matched_categories,
            "recipe_key": recipe_key,
            "swatch_name": swatch_name,
            "tags": tags,
            "value": value_dict,
            "recipe": recipe_data,
            "sources": unique_sources,
            "seasons": ordered_seasons,
            "weather": weather,
            "time": time_info,
            "icon_sprite": item_def.get("icon_sprite") or f"spr_ui_item_{item_id}",
        }

    # Update category totals
    for cat_data in categories.values():
        cat_data["total_items"] = len(cat_data["item_ids"])

    return {
        "version": "1.0.0",
        "categories": categories,
        "items": items,
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    dataset = build_almanac_dataset()

    data_file = DATA_DIR / "almanac_data.json"
    web_file = WEB_DATA_DIR / "almanac_data.json"

    content = json.dumps(dataset, indent=2, ensure_ascii=False)

    with open(data_file, "w", encoding="utf-8") as f:
        f.write(content)

    with open(web_file, "w", encoding="utf-8") as f:
        f.write(content)

    print("=" * 60)
    print("Fields of Mistria — Almanac Dataset Generator")
    print("=" * 60)
    print(f"Categories Generated: {len(dataset['categories'])}")
    for cat_k, cat_v in dataset["categories"].items():
        print(f"  - {cat_k:18s}: {cat_v['total_items']:4d} items ({cat_v['name']})")
    print(f"Total Unique Items:   {len(dataset['items'])}")

    recipes_count = sum(1 for it in dataset["items"].values() if it.get("recipe"))
    default_recipes = sum(1 for it in dataset["items"].values() if it.get("recipe") and it["recipe"]["is_default"])
    furniture_unique = len(set(
        it.get("recipe_key") or it["item_id"]
        for it in dataset["items"].values()
        if "furniture" in it.get("categories", [])
    ))

    print(f"Items with Recipes:   {recipes_count}")
    print(f"  - Default Unlocked: {default_recipes}")
    print(f"Unique Furniture Keys:{furniture_unique}")
    print(f"Wrote target:         {data_file}")
    print(f"Mirrored target:      {web_file}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
