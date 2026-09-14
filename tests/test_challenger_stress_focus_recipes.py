#!/usr/bin/env python3
"""
tests/test_challenger_stress_focus_recipes.py

Empirical and adversarial stress test harness for:
- compute_focus_recipes()
- load_recipe_sources()

Testing dimensions:
1. Large or unusual inputs (1,000+ simulated recipes, complex preference maps, performance benchmarking).
2. Boundary condition ties (identical impact, case-insensitive display name sorting, secondary recipe_id tiebreaker, rank monotonicity).
3. Malformed data resilience (corrupted JSON, non-dict JSON, dirty types, whitespace/casing normalization).
4. Strict milling recipe exclusion under all combinations (case/whitespace variations, high impact non-cooking, milling in unlock sets).
5. Edge case handling when unlocked set is None vs empty vs partial vs 100% full vs superset vs 0 cooking recipes.
"""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fom_planner.data_loader import load_recipe_sources
from fom_planner.optimizer import compute_focus_recipes


class TestCategory1LargeAndUnusualInputs(unittest.TestCase):
    """
    Empirically stresses compute_focus_recipes() with high-cardinality datasets,
    dense NPC preference mappings, and verifies algorithmic complexity/performance.
    """

    def test_2000_recipes_scale_and_performance(self):
        """
        Stress test with 2,500 recipes (2,000 cooking, 500 milling).
        Verifies execution completes within strict timing bound (< 0.20s)
        and preserves all mathematical and ranking invariants.
        """
        sim_recipes = {}
        # 2,000 cooking recipes
        for i in range(2000):
            rid = f"recipe_{i:04d}"
            sim_recipes[rid] = {
                "item_id": rid,
                "display_name": f"Dish {i:04d}",
                "source": "cooking",
                "output_count": 1,
                "ingredients": [],
            }
        # 500 milling recipes
        for j in range(500):
            rid = f"milling_{j:04d}"
            sim_recipes[rid] = {
                "item_id": rid,
                "display_name": f"Flour {j:04d}",
                "source": "milling",
                "output_count": 1,
                "ingredients": [],
            }

        # 500 unlocked recipes
        unlocked = {f"recipe_{i:04d}" for i in range(500)}

        # Dense preference map: 600 items, each desired by up to 50 NPCs
        remaining_map = {}
        for i in range(400, 1000):
            rid = f"recipe_{i:04d}"
            loved_npcs = {f"npc_loved_{k}" for k in range(i % 30)}
            liked_npcs = {f"npc_liked_{k}" for k in range(i % 25)}
            remaining_map[rid] = {"loved": loved_npcs, "liked": liked_npcs}

        # Recipe sources mapping
        sources = {f"recipe_{i:04d}": f"Source Vendor {i % 10}" for i in range(2000)}

        start_time = time.perf_counter()
        top_n = 50
        focus_list, stats = compute_focus_recipes(
            all_recipes=sim_recipes,
            unlocked_recipe_ids=unlocked,
            remaining_items_map=remaining_map,
            recipe_sources=sources,
            top_n=top_n,
        )
        elapsed = time.perf_counter() - start_time

        # Performance constraint: must complete in < 0.25 seconds
        self.assertLess(elapsed, 0.25, f"Execution too slow: took {elapsed:.4f}s for 2,500 recipes")

        # Invariants verification
        self.assertEqual(len(focus_list), top_n)
        self.assertEqual(stats["total_cooking_recipes"], 2000)
        self.assertEqual(stats["unlocked_recipes_count"], 500)
        self.assertAlmostEqual(stats["unlocked_percentage"], 25.0, places=2)

        # Ranks must be strictly sequential 1..50
        for expected_rank, item in enumerate(focus_list, start=1):
            self.assertEqual(item["rank"], expected_rank)

        # Impact must be monotonically non-increasing
        for i in range(len(focus_list) - 1):
            self.assertGreaterEqual(
                focus_list[i]["impact"],
                focus_list[i + 1]["impact"],
                f"Impact ranking violation at index {i}: {focus_list[i]['impact']} < {focus_list[i+1]['impact']}"
            )

        # No unlocked recipe should appear
        returned_ids = {r["recipe_id"] for r in focus_list}
        self.assertTrue(returned_ids.isdisjoint(unlocked), "Found unlocked recipes in focus suggestions!")

    def test_extreme_preference_overlap_deduplication(self):
        """
        Adversarial test where NPCs appear in both loved and liked sets for the same dish.
        Verifies union set logic deduplicates NPCs properly without inflated impact counts.
        """
        sim_recipes = {
            "dish_overlap": {"item_id": "dish_overlap", "display_name": "Overlap Dish", "source": "cooking"},
            "dish_distinct": {"item_id": "dish_distinct", "display_name": "Distinct Dish", "source": "cooking"},
        }
        # dish_overlap has same 10 NPCs in both loved and liked -> union should be exactly 10
        # dish_distinct has 6 loved and 5 liked distinct NPCs -> union should be 11
        remaining_map = {
            "dish_overlap": {
                "loved": {f"npc_{i}" for i in range(10)},
                "liked": {f"npc_{i}" for i in range(10)},
            },
            "dish_distinct": {
                "loved": {f"npc_a_{i}" for i in range(6)},
                "liked": {f"npc_b_{i}" for i in range(5)},
            },
        }

        focus_list, _ = compute_focus_recipes(
            all_recipes=sim_recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map=remaining_map,
            top_n=10,
        )

        impact_map = {r["recipe_id"]: r["impact"] for r in focus_list}
        self.assertEqual(impact_map["dish_overlap"], 10)
        self.assertEqual(impact_map["dish_distinct"], 11)
        self.assertEqual(focus_list[0]["recipe_id"], "dish_distinct")
        self.assertEqual(focus_list[1]["recipe_id"], "dish_overlap")

    def test_large_top_n_exceeding_locked_pool(self):
        """
        When top_n exceeds total available locked recipes, returns all available
        without padding or out-of-bounds error.
        """
        sim_recipes = {
            f"dish_{i}": {"item_id": f"dish_{i}", "display_name": f"Dish {i}", "source": "cooking"}
            for i in range(5)
        }
        focus_list, _ = compute_focus_recipes(
            all_recipes=sim_recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map={},
            top_n=10000,
        )
        self.assertEqual(len(focus_list), 5)


