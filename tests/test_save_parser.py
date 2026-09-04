#!/usr/bin/env python3
"""
test_save_parser_chests.py

Unit and integration tests for Fields of Mistria SaveData chest parsing,
inventory aggregation, dynamic grid extraction, and edge-case handling.
"""

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

try:
    from save_parser import (
        NON_LOCATION_KEYS,
        SaveData,
        _extract_slot_item_and_count,
        find_latest_save,
        find_save_files,
        parse_save_file,
    )
except ImportError:
    from scripts.save_parser import (
        NON_LOCATION_KEYS,
        SaveData,
        _extract_slot_item_and_count,
        find_latest_save,
        find_save_files,
        parse_save_file,
    )


def _make_slot(item_id: str, count: Any) -> Dict[str, Any]:
    """Helper to create a standard inventory slot dictionary."""
    return {
        "count": count,
        "item": {
            "item_id": item_id,
            "cosmetic": None,
            "infusion": None,
        },
        "required_tags": [],
    }


def _make_empty_slot() -> Dict[str, Any]:
    """Helper to create an empty inventory slot dictionary."""
    return {
        "count": 0,
        "item": None,
        "required_tags": [],
    }


def _make_mock_savedata(
    bag_slots: List[Any] = None,
    locations: Dict[str, List[List[Any]]] = None,
    extra_entries: Dict[str, str] = None,
) -> SaveData:
    """Helper to instantiate an in-memory SaveData instance with custom slots and locations."""
    entries: Dict[str, str] = {}

    # Standard player state
    player_data = {
        "name": "TestHero",
        "farm_name": "TestFarm",
        "inventory": bag_slots if bag_slots is not None else [],
    }
    entries["player"] = json.dumps(player_data)

    # Standard header
    header_data = {
        "name": "TestHero",
        "farm_name": "TestFarm",
        "playtime": 3600.0,
        "calendar_time": 86400,
        "clock_time": 21600,
    }
    entries["header"] = json.dumps(header_data)

    # Location entries
    if locations:
        for loc_name, chest_list in locations.items():
            loc_data = {
                "location_id": loc_name,
                "inventories": chest_list,
            }
            entries[loc_name] = json.dumps(loc_data)

    # Extra arbitrary entries (e.g. malformed or metadata)
    if extra_entries:
        entries.update(extra_entries)

    return SaveData(Path("mock.sav"), entries)


class TestSlotExtractor(unittest.TestCase):
    """Tests for the helper _extract_slot_item_and_count."""

    def test_valid_slot_integer_count(self):
        slot = _make_slot("turnip", 5)
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertEqual(item_id, "turnip")
        self.assertEqual(count, 5)

    def test_valid_slot_float_count(self):
        slot = _make_slot("carrot", 3.0)
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertEqual(item_id, "carrot")
        self.assertEqual(count, 3)

    def test_valid_slot_string_float_count(self):
        slot = _make_slot("potato", "4.0")
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertEqual(item_id, "potato")
        self.assertEqual(count, 4)

    def test_empty_slot(self):
        slot = _make_empty_slot()
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertIsNone(item_id)
        self.assertEqual(count, 0)

    def test_zero_count_slot(self):
        slot = _make_slot("apple", 0)
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertIsNone(item_id)
        self.assertEqual(count, 0)

    def test_negative_count_slot(self):
        slot = _make_slot("apple", -5)
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertIsNone(item_id)
        self.assertEqual(count, 0)

    def test_non_dict_slot(self):
        for bad_slot in [None, "invalid", 123, [1, 2, 3], True]:
            item_id, count = _extract_slot_item_and_count(bad_slot)
            self.assertIsNone(item_id)
            self.assertEqual(count, 0)

    def test_non_dict_item_field(self):
        slot = {"count": 5, "item": "not_a_dict"}
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertIsNone(item_id)
        self.assertEqual(count, 0)

    def test_missing_or_empty_item_id(self):
        for bad_id in [None, "", {}, []]:
            slot = {"count": 5, "item": {"item_id": bad_id}}
            item_id, count = _extract_slot_item_and_count(slot)
            self.assertIsNone(item_id)
            self.assertEqual(count, 0)

    def test_invalid_count_type(self):
        slot = {"count": "unparseable_string", "item": {"item_id": "turnip"}}
        item_id, count = _extract_slot_item_and_count(slot)
        self.assertIsNone(item_id)
        self.assertEqual(count, 0)


