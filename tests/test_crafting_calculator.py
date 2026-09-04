#!/usr/bin/env python3
"""
scripts/test_crafting_calculator.py

Unit test suite for scripts/crafting_calculator.py.
Validates the Recursive Crafting DAG Resolver, AvailabilityTier categorization,
the Golden Milk Problem, multi-tier intermediate chains, max craftable binary search,
pool deduction, cycle safety, formatting, and real recipe database integration.
"""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict
import unittest

try:
    from crafting_calculator import (
        AvailabilityTier,
        CraftingPlan,
        CraftingStep,
        deduct_crafting_materials,
        evaluate_craftability,
        format_crafting_chain,
        load_recipes,
    )
except ImportError:
    from scripts.crafting_calculator import (
        AvailabilityTier,
        CraftingPlan,
        CraftingStep,
        deduct_crafting_materials,
        evaluate_craftability,
        format_crafting_chain,
        load_recipes,
    )


def get_mock_recipes() -> Dict[str, Any]:
    """Provides a deterministic fixture recipe database for isolated unit testing."""
    return {
        # --- The Golden Milk Problem ---
        "golden_cheesecake": {
            "item_id": "golden_cheesecake",
            "display_name": "Golden Cheesecake",
            "source": "cooking",
            "output_count": 1,
            "ingredients": [
                {"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2},
                {"item_id": "golden_cheese", "display_name": "Golden Cheese", "count": 1},
                {"item_id": "golden_butter", "display_name": "Golden Butter", "count": 1},
                {"item_id": "egg", "display_name": "Egg", "count": 1},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1},
            ],
        },
        "golden_cheese": {
            "item_id": "golden_cheese",
            "display_name": "Golden Cheese",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}
            ],
        },
        "golden_butter": {
            "item_id": "golden_butter",
            "display_name": "Golden Butter",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}
            ],
        },
        # --- Multi-Level Intermediate Chains ---
        "deluxe_sandwich": {
            "item_id": "deluxe_sandwich",
            "display_name": "Deluxe Sandwich",
            "source": "cooking",
            "output_count": 1,
            "ingredients": [
                {"item_id": "bread", "display_name": "Bread", "count": 2},
                {"item_id": "cheese", "display_name": "Cheese", "count": 1},
                {"item_id": "mayo", "display_name": "Mayo", "count": 1},
                {"item_id": "tomato", "display_name": "Tomato", "count": 1},
            ],
        },
        "bread": {
            "item_id": "bread",
            "display_name": "Bread",
            "source": "cooking",
            "output_count": 1,
            "ingredients": [
                {"item_id": "flour", "display_name": "Flour", "count": 2}
            ],
        },
        "cheese": {
            "item_id": "cheese",
            "display_name": "Cheese",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "cow_milk", "display_name": "Cow Milk", "count": 1}
            ],
        },
        "mayo": {
            "item_id": "mayo",
            "display_name": "Mayo",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "egg", "display_name": "Egg", "count": 1}
            ],
        },
        "flour": {
            "item_id": "flour",
            "display_name": "Flour",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "wheat", "display_name": "Wheat", "count": 1}
            ],
        },
        "sugar": {
            "item_id": "sugar",
            "display_name": "Sugar",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "sugarcane", "display_name": "Sugarcane", "count": 1}
            ],
        },
        # --- Single-Step Recipes ---
        "cornmeal": {
            "item_id": "cornmeal",
            "display_name": "Cornmeal",
            "source": "milling",
            "output_count": 1,
            "ingredients": [
                {"item_id": "corn", "display_name": "Corn", "count": 1}
            ],
        },
        "strawberry_shortcake": {
            "item_id": "strawberry_shortcake",
            "display_name": "Strawberry Shortcake",
            "source": "cooking",
            "output_count": 1,
            "ingredients": [
                {"item_id": "strawberry", "display_name": "Strawberry", "count": 3},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1},
            ],
        },
        "cookies": {
            "item_id": "cookies",
            "display_name": "Cookies",
            "source": "cooking",
            "output_count": 4,
            "ingredients": [
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1},
            ],
        },
    }


