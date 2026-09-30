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
UI_DIR = PROJECT_ROOT / "companion" / "static" / "icons" / "ui"
FAVICON_PATH = PROJECT_ROOT / "companion" / "static" / "icons" / "favicon.png"

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


def harvest_sprites() -> None:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target UI icons directory: {UI_DIR}")

    success_count = 0
    for dest_name, (src_path, crop_box) in SPRITE_MAP.items():
        if not src_path.exists():
            print(f"WARNING: Source file not found: {src_path}")
            continue

        dest_path = UI_DIR / dest_name
        if crop_box:
            with Image.open(src_path) as im:
                cropped = im.crop(crop_box)
                cropped.save(dest_path)
            print(f"Cropped & saved: {dest_name} from {src_path.name} {crop_box}")
        else:
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {dest_name} from {src_path.name}")
        success_count += 1

    print(f"Successfully processed {success_count}/{len(SPRITE_MAP)} UI sprites.")


def generate_favicon() -> None:
    src = ANIM_DIR / "UI NEW/Calendar/spr_ui_calendar_icon_event_gift_festival.png"
    if not src.exists():
        print(f"ERROR: Cannot generate favicon, missing {src}")
        return

    FAVICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        # Scale to 32x32 using nearest neighbor interpolation to preserve pixel art
        fav = im.resize((32, 32), resample=Image.Resampling.NEAREST)
        fav.save(FAVICON_PATH)
    print(f"Generated 32x32 favicon at: {FAVICON_PATH}")


if __name__ == "__main__":
    harvest_sprites()
    generate_favicon()
