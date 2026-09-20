"""
test_zorel_features.py

Comprehensive test suite verifying that Zorel's new loved and liked gift preferences
(10 Loved, 20 Liked) function correctly across all fom_planner features:
- Data loaders and JSON schema integrity
- Item metadata and location mapping (including metal_leaf)
- Gift rankings and popularity tables
- Saturday Market presence and vendor unlock progression
- Journal Strategy and Max Relationship Strategy optimization
- Max relationship cap and auto-exclusion
"""

import unittest
from pathlib import Path

from fom_planner.constants import (
    DEFAULT_MAX_RELATIONSHIP_POINTS,
    SATURDAY_MARKET_UPGRADE_2_VENDORS,
    SATURDAY_MARKET_VENDORS,
)
from fom_planner.data_loader import (
    load_item_locations,
    load_item_metadata,
    load_npc_preferences_from_json,
)
from fom_planner.optimizer import plan_daily_gift_bag, plan_max_relationship
from fom_planner.parser import parse_save_file
from fom_planner.rankings import build_ranked_rows

EXPECTED_ZOREL_LOVED = {
    "ancient_crystal_goblet",
    "crispy_fried_earthshroom",
    "crystal_apple",
    "crystal_berry_pie",
    "metal_leaf",
    "miners_mushroom_stew",
    "mushroom_brew",
    "mushroom_rice",
    "mushroom_steak_dinner",
    "pineshroom_toast",
}

EXPECTED_ZOREL_LIKED = {
    "acorn",
    "ash_mushroom",
    "bell_berry",
    "crystal",
    "crystal_berries",
    "crystal_rose",
    "crystal_wing_moth",
    "crystalline_cricket",
    "dandelion",
    "earthshroom",
    "ethereal_grass",
    "glowing_mushroom",
    "morel_mushroom",
    "nettle",
    "oyster_mushroom",
    "pinecone",
    "pineshroom",
    "red_toadstool",
    "upper_mines_mushroom",
    "wild_mushroom",
}

OUTDATED_ZOREL_ITEMS = {
    "heather",
    "middlemist",
    "sunflower",
    "fennel",
    "fiddlehead",
    "sage",
    "wild_leek",
}


class TestZorelFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.item_data_path = cls.root_dir / "data" / "item_data.json"
        cls.item_locations_path = cls.root_dir / "data" / "item_locations.json"
        cls.sample_save_path = cls.root_dir / "samples" / "sample_save.sav"

        cls.npcs_def, cls.items_def = load_npc_preferences_from_json(cls.item_data_path)
        cls.item_meta = load_item_metadata(None, item_data_json_path=cls.item_data_path)
        cls.item_locs = load_item_locations(cls.item_locations_path)

    def test_zorel_gift_counts_and_membership(self):
        """Zorel must have exactly 10 loved and 20 liked gifts loaded from item_data.json."""
        self.assertIn("zorel", self.npcs_def, "Zorel must be present in loaded NPC definitions")
        zorel = self.npcs_def["zorel"]

        self.assertEqual(len(zorel["loved"]), 10, "Zorel must have exactly 10 loved gifts")
        self.assertEqual(len(zorel["liked"]), 20, "Zorel must have exactly 20 liked gifts")

        self.assertEqual(set(zorel["loved"]), EXPECTED_ZOREL_LOVED)
        self.assertEqual(set(zorel["liked"]), EXPECTED_ZOREL_LIKED)

        # None of the old placeholder gifts should be in Zorel's loved or liked sets
        for outdated in OUTDATED_ZOREL_ITEMS:
            self.assertNotIn(outdated, zorel["loved"], f"{outdated} should not be loved by Zorel")
            self.assertNotIn(outdated, zorel["liked"], f"{outdated} should not be liked by Zorel")

    def test_metal_leaf_metadata_and_location(self):
        """metal_leaf artifact must be correctly registered with metadata and location hint."""
        self.assertIn("metal_leaf", self.item_meta)
        meta = self.item_meta["metal_leaf"]
        self.assertEqual(meta["display_name"], "Metal Leaf")
        self.assertIn("archaeology", meta["tags"])

        self.assertIn("metal_leaf", self.item_locs)
        self.assertEqual(self.item_locs["metal_leaf"], "Digging (The Deep Woods)")

    def test_zorel_in_constants_and_vendor_tiers(self):
        """Zorel must be recognized as Saturday Market vendor and part of Upgrade 2 tier."""
        self.assertIn("zorel", SATURDAY_MARKET_VENDORS)
        self.assertIn("zorel", SATURDAY_MARKET_UPGRADE_2_VENDORS)

    def test_zorel_in_gift_rankings(self):
        """build_ranked_rows must include Zorel for all 30 preferred items."""
        ranked_rows = build_ranked_rows(self.items_def, self.item_meta)
        rows_by_id = {r["item_id"]: r for r in ranked_rows}

        for item_id in EXPECTED_ZOREL_LOVED:
            self.assertIn(item_id, rows_by_id, f"Loved item {item_id} must appear in rankings")
            row = rows_by_id[item_id]
            self.assertIn("Zorel", row["loved_by"])

        for item_id in EXPECTED_ZOREL_LIKED:
            self.assertIn(item_id, rows_by_id, f"Liked item {item_id} must appear in rankings")
            row = rows_by_id[item_id]
            self.assertIn("Zorel", row["liked_by"])

    def test_saturday_market_bag_planning_with_zorel(self):
        """When Zorel is present on Saturday with available items, Zorel is assigned a gift."""
        save = parse_save_file(self.sample_save_path)
        # Force in-game day to Saturday
        save.in_game_date.day = 6  # Saturday
        self.assertTrue(save.in_game_date.is_saturday)

        # Provide Ancient Crystal Goblet (Loved by Stillwell and Zorel)
        inventory = {"ancient_crystal_goblet": 5}
        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.item_meta,
            recipes={},
            mode="saturday",
            inventory=inventory,
            max_slots=10,
        )

        # Zorel should be among the target recipients for ancient_crystal_goblet
        zorel_covered = False
        for item in plan["bag_plan"]:
            if item["item_id"] == "ancient_crystal_goblet":
                recipient_names = [r["name"] for r in item.get("all_recipients_today", [])]
                if "Zorel" in recipient_names:
                    zorel_covered = True
        self.assertTrue(zorel_covered, "Zorel should be covered with Ancient Crystal Goblet on Saturday")

    def test_zorel_max_relationship_auto_exclusion(self):
        """When Zorel has reached maximum heart points, Zorel is auto-excluded from max-relationship plan."""
        save = parse_save_file(self.sample_save_path)
        save.in_game_date.day = 6  # Saturday

        # Case 1: Zorel has low hearts (200 HP) -> eligible for gift
        save.npcs["zorel"]["heart_points"] = 200.0
        inventory = {"mushroom_brew": 2}
        result_eligible = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.item_meta,
            mode="saturday",
            inventory=inventory,
        )
        recipients = {r["npc_id"] for slot in result_eligible["bag_plan"] for r in slot["all_recipients_today"]}
        self.assertIn("zorel", recipients)

        # Case 2: Zorel has max relationship (>= 1755 HP) -> auto-excluded
        save.npcs["zorel"]["heart_points"] = DEFAULT_MAX_RELATIONSHIP_POINTS + 10.0
        result_maxed = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.item_meta,
            mode="saturday",
            inventory=inventory,
        )
        recipients_maxed = {r["npc_id"] for slot in result_maxed["bag_plan"] for r in slot["all_recipients_today"]}
        self.assertNotIn("zorel", recipients_maxed, "Maxed Zorel must be auto-excluded from bag plan")


if __name__ == "__main__":
    unittest.main()