class TestGoldenMilkProblem(unittest.TestCase):
    """Specific unit test validation for the Golden Milk Problem."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_golden_cheesecake_exact_6_milk_craftable(self):
        """Golden Cheesecake requires 6 Golden Milk (2 direct + 2 cheese + 2 butter) -> CRAFT (max 1)."""
        inventory = {
            "golden_cow_milk": 6,
            "egg": 1,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.status, 1)
        self.assertEqual(plan.max_craftable, 1)
        self.assertEqual(plan.raw_materials_needed.get("golden_cow_milk"), 6)
        self.assertEqual(plan.raw_materials_needed.get("egg"), 1)
        self.assertEqual(plan.raw_materials_needed.get("flour"), 1)
        self.assertEqual(plan.raw_materials_needed.get("sugar"), 1)

    def test_golden_cheesecake_5_milk_unavailable(self):
        """Golden Cheesecake with 5 Golden Milk fails (needs 6 total) -> UNAVAILABLE (max 0)."""
        inventory = {
            "golden_cow_milk": 5,
            "egg": 1,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.status, 0)
        self.assertEqual(plan.max_craftable, 0)

    def test_golden_cheesecake_12_milk_max_2(self):
        """Golden Cheesecake with 12 Golden Milk + 2 sets of other ingredients -> CRAFT (max 2)."""
        inventory = {
            "golden_cow_milk": 12,
            "egg": 2,
            "flour": 2,
            "sugar": 2,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 2)

    def test_golden_cheesecake_partial_intermediate_cheese_and_4_milk(self):
        """Pre-owned Golden Cheese saves 2 Golden Milk; 4 Golden Milk fulfills direct + butter."""
        inventory = {
            "golden_cheese": 1,
            "golden_cow_milk": 4,
            "egg": 1,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 1)
        self.assertEqual(plan.raw_materials_needed.get("golden_cheese"), 1)
        self.assertEqual(plan.raw_materials_needed.get("golden_cow_milk"), 4)

    def test_golden_cheesecake_partial_intermediate_cheese_butter_and_2_milk(self):
        """Pre-owned Golden Cheese and Golden Butter save 4 Golden Milk; 2 Milk fulfills direct."""
        inventory = {
            "golden_cheese": 1,
            "golden_butter": 1,
            "golden_cow_milk": 2,
            "egg": 1,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 1)
        self.assertEqual(plan.raw_materials_needed.get("golden_cow_milk"), 2)
        self.assertEqual(plan.raw_materials_needed.get("golden_cheese"), 1)
        self.assertEqual(plan.raw_materials_needed.get("golden_butter"), 1)

    def test_golden_cheesecake_missing_other_raw_ingredient(self):
        """Having 100 Golden Milk but missing sugar causes UNAVAILABLE."""
        inventory = {
            "golden_cow_milk": 100,
            "egg": 10,
            "flour": 10,
            # sugar is missing
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_shared_milk_pool_cannot_double_count(self):
        """2 Golden Milk can craft cheese OR butter, but not both + direct cheesecake."""
        inventory = {
            "golden_cow_milk": 2,
            "egg": 1,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)


class TestInventoryAvailabilityTierHAVE(unittest.TestCase):
    """Unit tests for items already present in inventory (HAVE tier)."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_have_item_in_inventory_returns_tier_2(self):
        """Item already owned in inventory returns AvailabilityTier.HAVE (2)."""
        inventory = {"strawberry_shortcake": 3}
        plan = evaluate_craftability("strawberry_shortcake", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.HAVE)
        self.assertEqual(plan.status, 2)
        self.assertEqual(plan.max_craftable, 3)
        self.assertEqual(plan.raw_materials_needed, {})
        self.assertEqual(plan.steps, [])

    def test_have_item_bypasses_recipe_lookup_even_if_recipe_missing(self):
        """Owned items return HAVE without requiring a recipe entry."""
        inventory = {"rare_diamond_artifact": 5}
        empty_recipes: Dict[str, Any] = {}
        plan = evaluate_craftability("rare_diamond_artifact", inventory, empty_recipes)
        self.assertEqual(plan.status, AvailabilityTier.HAVE)
        self.assertEqual(plan.max_craftable, 5)

    def test_have_item_with_count_needed_greater_than_1(self):
        """Requesting count_needed=2 with 5 in inventory gives max_craftable=2 sets."""
        inventory = {"cornmeal": 5}
        plan = evaluate_craftability("cornmeal", inventory, self.recipes, count_needed=2)
        self.assertEqual(plan.status, AvailabilityTier.HAVE)
        self.assertEqual(plan.max_craftable, 2)

    def test_have_item_partial_inventory_triggers_crafting_for_remainder(self):
        """Having 1 Strawberry Shortcake but requesting 2 crafts 1 additional from materials."""
        inventory = {
            "strawberry_shortcake": 1,
            "strawberry": 3,
            "flour": 1,
            "sugar": 1,
        }
        plan = evaluate_craftability("strawberry_shortcake", inventory, self.recipes, count_needed=2)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 2)


