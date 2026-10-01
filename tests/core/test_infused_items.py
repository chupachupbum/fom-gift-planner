"""
tests/test_infused_items.py

Comprehensive edge-case and stress test suite for cooking-perk infused items:
- _extract_slot_item_count_and_infusion helper function
- SaveData.get_infused_items multi-location extraction and deterministic ordering
- Non-location filtering, aggregation across chests, scaling, and malformed inputs
"""

import json
import math
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fom_planner.constants import NON_LOCATION_KEYS
from fom_planner.models import (
    SaveData,
    _extract_slot_item_and_count,
    _extract_slot_item_count_and_infusion,
)


# ============================================================================
# EDGE CASES & ADVERSARIAL EXTRACTION SUITE
# ============================================================================

class TestSlotExtractionMalformedSlots(unittest.TestCase):
    """Category 1: Malformed slots (strings, None, numbers, missing item keys)."""

    def test_primitive_slots(self):
        primitives = [
            None,
            "",
            "not_a_slot",
            123,
            45.67,
            True,
            False,
            [],
            [{"item": {"item_id": "apple"}}],
            (1, 2),
            set(),
        ]
        for slot in primitives:
            with self.subTest(slot=slot):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_missing_or_invalid_item_field(self):
        slots = [
            {},
            {"count": 5},
            {"count": 5, "item": None},
            {"count": 5, "item": "string_not_dict"},
            {"count": 5, "item": 123},
            {"count": 5, "item": []},
            {"count": 5, "item": True},
            {"count": 5, "item": False},
            {"count": 5, "item": {}},  # empty item dict
        ]
        for slot in slots:
            with self.subTest(slot=slot):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_invalid_item_id_values(self):
        invalid_ids = [
            None,
            "",
            "   ",
            "\t\n  \r",
            123,
            45.6,
            True,
            False,
            [],
            {},
            ["apple"],
            {"id": "apple"},
        ]
        for invalid_id in invalid_ids:
            slot = {"count": 1, "item": {"item_id": invalid_id}}
            with self.subTest(invalid_id=invalid_id):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_item_id_normalization(self):
        slot = {"count": 2, "item": {"item_id": "  Apple_Pie  "}}
        self.assertEqual(
            _extract_slot_item_count_and_infusion(slot),
            ("apple_pie", 2, None),
        )


class TestSlotExtractionBooleanCountTrap(unittest.TestCase):
    """Category 2: Boolean count trap (count=True, count=False)."""

    def test_bool_true_count(self):
        # In Python: isinstance(True, int) is True and int(True) == 1.
        # Must be explicitly caught and rejected.
        slot = {
            "count": True,
            "item": {"item_id": "apple_pie", "infusion": "lovable"},
        }
        self.assertEqual(
            _extract_slot_item_count_and_infusion(slot),
            (None, 0, None),
        )

    def test_bool_false_count(self):
        slot = {
            "count": False,
            "item": {"item_id": "apple_pie", "infusion": "lovable"},
        }
        self.assertEqual(
            _extract_slot_item_count_and_infusion(slot),
            (None, 0, None),
        )

    def test_string_boolean_count(self):
        for val in ["True", "False", "true", "false"]:
            slot = {
                "count": val,
                "item": {"item_id": "apple_pie", "infusion": "lovable"},
            }
            with self.subTest(val=val):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )


class TestSlotExtractionNumericEdgeCases(unittest.TestCase):
    """Category 3: Float counts, negative counts, zero counts, NaN, Infinity."""

    def test_zero_and_negative_counts(self):
        cases = [0, 0.0, -0.0, -1, -5.5, -999999, "-1", "0", "-0.0"]
        for count in cases:
            slot = {"count": count, "item": {"item_id": "apple"}}
            with self.subTest(count=count):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_sub_unitary_counts(self):
        # Counts < 0.5 round to 0, which must return (None, 0, None)
        for count in [0.1, 0.4, 0.49, 0.4999]:
            slot = {"count": count, "item": {"item_id": "apple"}}
            with self.subTest(count=count):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_valid_float_rounding(self):
        cases = [
            (1.0, 1),
            (2.4, 2),
            (2.6, 3),
            ("3.0", 3),
            ("5", 5),
            (9.9, 10),
        ]
        for count, expected in cases:
            slot = {"count": count, "item": {"item_id": "apple"}}
            with self.subTest(count=count, expected=expected):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    ("apple", expected, None),
                )

    def test_nan_and_infinities(self):
        nan_inf_cases = [
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "NaN",
            "inf",
            "Infinity",
            "-inf",
            "-Infinity",
        ]
        for val in nan_inf_cases:
            slot = {"count": val, "item": {"item_id": "apple"}}
            with self.subTest(val=val):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )

    def test_overflow_and_unparseable_strings(self):
        cases = [1e309, "1e309", "not_a_number", None, [1], {"num": 1}]
        for val in cases:
            slot = {"count": val, "item": {"item_id": "apple"}}
            with self.subTest(val=val):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    (None, 0, None),
                )


class TestSlotExtractionInfusionVariations(unittest.TestCase):
    """Category 4: Unrecognized infusions, casing variations, whitespace."""

    def test_lovable_casing_and_whitespace(self):
        variations = [
            "lovable",
            "LOVABLE",
            "Lovable",
            "  lovable  ",
            "\tlovable\n",
            "  LoVaBlE  ",
        ]
        for inf in variations:
            slot = {"count": 1, "item": {"item_id": "pie", "infusion": inf}}
            with self.subTest(inf=inf):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    ("pie", 1, "lovable"),
                )

    def test_likable_casing_and_spelling_tolerance(self):
        variations = [
            "likable",
            "likeable",  # common alternate spelling
            "LIKABLE",
            "LIKEABLE",
            "Likable",
            "Likeable",
            "  likable  ",
            "  likeable  ",
            "\tLiKeAbLe\n",
        ]
        for inf in variations:
            slot = {"count": 1, "item": {"item_id": "soup", "infusion": inf}}
            with self.subTest(inf=inf):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    ("soup", 1, "likable"),
                )

    def test_unrecognized_infusions(self):
        unrecognized = [
            "spicy",
            "sweet",
            "sour",
            "universal",
            "love",
            "like",
            "",
            "   ",
            None,
            123,
            True,  # boolean infusion trap
            False,
            ["lovable"],
            {"type": "lovable"},
        ]
        for inf in unrecognized:
            slot = {"count": 1, "item": {"item_id": "soup", "infusion": inf}}
            with self.subTest(inf=inf):
                self.assertEqual(
                    _extract_slot_item_count_and_infusion(slot),
                    ("soup", 1, None),
                )


class TestSaveDataGetInfusedItemsAdversarial(unittest.TestCase):
    """Category 5: Empty inventory and empty raw_entries, corruption, and edge cases."""

    def test_empty_raw_entries(self):
        save = SaveData(Path("empty.sav"), {})
        res = save.get_infused_items()
        self.assertEqual(res, {"lovable": [], "likable": []})

    def test_empty_bag_and_empty_chests(self):
        save = SaveData(
            Path("empty.sav"),
            {
                "player": json.dumps({"inventory": []}),
                "farm": json.dumps({"location_id": "farm", "inventories": [[]]}),
            },
        )
        res = save.get_infused_items()
        self.assertEqual(res, {"lovable": [], "likable": []})

    def test_bag_with_adversarial_mixed_slots(self):
        mixed_slots = [
            None,
            "corrupted_slot",
            123,
            {},
            {"count": 0, "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": True, "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": -1, "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": float("nan"), "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": 2, "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": 3, "item": {"item_id": "pie", "infusion": "lovable"}},
            {"count": 1, "item": {"item_id": "stone"}},  # non-infused
            {"count": 1, "item": {"item_id": "wood", "infusion": "unknown"}},
            {"count": 4, "item": {"item_id": "soup", "infusion": "LIKEABLE"}},
        ]
        save = SaveData(
            Path("mock.sav"),
            {"player": json.dumps({"inventory": mixed_slots})},
        )
        res = save.get_infused_items()
        self.assertEqual(
            res["lovable"],
            [{"item_id": "pie", "count": 5, "location": "bag"}],
        )
        self.assertEqual(
            res["likable"],
            [{"item_id": "soup", "count": 4, "location": "bag"}],
        )

    def test_corrupted_location_blocks_survived(self):
        entries = {
            "bad_json": "{not valid json at all",
            "bad_dict": json.dumps(["not", "a", "dict"]),
            "bad_invs": json.dumps({"inventories": "not a list"}),
            "chest_bad": json.dumps({"inventories": ["not a list", 123, None]}),
            "good_loc": json.dumps({
                "inventories": [
                    [{"count": 2, "item": {"item_id": "pie", "infusion": "lovable"}}]
                ]
            }),
        }
        save = SaveData(Path("mock.sav"), entries)
        res = save.get_infused_items()
        self.assertEqual(
            res["lovable"],
            [{"item_id": "pie", "count": 2, "location": "good_loc"}],
        )

    def test_uninitialized_savedata_defense(self):
        # Test extreme edge case where instance is created without __init__
        save = SaveData.__new__(SaveData)
        save.raw_entries = None
        save.player = None
        res = save.get_infused_items()
        self.assertEqual(res, {"lovable": [], "likable": []})