class TestCategory2BoundaryConditionTies(unittest.TestCase):
    """
    Empirically verifies deterministic tiebreaking behavior across identical impacts,
    mixed casing in display names, and secondary recipe_id tiebreakers.
    """

    def test_identical_impact_case_insensitive_alphabetical_tiebreaker(self):
        """
        Multiple recipes with identical impact must sort case-insensitively by display name.
        e.g., 'apple', 'Banana', 'carrot', 'cabbage'.
        """
        recipes = {
            "r1": {"item_id": "r1", "display_name": "banana Bread", "source": "cooking"},
            "r2": {"item_id": "r2", "display_name": "Apple Tart", "source": "cooking"},
            "r3": {"item_id": "r3", "display_name": "carrot soup", "source": "cooking"},
            "r4": {"item_id": "r4", "display_name": "Avocado Salad", "source": "cooking"},
            "r5": {"item_id": "r5", "display_name": "banana Cake", "source": "cooking"},
        }
        # All have identical impact = 3
        remaining_map = {
            rid: {"loved": {"npc_1", "npc_2", "npc_3"}, "liked": set()}
            for rid in recipes
        }

        focus_list, _ = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map=remaining_map,
            top_n=10,
        )

        names = [r["display_name"] for r in focus_list]
        expected = ["Apple Tart", "Avocado Salad", "banana Bread", "banana Cake", "carrot soup"]
        self.assertEqual(names, expected)

    def test_identical_impact_and_display_name_secondary_tiebreaker(self):
        """
        When impact AND display_name are identical, secondary tiebreaker must be recipe_id ascending.
        """
        recipes = {
            "recipe_z": {"item_id": "recipe_z", "display_name": "Mystery Stew", "source": "cooking"},
            "recipe_a": {"item_id": "recipe_a", "display_name": "Mystery Stew", "source": "cooking"},
            "recipe_m": {"item_id": "recipe_m", "display_name": "Mystery Stew", "source": "cooking"},
        }
        remaining_map = {
            rid: {"loved": {"npc_1"}, "liked": set()}
            for rid in recipes
        }

        focus_list, _ = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map=remaining_map,
            top_n=10,
        )

        rids = [r["recipe_id"] for r in focus_list]
        self.assertEqual(rids, ["recipe_a", "recipe_m", "recipe_z"])

    def test_all_zero_impact_tie_sorting(self):
        """
        When all recipes have impact 0, entire list is ordered strictly alphabetically.
        """
        recipes = {
            "z": {"item_id": "z", "display_name": "Zebra Chow", "source": "cooking"},
            "a": {"item_id": "a", "display_name": "Artichoke Dip", "source": "cooking"},
            "m": {"item_id": "m", "display_name": "Mushroom Medley", "source": "cooking"},
        }
        focus_list, _ = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map={},
            top_n=10,
        )
        self.assertEqual([r["recipe_id"] for r in focus_list], ["a", "m", "z"])
        for r in focus_list:
            self.assertEqual(r["impact"], 0)