class TestSaveDataBagExtraction(unittest.TestCase):
    """Tests for SaveData.get_bag_items()."""

    def test_empty_bag(self):
        save = _make_mock_savedata(bag_slots=[])
        self.assertEqual(save.get_bag_items(), {})

    def test_bag_with_all_empty_slots(self):
        bag = [_make_empty_slot() for _ in range(30)]
        save = _make_mock_savedata(bag_slots=bag)
        self.assertEqual(save.get_bag_items(), {})

    def test_bag_with_unique_items(self):
        bag = [
            _make_slot("sword_iron", 1),
            _make_slot("turnip", 10),
            _make_slot("cabbage", 4),
            _make_empty_slot(),
        ]
        save = _make_mock_savedata(bag_slots=bag)
        expected = {"sword_iron": 1, "turnip": 10, "cabbage": 4}
        self.assertEqual(save.get_bag_items(), expected)

    def test_bag_merging_duplicate_items(self):
        bag = [
            _make_slot("wood", 50),
            _make_slot("stone", 20),
            _make_slot("wood", 35),
            _make_slot("wood", 15),
            _make_slot("stone", 10),
        ]
        save = _make_mock_savedata(bag_slots=bag)
        expected = {"wood": 100, "stone": 30}
        self.assertEqual(save.get_bag_items(), expected)

    def test_bag_with_corrupted_and_valid_mix(self):
        bag = [
            _make_slot("gold_ore", 5),
            None,
            "corrupted_slot_string",
            {"count": -1, "item": {"item_id": "bad"}},
            {"count": 10, "item": None},
            _make_slot("gold_ore", 7),
        ]
        save = _make_mock_savedata(bag_slots=bag)
        self.assertEqual(save.get_bag_items(), {"gold_ore": 12})


class TestSaveDataChestExtraction(unittest.TestCase):
    """Tests for SaveData.get_chest_items()."""

    def test_no_locations(self):
        save = _make_mock_savedata(locations={})
        self.assertEqual(save.get_chest_items(), {})

    def test_non_location_keys_ignored(self):
        """Verifies that non-location metadata keys containing 'inventories' are skipped."""
        extra_entries = {}
        fake_chest = [[_make_slot("secret_gem", 999)]]
        for key in NON_LOCATION_KEYS:
            extra_entries[key] = json.dumps({"inventories": fake_chest})

        save = _make_mock_savedata(locations={}, extra_entries=extra_entries)
        # None of the non-location entries should be parsed as chests
        self.assertEqual(save.get_chest_items(), {})

    def test_single_location_single_chest(self):
        locations = {
            "farm": [
                [
                    _make_slot("wheat", 25),
                    _make_slot("sugar", 10),
                    _make_empty_slot(),
                ]
            ]
        }
        save = _make_mock_savedata(locations=locations)
        expected = {"wheat": 25, "sugar": 10}
        self.assertEqual(save.get_chest_items(), expected)

    def test_single_location_multiple_chests(self):
        locations = {
            "farm": [
                [_make_slot("wheat", 15), _make_slot("flour", 5)],
                [_make_slot("wheat", 10), _make_slot("egg", 8)],
                [_make_slot("milk", 12), _make_empty_slot()],
            ]
        }
        save = _make_mock_savedata(locations=locations)
        expected = {"wheat": 25, "flour": 5, "egg": 8, "milk": 12}
        self.assertEqual(save.get_chest_items(), expected)

    def test_multiple_locations_and_dynamic_grids(self):
        locations = {
            "farm": [
                [_make_slot("golden_cow_milk", 2), _make_slot("golden_cheese", 1)]
            ],
            "player_home": [
                [_make_slot("golden_cow_milk", 3), _make_slot("sugar", 5)]
            ],
            "mines_entry": [
                [_make_slot("iron_ore", 40), _make_slot("copper_ore", 30)]
            ],
            "DynamicGrid_0": [  # small barn
                [_make_slot("hay", 50), _make_slot("golden_cow_milk", 1)]
            ],
            "DynamicGrid_1": [  # coop
                [_make_slot("egg", 20), _make_slot("golden_egg", 4)]
            ],
        }
        save = _make_mock_savedata(locations=locations)
        chest_items = save.get_chest_items()
        self.assertEqual(chest_items["golden_cow_milk"], 6)  # 2 + 3 + 1
        self.assertEqual(chest_items["golden_cheese"], 1)
        self.assertEqual(chest_items["sugar"], 5)
        self.assertEqual(chest_items["iron_ore"], 40)
        self.assertEqual(chest_items["copper_ore"], 30)
        self.assertEqual(chest_items["hay"], 50)
        self.assertEqual(chest_items["egg"], 20)
        self.assertEqual(chest_items["golden_egg"], 4)

    def test_malformed_location_json_handling(self):
        extra_entries = {
            "corrupted_loc": "{invalid_json: 123",
            "non_dict_loc": json.dumps(["some_list_instead_of_dict"]),
            "non_list_inventories": json.dumps({"inventories": "not_a_list"}),
            "non_list_chest": json.dumps({"inventories": ["not_a_list_chest"]}),
        }
        locations = {
            "farm": [
                [_make_slot("strawberry", 14)]
            ]
        }
        save = _make_mock_savedata(locations=locations, extra_entries=extra_entries)
        # Should gracefully skip bad entries and parse farm successfully
        self.assertEqual(save.get_chest_items(), {"strawberry": 14})