# ============================================================================
# MULTI-LOCATION, SCALE & STRESS SUITE
# ============================================================================

def create_slot(
    item_id: Optional[str] = None,
    count: Any = 1,
    infusion: Optional[str] = None,
    corrupt: bool = False,
) -> Any:
    """Helper to create inventory slots for testing."""
    if corrupt:
        return "not_a_dict_slot"
    if item_id is None:
        return {"count": 0, "item": None, "required_tags": []}

    item_dict: Dict[str, Any] = {"item_id": item_id}
    if infusion is not None:
        item_dict["infusion"] = infusion
    return {
        "count": count,
        "item": item_dict,
        "required_tags": [],
    }


def make_save_data(
    bag_slots: Optional[List[Any]] = None,
    location_chests: Optional[Dict[str, List[List[Any]]]] = None,
    extra_entries: Optional[Dict[str, Any]] = None,
) -> SaveData:
    """Helper to create a SaveData instance with specified bag and chest contents."""
    entries: Dict[str, str] = {
        "header": json.dumps({
            "name": "ChallengerHero",
            "farm_name": "EmpiricalFarm",
            "playtime": 7200.0,
            "calendar_time": 86400 * 5,
        }),
        "player": json.dumps({
            "name": "ChallengerHero",
            "farm_name": "EmpiricalFarm",
            "inventory": bag_slots if bag_slots is not None else [],
        }),
        "npcs": json.dumps({}),
        "gamedata": json.dumps({}),
        "game_stats": json.dumps({}),
        "quests": json.dumps({}),
        "info": json.dumps({}),
        "date_photos": json.dumps({}),
    }

    if location_chests:
        for loc_key, chests in location_chests.items():
            entries[loc_key] = json.dumps({
                "location_id": loc_key,
                "inventories": chests,
            })

    if extra_entries:
        for k, v in extra_entries.items():
            if isinstance(v, str):
                entries[k] = v
            else:
                entries[k] = json.dumps(v)

    return SaveData(Path("test_save.sav"), entries)