class TestDeepIntermediateChains(unittest.TestCase):
    """Unit tests for multi-level intermediate crafting DAGs."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_four_level_chain_deluxe_sandwich_craftable(self):
        """
        Deluxe Sandwich (4 levels):
        Wheat (4) -> Flour (4) -> Bread (2)
        Cow Milk (1) -> Cheese (1)
        Egg (1) -> Mayo (1)
        Tomato (1) -> Deluxe Sandwich (1)
        """
        inventory = {
            "wheat": 4,
            "cow_milk": 1,
            "egg": 1,
            "tomato": 1,
        }
        plan = evaluate_craftability("deluxe_sandwich", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 1)
        self.assertEqual(plan.raw_materials_needed.get("wheat"), 4)
        self.assertEqual(plan.raw_materials_needed.get("cow_milk"), 1)
        self.assertEqual(plan.raw_materials_needed.get("egg"), 1)
        self.assertEqual(plan.raw_materials_needed.get("tomato"), 1)

    def test_four_level_chain_bottleneck_detection(self):
        """Bottleneck on wheat (3 instead of 4) fails Deluxe Sandwich craft."""
        inventory = {
            "wheat": 3,  # Needs 4
            "cow_milk": 5,
            "egg": 5,
            "tomato": 5,
        }
        plan = evaluate_craftability("deluxe_sandwich", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_intermediate_chain_with_partial_intermediate_in_inventory(self):
        """Player has 1 Bread and 2 Flour (needs 2 Bread total)."""
        inventory = {
            "bread": 1,
            "flour": 2,  # Crafts 1 Bread
            "cheese": 1,
            "mayo": 1,
            "tomato": 1,
        }
        plan = evaluate_craftability("deluxe_sandwich", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 1)
        self.assertEqual(plan.raw_materials_needed.get("bread"), 1)
        self.assertEqual(plan.raw_materials_needed.get("flour"), 2)


class TestDeductCraftingMaterials(unittest.TestCase):
    """Unit tests for deduct_crafting_materials."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_deduct_directly_from_owned_inventory(self):
        """Deducting an owned item decrements stock without touching recipe materials."""
        inventory = {"strawberry_shortcake": 5, "strawberry": 10}
        updated = deduct_crafting_materials("strawberry_shortcake", inventory, self.recipes, count=2)
        self.assertEqual(updated.get("strawberry_shortcake"), 3)
        self.assertEqual(updated.get("strawberry"), 10)

    def test_deduct_single_step_crafting_materials(self):
        """Deducting 2 cornmeal consumes 2 corn."""
        inventory = {"corn": 10}
        updated = deduct_crafting_materials("cornmeal", inventory, self.recipes, count=2)
        self.assertEqual(updated.get("corn"), 8)

    def test_deduct_multi_step_golden_cheesecake_materials(self):
        """Deducting 1 Golden Cheesecake consumes 6 Golden Milk, 1 Egg, 1 Flour, 1 Sugar."""
        inventory = {
            "golden_cow_milk": 10,
            "egg": 3,
            "flour": 2,
            "sugar": 5,
        }
        updated = deduct_crafting_materials("golden_cheesecake", inventory, self.recipes, count=1)
        self.assertEqual(updated.get("golden_cow_milk"), 4)
        self.assertEqual(updated.get("egg"), 2)
        self.assertEqual(updated.get("flour"), 1)
        self.assertEqual(updated.get("sugar"), 4)

    def test_deduct_sequential_crafts_shared_ingredient_exhaustion(self):
        """Two sequential crafts competing for Flour properly exhaust the shared pool."""
        inventory = {"flour": 2, "strawberry": 10, "sugar": 5}
        # First craft: Strawberry Shortcake (uses 1 Flour)
        inv_after_shortcake = deduct_crafting_materials("strawberry_shortcake", inventory, self.recipes, 1)
        self.assertEqual(inv_after_shortcake["flour"], 1)

        # Second craft: Bread (needs 2 Flour) -> now UNAVAILABLE
        plan_bread = evaluate_craftability("bread", inv_after_shortcake, self.recipes)
        self.assertEqual(plan_bread.status, AvailabilityTier.UNAVAILABLE)

    def test_deduct_count_zero_or_negative_returns_unmodified_copy(self):
        """Deducting 0 or negative count returns copy of inventory without mutation."""
        inventory = {"corn": 5}
        updated = deduct_crafting_materials("cornmeal", inventory, self.recipes, count=0)
        self.assertEqual(updated, inventory)

    def test_deduct_partial_owned_plus_craft(self):
        """Player has 1 Golden Cheesecake, asks to deduct 2 -> consumes 1 owned + 6 Milk etc."""
        inventory = {
            "golden_cheesecake": 1,
            "golden_cow_milk": 8,
            "egg": 2,
            "flour": 2,
            "sugar": 2,
        }
        updated = deduct_crafting_materials("golden_cheesecake", inventory, self.recipes, count=2)
        self.assertEqual(updated.get("golden_cheesecake"), 0)
        self.assertEqual(updated.get("golden_cow_milk"), 2)
        self.assertEqual(updated.get("egg"), 1)
        self.assertEqual(updated.get("flour"), 1)
        self.assertEqual(updated.get("sugar"), 1)


