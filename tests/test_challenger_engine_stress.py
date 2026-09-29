#!/usr/bin/env python3
"""
tests/test_challenger_engine_stress.py

Empirical Challenger 1 Stress Test Harness:
Adversarially tests Data Layer (alt_sources.json, load_alt_sources)
and Core Crafting Tree Engine (build_focus_crafting_trees)
for data integrity, edge-case resilience, cycle safety, DAG branching,
dead-end pruning, malformed inputs, and large-scale synthetic workloads.
"""

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fom_planner.data_loader import load_alt_sources
from fom_planner.optimizer import (
    _TREE_ITEM_ALIASES,
    build_focus_crafting_trees,
)

DATA_ALT_SOURCES_PATH = REPO_ROOT / "data" / "alt_sources.json"

VALID_SOURCE_TYPES = {
    "shop",
    "inn",
    "market_stall",
    "chicken_statue",
    "mimic",
    "mill",
    "fishing",
    "wishing_well",
    "festival",
    "date",
    "quest",
    "museum",
    "living_off_the_land",
}


class TestAltSourcesDataIntegrityEmpirical(unittest.TestCase):
    """Deep data integrity, normalization, alias consistency, and completeness tests."""

    def setUp(self):
        self.assertTrue(DATA_ALT_SOURCES_PATH.exists(), f"Missing {DATA_ALT_SOURCES_PATH}")
        with open(DATA_ALT_SOURCES_PATH, "r", encoding="utf-8") as f:
            self.raw_data = json.load(f)

    def test_file_syntax_and_root_type(self):
        """alt_sources.json must be a valid JSON dictionary."""
        self.assertIsInstance(self.raw_data, dict)
        self.assertGreater(len(self.raw_data), 0)

    def test_item_count_and_completeness(self):
        """Must cover at least 150 distinct item IDs and 200+ source entries."""
        item_count = len(self.raw_data)
        total_sources = sum(len(v) for v in self.raw_data.values() if isinstance(v, list))
        self.assertGreaterEqual(
            item_count, 150, f"Expected >= 150 items in alt_sources.json, got {item_count}"
        )
        self.assertGreaterEqual(
            total_sources, 200, f"Expected >= 200 total sources in alt_sources.json, got {total_sources}"
        )

    def test_source_types_and_schema_strict(self):
        """Every source entry must match defined taxonomy and schema."""
        type_counts = {t: 0 for t in VALID_SOURCE_TYPES}

        for item_id, sources in self.raw_data.items():
            self.assertIsInstance(
                sources, list, f"Item {item_id} value must be a list, got {type(sources)}"
            )
            self.assertGreater(len(sources), 0, f"Item {item_id} has empty sources list")

            for idx, source in enumerate(sources):
                self.assertIsInstance(
                    source, dict, f"Item {item_id}[{idx}] is not a dict: {source}"
                )
                source_type = source.get("type")
                self.assertIn(
                    source_type,
                    VALID_SOURCE_TYPES,
                    f"Item {item_id}[{idx}] has invalid type: {source_type}",
                )
                type_counts[source_type] += 1

                # Check cost / currency type constraints if present
                if "cost" in source and source["cost"] is not None:
                    self.assertIsInstance(
                        source["cost"],
                        (int, float),
                        f"Item {item_id}[{idx}] cost must be numeric or None, got {type(source['cost'])}",
                    )
                    self.assertGreaterEqual(
                        source["cost"], 0, f"Item {item_id}[{idx}] has negative cost"
                    )

                if "currency" in source and source["currency"] is not None:
                    self.assertIsInstance(
                        source["currency"],
                        str,
                        f"Item {item_id}[{idx}] currency must be str, got {type(source['currency'])}",
                    )

                if "icon" in source and source["icon"] is not None:
                    self.assertIsInstance(
                        source["icon"],
                        str,
                        f"Item {item_id}[{idx}] icon must be str, got {type(source['icon'])}",
                    )
                    self.assertTrue(
                        len(source["icon"].strip()) > 0,
                        f"Item {item_id}[{idx}] has empty icon string",
                    )

        # All 12 source types must be represented
        for stype, count in type_counts.items():
            self.assertGreater(
                count, 0, f"Source type '{stype}' is not represented in alt_sources.json"
            )

    def test_key_normalization(self):
        """All item keys in alt_sources.json must be stripped lowercase strings."""
        for item_id in self.raw_data.keys():
            self.assertIsInstance(item_id, str)
            self.assertEqual(
                item_id,
                item_id.strip().lower(),
                f"Key '{item_id}' is not lowercase stripped",
            )
            self.assertNotIn(" ", item_id, f"Key '{item_id}' contains spaces")

    def test_alias_coverage_and_consistency(self):
        """Check known game aliases (e.g. milk vs cow_milk) consistency."""
        alias_pairs = [
            ("milk", "cow_milk"),
            ("golden_milk", "golden_cow_milk"),
            ("wood", "basic_wood"),
            ("stone", "ore_stone"),
            ("rice_ball", "riceball"),
            ("tea", "cup_of_tea"),
        ]
        loaded = load_alt_sources(DATA_ALT_SOURCES_PATH)
        for a, b in alias_pairs:
            # At least one member of the pair should resolve or have sources defined
            sources_a = loaded.get(a) or []
            sources_b = loaded.get(b) or []
            has_sources = len(sources_a) > 0 or len(sources_b) > 0
            self.assertTrue(
                has_sources,
                f"Neither alias in pair ('{a}', '{b}') has sources in alt_sources.json",
            )