class TestMultiLocationChestsAndBag(unittest.TestCase):
    """Test items distributed across player bag and multiple world locations."""

    def test_bag_vs_multiple_chest_locations_distinct_entries(self):
        """Verify identical infused items in bag and separate locations remain distinct."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=3, infusion="lovable"),
            ],
            location_chests={
                "farm": [[create_slot("apple_pie", count=2, infusion="lovable")]],
                "farm_house": [[create_slot("apple_pie", count=5, infusion="lovable")]],
                "mines": [[create_slot("apple_pie", count=1, infusion="lovable")]],
            },
        )
        res = save.get_infused_items()

        # Lovable list should have 4 separate entries sorted by (item_id, location)
        self.assertEqual(len(res["lovable"]), 4)
        self.assertEqual(res["likable"], [])

        expected_locations = ["bag", "farm", "farm_house", "mines"]
        expected_counts = [3, 2, 5, 1]

        for i, (loc, cnt) in enumerate(zip(expected_locations, expected_counts)):
            self.assertEqual(res["lovable"][i]["item_id"], "apple_pie")
            self.assertEqual(res["lovable"][i]["location"], loc)
            self.assertEqual(res["lovable"][i]["count"], cnt)

    def test_distinct_items_across_distinct_locations(self):
        """Verify distinct items in bag, farm, and mines populate lovable and likable appropriately."""
        save = make_save_data(
            bag_slots=[
                create_slot("herb_tea", count=1, infusion="likable"),
                create_slot("apple_pie", count=2, infusion="lovable"),
            ],
            location_chests={
                "farm": [[create_slot("vegetable_soup", count=4, infusion="likable")]],
                "beach": [[create_slot("grilled_fish", count=3, infusion="lovable")]],
            },
        )
        res = save.get_infused_items()

        self.assertEqual(
            res["lovable"],
            [
                {"item_id": "apple_pie", "count": 2, "location": "bag"},
                {"item_id": "grilled_fish", "count": 3, "location": "beach"},
            ],
        )
        self.assertEqual(
            res["likable"],
            [
                {"item_id": "herb_tea", "count": 1, "location": "bag"},
                {"item_id": "vegetable_soup", "count": 4, "location": "farm"},
            ],
        )

    def test_same_item_different_infusions_across_locations(self):
        """Verify the same item_id with lovable in bag and likable in mines are segregated."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=2, infusion="lovable"),
            ],
            location_chests={
                "mines": [[create_slot("apple_pie", count=3, infusion="likable")]],
            },
        )
        res = save.get_infused_items()

        self.assertEqual(res["lovable"], [{"item_id": "apple_pie", "count": 2, "location": "bag"}])
        self.assertEqual(res["likable"], [{"item_id": "apple_pie", "count": 3, "location": "mines"}])


class TestLocationStackAggregation(unittest.TestCase):
    """Test aggregation of duplicate stacks within the same location."""

    def test_multiple_chests_same_location_aggregation(self):
        """Multiple chests within 'farm' containing the same item must sum their counts into one entry."""
        save = make_save_data(
            location_chests={
                "farm": [
                    [create_slot("apple_pie", count=4, infusion="lovable")],
                    [create_slot("apple_pie", count=6, infusion="lovable")],
                    [create_slot("apple_pie", count=1, infusion="lovable")],
                ]
            }
        )
        res = save.get_infused_items()

        self.assertEqual(len(res["lovable"]), 1)
        self.assertEqual(res["lovable"][0], {"item_id": "apple_pie", "count": 11, "location": "farm"})

    def test_multiple_stacks_in_bag_aggregation(self):
        """Multiple slots in player bag containing the same item must sum their counts."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=2, infusion="lovable"),
                create_slot("apple_pie", count=5, infusion="lovable"),
                create_slot("apple_pie", count=3, infusion="lovable"),
            ]
        )
        res = save.get_infused_items()

        self.assertEqual(len(res["lovable"]), 1)
        self.assertEqual(res["lovable"][0], {"item_id": "apple_pie", "count": 10, "location": "bag"})

    def test_multi_location_and_multi_chest_aggregation(self):
        """Simultaneous aggregation in bag, farm, and mines with multiple chests each."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=1, infusion="lovable"),
                create_slot("apple_pie", count=4, infusion="lovable"),
            ],
            location_chests={
                "farm": [
                    [create_slot("apple_pie", count=5, infusion="lovable")],
                    [create_slot("apple_pie", count=5, infusion="lovable")],
                ],
                "mines": [
                    [create_slot("apple_pie", count=2, infusion="lovable")],
                    [create_slot("apple_pie", count=3, infusion="lovable")],
                ],
            },
        )
        res = save.get_infused_items()

        self.assertEqual(
            res["lovable"],
            [
                {"item_id": "apple_pie", "count": 5, "location": "bag"},
                {"item_id": "apple_pie", "count": 10, "location": "farm"},
                {"item_id": "apple_pie", "count": 5, "location": "mines"},
            ],
        )

    def test_multiple_distinct_items_aggregated_per_item_in_same_location(self):
        """Chests with multiple distinct infused items in the same location aggregate independently."""
        save = make_save_data(
            location_chests={
                "farm": [
                    [
                        create_slot("apple_pie", count=2, infusion="lovable"),
                        create_slot("soup", count=3, infusion="likable"),
                    ],
                    [
                        create_slot("apple_pie", count=4, infusion="lovable"),
                        create_slot("soup", count=7, infusion="likable"),
                    ],
                ]
            }
        )
        res = save.get_infused_items()

        self.assertEqual(res["lovable"], [{"item_id": "apple_pie", "count": 6, "location": "farm"}])
        self.assertEqual(res["likable"], [{"item_id": "soup", "count": 10, "location": "farm"}])