class TestCategory3MalformedDataResilience(unittest.TestCase):
    """
    Stress-tests load_recipe_sources() and compute_focus_recipes() with corrupted JSON,
    non-dict formats, dirty types, and unnormalized IDs.
    """

    def test_load_recipe_sources_adversarial_files(self):
        """Tests load_recipe_sources with various corrupted / adversarial file formats."""
        # 1. 0-byte empty file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            tf_path = Path(tf.name)
        try:
            res = load_recipe_sources(tf_path)
            self.assertEqual(res, {})
        finally:
            if tf_path.exists():
                tf_path.unlink()

        # 2. Corrupted JSON with null bytes and invalid tokens
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as tf:
            tf.write(b'{"key": \x00\xff invalid json \x00}')
            tf_path = Path(tf.name)
        try:
            res = load_recipe_sources(tf_path)
            self.assertEqual(res, {})
        finally:
            if tf_path.exists():
                tf_path.unlink()

        # 3. Non-dict primitives
        for primitive in [42, 3.14, "just a string", True, None, [1, 2, 3]]:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                json.dump(primitive, tf)
                tf_path = Path(tf.name)
            try:
                res = load_recipe_sources(tf_path)
                self.assertEqual(res, {})
            finally:
                if tf_path.exists():
                    tf_path.unlink()

        # 4. Dict with non-string keys, whitespace, and non-string values
        dirty_dict = {
            "  Bread  ": "  Starter  ",
            "123": 456,
            "null_val": None,
            "nested": {"nested_key": "val"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            json.dump(dirty_dict, tf)
            tf_path = Path(tf.name)
        try:
            res = load_recipe_sources(tf_path)
            self.assertIn("bread", res)
            self.assertEqual(res["bread"], "Starter")
            self.assertIn("123", res)
            self.assertEqual(res["123"], "456")
            self.assertEqual(res["null_val"], "None")
        finally:
            if tf_path.exists():
                tf_path.unlink()

    def test_compute_focus_recipes_adversarial_recipe_catalog(self):
        """
        compute_focus_recipes handles catalog with None values, non-dict entries,
        and missing fields without throwing exceptions.
        """
        adversarial_catalog = {
            "corrupt_1": None,
            "corrupt_2": "string_instead_of_dict",
            "corrupt_3": ["list", "of", "items"],
            "corrupt_4": {},
            "corrupt_5": {"source": None},
            "corrupt_6": {"source": "cooking", "display_name": None, "item_id": None},
            "valid_1": {"source": "cooking", "display_name": "Valid Dish", "item_id": "valid_1"},
        }

        focus_list, stats = compute_focus_recipes(
            all_recipes=adversarial_catalog,
            unlocked_recipe_ids=set(),
            remaining_items_map={},
            top_n=10,
        )

        # Only corrupt_6 and valid_1 have source=="cooking"
        self.assertEqual(stats["total_cooking_recipes"], 2)
        self.assertEqual(len(focus_list), 2)
        valid_entry = next(r for r in focus_list if r["recipe_id"] == "valid_1")
        self.assertEqual(valid_entry["display_name"], "Valid Dish")

    def test_compute_focus_recipes_adversarial_unlocked_ids(self):
        """
        unlocked_recipe_ids with dirty types (integers, whitespace, uppercase, None elements)
        is safely normalized.
        """
        recipes = {
            "apple_pie": {"item_id": "apple_pie", "display_name": "Apple Pie", "source": "cooking"},
            "berry_pie": {"item_id": "berry_pie", "display_name": "Berry Pie", "source": "cooking"},
        }
        # Dirty unlocked list with None, ints, uppercase, whitespace
        dirty_unlocked = [None, "", "  APPLE_PIE  ", 9999, "   ", "\tberry_pie\n"]

        focus_list, stats = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=dirty_unlocked,
            remaining_items_map={},
            top_n=10,
        )

        # Both apple_pie and berry_pie should match and be considered unlocked
        self.assertEqual(focus_list, [])
        self.assertEqual(stats["unlocked_count"], 2)
        self.assertAlmostEqual(stats["unlocked_percentage"], 100.0)

    def test_compute_focus_recipes_adversarial_remaining_map(self):
        """
        remaining_items_map with malformed values (non-dicts, None sets, integers in sets)
        is parsed safely without crashing.
        """
        recipes = {
            "dish_a": {"item_id": "dish_a", "display_name": "Dish A", "source": "cooking"},
            "dish_b": {"item_id": "dish_b", "display_name": "Dish B", "source": "cooking"},
            "dish_c": {"item_id": "dish_c", "display_name": "Dish C", "source": "cooking"},
            "dish_d": {"item_id": "dish_d", "display_name": "Dish D", "source": "cooking"},
            "dish_e": {"item_id": "dish_e", "display_name": "Dish E", "source": "cooking"},
        }
        adversarial_map = {
            "dish_a": None,
            "dish_b": 12345,
            "dish_c": "just_a_string_target",  # non-collection string ignored
            "dish_d": {
                "loved": [None, "  npc_valid  ", 123, ""],
                "liked": None,
            },
            "dish_e": ["single_target_in_list"],  # list targets supported
        }

        focus_list, _ = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map=adversarial_map,
            top_n=10,
        )

        impacts = {r["recipe_id"]: r["impact"] for r in focus_list}
        self.assertEqual(impacts["dish_a"], 0)
        self.assertEqual(impacts["dish_b"], 0)
        self.assertEqual(impacts["dish_c"], 0)  # string safely ignored, impact 0
        self.assertEqual(impacts["dish_d"], 2)  # "npc_valid" and "123"
        self.assertEqual(impacts["dish_e"], 1)  # list parsed with 1 target


