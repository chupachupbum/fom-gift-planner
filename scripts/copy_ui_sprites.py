#!/usr/bin/env python3
"""Harvest UI sprites from game assets and generate favicon.

Copies in-game UI sprites from /home/tyrell/Downloads/assets/animations/
and companion/static/icons/items/ into companion/static/icons/ui/.
Extracts frame 0 for multi-frame dialogue hearts.
Generates companion/static/icons/favicon.png (32x32, nearest-neighbor resampled).
"""

from pathlib import Path
import shutil
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANIM_DIR = Path("/home/tyrell/Downloads/assets/animations")
UI_DIRS = [
    PROJECT_ROOT / "companion" / "static" / "icons" / "ui",
    PROJECT_ROOT / "web" / "icons" / "ui",
]
FAVICON_PATHS = [
    PROJECT_ROOT / "companion" / "static" / "icons" / "favicon.png",
    PROJECT_ROOT / "web" / "icons" / "favicon.png",
]
UI_DIR = UI_DIRS[0]
FAVICON_PATH = FAVICON_PATHS[0]

# Mapping: destination filename -> (source path relative to ANIM_DIR or PROJECT_ROOT, is_relative_to_project, crop_box_or_none)
SPRITE_MAP = {
    "icon_gift.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_event_gift_festival.png",
        None,
    ),
    "icon_calendar.png": (
        ANIM_DIR / "UI NEW/Crafting/Woodcrafting/spr_ui_woodcrafting_category_icon_calendar.png",
        None,
    ),
    "season_spring.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_spring.png",
        None,
    ),
    "season_summer.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_summer.png",
        None,
    ),
    "season_fall.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_autumn.png",
        None,
    ),
    "season_winter.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_winter.png",
        None,
    ),
    "icon_saturday.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_event_saturday_market.png",
        None,
    ),
    "icon_stats.png": (
        ANIM_DIR / "UI NEW/Inventory and Storage/Storage Chest Bark Icons/spr_ui_storage_chest_bark_icon_crown.png",
        (7, 8, 17, 15),
    ),
    "icon_star.png": (
        ANIM_DIR / "UI NEW/Barks/spr_ui_bark_icon_stars.png",
        None,
    ),
    "icon_npc_group.png": (
        ANIM_DIR / "UI NEW/Generic/Icons/spr_ui_generic_my_name_icon.png",
        None,
    ),
    "icon_recipe.png": (
        ANIM_DIR / "UI NEW/Store Menu/spr_ui_store_category_icon_cooking_recipes.png",
        None,
    ),
    "icon_bag.png": (
        ANIM_DIR / "Item Icons/Wearable/spr_ui_item_wearable_back_gear_pumpkin_backpack.png",
        (3, 3, 15, 14),
    ),
    "icon_wheat.png": (
        PROJECT_ROOT / "companion/static/icons/items/spr_ui_item_wheat.png",
        None,
    ),
    "icon_perk_essence.png": (
        ANIM_DIR / "UI NEW/Inventory and Storage/Storage Chest Bark Icons/spr_ui_storage_chest_bark_icon_magic.png",
        (6, 7, 17, 16),
    ),
    "icon_save.png": (
        ANIM_DIR / "UI NEW/Barks/spr_ui_bark_icon_saving.png",
        None,
    ),
    "icon_tree.png": (
        PROJECT_ROOT / "companion/static/icons/items/spr_ui_item_oak_sapling.png",
        None,
    ),
    "icon_festival.png": (
        ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_event_spring_festival.png",
        None,
    ),
    "icon_check.png": (
        ANIM_DIR / "UI NEW/Generic/spr_ui_generic_checkbox_on.png",
        None,
    ),
    "heart_loved.png": (
        ANIM_DIR / "UI NEW/Dialogue/spr_ui_dialogue_heart_red.png",
        (0, 0, 15, 12),  # Frame 0 of red dialogue heart
    ),
    "heart_liked.png": (
        ANIM_DIR / "UI NEW/Dialogue/spr_ui_dialogue_heart_purple.png",
        (0, 0, 15, 12),  # Frame 0 of purple dialogue heart
    ),
    "icon_location_pin.png": (
        ANIM_DIR / "UI NEW/HUD/spr_ui_hud_map_icon.png",
        None,
    ),
    "icon_hammer.png": (
        ANIM_DIR / "UI NEW/Inventory and Storage/Storage Chest Bark Icons/spr_ui_storage_chest_bark_icon_crafting.png",
        None,
    ),
    "icon_lock.png": (
        ANIM_DIR / "UI NEW/Generic/Icons/spr_ui_generic_lock_icon.png",
        None,
    ),
    "tier_quick.png": (
        ANIM_DIR / "UI NEW/Barks/spr_ui_bark_icon_thunderstorm.png",
        None,
    ),
    "tier_grind.png": (
        ANIM_DIR / "UI NEW/Inventory and Storage/Storage Chest Bark Icons/spr_ui_storage_chest_bark_icon_mining.png",
        None,
    ),
    "tier_farm.png": (
        ANIM_DIR / "UI NEW/Inventory and Storage/Storage Chest Bark Icons/spr_ui_storage_chest_bark_icon_farming.png",
        None,
    ),
    "icon_search.png": (
        ANIM_DIR / "UI NEW/Generic/Icons/spr_ui_generic_renown_magnify_icon_enabled.png",
        None,
    ),
    "icon_sparkle.png": (
        ANIM_DIR / "UI NEW/Barks/spr_ui_bark_icon_stars.png",
        None,
    ),
}