class TestSaveDataAllAvailableItems(unittest.TestCase):
    """Tests for SaveData.get_all_available_items()."""

    def setUp(self):
        bag = [
            _make_slot("golden_cow_milk", 2),
            _make_slot("flour", 3),
        ]
        locations = {
            "farm": [
                [_make_slot("golden_cow_milk", 4), _make_slot("sugar", 5)]
            ],
            "player_home": [
                [_make_slot("flour", 7), _make_slot("butter", 2)]
            ],
        }
        self.save = _make_mock_savedata(bag_slots=bag, locations=locations)

    def test_combined_bag_and_chests(self):
        all_items = self.save.get_all_available_items(include_bag=True, include_chests=True)
        expected = {
            "golden_cow_milk": 6,  # 2 in bag + 4 in chest
            "flour": 10,           # 3 in bag + 7 in chest
            "sugar": 5,            # chest only
            "butter": 2,           # chest only
        }
        self.assertEqual(all_items, expected)

    def test_bag_only(self):
        bag_items = self.save.get_all_available_items(include_bag=True, include_chests=False)
        expected = {
            "golden_cow_milk": 2,
            "flour": 3,
        }
        self.assertEqual(bag_items, expected)
        self.assertEqual(bag_items, self.save.get_bag_items())

    def test_chests_only(self):
        chest_items = self.save.get_all_available_items(include_bag=False, include_chests=True)
        expected = {
            "golden_cow_milk": 4,
            "flour": 7,
            "sugar": 5,
            "butter": 2,
        }
        self.assertEqual(chest_items, expected)
        self.assertEqual(chest_items, self.save.get_chest_items())

    def test_neither_bag_nor_chests(self):
        none_items = self.save.get_all_available_items(include_bag=False, include_chests=False)
        self.assertEqual(none_items, {})


class TestSaveDataChestsByLocation(unittest.TestCase):
    """Tests for SaveData.get_chests_by_location()."""

    def test_chests_by_location_mapping(self):
        farm_chests = [[_make_slot("apple", 5)], [_make_slot("pear", 3)]]
        home_chests = [[_make_slot("bed", 1)]]
        locations = {
            "farm": farm_chests,
            "player_home": home_chests,
            "town": [],  # empty inventories list
        }
        save = _make_mock_savedata(locations=locations)
        loc_map = save.get_chests_by_location()

        self.assertIn("farm", loc_map)
        self.assertIn("player_home", loc_map)
        self.assertNotIn("town", loc_map)  # Empty chests list excluded
        self.assertEqual(len(loc_map["farm"]), 2)
        self.assertEqual(len(loc_map["player_home"]), 1)


class TestSaveParserIntegration(unittest.TestCase):
    """Integration test against actual live save file if present on system."""

    def test_live_save_parsing_and_baseline_counts(self):
        save_path = find_latest_save()
        if not save_path or not Path(save_path).exists():
            self.skipTest("No live Fields of Mistria save file found on this system.")

        save_data = parse_save_file(save_path)
        self.assertIsInstance(save_data, SaveData)

        # Bag items verification
        bag_items = save_data.get_bag_items()
        self.assertIsInstance(bag_items, dict)

        # Chest items verification (Requirement: 582+ unique chest items in reference save)
        chest_items = save_data.get_chest_items()
        self.assertIsInstance(chest_items, dict)
        self.assertGreaterEqual(
            len(chest_items),
            582,
            f"Expected at least 582 unique chest items, found {len(chest_items)}",
        )

        # Combined items verification (Requirement: 591 combined items in reference save)
        all_items = save_data.get_all_available_items()
        self.assertIsInstance(all_items, dict)
        self.assertGreaterEqual(
            len(all_items),
            591,
            f"Expected at least 591 combined items, found {len(all_items)}",
        )

        # Verify chest locations structure
        loc_chests = save_data.get_chests_by_location()
        self.assertIsInstance(loc_chests, dict)
        self.assertIn("farm", loc_chests)
        total_chests = sum(len(c_list) for c_list in loc_chests.values())
        self.assertGreaterEqual(
            total_chests,
            30,
            f"Expected at least 30 chests across locations, found {total_chests}",
        )

        # Summary string check
        summary_str = save_data.summary()
        self.assertIn("unique items in chests", summary_str)
        self.assertIn("Total available:", summary_str)


if __name__ == "__main__":
    unittest.main()