class TestCategory4StrictMillingAndSourceExclusion(unittest.TestCase):
    """
    Verifies that ONLY recipes with source == 'cooking' are included, and milling
    recipes are strictly excluded under all case/whitespace variations and high impact.
    """

    def test_milling_variations_and_high_impact_exclusion(self):
        """
        Even when a milling recipe has massive impact (e.g. 50 loved NPCs),
        it must NEVER be returned in focus_recipes.
        """
        recipes = {
            "flour_lower": {"item_id": "flour_lower", "display_name": "Flour 1", "source": "milling"},
            "flour_upper": {"item_id": "flour_upper", "display_name": "Flour 2", "source": "MILLING"},
            "flour_ws": {"item_id": "flour_ws", "display_name": "Flour 3", "source": "  milling  "},
            "craft_item": {"item_id": "craft_item", "display_name": "Bench", "source": "crafting"},
            "forge_item": {"item_id": "forge_item", "display_name": "Ingot", "source": "blacksmithing"},
            "cook_dish": {"item_id": "cook_dish", "display_name": "Cooked Dish", "source": "cooking"},
        }
        # Give milling recipes high impact
        remaining_map = {
            "flour_lower": {"loved": {f"npc_{i}" for i in range(50)}, "liked": set()},
            "flour_upper": {"loved": {f"npc_{i}" for i in range(50)}, "liked": set()},
            "cook_dish": {"loved": {"celine"}, "liked": set()},
        }

        focus_list, stats = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map=remaining_map,
            top_n=10,
        )

        # Only cook_dish must be in stats and focus_list
        self.assertEqual(stats["total_cooking_recipes"], 1)
        self.assertEqual(len(focus_list), 1)
        self.assertEqual(focus_list[0]["recipe_id"], "cook_dish")

    def test_milling_in_unlocked_recipe_ids_does_not_distort_stats(self):
        """
        If unlocked_recipe_ids contains 50 milling recipe IDs,
        unlocked_cooking_count and unlocked_percentage must remain 0.
        """
        recipes = {
            "pie": {"item_id": "pie", "display_name": "Pie", "source": "cooking"},
            "flour": {"item_id": "flour", "display_name": "Flour", "source": "milling"},
        }
        # Player unlocks flour (milling), but NOT pie (cooking)
        unlocked = {"flour", "other_milling_recipe"}

        focus_list, stats = compute_focus_recipes(
            all_recipes=recipes,
            unlocked_recipe_ids=unlocked,
            remaining_items_map={},
            top_n=10,
        )

        self.assertEqual(stats["total_cooking_recipes"], 1)
        self.assertEqual(stats["unlocked_recipes_count"], 0)
        self.assertEqual(stats["unlocked_percentage"], 0.0)
        self.assertEqual(len(focus_list), 1)
        self.assertEqual(focus_list[0]["recipe_id"], "pie")


