"""
tests/core/test_almanac_dataset.py

Milestone 1 Verification Test Suite for Almanac Dataset & Sprite Assets:
1. Verifies data/almanac_data.json and web/data/almanac_data.json match identically.
2. Validates all 12 canonical Almanac categories and exact item counts.
3. Validates exclusion of internal debug item harvest_day_pie.
4. Validates 1,008 unique furniture recipe_key groups across 1,530 furniture swatches.
5. Validates recipe classification across all 6 stations (cooking, milling, refining, blacksmithing, dragon_forging, woodcrafting).
6. Validates default recipe unlock counts and ingredient structure.
7. Validates that 100% of Almanac items have resolved sprites in both companion and web static dirs.
8. Validates category UI icons, header, and tab icons in both companion and web static dirs.
"""

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "almanac_data.json"
WEB_DATA_FILE = REPO_ROOT / "web" / "data" / "almanac_data.json"

COMP_ITEMS_DIR = REPO_ROOT / "companion" / "static" / "icons" / "items"
WEB_ITEMS_DIR = REPO_ROOT / "web" / "icons" / "items"
COMP_UI_DIR = REPO_ROOT / "companion" / "static" / "icons" / "ui"
WEB_UI_DIR = REPO_ROOT / "web" / "icons" / "ui"

EXPECTED_CATEGORY_COUNTS = {
    "artifacts": 105,
    "blacksmithing": 76,
    "bugs": 93,
    "cooked_dishes": 166,
    "crops": 38,
    "date_inspiration": 6,
    "fish": 148,
    "forageables": 92,
    "furniture": 1530,
    "materials": 77,
    "ranching": 39,
    "song_crystal": 22,
}

EXPECTED_STATION_COUNTS = {
    "cooking": 163,
    "milling": 22,
    "refining": 25,
    "blacksmithing": 71,
    "dragon_forging": 5,
    "woodcrafting": 1102,
}


@pytest.fixture(scope="module")
def almanac_data():
    assert DATA_FILE.exists(), f"Missing {DATA_FILE}"
    assert WEB_DATA_FILE.exists(), f"Missing {WEB_DATA_FILE}"
    with open(DATA_FILE, "r", encoding="utf-8") as f1, open(WEB_DATA_FILE, "r", encoding="utf-8") as f2:
        d1 = json.load(f1)
        d2 = json.load(f2)
    assert d1 == d2, "Mirror mismatch between data/almanac_data.json and web/data/almanac_data.json"
    return d1


def test_almanac_categories_and_counts(almanac_data):
    cats = almanac_data.get("categories", {})
    assert len(cats) == 12, f"Expected 12 categories, got {len(cats)}"
    for cat_key, expected_count in EXPECTED_CATEGORY_COUNTS.items():
        assert cat_key in cats, f"Missing category {cat_key}"
        cat_info = cats[cat_key]
        assert cat_info["total_items"] == expected_count, (
            f"Category {cat_key} count mismatch: {cat_info['total_items']} != {expected_count}"
        )
        assert len(cat_info["item_ids"]) == expected_count, (
            f"Category {cat_key} item_ids length mismatch: {len(cat_info['item_ids'])} != {expected_count}"
        )
        icon_name = cat_info.get("icon", "")
        assert icon_name.endswith(".png"), (
            f"Category {cat_key} icon '{icon_name}' lacks .png extension"
        )
        assert (COMP_UI_DIR / icon_name).exists(), (
            f"Category {cat_key} icon '{icon_name}' missing on disk in {COMP_UI_DIR}"
        )
        assert (WEB_UI_DIR / icon_name).exists(), (
            f"Category {cat_key} icon '{icon_name}' missing on disk in {WEB_UI_DIR}"
        )


def test_almanac_unique_items_and_debug_filter(almanac_data):
    items = almanac_data.get("items", {})
    assert len(items) == 2369, f"Expected 2,369 unique items, got {len(items)}"
    assert "harvest_day_pie" not in items, "Debug item harvest_day_pie was not filtered out"


def test_furniture_recipe_key_grouping(almanac_data):
    items = almanac_data["items"]
    furniture_ids = almanac_data["categories"]["furniture"]["item_ids"]
    assert len(furniture_ids) == 1530

    unique_recipe_keys = set()
    for item_id in furniture_ids:
        entry = items[item_id]
        rk = entry.get("recipe_key") or item_id
        unique_recipe_keys.add(rk)

    assert len(unique_recipe_keys) == 1008, (
        f"Expected 1,008 unique furniture recipe keys, got {len(unique_recipe_keys)}"
    )