# Almanac Category Sprites
ALMANAC_CATEGORIES = [
    "artifacts",
    "blacksmithing",
    "bugs",
    "cooked_dishes",
    "crops",
    "date_inspiration",
    "fish",
    "forageables",
    "furniture",
    "materials",
    "ranching",
    "song_crystals",
]

for cat in ALMANAC_CATEGORIES:
    src = ANIM_DIR / f"UI NEW/Journal/Almanac/spr_ui_journal_almanac_icon_{cat}.png"
    # Canonical name
    SPRITE_MAP[f"spr_ui_journal_almanac_icon_{cat}.png"] = (src, None)
    # itemcategory alias
    SPRITE_MAP[f"spr_ui_journal_almanac_icon_itemcategory_{cat}.png"] = (src, None)
    # short alias
    SPRITE_MAP[f"almanac_{cat}.png"] = (src, None)

# Handle singular song_crystal aliases
_song_crystals_src = ANIM_DIR / "UI NEW/Journal/Almanac/spr_ui_journal_almanac_icon_song_crystals.png"
SPRITE_MAP["spr_ui_journal_almanac_icon_song_crystal.png"] = (_song_crystals_src, None)
SPRITE_MAP["spr_ui_journal_almanac_icon_itemcategory_song_crystal.png"] = (_song_crystals_src, None)
SPRITE_MAP["almanac_song_crystal.png"] = (_song_crystals_src, None)

# Almanac Header and Tab Sprites
_header_src = ANIM_DIR / "UI NEW/Journal/Almanac/spr_ui_journal_almanac_header_icon.png"
SPRITE_MAP["spr_ui_journal_almanac_header_icon.png"] = (_header_src, None)
SPRITE_MAP["almanac_header.png"] = (_header_src, None)

_tab_enabled_src = ANIM_DIR / "UI NEW/Journal/Tabs/spr_ui_journal_tab_almanac_enabled.png"
SPRITE_MAP["spr_ui_journal_tab_almanac_enabled.png"] = (_tab_enabled_src, None)
SPRITE_MAP["spr_ui_journal_tab_almanac.png"] = (_tab_enabled_src, None)
SPRITE_MAP["almanac_tab.png"] = (_tab_enabled_src, None)

_tab_selected_src = ANIM_DIR / "UI NEW/Journal/Tabs/spr_ui_journal_tab_almanac_selected_enabled.png"
SPRITE_MAP["spr_ui_journal_tab_almanac_selected_enabled.png"] = (_tab_selected_src, None)

# Crafting station skill badges for batch queue
SKILL_STATIONS = [
    "cooking",
    "woodcrafting",
    "blacksmithing",
    "mining",
    "farming",
    "archaeology",
    "fishing",
    "ranching",
]
for skill in SKILL_STATIONS:
    skill_src = ANIM_DIR / f"UI NEW/Generic/Icons/Skill/spr_ui_skill_icon_{skill}.png"
    if skill_src.exists():
        SPRITE_MAP[f"spr_ui_skill_icon_{skill}.png"] = (skill_src, None)


def harvest_sprites() -> None:
    for ui_dir in UI_DIRS:
        ui_dir.mkdir(parents=True, exist_ok=True)
        print(f"Target UI icons directory: {ui_dir}")

    success_count = 0
    for dest_name, (src_path, crop_box) in SPRITE_MAP.items():
        if not src_path.exists():
            print(f"WARNING: Source file not found: {src_path}")
            continue

        if crop_box:
            with Image.open(src_path) as im:
                cropped = im.crop(crop_box)
                for ui_dir in UI_DIRS:
                    dest_path = ui_dir / dest_name
                    cropped.save(dest_path)
            print(f"Cropped & saved: {dest_name} from {src_path.name} {crop_box}")
        else:
            for ui_dir in UI_DIRS:
                dest_path = ui_dir / dest_name
                shutil.copy2(src_path, dest_path)
            print(f"Copied: {dest_name} from {src_path.name}")
        success_count += 1

    print(f"Successfully processed {success_count}/{len(SPRITE_MAP)} UI sprites across {len(UI_DIRS)} directories.")


def generate_favicon() -> None:
    src = ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_event_gift_festival.png"
    if not src.exists():
        print(f"ERROR: Cannot generate favicon, missing {src}")
        return

    with Image.open(src) as im:
        # Scale to 32x32 using nearest neighbor interpolation to preserve pixel art
        fav = im.resize((32, 32), resample=Image.Resampling.NEAREST)
        for fav_path in FAVICON_PATHS:
            fav_path.parent.mkdir(parents=True, exist_ok=True)
            fav.save(fav_path)
            print(f"Generated 32x32 favicon at: {fav_path}")


if __name__ == "__main__":
    harvest_sprites()
    generate_favicon()