class TestNonLocationKeysFiltering(unittest.TestCase):
    """Test that NON_LOCATION_KEYS and variations are never treated as world chest locations."""

    def test_all_standard_non_location_keys_ignored(self):
        """Inventories placed inside any of the canonical NON_LOCATION_KEYS must be ignored."""
        extra_entries = {}
        for key in NON_LOCATION_KEYS:
            entry_dict: Dict[str, Any] = {
                "inventories": [
                    [create_slot(f"cheat_{key}", count=99, infusion="lovable")]
                ]
            }
            # Ensure player block retains bag inventory
            if key == "player":
                entry_dict["inventory"] = [create_slot("legit_pie", count=1, infusion="lovable")]
            extra_entries[key] = entry_dict

        save = make_save_data(
            bag_slots=[create_slot("legit_pie", count=1, infusion="lovable")],
            extra_entries=extra_entries,
        )
        res = save.get_infused_items()

        # Only the bag item should be present; none of the NON_LOCATION_KEYS should leak
        self.assertEqual(res["lovable"], [{"item_id": "legit_pie", "count": 1, "location": "bag"}])
        self.assertEqual(res["likable"], [])

    def test_case_and_whitespace_variations_of_non_location_keys(self):
        """Ensure case differences (HEADER, Player) and whitespace ('  quests  ') are filtered."""
        corrupt_entries = {
            "HEADER": {"inventories": [[create_slot("cheat_1", 10, "lovable")]]},
            "  player  ": {"inventories": [[create_slot("cheat_2", 10, "lovable")]]},
            "NpCs": {"inventories": [[create_slot("cheat_3", 10, "lovable")]]},
            "GAMEDATA": {"inventories": [[create_slot("cheat_4", 10, "lovable")]]},
            "  quests  ": {"inventories": [[create_slot("cheat_5", 10, "lovable")]]},
            "INFO": {"inventories": [[create_slot("cheat_6", 10, "lovable")]]},
            "date_PHOTOS": {"inventories": [[create_slot("cheat_7", 10, "lovable")]]},
            "  GAME_STATS  ": {"inventories": [[create_slot("cheat_8", 10, "lovable")]]},
        }
        save = make_save_data(
            bag_slots=[create_slot("legit_item", count=2, infusion="lovable")],
            extra_entries=corrupt_entries,
        )
        res = save.get_infused_items()

        self.assertEqual(res["lovable"], [{"item_id": "legit_item", "count": 2, "location": "bag"}])

    def test_near_match_location_names_are_not_filtered(self):
        """Legitimate location names containing non-location words (e.g. 'player_house') must be kept."""
        save = make_save_data(
            location_chests={
                "player_house": [[create_slot("pie", count=3, infusion="lovable")]],
                "npc_sanctuary": [[create_slot("soup", count=4, infusion="likable")]],
                "mines_header": [[create_slot("stew", count=1, infusion="lovable")]],
            }
        )
        res = save.get_infused_items()

        # 'pie' < 'stew' alphabetically
        self.assertEqual(
            res["lovable"],
            [
                {"item_id": "pie", "count": 3, "location": "player_house"},
                {"item_id": "stew", "count": 1, "location": "mines_header"},
            ],
        )
        self.assertEqual(
            res["likable"],
            [
                {"item_id": "soup", "count": 4, "location": "npc_sanctuary"},
            ],
        )