class TestLoadAltSourcesEdgeCases(unittest.TestCase):
    """Empirical tests for load_alt_sources robustness across failure modes."""

    def test_missing_file_returns_empty_dict(self):
        """Non-existent path returns {} without throwing."""
        result = load_alt_sources("/non/existent/path/alt_sources.json")
        self.assertEqual(result, {})

    def test_corrupted_json_syntax(self):
        """Invalid JSON syntax returns {} without crashing."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{ invalid json syntax [}: 1234")
            temp_path = f.name
        try:
            result = load_alt_sources(temp_path)
            self.assertEqual(result, {})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_non_dict_root_types(self):
        """Non-dict JSON roots (list, string, int, bool, null) return {}."""
        bad_roots = [
            json.dumps(["item1", "item2"]),
            json.dumps("string root"),
            json.dumps(42),
            json.dumps(True),
            json.dumps(None),
        ]
        for payload in bad_roots:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                f.write(payload)
                temp_path = f.name
            try:
                result = load_alt_sources(temp_path)
                self.assertEqual(result, {}, f"Failed for payload: {payload}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    def test_invalid_values_filtering(self):
        """Non-list values and malformed list entries are filtered gracefully."""
        payload = {
            "valid_item": [{"type": "shop", "vendor": "General Store"}],
            "non_list_val": "not a list",
            "int_val": 123,
            "dict_val": {"nested": "dict"},
            "empty_list": [],
            "list_with_bad_items": ["string_entry", None, 45, {}, {"no_type": "val"}],
            "item_with_good_and_bad": [
                {"type": "inn", "vendor": "Inn"},
                {"broken": "no type"},
                None,
            ],
            "": [{"type": "shop"}],  # empty string key should be skipped
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            temp_path = f.name
        try:
            result = load_alt_sources(temp_path)
            self.assertIn("valid_item", result)
            self.assertEqual(len(result["valid_item"]), 1)
            self.assertNotIn("non_list_val", result)
            self.assertNotIn("int_val", result)
            self.assertNotIn("dict_val", result)
            self.assertNotIn("empty_list", result)
            self.assertNotIn("list_with_bad_items", result)
            self.assertIn("item_with_good_and_bad", result)
            self.assertEqual(len(result["item_with_good_and_bad"]), 1)
            self.assertEqual(result["item_with_good_and_bad"][0]["type"], "inn")
            self.assertNotIn("", result)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_empty_and_whitespace_files(self):
        """0-byte and whitespace-only files return {} without crashing."""
        for content in ["", "   \n\t  \r\n"]:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                f.write(content)
                temp_path = f.name
            try:
                result = load_alt_sources(temp_path)
                self.assertEqual(result, {})
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    def test_file_permission_denied(self):
        """Unreadable file returns {} without unhandled OSError/PermissionError."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(json.dumps({"test": [{"type": "shop"}]}))
            temp_path = f.name
        try:
            from unittest.mock import patch
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                result = load_alt_sources(temp_path)
            self.assertEqual(result, {})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_directory_passed_as_file(self):
        """Passing a directory path returns {}."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = load_alt_sources(temp_dir)
            self.assertEqual(result, {})

    def test_path_type_flexibility(self):
        """Accepts str, Path, and None."""
        res_str = load_alt_sources(str(DATA_ALT_SOURCES_PATH))
        res_path = load_alt_sources(Path(DATA_ALT_SOURCES_PATH))
        res_none = load_alt_sources(None)
        self.assertEqual(len(res_str), len(res_path))
        self.assertEqual(len(res_str), len(res_none))


class TestBuildFocusCraftingTreesComplexGraphs(unittest.TestCase):
    """Adversarial stress-testing of DAG traversal, cycle guards, pruning, and scaling."""

    def test_deep_recipe_chain_5_plus_levels(self):
        """Deep linear recipe chain (Level 0 to Level 6) traces correctly without truncation."""
        # Level 0 (Raw) -> Level 1 -> Level 2 -> Level 3 -> Level 4 -> Level 5 -> Level 6 (Gift)
        recipes = {
            f"r_{i}": {
                "item_id": f"item_lvl_{i+1}",
                "display_name": f"Level {i+1} Product",
                "ingredients": [{"item_id": f"item_lvl_{i}", "count": 1}],
            }
            for i in range(6)
        }
        remaining_items_map = {
            "item_lvl_6": {"loved": {"Adeline"}, "liked": set()}
        }
        suggestions = [{"item_id": "item_lvl_0", "item_name": "Root Blocker"}]

        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=remaining_items_map,
        )

        self.assertEqual(len(trees), 1)
        curr = trees[0]
        self.assertEqual(curr["item_id"], "item_lvl_0")

        for lvl in range(1, 7):
            self.assertEqual(len(curr["children"]), 1, f"Expected 1 child at depth {lvl-1}")
            curr = curr["children"][0]
            self.assertEqual(curr["item_id"], f"item_lvl_{lvl}")
            if lvl < 6:
                self.assertEqual(curr["gift_npcs"], [])
            else:
                self.assertEqual(curr["gift_npcs"], ["Adeline"])
                self.assertEqual(curr["children"], [])

    def test_mutual_circular_recipes_2_cycle(self):
        """Mutual 2-cycle (A -> B -> A) terminates safely and reaches attached gift."""
        # A -> B -> A, and B -> Gift
        recipes = {
            "r_a_to_b": {
                "item_id": "item_b",
                "ingredients": [{"item_id": "item_a", "count": 1}],
            },
            "r_b_to_a": {
                "item_id": "item_a",
                "ingredients": [{"item_id": "item_b", "count": 1}],
            },
            "r_b_to_gift": {
                "item_id": "item_gift",
                "ingredients": [{"item_id": "item_b", "count": 1}],
            },
        }
        remaining = {"item_gift": {"loved": {"March"}}}
        suggestions = [{"item_id": "item_a"}]

        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        self.assertEqual(root["item_id"], "item_a")
        # Should have child item_b
        child_ids = [c["item_id"] for c in root["children"]]
        self.assertIn("item_b", child_ids)
        b_node = next(c for c in root["children"] if c["item_id"] == "item_b")
        # Under B, A is guarded against recursion, and item_gift is present
        b_child_ids = [c["item_id"] for c in b_node["children"]]
        self.assertIn("item_gift", b_child_ids)
        self.assertNotIn("item_a", b_child_ids)

    def test_mutual_circular_recipes_3_cycle(self):
        """3-cycle (A -> B -> C -> A) terminates safely and reaches attached gift."""
        recipes = {
            "r_ab": {"item_id": "item_b", "ingredients": [{"item_id": "item_a"}]},
            "r_bc": {"item_id": "item_c", "ingredients": [{"item_id": "item_b"}]},
            "r_ca": {"item_id": "item_a", "ingredients": [{"item_id": "item_c"}]},
            "r_cg": {"item_id": "item_gift", "ingredients": [{"item_id": "item_c"}]},
        }
        remaining = {"item_gift": {"loved": {"Celine"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "item_a"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        b_node = root["children"][0]
        self.assertEqual(b_node["item_id"], "item_b")
        c_node = b_node["children"][0]
        self.assertEqual(c_node["item_id"], "item_c")
        # C should lead to item_gift, and NOT loop back to A
        c_child_ids = [c["item_id"] for c in c_node["children"]]
        self.assertIn("item_gift", c_child_ids)
        self.assertNotIn("item_a", c_child_ids)

    def test_self_loop_recipe(self):
        """Self-loop (A -> A) terminates safely."""
        recipes = {
            "r_self": {"item_id": "item_a", "ingredients": [{"item_id": "item_a"}]},
            "r_gift": {"item_id": "item_gift", "ingredients": [{"item_id": "item_a"}]},
        }
        remaining = {"item_gift": {"loved": {"Valen"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "item_a"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        self.assertEqual(len(root["children"]), 1)
        self.assertEqual(root["children"][0]["item_id"], "item_gift")

    def test_complex_intertwined_multi_cycles(self):
        """Intertwined cycles (A->B->A, B->C->D->B, C->A) terminate without recursion error."""
        recipes = {
            "r_ab": {"item_id": "b", "ingredients": [{"item_id": "a"}]},
            "r_ba": {"item_id": "a", "ingredients": [{"item_id": "b"}]},
            "r_bc": {"item_id": "c", "ingredients": [{"item_id": "b"}]},
            "r_cd": {"item_id": "d", "ingredients": [{"item_id": "c"}]},
            "r_db": {"item_id": "b", "ingredients": [{"item_id": "d"}]},
            "r_ca": {"item_id": "a", "ingredients": [{"item_id": "c"}]},
            "r_dg": {"item_id": "gift", "ingredients": [{"item_id": "d"}]},
        }
        remaining = {"gift": {"loved": {"Eiland"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "a"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        self.assertEqual(trees[0]["item_id"], "a")

    def test_diamond_dag_dependencies(self):
        """Diamond DAG (Root -> B -> D and Root -> C -> D) preserves both paths."""
        recipes = {
            "r_rb": {"item_id": "b", "ingredients": [{"item_id": "root"}]},
            "r_rc": {"item_id": "c", "ingredients": [{"item_id": "root"}]},
            "r_bd": {"item_id": "d", "ingredients": [{"item_id": "b"}]},
            "r_cd": {"item_id": "d", "ingredients": [{"item_id": "c"}]},
        }
        remaining = {"d": {"loved": {"Balor"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        child_ids = sorted(c["item_id"] for c in root["children"])
        self.assertEqual(child_ids, ["b", "c"])
        # Both b and c must have d as a child
        b_node = next(c for c in root["children"] if c["item_id"] == "b")
        c_node = next(c for c in root["children"] if c["item_id"] == "c")
        self.assertEqual(len(b_node["children"]), 1)
        self.assertEqual(b_node["children"][0]["item_id"], "d")
        self.assertEqual(b_node["children"][0]["gift_npcs"], ["Balor"])
        self.assertEqual(len(c_node["children"]), 1)
        self.assertEqual(c_node["children"][0]["item_id"], "d")
        self.assertEqual(c_node["children"][0]["gift_npcs"], ["Balor"])

    def test_multi_diamond_nested_dag(self):
        """Nested diamond (Root -> B1/B2 -> D1/D2 -> Gift) renders correctly."""
        recipes = {
            "r_rb1": {"item_id": "b1", "ingredients": [{"item_id": "root"}]},
            "r_rb2": {"item_id": "b2", "ingredients": [{"item_id": "root"}]},
            "r_b1_d1": {"item_id": "d1", "ingredients": [{"item_id": "b1"}]},
            "r_b1_d2": {"item_id": "d2", "ingredients": [{"item_id": "b1"}]},
            "r_b2_d1": {"item_id": "d1", "ingredients": [{"item_id": "b2"}]},
            "r_b2_d2": {"item_id": "d2", "ingredients": [{"item_id": "b2"}]},
            "r_d1_g": {"item_id": "gift", "ingredients": [{"item_id": "d1"}]},
            "r_d2_g": {"item_id": "gift", "ingredients": [{"item_id": "d2"}]},
        }
        remaining = {"gift": {"loved": {"Juniper"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        self.assertEqual(len(root["children"]), 2)

    def test_multiple_shared_ingredients(self):
        """Multi-ingredient recipe (Ing1 + Ing2 -> Gift) appears for both blockers."""
        recipes = {
            "r_multi": {
                "item_id": "super_cake",
                "ingredients": [
                    {"item_id": "flour", "count": 2},
                    {"item_id": "sugar", "count": 1},
                    {"item_id": "milk", "count": 1},
                ],
            }
        }
        remaining = {"super_cake": {"loved": {"Darcy"}}}
        for ing in ["flour", "sugar", "milk"]:
            trees = build_focus_crafting_trees(
                focus_suggestions=[{"item_id": ing}],
                recipes=recipes,
                remaining_items_map=remaining,
            )
            self.assertEqual(len(trees), 1, f"Failed for {ing}")
            self.assertEqual(len(trees[0]["children"]), 1, f"Failed for {ing}")
            self.assertEqual(trees[0]["children"][0]["item_id"], "super_cake")
            self.assertEqual(trees[0]["children"][0]["gift_npcs"], ["Darcy"])

    def test_disjoint_and_unneeded_recipes_pruning(self):
        """Recipes not leading to any pending gift are strictly pruned."""
        recipes = {
            # Active branch: root -> used_inter -> gift
            "r_used_1": {"item_id": "used_inter", "ingredients": [{"item_id": "root"}]},
            "r_used_2": {"item_id": "gift", "ingredients": [{"item_id": "used_inter"}]},
            # Dead end from root: root -> dead_end_1 -> dead_end_2
            "r_dead_1": {"item_id": "dead_end_1", "ingredients": [{"item_id": "root"}]},
            "r_dead_2": {"item_id": "dead_end_2", "ingredients": [{"item_id": "dead_end_1"}]},
            # Completely disconnected island: island_1 -> island_2 -> island_gift
            "r_isl_1": {"item_id": "island_2", "ingredients": [{"item_id": "island_1"}]},
            "r_isl_2": {"item_id": "island_gift", "ingredients": [{"item_id": "island_2"}]},
        }
        remaining = {
            "gift": {"loved": {"Hayden"}},
            "island_gift": {"loved": {"Reina"}},
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=recipes,
            remaining_items_map=remaining,
        )
        self.assertEqual(len(trees), 1)
        root = trees[0]
        # Only used_inter should be in root.children
        child_ids = [c["item_id"] for c in root["children"]]
        self.assertEqual(child_ids, ["used_inter"])
        self.assertNotIn("dead_end_1", child_ids)
        self.assertNotIn("island_2", child_ids)

    def test_empty_remaining_items_map(self):
        """When no gifts are pending, trees return blocker roots with empty children."""
        recipes = {
            "r_1": {"item_id": "prod1", "ingredients": [{"item_id": "root"}]},
            "r_2": {"item_id": "prod2", "ingredients": [{"item_id": "prod1"}]},
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=recipes,
            remaining_items_map={},
        )
        self.assertEqual(len(trees), 1)
        self.assertEqual(trees[0]["children"], [])
        self.assertEqual(trees[0]["gift_npcs"], [])

    def test_large_synthetic_workload_performance(self):
        """100 suggestions against 1,000+ recipes executes in < 2.0s without memory blowup."""
        # Generate 1,000 recipes across 10 levels
        recipes = {}
        for lvl in range(1, 11):
            for idx in range(100):
                rid = f"recipe_l{lvl}_{idx}"
                prod_id = f"item_l{lvl}_{idx}"
                # Parent ingredients from previous level
                prev_idx_1 = idx
                prev_idx_2 = (idx + 1) % 100
                if lvl == 1:
                    ing1 = f"root_{prev_idx_1}"
                    ing2 = f"root_{prev_idx_2}"
                else:
                    ing1 = f"item_l{lvl-1}_{prev_idx_1}"
                    ing2 = f"item_l{lvl-1}_{prev_idx_2}"
                recipes[rid] = {
                    "item_id": prod_id,
                    "display_name": f"Product L{lvl} #{idx}",
                    "ingredients": [
                        {"item_id": ing1, "count": 1},
                        {"item_id": ing2, "count": 2},
                    ],
                }

        # 100 focus suggestions (all root items)
        suggestions = [{"item_id": f"root_{i}", "item_name": f"Root {i}"} for i in range(100)]

        # 20 pending gifts at top levels
        remaining = {
            f"item_l10_{i}": {"loved": {f"NPC_{i}"}} for i in range(0, 100, 5)
        }

        t0 = time.perf_counter()
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=remaining,
        )
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(trees), 100)
        self.assertLess(
            elapsed, 2.0, f"Performance bottleneck: took {elapsed:.3f}s for 100 suggestions & 1000 recipes"
        )

    def test_deep_recipe_chain_10_levels(self):
        """Deep linear recipe chain (Level 0 to Level 10) traces correctly."""
        recipes = {
            f"r_{i}": {
                "item_id": f"lvl_{i+1}",
                "display_name": f"Level {i+1} Item",
                "ingredients": [{"item_id": f"lvl_{i}", "count": 1}],
            }
            for i in range(10)
        }
        remaining_items_map = {"lvl_10": {"loved": {"Adeline"}}}
        suggestions = [{"item_id": "lvl_0", "item_name": "Root 0"}]

        trees = build_focus_crafting_trees(suggestions, recipes, remaining_items_map)
        self.assertEqual(len(trees), 1)
        curr = trees[0]
        for lvl in range(1, 11):
            self.assertEqual(len(curr["children"]), 1, f"Missing child at lvl {lvl}")
            curr = curr["children"][0]
            self.assertEqual(curr["item_id"], f"lvl_{lvl}")
        self.assertEqual(curr["gift_npcs"], ["Adeline"])

    def test_butterfly_dual_root_shared_intermediate(self):
        """Butterfly DAG: Root1 & Root2 both craft into Inter, which crafts into Gift1 & Gift2."""
        recipes = {
            "r_r1_inter": {"item_id": "inter", "ingredients": [{"item_id": "root1"}]},
            "r_r2_inter": {"item_id": "inter", "ingredients": [{"item_id": "root2"}]},
            "r_inter_g1": {"item_id": "gift1", "ingredients": [{"item_id": "inter"}]},
            "r_inter_g2": {"item_id": "gift2", "ingredients": [{"item_id": "inter"}]},
        }
        remaining = {
            "gift1": {"loved": {"Balor"}},
            "gift2": {"liked": {"Celine"}},
        }
        suggestions = [{"item_id": "root1"}, {"item_id": "root2"}]
        trees = build_focus_crafting_trees(suggestions, recipes, remaining)
        self.assertEqual(len(trees), 2)
        for t in trees:
            self.assertEqual(len(t["children"]), 1)
            inter = t["children"][0]
            self.assertEqual(inter["item_id"], "inter")
            inter_child_ids = sorted(c["item_id"] for c in inter["children"])
            self.assertEqual(inter_child_ids, ["gift1", "gift2"])

    def test_sibling_pruning_active_dead_and_cyclic(self):
        """Root has 3 branches: (1) leads to Gift, (2) leads to dead end, (3) loops without Gift."""
        recipes = {
            # Branch 1 (Active -> leads to Gift)
            "r_b1": {"item_id": "active_inter", "ingredients": [{"item_id": "root"}]},
            "r_b1_gift": {"item_id": "gift_item", "ingredients": [{"item_id": "active_inter"}]},
            # Branch 2 (Dead end)
            "r_b2": {"item_id": "dead_inter", "ingredients": [{"item_id": "root"}]},
            "r_b2_dead": {"item_id": "dead_leaf", "ingredients": [{"item_id": "dead_inter"}]},
            # Branch 3 (Cycle: c1 -> c2 -> c1, no gift)
            "r_b3": {"item_id": "cycle1", "ingredients": [{"item_id": "root"}]},
            "r_b3_loop": {"item_id": "cycle2", "ingredients": [{"item_id": "cycle1"}]},
            "r_b3_back": {"item_id": "cycle1", "ingredients": [{"item_id": "cycle2"}]},
        }
        remaining = {"gift_item": {"loved": {"Hayden"}}}
        suggestions = [{"item_id": "root"}]

        trees = build_focus_crafting_trees(suggestions, recipes, remaining)
        self.assertEqual(len(trees), 1)
        root = trees[0]
        # Only active_inter should survive pruning
        child_ids = [c["item_id"] for c in root["children"]]
        self.assertEqual(child_ids, ["active_inter"])
        self.assertEqual(len(root["children"][0]["children"]), 1)
        self.assertEqual(root["children"][0]["children"][0]["item_id"], "gift_item")

    def test_alias_bidirectional_tree_expansion(self):
        """Blocker 'cow_milk' resolves recipes registered under 'milk', and vice versa."""
        recipes = {
            "r_cheese": {"item_id": "cheese", "ingredients": [{"item_id": "milk"}]},
            "r_butter": {"item_id": "butter", "ingredients": [{"item_id": "cow_milk"}]},
        }
        remaining = {
            "cheese": {"loved": {"Darcy"}},
            "butter": {"loved": {"March"}},
        }
        # Query with cow_milk
        trees_cow = build_focus_crafting_trees([{"item_id": "cow_milk"}], recipes, remaining)
        self.assertEqual(len(trees_cow), 1)
        child_ids_cow = sorted(c["item_id"] for c in trees_cow[0]["children"])
        self.assertEqual(child_ids_cow, ["butter", "cheese"])

        # Query with milk
        trees_milk = build_focus_crafting_trees([{"item_id": "milk"}], recipes, remaining)
        self.assertEqual(len(trees_milk), 1)
        child_ids_milk = sorted(c["item_id"] for c in trees_milk[0]["children"])
        self.assertEqual(child_ids_milk, ["butter", "cheese"])

    def test_malformed_inputs_robustness(self):
        """Malformed, None, or abnormal inputs do not crash build_focus_crafting_trees."""
        # 1. Malformed focus suggestions
        bad_suggestions = [
            None,
            {},
            {"item_id": ""},
            {"item_id": "   "},
            {"item_id": None},
            {"item_id": 12345},
            "not a dict",
            ["list"],
        ]
        trees = build_focus_crafting_trees(focus_suggestions=bad_suggestions)
        # Should gracefully handle or skip invalid entries
        self.assertIsInstance(trees, list)

        # 2. Malformed recipes dict
        bad_recipes = {
            "r_none": None,
            "r_str": "a string",
            "r_empty": {},
            "r_no_ings": {"item_id": "test"},
            "r_bad_ings_type": {"item_id": "test", "ingredients": "not a list"},
            "r_bad_ings_content": {
                "item_id": "test",
                "ingredients": [None, 123, "foo", {}, {"item_id": None}],
            },
            "r_valid": {
                "item_id": "gift",
                "ingredients": [{"item_id": "root", "count": 1}],
            },
        }
        trees2 = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=bad_recipes,
            remaining_items_map={"gift": {"loved": {"Adeline"}}},
        )
        self.assertEqual(len(trees2), 1)
        self.assertEqual(trees2[0]["children"][0]["item_id"], "gift")

        # 3. Malformed remaining_items_map
        bad_remaining = {
            "gift1": None,
            "gift2": "not a dict or set",
            "gift3": {"loved": "string_not_set", "liked": None},
            "gift4": {"loved": [None, "", "adeline"]},
            "gift5": {"loved": {"march"}},
        }
        recipes_valid = {
            f"r_{i}": {"item_id": f"gift{i}", "ingredients": [{"item_id": "root"}]}
            for i in range(1, 6)
        }
        trees3 = build_focus_crafting_trees(
            focus_suggestions=[{"item_id": "root"}],
            recipes=recipes_valid,
            remaining_items_map=bad_remaining,
            npc_names={"march": "March", "adeline": "Adeline"},
        )
        self.assertEqual(len(trees3), 1)
        # Verify gift5 formatted properly
        g5 = next((c for c in trees3[0]["children"] if c["item_id"] == "gift5"), None)
        self.assertIsNotNone(g5)
        self.assertEqual(g5["gift_npcs"], ["March"])


if __name__ == "__main__":
    unittest.main()
