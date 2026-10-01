"""
tests/fixtures.py

Common synthetic test fixtures and data generators for FoM Gift Planner test suite.
Extracted from core test suites to provide reusable fixtures across tests/core, tests/web, tests/companion.
"""

import json
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional
import zlib

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    AvailabilityTier,
    SATURDAY_MARKET_VENDORS,
)


def create_mock_slot(
    item_id: Optional[str],
    count: int,
    infusion: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a standard FoM inventory slot dictionary with optional cooking perk infusion."""
    if item_id is None or count <= 0:
        return {"count": 0, "item": None, "required_tags": []}
    item_dict: Dict[str, Any] = {"item_id": str(item_id)}
    if infusion is not None:
        item_dict["infusion"] = str(infusion)
    return {
        "count": float(count),
        "item": item_dict,
        "required_tags": []
    }


def create_synthetic_save_entries(
    bag_items: Optional[Dict[str, int]] = None,
    chests_by_location: Optional[Dict[str, List[List[Dict[str, Any]]]]] = None,
    year: int = 2,
    season: str = "winter",
    day: int = 6,  # Day 6 is Saturday
    player_name: str = "TestHero",
    farm_name: str = "TestFarm",
    giftable_all: bool = True,
    gifted_npcs: Optional[Dict[str, List[str]]] = None,
    npc_ids: Optional[List[str]] = None,
    bag_slots: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Generates a complete dictionary of raw_entries for a FoM save file."""
    season_idx = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}.get(season.lower(), 0)
    cal_days = (year - 1) * 112 + season_idx * 28 + (day - 1)
    cal_time = cal_days * 86400

    entries: Dict[str, str] = {}

    header_data = {
        "name": player_name,
        "farm_name": farm_name,
        "playtime": 7200.0,
        "calendar_time": cal_time,
        "clock_time": 21600,
    }
    entries["header"] = json.dumps(header_data)

    if bag_slots is not None:
        bag_slots_to_use = [dict(s) for s in bag_slots]
        while len(bag_slots_to_use) < 30:
            bag_slots_to_use.append(create_mock_slot(None, 0))
    else:
        bag_slots_to_use = []
        if bag_items:
            for iid, cnt in bag_items.items():
                bag_slots_to_use.append(create_mock_slot(iid, cnt))
        while len(bag_slots_to_use) < 30:
            bag_slots_to_use.append(create_mock_slot(None, 0))

    player_data = {
        "name": player_name,
        "farm_name": farm_name,
        "inventory": bag_slots_to_use,
    }
    entries["player"] = json.dumps(player_data)

    npcs_data: Dict[str, Any] = {}
    all_34_npc_ids = [
        "adeline", "balor", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis",
        "luc", "maple", "march", "merri", "nora", "olric", "reina", "ryis", "seridia",
        "stillwell", "taliferro", "terithia", "valen", "vera", "wheedle", "zorel", "caldarus"
    ]
    target_npc_list = npc_ids if npc_ids is not None else all_34_npc_ids
    if gifted_npcs is None:
        gifted_npcs = {}

    is_animal_fest = (season.lower() == "winter" and day == 10)
    for nid in target_npc_list:
        is_vendor = nid in SATURDAY_MARKET_VENDORS
        is_fest_vendor = is_animal_fest and (nid in ("merri", "louis"))
        loc_id = "town" if (day % 7 == 6 or not is_vendor or is_fest_vendor) else "aldaria"
        npcs_data[nid] = {
            "name": nid.capitalize(),
            "heart_points": 100.0,
            "gift_flag": giftable_all,
            "gifts_given": gifted_npcs.get(nid, []),
            "known_gift_preferences": [],
            "location_position": {"location_id": loc_id},
        }
    entries["npcs"] = json.dumps(npcs_data)

    if chests_by_location:
        for loc_name, chest_list in chests_by_location.items():
            entries[loc_name] = json.dumps({
                "location_id": loc_name,
                "inventories": chest_list
            })

    entries["gamedata"] = json.dumps({"date": cal_time})
    entries["game_stats"] = json.dumps({})
    entries["quests"] = json.dumps({})
    entries["info"] = json.dumps({})

    return entries