class TestDeterministicSortingOrder(unittest.TestCase):
    """Test deterministic sorting by (item_id, location)."""

    def test_deterministic_sorting_by_item_and_location(self):
        """Verify sorting order across shuffled items and locations."""
        save = make_save_data(
            bag_slots=[
                create_slot("zebra_cake", count=1, infusion="lovable"),
                create_slot("berry_tart", count=2, infusion="lovable"),
            ],
            location_chests={
                "z_shed": [[create_slot("apple_pie", count=3, infusion="lovable")]],
                "a_barn": [[create_slot("apple_pie", count=4, infusion="lovable")]],
                "farm": [
                    [
                        create_slot("banana_bread", count=5, infusion="lovable"),
                        create_slot("apple_pie", count=6, infusion="lovable"),
                    ]
                ],
                "mines": [[create_slot("banana_bread", count=7, infusion="lovable")]],
            },
        )
        res = save.get_infused_items()

        expected = [
            {"item_id": "apple_pie", "count": 4, "location": "a_barn"},
            {"item_id": "apple_pie", "count": 6, "location": "farm"},
            {"item_id": "apple_pie", "count": 3, "location": "z_shed"},
            {"item_id": "banana_bread", "count": 5, "location": "farm"},
            {"item_id": "banana_bread", "count": 7, "location": "mines"},
            {"item_id": "berry_tart", "count": 2, "location": "bag"},
            {"item_id": "zebra_cake", "count": 1, "location": "bag"},
        ]
        self.assertEqual(res["lovable"], expected)

    def test_sorting_idempotence(self):
        """Repeated invocations of get_infused_items return identical output."""
        save = make_save_data(
            bag_slots=[create_slot("soup", 1, "likable")],
            location_chests={
                "loc_b": [[create_slot("pie", 2, "likable")]],
                "loc_a": [[create_slot("pie", 3, "likable")]],
            },
        )
        res1 = save.get_infused_items()
        res2 = save.get_infused_items()
        self.assertEqual(res1, res2)