class TestCraftingChainFormatting(unittest.TestCase):
    """Unit tests for format_crafting_chain."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_format_chain_single_step(self):
        """Single-step recipe formats as 'Product [← Count× Ingredient]'."""
        inventory = {"corn": 5}
        plan = evaluate_craftability("cornmeal", inventory, self.recipes)
        summary = format_crafting_chain(plan)
        self.assertIn("Cornmeal", summary)
        self.assertIn("1× Corn", summary)

    def test_format_chain_multi_step_golden_cheesecake(self):
        """Multi-step Golden Cheesecake formats sub-steps Golden Cheese and Golden Butter."""
        inventory = {"golden_cow_milk": 6, "egg": 1, "flour": 1, "sugar": 1}
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        summary = format_crafting_chain(plan)
        self.assertIn("Golden Cheese [← 2× Golden Milk]", summary)
        self.assertIn("Golden Butter [← 2× Golden Milk]", summary)

    def test_format_chain_have_empty(self):
        """HAVE items have empty chain summary."""
        inventory = {"cornmeal": 5}
        plan = evaluate_craftability("cornmeal", inventory, self.recipes)
        summary = format_crafting_chain(plan)
        self.assertEqual(summary, "")

    def test_format_chain_unavailable_empty(self):
        """UNAVAILABLE items have empty chain summary."""
        inventory = {}
        plan = evaluate_craftability("golden_cheesecake", inventory, self.recipes)
        summary = format_crafting_chain(plan)
        self.assertEqual(summary, "")


class TestEdgeCasesAndSafety(unittest.TestCase):
    """Unit tests for boundary conditions, cycle safety, and corner cases."""

    def setUp(self):
        self.recipes = get_mock_recipes()

    def test_circular_dependency_a_b_a_returns_unavailable(self):
        """Circular recipe dependency (A -> B -> A) returns UNAVAILABLE without recursion crash."""
        cyclic_recipes = {
            "item_a": {
                "item_id": "item_a",
                "display_name": "Item A",
                "source": "cooking",
                "output_count": 1,
                "ingredients": [{"item_id": "item_b", "display_name": "Item B", "count": 1}],
            },
            "item_b": {
                "item_id": "item_b",
                "display_name": "Item B",
                "source": "cooking",
                "output_count": 1,
                "ingredients": [{"item_id": "item_a", "display_name": "Item A", "count": 1}],
            },
        }
        plan = evaluate_craftability("item_a", {}, cyclic_recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_circular_dependency_self_reference_returns_unavailable(self):
        """Recipe listing itself as ingredient (A -> A) returns UNAVAILABLE safely."""
        self_ref_recipe = {
            "loop_item": {
                "item_id": "loop_item",
                "display_name": "Loop Item",
                "source": "cooking",
                "output_count": 1,
                "ingredients": [{"item_id": "loop_item", "display_name": "Loop Item", "count": 1}],
            }
        }
        plan = evaluate_craftability("loop_item", {}, self_ref_recipe)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_missing_recipe_returns_unavailable(self):
        """Evaluating craftability for an unknown item returns UNAVAILABLE."""
        plan = evaluate_craftability("unknown_mythical_elixir", {}, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_non_craftable_raw_item_with_no_recipe(self):
        """Raw items like ores or forage without recipes return UNAVAILABLE if not owned."""
        plan = evaluate_craftability("iron_ore", {}, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_count_needed_zero_or_negative_safe(self):
        """count_needed <= 0 handles safely."""
        inventory = {"corn": 5}
        plan = evaluate_craftability("cornmeal", inventory, self.recipes, count_needed=0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 5)

    def test_empty_inventory_returns_unavailable(self):
        """Empty inventory dictionary returns UNAVAILABLE."""
        plan = evaluate_craftability("cornmeal", {}, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.UNAVAILABLE)
        self.assertEqual(plan.max_craftable, 0)

    def test_case_insensitive_and_whitespace_ids(self):
        """Whitespace and casing in item IDs are normalized."""
        inventory = {"  corn  ": 5}
        plan = evaluate_craftability("  CORNMEAL  ", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 5)

    def test_float_counts_in_inventory_cleaned_to_int(self):
        """Floating point counts in inventory (e.g. 5.0) are handled cleanly."""
        inventory = {"corn": 5.0}  # type: ignore
        plan = evaluate_craftability("cornmeal", inventory, self.recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 5)

    def test_recipe_with_multiple_outputs_surplus_in_pool(self):
        """Recipe with output_count=4 crafts 1 batch when 1 requested, producing surplus 3."""
        inventory = {"flour": 1, "sugar": 1}
        plan = evaluate_craftability("cookies", inventory, self.recipes, count_needed=1)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 4)


class TestRealRecipeDatabase(unittest.TestCase):
    """Unit tests validating load_recipes against actual data/recipes.json."""

    def test_load_recipes_default_path(self):
        """load_recipes() loads the canonical data/recipes.json from repo."""
        recipes = load_recipes()
        self.assertGreater(len(recipes), 0)
        self.assertIn("blackberry_jam", recipes)
        self.assertIn("bread", recipes)

    def test_load_recipes_custom_temp_file(self):
        """load_recipes() loads from custom file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "custom_recipes.json"
            mock_data = get_mock_recipes()
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(mock_data, f)

            loaded = load_recipes(str(tmp_path))
            self.assertEqual(len(loaded), len(mock_data))
            self.assertIn("golden_cheesecake", loaded)

    def test_load_recipes_nonexistent_returns_empty_dict(self):
        """load_recipes() on nonexistent path returns empty dict without throwing."""
        loaded = load_recipes("/path/that/does/not/exist_12345.json")
        self.assertEqual(loaded, {})

    def test_evaluate_craftability_with_real_recipes_json(self):
        """Evaluate craftability of blackberry_jam using real data/recipes.json."""
        real_recipes = load_recipes()
        if not real_recipes:
            self.skipTest("data/recipes.json not available")

        # Blackberry Jam needs 6 Blackberry + 1 Sugar
        inventory = {"blackberry": 12, "sugar": 2}
        plan = evaluate_craftability("blackberry_jam", inventory, real_recipes)
        self.assertEqual(plan.status, AvailabilityTier.CRAFT)
        self.assertEqual(plan.max_craftable, 2)


if __name__ == "__main__":
    unittest.main()