def test_recipe_station_classification_and_defaults(almanac_data):
    items = almanac_data["items"]
    station_counts = {}
    default_unlock_count = 0
    total_recipes = 0

    for item_id, entry in items.items():
        rec = entry.get("recipe")
        if rec:
            total_recipes += 1
            st = rec.get("station")
            station_counts[st] = station_counts.get(st, 0) + 1
            if rec.get("is_default"):
                default_unlock_count += 1
            # Check ingredients have no duration dicts
            for ing in rec.get("ingredients", []):
                assert "item_id" in ing, f"Missing item_id in ingredient for {item_id}"
                assert "count" in ing, f"Missing count in ingredient for {item_id}"
                assert "hours" not in ing, f"Duration dict leaked into ingredient for {item_id}"
                assert "minutes" not in ing, f"Duration dict leaked into ingredient for {item_id}"

    assert total_recipes == 1388, f"Expected 1,388 recipes, got {total_recipes}"
    assert default_unlock_count == 202, f"Expected 202 default recipes, got {default_unlock_count}"
    assert station_counts == EXPECTED_STATION_COUNTS, (
        f"Station counts mismatch: {station_counts} != {EXPECTED_STATION_COUNTS}"
    )


def test_all_almanac_items_have_sprites_in_both_targets(almanac_data):
    items = almanac_data["items"]
    missing_companion = []
    missing_web = []

    for item_id, entry in items.items():
        sprite_name = entry.get("icon_sprite")
        assert sprite_name, f"Item {item_id} missing icon_sprite field"
        # Test sprite accessibility via canonical name or spr_ui_item_{item_id}.png
        candidate_names = [
            f"{sprite_name}.png",
            f"spr_ui_item_{item_id}.png",
        ]
        if not any((COMP_ITEMS_DIR / name).exists() for name in candidate_names):
            missing_companion.append((item_id, sprite_name))
        if not any((WEB_ITEMS_DIR / name).exists() for name in candidate_names):
            missing_web.append((item_id, sprite_name))

    assert len(missing_companion) == 0, f"Missing sprites in companion: {missing_companion[:10]}"
    assert len(missing_web) == 0, f"Missing sprites in web: {missing_web[:10]}"


def test_ui_category_and_tab_sprites_in_both_targets():
    required_ui_sprites = [
        "almanac_artifacts.png",
        "almanac_blacksmithing.png",
        "almanac_bugs.png",
        "almanac_cooked_dishes.png",
        "almanac_crops.png",
        "almanac_date_inspiration.png",
        "almanac_fish.png",
        "almanac_forageables.png",
        "almanac_furniture.png",
        "almanac_materials.png",
        "almanac_ranching.png",
        "almanac_song_crystals.png",
        "almanac_song_crystal.png",
        "almanac_tab.png",
        "almanac_header.png",
        "spr_ui_journal_tab_almanac_enabled.png",
        "spr_ui_journal_tab_almanac_selected_enabled.png",
        "spr_ui_skill_icon_cooking.png",
        "spr_ui_skill_icon_woodcrafting.png",
        "spr_ui_skill_icon_blacksmithing.png",
        "spr_ui_skill_icon_mining.png",
        "spr_ui_skill_icon_farming.png",
    ]

    for sprite in required_ui_sprites:
        assert (COMP_UI_DIR / sprite).exists(), f"Missing {sprite} in companion/static/icons/ui/"
        assert (WEB_UI_DIR / sprite).exists(), f"Missing {sprite} in web/icons/ui/"


def test_almanac_item_values_are_integers(almanac_data):
    items = almanac_data.get("items", {})
    assert len(items) == 2369, f"Expected 2,369 items, got {len(items)}"
    for item_id, entry in items.items():
        val = entry.get("value")
        assert isinstance(val, dict), f"Item {item_id} value is not a dict: {val!r}"
        bin_val = val.get("bin")
        store_val = val.get("store")
        assert isinstance(bin_val, int) and not isinstance(bin_val, bool), (
            f"Item {item_id} value.bin is not int: {bin_val!r}"
        )
        assert isinstance(store_val, int) and not isinstance(store_val, bool), (
            f"Item {item_id} value.store is not int: {store_val!r}"
        )
        assert bin_val >= 0, f"Item {item_id} value.bin is negative: {bin_val}"
        assert store_val >= 0, f"Item {item_id} value.store is negative: {store_val}"

