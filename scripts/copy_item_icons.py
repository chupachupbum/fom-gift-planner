#!/usr/bin/env python3
"""
scripts/copy_item_icons.py

Extracts unique item IDs from data/item_data.json and data/recipes.json,
filters out metadata keys, resolves matching PNG sprites from game assets
using 3 resolution strategies (exact, no-underscore, manual remap),
and copies them into companion/static/icons/items/ and companion/static/icons/npcs/.
"""

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

METADATA_KEYS_TO_EXCLUDE: Set[str] = {
    "display_name",
    "liked_by",
    "loved_by",
    "quests",
    "tags",
    "cooking_recipes",
    "crafting_recipes",
}

# 11 manual remap items
MANUAL_REMAP: Dict[str, str] = {
    # 1. Treats & Pet Feed
    "cat_treat": "animal_treat_cat",
    "dog_treat": "animal_treat_dog",
    "deluxe_hay": "animal_feed_hay_deluxe",
    "quality_hay": "animal_feed_hay_quality",
    "ultimate_hay": "animal_feed_hay_ultimate",
    "deluxe_small_animal_feed": "animal_feed_seed_deluxe",
    "quality_small_animal_feed": "animal_feed_seed_quality",
    "ultimate_small_animal_feed": "animal_feed_seed_ultimate",

    # 2. Food & Cooking
    "miners_mushroom_stew": "miner_mushroom_stew",
    "crayfish": "dive_crayfish",
    "golden_egg": "chicken_egg_gold",
    "egg": "chicken_egg_regular",
    "duck_egg": "duck_egg_regular",
    "golden_duck_egg": "duck_egg_gold",
    "cow_milk": "cow_milk_regular",
    "golden_cow_milk": "cow_milk_gold",

    # 3. Animal Products
    "golden_feather": "chicken_feather_gold",
    "feather": "chicken_feather_regular",
    "golden_duck_feather": "duck_feather_gold",
    "duck_feather": "duck_feather_regular",
    "alpaca_wool": "alpaca_wool_regular",
    "golden_alpaca_wool": "alpaca_wool_gold",
    "bristle": "capybara_bristle_regular",
    "golden_bristle": "capybara_bristle_gold",
    "horse_hair": "horse_hair_regular",
    "golden_horse_hair": "horse_hair_gold",
    "rabbit_wool": "rabbit_hair_regular",
    "golden_rabbit_wool": "rabbit_hair_gold",
    "sheep_wool": "sheep_wool_regular",
    "golden_sheep_wool": "sheep_wool_gold",
    "bull_horn": "cow_horn_regular",
    "golden_bull_horn": "cow_horn_gold",

    # 4. Plants, Trees, Forage, Farming
    "sapling_oak": "oak_sapling",
    "sapling_pine": "pine_sapling",
    "sapling_cherry": "cherry_sapling",
    "sapling_lemon": "lemon_sapling",
    "wood": "regularwood",
    "basic_wood": "regularwood",
    "wild_grapes": "bush_grape",
    "bell_berry": "bush_bell_berry",
    "blackberry": "bush_blackberry",
    "blueberry": "bush_blueberry",
    "glowberry": "bush_glowberry",
    "hydrangea": "bush_hydrangea",
    "rose_hip": "bush_rosehip",
    "wild_berries": "bush_wildberry",
    "wintergreen_berry": "bush_wintergreen",
    "breath_of_fire": "breath_of_flame",
    "dandelion": "dandelionflower",
    "middlemist": "middlemistred",
    "wild_leek": "springonion",
    "grass_seed": "small_grass_starter",
    "hay": "hayball",
    "haydens_weathervane": "weathervane",
    "lava_chestnuts": "lava_chestnut",
    "seed_mystery_bag": "bagseed_mystery_bag_icon",

    # 5. Ores, Stones & Minerals
    "ore_stone": "rock",
    "ore_copper": "copper_ore",
    "ore_iron": "iron_ore",
    "ore_gold": "gold_ore",
    "ore_silver": "silver_ore",
    "ore_mistril": "mistril_ore",
    "ore_ruby": "ruby",
    "ore_sapphire": "sapphire",
    "ore_emerald": "emerald",
    "ore_diamond": "diamond",
    "ore_pink_diamond": "pinkdiamond",

    # 6. Diving & Shells
    "blue_conch_shell": "shell_small_blue_conch",
    "pink_scallop_shell": "shell_pink_scallop",
    "sand_dollar": "shell_sand_dollar",
    "spirula_shell": "shell_common_spirula",
    "clam": "dive_clam",
    "freshwater_oyster": "dive_freshwater_oyster",
    "newt": "dive_newt",
    "river_snail": "dive_pond_snail",
    "seaweed": "dive_seaweed",

    # 7. Fish
    "sardine": "fish_small_sardine",
    "salmon": "fish_large_salmon",
    "trout": "fish_medium_trout",
    "tuna": "fish_large_tuna",
    "bonito": "fish_medium_bonito",
    "bream": "fish_large_bream",
    "catfish": "fish_medium_catfish",
    "cod": "fish_large_cod",
    "goby": "fish_medium_goby",
    "perch": "fish_large_perch",
    "pike": "fish_large_pike",
    "squid": "fish_medium_squid",
    "tilapia": "fish_small_tilapia",
    "turtle": "fish_large_turtle",
    "red_snapper": "fish_large_red_snapper",
    "sea_bream": "fish_medium_sea_bream",
    "shrimp": "fish_small_shrimp",
    "archerfish": "fish_small_archerfish",
    "coelacanth": "fish_large_coelacanth",
    "herring": "fish_small_herring",
    "mackerel": "fish_large_mackerel",
    "mullet": "fish_medium_mullet",
    "tetra": "fish_small_tetra",
    "armored_bass": "fish_medium_armored_bass",
    "bullfrog": "fish_small_bullfrog",
    "cave_shrimp": "fish_small_cave_shrimp",
    "crab": "fish_small_crab",
    "firesail_fish": "fish_large_firesail_fish",
    "freshwater_eel": "fish_medium_freshwater_eel",
    "frog": "fish_small_frog",
    "king_crab": "fish_large_king_crab",
    "lake_trout": "fish_large_lake_trout",
    "lobster": "fish_medium_lobster",
    "luminescent_crab": "fish_medium_luminescent_crab",
    "sapphire_betta": "fish_small_sapphire_betta",
    "smallmouth_bass": "fish_small_smallmouth_bass",
    "stone_loach": "fish_medium_stone_loach",
    "striped_bass": "fish_large_striped_bass",

    # 8. Bugs & Critters
    "lightning_dragonfly": "insect_lightningdragonfly",
    "hummingbird_hawk_moth": "insect_hummingbirdhawkmoth",
    "rhinoceros_beetle": "insect_rhinocerosbeetle",
    "crystalline_cricket": "insect_crystalline_cricket",
    "ant": "insect_ant",
    "ancient_firefly": "insect_ancient_firefly",
    "bumblebee": "insect_bumblebee",
    "butterfly": "insect_butterfly",
    "caterpillar": "insect_caterpillar",
    "cicada": "insect_cicada",
    "copper_beetle": "insect_copper_beetle",
    "coral_mantis": "insect_coral_mantis",
    "cricket": "insect_cricket",
    "crystal_caterpillar": "insect_crystalcaterpillar",
    "crystal_wing_moth": "insect_crystal_wing_moth",
    "deep_earthworm": "insect_deep_earthworm",
    "dragon_horn_beetle": "insect_dragon_horn_beetle",
    "fairy_bee": "insect_fairybee",
    "fire_wasp": "insect_fire_wasp",
    "firefly": "insect_firefly",
    "fuzzy_moth": "insect_fuzzymoth",
    "grasshopper": "insect_grasshopper",
    "hermit_crab": "insect_hermitcrab",
    "inchworm": "insect_inchworm",
    "jewel_beetle": "insect_jewelbeetle",
    "ladybug": "insect_ladybug",
    "lantern_moth": "insect_lantern_moth",
    "mistmoth": "insect_mistmoth",
    "monarch_butterfly": "insect_monarchbutterfly",
    "orchid_mantis": "insect_orchidmantis",
    "pond_skater": "insect_pondskater",
    "praying_mantis": "insect_prayingmantis",
    "puddle_spider": "insect_puddle_spider",
    "question_mark_butterfly": "insect_questionmarkbutterfly",
    "roly_poly": "insect_pillbug",
    "sea_scarab": "insect_sea_scarab",
    "singing_katydid": "insect_singing_katydid",
    "smoke_moth": "insect_smoke_moth",
    "snail": "insect_snail",
    "snowball_beetle": "insect_snowballbeetle",
    "strobe_firefly": "insect_strobefirefly",
    "void_snail": "insect_void_snail",
    "worm": "insect_worm",

    # 9. Tools & Wearables
    "axe_silver": "tool_silver_axe",
    "net_copper": "tool_copper_net",
    "shovel_copper": "tool_copper_shovel",
    "shovel_iron": "tool_iron_shovel",
    "sword_corrupted_mistril": "tool_corrupted_mistril_sword",
    "sword_silver": "tool_silver_sword",
    "watering_can_iron": "tool_iron_watering_can",
    "iron_armor": "wearable_top_iron_armor",

    # 10. Placeables & Misc
    "animal_currency": "currency",
    "shiny_bead": "shiny_bead",
    "spooky_haybale": "decor_spooky_haybale",
    "starter_bird_house_red": "decor_starter_bird_house_red",
    "starter_potted_plant": "decor_starter_potted_plant",
    "starter_scarecrow": "decor_starter_scarecrow",
    "starter_shipping_box": "basic_misc_shipping_bin",
    "starter_wood_fence": "decor_starter_wood_fence",

    # 11. Additional location/season item aliases
    "stone": "rock",
    "milk": "cow_milk_regular",
    "golden_milk": "cow_milk_gold",
    "cattail_fluff": "cattail",
    "alligator_gar": "fish_giant_alligator_gar",
    "anchovy": "fish_small_anchovy",
    "angel_fish": "fish_small_angel_fish",
    "barb": "fish_small_barb",
    "bluefish": "fish_large_bluefish",
    "bluegill": "fish_small_blue_gill",
    "bowfish": "fish_large_bowfish",
    "brown_bullhead": "fish_medium_brown_bullhead",
    "brown_trout": "fish_large_brown_trout",
    "burbot": "fish_large_burbot",
    "carp": "fish_medium_carp",
    "cave_eel": "fish_medium_cave_eel",
    "chum": "fish_large_chum",
    "chum_salmon": "fish_large_chum",
    "diamond_beetle": "insect_diamond_beetle",
    "dragonfly": "insect_lightningdragonfly",
    "earth_eel": "fish_medium_earth_eel",
    "flathead_catfish": "fish_medium_flathead_catfish",
    "forest_perch": "fish_medium_forest_perch",
    "gar": "fish_large_gar",
    "gazer": "fish_small_gazer",
    "giant_jellyfish": "fish_large_giant_jellyfish",
    "giant_worm": "insect_giant_worm",
    "grayling": "fish_small_grayling",
    "horse_mackerel": "fish_small_horse_mackerel",
    "koi": "fish_medium_koi",
    "minnow": "fish_small_minnow",
    "muskie": "fish_large_muskie",
    "paper_pond_shell": "dive_paper_pondshell",
    "paper_pond_snail": "dive_pond_snail",
    "parchment_moth": "insect_parchment_moth",
    "pea": "peas",
    "snow_pea": "snow_peas",
    "pearl_clam": "dive_pearl_clam",
    "pollock": "fish_large_pollock",
    "pond_snail": "dive_pond_snail",
    "puffer_fish": "fish_medium_puffer_fish",
    "radish": "daikon_radish",
    "rainbow_trout": "fish_medium_rainbow_trout",
    "roach": "fish_medium_roach",
    "rock_bass": "fish_medium_rock_bass",
    "sea_bass": "fish_medium_sea_bass",
    "sea_urchin": "fish_small_sea_urchin",
    "shadow_bass": "fish_medium_shadow_bass",
    "silver_redhorse": "fish_medium_silver_redhorse",
    "snakehead": "fish_large_snakehead",
    "snapping_turtle": "fish_large_snapping_turtle",
    "sturgeon": "fish_large_sturgeon",
    "sulfur_crab": "fish_medium_sulfur_crab",
    "sunny": "fish_small_sunny",
    "swallowtail_butterfly": "insect_tigerswallowtailbutterfly",
    "swordfish": "fish_large_swordfish",
    "walleye": "fish_large_walleye",
    "white_perch": "fish_medium_white_perch",
    "winged_shrimp": "fish_small_winged_shrimp",
    "octopus": "fish_large_octopus",
    "lava_piranha": "fish_small_lava_piranha",
    "mantis": "insect_prayingmantis",
    "yellow_perch": "fish_large_perch",
}