def create_synthetic_save_file(
    file_path: Path,
    bag_items: Optional[Dict[str, int]] = None,
    chests_by_location: Optional[Dict[str, List[List[Dict[str, Any]]]]] = None,
    year: int = 2,
    season: str = "winter",
    day: int = 6,
    player_name: str = "TestHero",
    farm_name: str = "TestFarm",
    giftable_all: bool = True,
    gifted_npcs: Optional[Dict[str, List[str]]] = None,
    npc_ids: Optional[List[str]] = None,
    bag_slots: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Encodes and writes a synthetic binary FoM .sav file to disk."""
    entries = create_synthetic_save_entries(
        bag_items=bag_items,
        chests_by_location=chests_by_location,
        year=year,
        season=season,
        day=day,
        player_name=player_name,
        farm_name=farm_name,
        giftable_all=giftable_all,
        gifted_npcs=gifted_npcs,
        npc_ids=npc_ids,
        bag_slots=bag_slots,
    )
    raw = bytearray()
    raw.extend(struct.pack("<Q", len(entries)))
    for k, v in entries.items():
        kb = k.encode("utf-8")
        vb = v.encode("utf-8")
        raw.extend(struct.pack("<Q", len(kb)))
        raw.extend(kb)
        raw.extend(struct.pack("<Q", len(vb)))
        raw.extend(vb)

    compressed = zlib.compress(bytes(raw))
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(compressed)
    return file_path


def get_mock_recipes() -> Dict[str, Any]:
    """Returns a comprehensive mock recipe dictionary for tests."""
    return {
        "golden_cheese": {
            "item_id": "golden_cheese", "display_name": "Golden Cheese", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}]
        },
        "golden_butter": {
            "item_id": "golden_butter", "display_name": "Golden Butter", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}]
        },
        "golden_cheesecake": {
            "item_id": "golden_cheesecake", "display_name": "Golden Cheesecake", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2},
                {"item_id": "golden_cheese", "display_name": "Golden Cheese", "count": 1},
                {"item_id": "golden_butter", "display_name": "Golden Butter", "count": 1},
                {"item_id": "egg", "display_name": "Egg", "count": 1},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1}
            ]
        },
        "cornmeal": {
            "item_id": "cornmeal", "display_name": "Cornmeal", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "corn", "display_name": "Corn", "count": 1}]
        },
        "strawberry_shortcake": {
            "item_id": "strawberry_shortcake", "display_name": "Strawberry Shortcake", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "strawberry", "display_name": "Strawberry", "count": 3},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1}
            ]
        },
        "bread": {
            "item_id": "bread", "display_name": "Bread", "source": "cooking", "output_count": 1,
            "ingredients": [{"item_id": "flour", "display_name": "Flour", "count": 2}]
        },
        "deluxe_sandwich": {
            "item_id": "deluxe_sandwich", "display_name": "Deluxe Sandwich", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "bread", "display_name": "Bread", "count": 1},
                {"item_id": "tomato", "display_name": "Tomato", "count": 1}
            ]
        }
    }


def get_mock_npcs() -> Dict[str, Any]:
    """Returns sample NPC gift preferences for testing."""
    return {
        "adeline": {
            "name": "Adeline",
            "loved": ["golden_cheesecake", "strawberry_shortcake"],
            "liked": ["strawberry", "cornmeal"]
        },
        "darcy": {  # Saturday Vendor
            "name": "Darcy",
            "loved": ["golden_cheesecake", "deluxe_sandwich"],
            "liked": ["cornmeal", "sugar"]
        },
        "louis": {  # Saturday Vendor
            "name": "Louis",
            "loved": ["strawberry_shortcake"],
            "liked": ["strawberry"]
        },
        "march": {
            "name": "March",
            "loved": ["deluxe_sandwich"],
            "liked": ["bread", "cornmeal"]
        },
        "celine": {
            "name": "Celine",
            "loved": ["strawberry_shortcake"],
            "liked": ["strawberry"]
        }
    }


def get_mock_meta() -> Dict[str, Any]:
    """Returns sample item metadata for testing."""
    return {
        "golden_cheesecake": {"display_name": "Golden Cheesecake", "bin_price": 500, "store_price": 1000},
        "strawberry_shortcake": {"display_name": "Strawberry Shortcake", "bin_price": 200, "store_price": 400},
        "deluxe_sandwich": {"display_name": "Deluxe Sandwich", "bin_price": 300, "store_price": 600},
        "cornmeal": {"display_name": "Cornmeal", "bin_price": 50, "store_price": 100},
        "bread": {"display_name": "Bread", "bin_price": 70, "store_price": 140},
        "strawberry": {"display_name": "Strawberry", "bin_price": 40, "store_price": 80},
    }