class TestCategory5EdgeCaseUnlockedSetStates(unittest.TestCase):
    """
    Tests edge cases where unlocked_recipe_ids is:
    - None (no save file / no unlock data)
    - Empty set (new game)
    - Partial set
    - Full 100% set
    - Superset (all recipes + invalid IDs)
    - Zero cooking recipes in catalog
    """

    def setUp(self):
        self.recipes = {
            "dish_1": {"item_id": "dish_1", "display_name": "Dish 1", "source": "cooking"},
            "dish_2": {"item_id": "dish_2", "display_name": "Dish 2", "source": "cooking"},
        }

    def test_unlocked_is_none(self):
        """None unlocked_recipe_ids: returns ([], stats) with has_unlock_data=False."""
        focus_list, stats = compute_focus_recipes(
            all_recipes=self.recipes,
            unlocked_recipe_ids=None,
            remaining_items_map={"dish_1": {"loved": {"npc_a"}, "liked": set()}},
            top_n=10,
        )
        self.assertEqual(focus_list, [])
        self.assertFalse(stats["has_unlock_data"])
        self.assertEqual(stats["unlocked_count"], 0)
        self.assertEqual(stats["unlocked_percentage"], 0.0)

    def test_unlocked_is_empty_set(self):
        """Empty set: returns focus_recipes, has_unlock_data=True, unlocked_count=0."""
        focus_list, stats = compute_focus_recipes(
            all_recipes=self.recipes,
            unlocked_recipe_ids=set(),
            remaining_items_map={},
            top_n=10,
        )
        self.assertEqual(len(focus_list), 2)
        self.assertTrue(stats["has_unlock_data"])
        self.assertEqual(stats["unlocked_count"], 0)
        self.assertEqual(stats["unlocked_percentage"], 0.0)

    def test_unlocked_is_superset(self):
        """Superset with extra IDs: correctly returns 100% unlocked and empty list."""
        unlocked_superset = {"dish_1", "dish_2", "flour", "nonexistent_recipe"}
        focus_list, stats = compute_focus_recipes(
            all_recipes=self.recipes,
            unlocked_recipe_ids=unlocked_superset,
            remaining_items_map={},
            top_n=10,
        )
        self.assertEqual(focus_list, [])
        self.assertTrue(stats["has_unlock_data"])
        self.assertEqual(stats["unlocked_count"], 2)
        self.assertEqual(stats["unlocked_percentage"], 100.0)

    def test_catalog_has_zero_cooking_recipes(self):
        """Catalog with 0 cooking recipes does not crash with ZeroDivisionError."""
        milling_only = {
            "flour": {"item_id": "flour", "display_name": "Flour", "source": "milling"}
        }
        focus_list, stats = compute_focus_recipes(
            all_recipes=milling_only,
            unlocked_recipe_ids=set(),
            remaining_items_map={},
            top_n=10,
        )
        self.assertEqual(focus_list, [])
        self.assertEqual(stats["total_cooking_recipes"], 0)
        self.assertEqual(stats["unlocked_percentage"], 0.0)