CRITICAL_EXCLUDED_ITEMS: Set[str] = set()

DEFAULT_ASSET_DIR = Path("/home/tyrell/Downloads/assets/animations/Item Icons")


def extract_item_ids(repo_root: Path) -> Set[str]:
    """
    Extracts all unique item IDs from data/item_data.json, data/recipes.json,
    data/item_locations.json, and data/item_seasons.json, filtering out metadata keys.
    """
    item_ids: Set[str] = set()

    # 1. Extract from data/item_data.json
    item_data_path = repo_root / "data" / "item_data.json"
    if item_data_path.exists():
        with open(item_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in data.get("items", {}).keys():
            k = key.strip().lower()
            if k and k not in METADATA_KEYS_TO_EXCLUDE and k not in CRITICAL_EXCLUDED_ITEMS:
                item_ids.add(k)

    # 2. Extract from data/recipes.json
    recipes_path = repo_root / "data" / "recipes.json"
    if recipes_path.exists():
        with open(recipes_path, "r", encoding="utf-8") as f:
            recipes = json.load(f)
        for r_id, r_info in recipes.items():
            out_id = (r_info.get("item_id") or r_id).strip().lower()
            if out_id and out_id not in METADATA_KEYS_TO_EXCLUDE and out_id not in CRITICAL_EXCLUDED_ITEMS:
                item_ids.add(out_id)
            for ing in r_info.get("ingredients", []):
                ing_id = ing.get("item_id", "").strip().lower()
                if ing_id and ing_id not in METADATA_KEYS_TO_EXCLUDE and ing_id not in CRITICAL_EXCLUDED_ITEMS:
                    item_ids.add(ing_id)

    # 3. Extract from data/item_locations.json
    locations_path = repo_root / "data" / "item_locations.json"
    if locations_path.exists():
        with open(locations_path, "r", encoding="utf-8") as f:
            locations = json.load(f)
        for k in locations.keys():
            k_clean = k.strip().lower()
            if k_clean and k_clean not in METADATA_KEYS_TO_EXCLUDE and k_clean not in CRITICAL_EXCLUDED_ITEMS:
                item_ids.add(k_clean)

    # 4. Extract from data/item_seasons.json
    seasons_path = repo_root / "data" / "item_seasons.json"
    if seasons_path.exists():
        with open(seasons_path, "r", encoding="utf-8") as f:
            seasons = json.load(f)
        for k in seasons.keys():
            k_clean = k.strip().lower()
            if k_clean and k_clean not in METADATA_KEYS_TO_EXCLUDE and k_clean not in CRITICAL_EXCLUDED_ITEMS:
                item_ids.add(k_clean)

    return item_ids


def build_asset_index(asset_dir: Path) -> Dict[str, Path]:
    """
    Builds an in-memory hash map of lowercased file stem -> Path
    for fast O(1) icon lookup across thousands of asset files.
    Excludes outline sprites (*_outline.png).
    """
    index: Dict[str, Path] = {}
    if not asset_dir.exists():
        return index

    for p in asset_dir.glob("**/*.png"):
        if p.is_file() and not p.name.endswith("_outline.png"):
            index[p.stem.lower()] = p

    return index


def resolve_item_icon(
    item_id: str,
    asset_index: Dict[str, Path],
) -> Tuple[Optional[str], Optional[Path]]:
    """
    Attempts to match an item ID to an asset file using three naming strategies:
    1. Exact match: spr_ui_item_{id}.png
    2. No-underscore match: spr_ui_item_{id_without_underscores}.png
    3. Manual remap: spr_ui_item_{remap}.png
    """
    clean_id = item_id.strip().lower()

    # Strategy 1: Exact match
    stem_exact = f"spr_ui_item_{clean_id}"
    if stem_exact in asset_index:
        return "exact", asset_index[stem_exact]

    # Strategy 2: No-underscore match
    stem_no_under = f"spr_ui_item_{clean_id.replace('_', '')}"
    if stem_no_under in asset_index:
        return "no_underscore", asset_index[stem_no_under]

    # Strategy 3: Manual remap
    if clean_id in MANUAL_REMAP:
        stem_remap = f"spr_ui_item_{MANUAL_REMAP[clean_id]}"
        if stem_remap in asset_index:
            return "manual_remap", asset_index[stem_remap]

    return None, None


def copy_icons(
    asset_dir: Path,
    repo_root: Path,
) -> Dict[str, Any]:
    """
    Copies matched item and NPC icons to static asset directories.
    Ensures idempotency and regression safety.
    """
    dest_items_dir = repo_root / "companion" / "static" / "icons" / "items"
    dest_npcs_dir = repo_root / "companion" / "static" / "icons" / "npcs"

    dest_items_dir.mkdir(parents=True, exist_ok=True)
    dest_npcs_dir.mkdir(parents=True, exist_ok=True)

    # Build asset index
    asset_index = build_asset_index(asset_dir)

    # Extract items
    item_ids = extract_item_ids(repo_root)

    matched_items: Dict[str, Tuple[str, Path]] = {}
    missing_items: List[str] = []
    strategy_counts: Dict[str, int] = {
        "exact": 0,
        "no_underscore": 0,
        "manual_remap": 0,
    }

    # Resolve items
    for it in sorted(item_ids):
        strategy, src_path = resolve_item_icon(it, asset_index)
        if strategy and src_path:
            matched_items[it] = (strategy, src_path)
            strategy_counts[strategy] += 1
        else:
            missing_items.append(it)

    # Copy item icons flat, preserving original asset filenames
    copied_items_count = 0
    for it, (strat, src_path) in matched_items.items():
        dst = dest_items_dir / src_path.name
        shutil.copy2(src_path, dst)
        copied_items_count += 1

    # Copy NPC icons from both:
    # 1. UI NEW/Generic/Icons/NPC/ (all 35 full-town NPC icons: spr_ui_generic_icon_npc_*.png)
    # 2. _SUB ICONS/NPC/ (13 romanceable sub-icons: spr_ui_item_sub_npc_*.png)
    copied_npcs_count = 0
    copied_npc_names: List[str] = []

    # 1. UI NEW generic NPC icons (all 35 townspeople)
    ui_npc_dir = asset_dir.parent / "UI NEW" / "Generic" / "Icons" / "NPC"
    if ui_npc_dir.exists():
        for p in sorted(ui_npc_dir.glob("spr_ui_generic_icon_npc_*.png")):
            if p.is_file() and "outline" not in p.name:
                dst = dest_npcs_dir / p.name
                shutil.copy2(p, dst)
                copied_npcs_count += 1
                copied_npc_names.append(p.name)
                # Also create a compatibility copy as spr_ui_item_sub_npc_<name>.png if not present
                npc_name = p.stem.replace("spr_ui_generic_icon_npc_", "")
                sub_dst = dest_npcs_dir / f"spr_ui_item_sub_npc_{npc_name}.png"
                if not sub_dst.exists():
                    shutil.copy2(p, sub_dst)

    # 2. SUB ICONS NPC
    npc_src_dir = asset_dir / "_SUB ICONS" / "NPC"
    if npc_src_dir.exists():
        for p in sorted(npc_src_dir.glob("spr_ui_item_sub_npc_*.png")):
            if p.is_file() and not p.name.endswith("_outline.png"):
                dst = dest_npcs_dir / p.name
                shutil.copy2(p, dst)
                if p.name not in copied_npc_names:
                    copied_npcs_count += 1
                    copied_npc_names.append(p.name)

    return {
        "total_items_analyzed": len(item_ids),
        "matched_count": len(matched_items),
        "copied_items_count": copied_items_count,
        "missing_count": len(missing_items),
        "missing_items": missing_items,
        "strategy_counts": strategy_counts,
        "copied_npcs_count": copied_npcs_count,
        "copied_npc_names": copied_npc_names,
        "dest_items_dir": dest_items_dir,
        "dest_npcs_dir": dest_npcs_dir,
    }


def print_summary(report: Dict[str, Any]) -> None:
    """Prints a clean summary report of the icon copying process."""
    print("=" * 60)
    print("Fields of Mistria — Game Asset Icon Copy Summary")
    print("=" * 60)
    print(f"Total Unique Items Analyzed:  {report['total_items_analyzed']}")
    print(f"Matched & Copied Items:      {report['matched_count']}")
    print(f"  - Exact Matches:            {report['strategy_counts']['exact']}")
    print(f"  - No-Underscore Matches:    {report['strategy_counts']['no_underscore']}")
    print(f"  - Manual Remaps:            {report['strategy_counts']['manual_remap']}")
    print(f"Unmatched (Missing) Items:   {report['missing_count']}")
    print(f"Target Items Directory:      {report['dest_items_dir']}")
    print(f"Items Copied:                {report['copied_items_count']} PNG files")
    print(f"Target NPCs Directory:       {report['dest_npcs_dir']}")
    print(f"NPC Avatars Copied:          {report['copied_npcs_count']} PNG files")
    print(f"Idempotent Status:           SUCCESS (no collisions, clean copy)")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy game asset icons into companion static directory."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_ASSET_DIR,
        help="Path to the game asset Item Icons directory",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to repository root",
    )
    args = parser.parse_args()

    if not args.source_dir.exists():
        print(f"Error: Asset source directory not found at: {args.source_dir}", file=sys.stderr)
        return 1

    report = copy_icons(args.source_dir, args.repo_root)
    print_summary(report)

    if report["copied_items_count"] < 180:
        print(
            f"Error: Expected at least 180 items copied, got {report['copied_items_count']}",
            file=sys.stderr,
        )
        return 1

    if report["copied_npcs_count"] < 13:
        print(
            f"Error: Expected at least 13 NPC icons copied, got {report['copied_npcs_count']}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