class TestRegressionExistingSaveDataMethods(unittest.TestCase):
    """Verify that existing SaveData inventory methods suffer zero regressions."""

    def test_get_bag_items_unaffected_by_infusions(self):
        """get_bag_items returns item_id and total_count regardless of infusion tags."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=2, infusion="lovable"),
                create_slot("apple_pie", count=3, infusion="likable"),
                create_slot("wood", count=10),
                create_slot("stone", count=5),
            ]
        )
        bag_items = save.get_bag_items()
        self.assertEqual(bag_items, {"apple_pie": 5, "wood": 10, "stone": 5})

    def test_get_chest_items_unaffected_by_infusions(self):
        """get_chest_items returns combined counts from chests across locations."""
        save = make_save_data(
            location_chests={
                "farm": [
                    [create_slot("apple_pie", count=4, infusion="lovable")],
                    [create_slot("wood", count=20)],
                ],
                "mines": [
                    [create_slot("apple_pie", count=6, infusion="likable")],
                    [create_slot("copper_ore", count=15)],
                ],
            }
        )
        chest_items = save.get_chest_items()
        self.assertEqual(
            chest_items,
            {"apple_pie": 10, "wood": 20, "copper_ore": 15},
        )

    def test_get_all_available_items_unaffected(self):
        """get_all_available_items correctly merges bag and chests with infused items included."""
        save = make_save_data(
            bag_slots=[
                create_slot("apple_pie", count=2, infusion="lovable"),
                create_slot("wood", count=5),
            ],
            location_chests={
                "farm": [[create_slot("apple_pie", count=8, infusion="lovable")]],
                "mines": [[create_slot("wood", count=15)]],
            },
        )
        all_items = save.get_all_available_items(include_bag=True, include_chests=True)
        self.assertEqual(all_items, {"apple_pie": 10, "wood": 20})

        chests_only = save.get_all_available_items(include_bag=False, include_chests=True)
        self.assertEqual(chests_only, {"apple_pie": 8, "wood": 15})

        bag_only = save.get_all_available_items(include_bag=True, include_chests=False)
        self.assertEqual(bag_only, {"apple_pie": 2, "wood": 5})


class TestScaleAndStressScenarios(unittest.TestCase):
    """Large-scale stress harnesses with oracle verification."""

    def test_massive_scale_100_locations_1000_chests_20000_slots(self):
        """
        Stress test:
        100 locations, 10 chests per location, 20 slots per chest = 20,000 slots.
        Plus 50 bag slots.
        Verified against an independent oracle accumulator.
        """
        num_locations = 100
        chests_per_loc = 10
        slots_per_chest = 20

        # Oracle maps: (infusion, item_id, location) -> count
        oracle: Dict[Tuple[str, str, str], int] = {}

        bag_slots = []
        for i in range(50):
            item_id = f"item_{i % 10}"
            infusion = "lovable" if (i % 3 == 0) else ("likable" if (i % 3 == 1) else None)
            count = (i % 5) + 1
            bag_slots.append(create_slot(item_id, count, infusion))
            if infusion:
                key = (infusion, item_id, "bag")
                oracle[key] = oracle.get(key, 0) + count

        location_chests = {}
        for loc_idx in range(num_locations):
            loc_key = f"location_{loc_idx:03d}"
            chests = []
            for chest_idx in range(chests_per_loc):
                chest_slots = []
                for slot_idx in range(slots_per_chest):
                    # Rotate items, infusions, counts, and empty slots
                    item_num = (loc_idx + chest_idx + slot_idx) % 25
                    item_id = f"item_{item_num}"
                    mode = (loc_idx * 7 + chest_idx * 3 + slot_idx) % 5
                    if mode == 0:
                        inf = "lovable"
                    elif mode == 1:
                        inf = "likable"
                    elif mode == 2:
                        inf = "likeable"  # alternative spelling
                    elif mode == 3:
                        inf = None  # normal item
                    else:
                        inf = None  # empty slot
                        item_id = None

                    count = ((loc_idx + slot_idx) % 9) + 1 if item_id else 0
                    chest_slots.append(create_slot(item_id, count, inf))

                    if item_id and inf:
                        norm_inf = "likable" if inf in ("likable", "likeable") else "lovable"
                        key = (norm_inf, item_id, loc_key)
                        oracle[key] = oracle.get(key, 0) + count

                chests.append(chest_slots)
            location_chests[loc_key] = chests

        save = make_save_data(bag_slots=bag_slots, location_chests=location_chests)

        # Benchmark execution time
        start_time = time.perf_counter()
        result = save.get_infused_items()
        duration = time.perf_counter() - start_time

        # Verify performance: 20,000+ slots parsed and aggregated in < 1.0s
        self.assertLess(duration, 1.0, f"Execution too slow: {duration:.3f}s for 20,050 slots")

        # Verify oracle equivalence
        oracle_lovable = [
            {"item_id": k[1], "count": v, "location": k[2]}
            for k, v in oracle.items()
            if k[0] == "lovable"
        ]
        oracle_lovable.sort(key=lambda x: (x["item_id"], x["location"]))

        oracle_likable = [
            {"item_id": k[1], "count": v, "location": k[2]}
            for k, v in oracle.items()
            if k[0] == "likable"
        ]
        oracle_likable.sort(key=lambda x: (x["item_id"], x["location"]))

        self.assertEqual(len(result["lovable"]), len(oracle_lovable))
        self.assertEqual(result["lovable"], oracle_lovable)

        self.assertEqual(len(result["likable"]), len(oracle_likable))
        self.assertEqual(result["likable"], oracle_likable)

    def test_high_collision_same_item_aggregation_stress(self):
        """500 chests in a single location all containing the same item must cleanly aggregate."""
        chests = []
        for _ in range(500):
            chests.append([create_slot("super_pie", count=5, infusion="lovable")])

        save = make_save_data(location_chests={"farm": chests})
        res = save.get_infused_items()

        self.assertEqual(len(res["lovable"]), 1)
        self.assertEqual(res["lovable"][0], {"item_id": "super_pie", "count": 2500, "location": "farm"})

    def test_adversarial_malformed_entries_at_scale(self):
        """Hundreds of malformed and corrupt entries must be safely skipped without exception."""
        extra_entries: Dict[str, Any] = {
            "corrupt_json": "{not valid json at all...",
            "non_dict_json": json.dumps(["a", "list", "instead"]),
            "int_val": 12345,
            "none_val": None,
            "bad_inventories_type": json.dumps({"inventories": "should_be_list"}),
            "chest_not_a_list": json.dumps({"inventories": [{"not": "a chest list"}]}),
            "slot_not_a_dict": json.dumps({"inventories": [[None, 123, "corrupt", []]]}),
            "slot_item_not_dict": json.dumps({"inventories": [[{"count": 5, "item": "string_item"}]]}),
            "slot_bool_count": json.dumps({
                "inventories": [[{"count": True, "item": {"item_id": "pie", "infusion": "lovable"}}]]
            }),
            "slot_nan_count": json.dumps({
                "inventories": [[{"count": "nan", "item": {"item_id": "pie", "infusion": "lovable"}}]]
            }),
            "slot_inf_count": json.dumps({
                "inventories": [[{"count": "inf", "item": {"item_id": "pie", "infusion": "lovable"}}]]
            }),
            "slot_empty_item_id": json.dumps({
                "inventories": [[{"count": 5, "item": {"item_id": "   ", "infusion": "lovable"}}]]
            }),
            "slot_unknown_infusion": json.dumps({
                "inventories": [[{"count": 5, "item": {"item_id": "pie", "infusion": "unknown_type"}}]]
            }),
            "loc_valid": json.dumps({
                "inventories": [[create_slot("pie", 5, "lovable")]]
            }),
        }

        save = make_save_data(extra_entries=extra_entries)
        res = save.get_infused_items()

        self.assertEqual(res["lovable"], [{"item_id": "pie", "count": 5, "location": "loc_valid"}])
        self.assertEqual(res["likable"], [])


class TestEmptyAndCornerCases(unittest.TestCase):
    """Test boundary and corner conditions for get_infused_items."""

    def test_completely_empty_save(self):
        """Empty raw_entries must return empty lists under lovable and likable."""
        save = SaveData(Path("empty.sav"), {})
        res = save.get_infused_items()
        self.assertEqual(res, {"lovable": [], "likable": []})

    def test_save_with_no_infused_items(self):
        """Save with regular items only must return empty lists."""
        save = make_save_data(
            bag_slots=[create_slot("wood", 10), create_slot("stone", 20)],
            location_chests={
                "farm": [[create_slot("iron_ore", 5)]],
            },
        )
        res = save.get_infused_items()
        self.assertEqual(res, {"lovable": [], "likable": []})

    def test_casing_and_whitespace_normalization(self):
        """Items and infusions with whitespace or mixed casing must be normalized."""
        save = make_save_data(
            bag_slots=[
                create_slot("  Apple_Pie  ", count=2, infusion="  LOVABLE  "),
                create_slot(" Vegetable_Soup ", count=3, infusion=" Likeable "),
            ]
        )
        res = save.get_infused_items()
        self.assertEqual(
            res["lovable"],
            [{"item_id": "apple_pie", "count": 2, "location": "bag"}],
        )
        self.assertEqual(
            res["likable"],
            [{"item_id": "vegetable_soup", "count": 3, "location": "bag"}],
        )

    def test_count_is_strictly_integer(self):
        """Counts represented as GameMaker floats (e.g. 4.0) must be converted to int."""
        save = make_save_data(
            bag_slots=[create_slot("apple_pie", count=4.0, infusion="lovable")]
        )
        res = save.get_infused_items()
        count = res["lovable"][0]["count"]
        self.assertIsInstance(count, int)
        self.assertNotIsInstance(count, bool)
        self.assertEqual(count, 4)

    def test_result_freshness_no_shared_state(self):
        """Mutating the returned dictionary does not mutate internal SaveData state."""
        save = make_save_data(
            bag_slots=[create_slot("apple_pie", 2, "lovable")]
        )
        res1 = save.get_infused_items()
        res1["lovable"].append({"item_id": "corrupt", "count": 999, "location": "bad"})
        res1["lovable"][0]["count"] = 99999

        res2 = save.get_infused_items()
        self.assertEqual(len(res2["lovable"]), 1)
        self.assertEqual(res2["lovable"][0]["count"], 2)

if __name__ == "__main__":
    unittest.main()