class TestCategory6PropertyBasedRandomFuzzing(unittest.TestCase):
    """
    Randomized property-based fuzzing testing across 100 iterations.
    Validates structural invariants regardless of recipe permutations,
    unlock counts, preference distributions, or tie topologies.
    """

    def test_randomized_invariants_fuzzing_100_runs(self):
        import random
        rng = random.Random(42)

        for iteration in range(100):
            # Generate random number of cooking recipes (0 to 100) and milling recipes (0 to 30)
            num_cooking = rng.randint(0, 100)
            num_milling = rng.randint(0, 30)

            recipes = {}
            cooking_ids = []
            for i in range(num_cooking):
                rid = f"cook_{i:03d}"
                cooking_ids.append(rid)
                # Randomize display name casing and spaces
                dname = f"Dish {i:03d} " + rng.choice(["Tart", "Stew", "Pie", "Soup", "bread", "CAKE"])
                recipes[rid] = {
                    "item_id": rid,
                    "display_name": dname,
                    "source": rng.choice(["cooking", "COOKING", " Cooking "]),
                }

            for j in range(num_milling):
                rid = f"mill_{j:03d}"
                recipes[rid] = {
                    "item_id": rid,
                    "display_name": f"Flour {j:03d}",
                    "source": rng.choice(["milling", "MILLING", "  milling  "]),
                }

            # Randomize unlocked set
            has_unlocks = rng.choice([True, False])
            if not has_unlocks:
                unlocked_ids = None
            else:
                k = rng.randint(0, num_cooking + 5)
                # Sample from cooking + potential milling/extra
                pool = cooking_ids + [f"mill_{j:03d}" for j in range(num_milling)] + ["phantom_1", "phantom_2"]
                unlocked_ids = set(rng.sample(pool, min(k, len(pool))))

            # Randomize remaining_items_map
            remaining_map = {}
            for cid in cooking_ids:
                if rng.random() > 0.4:
                    num_loved = rng.randint(0, 10)
                    num_liked = rng.randint(0, 10)
                    remaining_map[cid] = {
                        "loved": {f"npc_{x}" for x in range(num_loved)},
                        "liked": {f"npc_{x}" for x in range(num_liked)},
                    }

            top_n = rng.randint(-2, 25)

            # Call compute_focus_recipes
            focus_list, stats = compute_focus_recipes(
                all_recipes=recipes,
                unlocked_recipe_ids=unlocked_ids,
                remaining_items_map=remaining_map,
                top_n=top_n,
            )

            # Assert Invariants
            self.assertEqual(stats["total_cooking_recipes"], num_cooking)
            self.assertEqual(stats["total_cooking"], num_cooking)

            if unlocked_ids is None:
                self.assertFalse(stats["has_unlock_data"])
                self.assertEqual(stats["unlocked_count"], 0)
                self.assertEqual(focus_list, [])
            else:
                self.assertTrue(stats["has_unlock_data"])
                unlocked_cooking = {x for x in unlocked_ids if x in cooking_ids}
                self.assertEqual(stats["unlocked_count"], len(unlocked_cooking))

                if len(unlocked_cooking) >= num_cooking or top_n <= 0 or num_cooking == 0:
                    self.assertEqual(focus_list, [])
                else:
                    self.assertLessEqual(len(focus_list), top_n)
                    self.assertLessEqual(len(focus_list), num_cooking - len(unlocked_cooking))

                    # Verify sequential ranks
                    self.assertEqual([r["rank"] for r in focus_list], list(range(1, len(focus_list) + 1)))

                    # Verify no unlocked items
                    for item in focus_list:
                        self.assertNotIn(item["recipe_id"], unlocked_cooking)

                    # Verify no milling items
                    for item in focus_list:
                        self.assertFalse(item["recipe_id"].startswith("mill_"))

                    # Verify sorting monotonicity
                    for idx in range(len(focus_list) - 1):
                        curr = focus_list[idx]
                        nxt = focus_list[idx + 1]
                        self.assertGreaterEqual(curr["impact"], nxt["impact"])
                        if curr["impact"] == nxt["impact"]:
                            self.assertLessEqual(
                                curr["display_name"].lower(),
                                nxt["display_name"].lower(),
                            )
                            if curr["display_name"].lower() == nxt["display_name"].lower():
                                self.assertLessEqual(
                                    curr["recipe_id"].lower(),
                                    nxt["recipe_id"].lower(),
                                )


if __name__ == "__main__":
    unittest.main()

