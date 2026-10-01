"""
tests/test_challenger_r3_invariants.py

Empirical Challenger Test Suite for Round 3:
1. Invariance of bag_plan and target_npcs between plan_daily_gift_bag and plan_max_relationship
   under focus_mode_enabled (True vs False) across all NPCs, subsets, and modes.
2. Focus mode filtering correctness: verify no items outside selected NPCs' loved/liked/crafted
   sets appear in focus suggestions, and blocked_npcs are strictly subsets of selected NPCs.
3. Source Priority Summary edge cases: empty inventory, zero shortages, multi-source items,
   unmapped locations, complex compound location strings with nested slashes and parentheses,
   tier classification, scoring sums, and JSON serialization.
"""

import itertools
import json
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from companion.json_exporter import plan_to_json
from fom_planner.crafting import load_recipes
from fom_planner.data_loader import (
    load_alt_sources,
    load_item_locations,
    load_item_metadata,
    load_npc_preferences_from_json,
)
from fom_planner.models import SaveData
from fom_planner.optimizer import (
    _split_compound_locations,
    classify_source_tier,
    compute_focus_suggestions,
    compute_source_priorities,
    filter_remaining_items_for_focus,
    normalize_source_name,
    plan_daily_gift_bag,
    plan_max_relationship,
    resolve_root_raw_materials,
)
from fom_planner.parser import parse_save_file


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sample_save(repo_root: Path) -> SaveData:
    save_path = repo_root / "samples" / "sample_save.sav"
    return parse_save_file(save_path)


@pytest.fixture(scope="module")
def game_data(repo_root: Path) -> Dict[str, Any]:
    item_data_path = repo_root / "data" / "item_data.json"
    fiddle_path = repo_root / "data" / "npc_gift_preferences.json"
    npcs_def, _ = load_npc_preferences_from_json(item_data_path)
    metadata = load_item_metadata(fiddle_path, item_data_path, None)
    locations = load_item_locations()
    recipes = load_recipes()
    alt_sources = load_alt_sources()
    return {
        "npc_gift_definitions": npcs_def,
        "item_metadata": metadata,
        "item_locations": locations,
        "recipes": recipes,
        "alt_sources": alt_sources,
    }


# ============================================================================
# Area 1: Bag Plan Invariance Stress Testing
# ============================================================================

class TestBagPlanInvariance:
    """
    Rigorously verifies that bag_plan and target_npcs are 100% bit-for-bit identical
    regardless of whether focus_mode_enabled is True or False, and regardless of
    which NPCs are selected.
    """

    def test_daily_gift_bag_invariance_all_34_single_npcs(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Test every single NPC in isolation for plan_daily_gift_bag."""
        baseline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
            focus_npcs=None,
        )

        all_npcs = list(game_data["npc_gift_definitions"].keys())
        assert len(all_npcs) >= 34

        for npc in all_npcs:
            focused = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                focus_mode_enabled=True,
                focus_npcs=npc,
            )
            # Invariant: bag_plan is identical
            assert focused["bag_plan"] == baseline["bag_plan"], f"bag_plan diverged for focus NPC: {npc}"
            # Invariant: target_npcs is identical
            assert focused["target_npcs"] == baseline["target_npcs"], f"target_npcs diverged for focus NPC: {npc}"
            # Invariant: covered_npcs is identical
            assert focused["covered_npcs"] == baseline["covered_npcs"], f"covered_npcs diverged for focus NPC: {npc}"
            # Invariant: slots_used is identical
            assert focused["overall_stats"]["slots_used"] == baseline["overall_stats"]["slots_used"]

    def test_max_relationship_invariance_all_34_single_npcs(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Test every single NPC in isolation for plan_max_relationship."""
        baseline = plan_max_relationship(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
            focus_npcs=None,
        )

        all_npcs = list(game_data["npc_gift_definitions"].keys())
        assert len(all_npcs) >= 34

        for npc in all_npcs:
            focused = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                focus_mode_enabled=True,
                focus_npcs=npc,
            )
            assert focused["bag_plan"] == baseline["bag_plan"], f"bag_plan diverged in max-rel for focus NPC: {npc}"
            assert focused["target_npcs"] == baseline["target_npcs"], f"target_npcs diverged in max-rel for focus NPC: {npc}"
            assert focused["covered_npcs"] == baseline["covered_npcs"], f"covered_npcs diverged in max-rel for focus NPC: {npc}"
            assert (
                focused["overall_stats"]["total_relationship_points"]
                == baseline["overall_stats"]["total_relationship_points"]
            )

    @pytest.mark.parametrize("mode", ["auto", "saturday", "market-only", "townsfolk", "all"])
    def test_invariance_across_all_planning_modes(
        self, sample_save: SaveData, game_data: Dict[str, Any], mode: str
    ):
        """Verify invariance holds across every planning mode."""
        test_npc_subsets = [
            "adeline,march,balor",
            ["celine", "hayden", "valen", "terithia"],
            {"darcy", "hector", "landen"},
            "nonexistent_npc_xyz",
            "",
        ]

        for npc_subset in test_npc_subsets:
            # Test plan_daily_gift_bag
            base_daily = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                mode=mode,
                focus_mode_enabled=False,
            )
            focus_daily = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                mode=mode,
                focus_mode_enabled=True,
                focus_npcs=npc_subset,
            )
            assert focus_daily["bag_plan"] == base_daily["bag_plan"]
            assert focus_daily["target_npcs"] == base_daily["target_npcs"]

            # Test plan_max_relationship
            base_max = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                mode=mode,
                focus_mode_enabled=False,
            )
            focus_max = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                mode=mode,
                focus_mode_enabled=True,
                focus_npcs=npc_subset,
            )
            assert focus_max["bag_plan"] == base_max["bag_plan"]
            assert focus_max["target_npcs"] == base_max["target_npcs"]

    def test_invariance_with_extreme_inventory_states(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Verify invariance under empty inventory and huge inventory."""
        empty_inv: Dict[str, int] = {}
        huge_inv = {item: 500 for item in ["apple", "milk", "cheese", "turnip", "egg", "bread"]}

        for test_inv in [empty_inv, huge_inv]:
            base_daily = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                inventory=test_inv,
                focus_mode_enabled=False,
            )
            focus_daily = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                inventory=test_inv,
                focus_mode_enabled=True,
                focus_npcs=["march", "celine"],
            )
            assert focus_daily["bag_plan"] == base_daily["bag_plan"]
            assert focus_daily["target_npcs"] == base_daily["target_npcs"]

            base_max = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                inventory=test_inv,
                focus_mode_enabled=False,
            )
            focus_max = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                inventory=test_inv,
                focus_mode_enabled=True,
                focus_npcs=["march", "celine"],
            )
            assert focus_max["bag_plan"] == base_max["bag_plan"]
            assert focus_max["target_npcs"] == base_max["target_npcs"]


# ============================================================================
# Area 2: Focus Mode Filtering Invariants Stress Testing
# ============================================================================

class TestFocusModeFilteringInvariants:
    """
    Rigorously tests that NO items outside selected NPCs' loved/liked sets
    (directly or through recipe trees) ever appear in focus suggestions.
    """

    def _get_allowed_root_materials_for_npcs(
        self,
        target_npcs: Set[str],
        npc_definitions: Dict[str, dict],
        recipes: Dict[str, Any],
    ) -> Set[str]:
        """Compute the ground-truth theoretical universe of allowed items for target_npcs."""
        allowed_items: Set[str] = set()
        for nid in target_npcs:
            g_def = npc_definitions.get(nid, {})
            loved = g_def.get("loved", []) or []
            liked = g_def.get("liked", []) or []
            for item in itertools.chain(loved, liked):
                item_clean = str(item).strip().lower()
                if not item_clean:
                    continue
                allowed_items.add(item_clean)
                if recipes and item_clean in recipes:
                    raws = resolve_root_raw_materials(item_clean, recipes)
                    allowed_items.update(raws.keys())
        return allowed_items

    @pytest.mark.parametrize(
        "focus_group",
        [
            {"adeline"},
            {"march", "balor"},
            {"celine", "hayden", "terithia"},
            {"valen", "juniper", "reina", "eroll"},
            {"darcy", "landen"},  # vendors
        ],
    )
    def test_strict_isolation_invariant(
        self,
        sample_save: SaveData,
        game_data: Dict[str, Any],
        focus_group: Set[str],
    ):
        """
        Verify that EVERY item in focus_suggestions belongs to the allowed universe
        of the selected NPCs, and all blocked_npcs are strictly a subset of focus_group.
        """
        allowed_universe = self._get_allowed_root_materials_for_npcs(
            target_npcs=focus_group,
            npc_definitions=game_data["npc_gift_definitions"],
            recipes=game_data["recipes"],
        )

        plan = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs=focus_group,
            focus_top_n=100,
        )

        suggestions = plan["focus_suggestions"]
        assert len(suggestions) > 0, f"Expected suggestions for group {focus_group}"

        for s in suggestions:
            item_id = s["item_id"]
            # Invariant 1: item must be in allowed root materials or direct gift
            assert item_id in allowed_universe, (
                f"LEAKED ITEM: '{item_id}' appeared in focus suggestions for {focus_group}, "
                f"but is NOT loved/liked or in crafting chain for any selected NPC!"
            )

            # Invariant 2: blocked_npcs must be a non-empty subset of the focus group
            blocked_npcs = {str(x).strip().lower() for x in s.get("blocked_npcs", [])}
            assert len(blocked_npcs) > 0, f"Item '{item_id}' has empty blocked_npcs!"
            assert blocked_npcs.issubset(focus_group), (
                f"LEAKED NPC: blocked_npcs {blocked_npcs} contains NPCs outside focus group {focus_group} "
                f"for item '{item_id}'!"
            )

            # Invariant 3: deficit and blocked_pairs must be strictly positive
            assert s["deficit"] > 0
            assert s["blocked_pairs"] > 0

    def test_focus_mode_with_unknown_or_whitespace_npcs(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Edge cases: non-existent NPCs, whitespace strings, mixed types."""
        # Non-existent NPC
        plan_nonexistent = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs="zelda,link,ganon",
        )
        assert plan_nonexistent["focus_suggestions"] == []
        assert plan_nonexistent["source_priority"] == []
        assert plan_nonexistent["focus_trees"] == []

        # Whitespace-only string falls back to all items (empty filter)
        plan_whitespace = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs="   ",
        )
        plan_baseline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
        )
        assert len(plan_whitespace["focus_suggestions"]) == len(plan_baseline["focus_suggestions"])

    def test_crafting_tree_npcs_consistent_with_focus_mode(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Verify leaf gift_npcs in focus_trees do not contain unselected NPCs when focus mode is active."""
        focus_npcs = {"adeline", "celine"}
        plan = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs=focus_npcs,
        )

        focus_names = {"adeline", "celine"}

        def _verify_tree_nodes(node: Dict[str, Any]):
            for recipient in node.get("gift_npcs", []):
                assert str(recipient).strip().lower() in focus_names, (
                    f"Leaked NPC '{recipient}' in focus crafting tree leaf node '{node.get('item_name')}'!"
                )
            for child in node.get("children", []):
                _verify_tree_nodes(child)

        for tree in plan["focus_trees"]:
            _verify_tree_nodes(tree)


# ============================================================================
# Area 3: Source Priority Summary Edge Cases Stress Testing
# ============================================================================

class TestSourcePrioritySummaryEdgeCases:
    """
    Rigorously stress-tests source grouping, tier classification, compound
    location parsing, multi-source items, unmapped items, and zero shortages.
    """

    def test_empty_focus_suggestions(self):
        """Empty focus suggestions must gracefully return empty list."""
        assert compute_source_priorities([]) == []
        assert compute_source_priorities([], item_locations={}, alt_sources={}) == []
        assert compute_source_priorities(None) == []  # type: ignore

    def test_zero_shortages_infinite_inventory(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """When player has huge inventory, deficit is zero, so source priority is empty."""
        huge_inv = {item: 9999 for item in game_data["item_metadata"].keys()}
        plan = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            inventory=huge_inv,
        )
        assert plan["focus_suggestions"] == []
        assert plan["source_priority"] == []

    def test_tier_ordering_and_score_descending_invariant(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """
        Verify that compute_source_priorities strictly maintains:
        1. Quick tier items come before Grind tier items, Grind before Farm.
        2. Within each tier, total_score is monotonically non-increasing.
        3. For each source, total_score equals the exact sum of item blocked_pairs.
        """
        plan = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_top_n=50,
        )

        sources = plan["source_priority"]
        assert len(sources) > 0

        tier_weights = {"Quick": 0, "Grind": 1, "Farm": 2}
        seen_tiers = []

        current_tier = None
        prev_score = float("inf")

        for s in sources:
            tier = s["tier"]
            score = s["total_score"]
            assert tier in tier_weights, f"Invalid tier '{tier}'"

            # Check tier sequence
            if tier != current_tier:
                if current_tier is not None:
                    assert tier_weights[tier] > tier_weights[current_tier], (
                        f"Tier ordering violated: {tier} appeared after {current_tier}"
                    )
                current_tier = tier
                prev_score = float("inf")

            # Check descending score within tier
            assert score <= prev_score, (
                f"Score ordering violated within tier {tier}: {score} > {prev_score} ({s['source_name']})"
            )
            prev_score = score

            # Check score sum equality
            expected_score = sum(it["blocked_pairs"] for it in s["items"])
            assert score == expected_score, (
                f"Score mismatch for {s['source_name']}: expected {expected_score}, got {score}"
            )

            # Check item sorting within source: blocked_pairs desc, deficit desc, name asc
            items = s["items"]
            for i in range(len(items) - 1):
                it1, it2 = items[i], items[i + 1]
                assert (it1["blocked_pairs"], it1["deficit"]) >= (it2["blocked_pairs"], it2["deficit"])

    def test_multi_source_items_appear_in_all_sources(self):
        """
        Verify that an item with both primary and alternate sources appears
        in each respective source group.
        """
        focus_suggestions = [
            {
                "item_id": "test_crop",
                "item_name": "Test Crop",
                "deficit": 5,
                "blocked_pairs": 12,
                "blocked_npcs": ["adeline", "balor"],
            }
        ]
        # Primary location has 2 locations via compound string
        item_locations = {
            "test_crop": "General Store / The Upper Mines (Floors 1-19)",
        }
        # Alt sources has 2 additional sources
        alt_sources = {
            "test_crop": [
                {"type": "chicken_statue", "note": "100 beads"},
                {"type": "shop", "vendor": "Balor's Wagon"},
            ]
        }
        npc_names = {"adeline": "Adeline", "balor": "Balor"}

        result = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources=alt_sources,
            npc_names=npc_names,
        )

        source_names = {s["source_name"] for s in result}
        assert "General Store" in source_names
        assert "Upper Mines (Floors 1-19)" in source_names
        assert "Chicken Statue" in source_names
        assert "Balor's Wagon" in source_names

        # Each source should have test_crop with 12 blocked_pairs and deficit 5
        for s in result:
            assert s["total_score"] == 12
            assert len(s["items"]) == 1
            assert s["items"][0]["item_id"] == "test_crop"
            assert s["items"][0]["deficit"] == 5
            assert s["items"][0]["blocked_pairs"] == 12
            assert s["benefited_npcs"] == ["Adeline", "Balor"]

    def test_unmapped_location_fallback(self):
        """Verify items with no location in primary or alt_sources fallback to 'Other / Unknown'."""
        focus_suggestions = [
            {
                "item_id": "mystery_item_123",
                "item_name": "Mystery Item",
                "deficit": 3,
                "blocked_pairs": 7,
                "blocked_npcs": ["celine"],
            }
        ]
        result = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations={},
            alt_sources={},
            npc_names={"celine": "Celine"},
        )
        assert len(result) == 1
        entry = result[0]
        assert entry["source_name"] == "Other / Unknown"
        assert entry["tier"] == "Grind"
        assert entry["total_score"] == 7
        assert entry["items"][0]["item_id"] == "mystery_item_123"
        assert entry["benefited_npcs"] == ["Celine"]

    def test_compound_location_parenthesis_and_nested_slashes(self):
        """
        Stress test _split_compound_locations with complex parentheses and slashes.
        """
        # Slashes inside parens preserved
        assert _split_compound_locations("Fishing (River, Spring / Fall)") == [
            "Fishing (River, Spring / Fall)"
        ]

        # Outer slashes split, inner preserved
        assert _split_compound_locations(
            "Fishing (River, Spring / Fall) / General Store / The Mill (Wheat / Corn)"
        ) == [
            "Fishing (River, Spring / Fall)",
            "General Store",
            "The Mill (Wheat / Corn)",
        ]

        # Nested parentheses
        assert _split_compound_locations(
            "Mines (Floor 1-20 (Upper / Lower)) / Farm (Spring)"
        ) == [
            "Mines (Floor 1-20 (Upper / Lower))",
            "Farm (Spring)",
        ]

        # Unmatched open parenthesis (does not split inside unclosed paren)
        res = _split_compound_locations("Mines (Level 1 / 2")
        assert len(res) == 1

        # Unmatched closing parenthesis (recovers without negative depth)
        res = _split_compound_locations("Mines ) / Store")
        assert res == ["Mines )", "Store"]

        # Multiple slashes
        assert _split_compound_locations("A / B / C") == ["A", "B", "C"]
        # In 'A / / B', ' / ' is at index 1..3, remainder is '/ B' (matching standard split(' / '))
        assert _split_compound_locations("A / / B") == ["A", "/ B"]

        # Edge cases: empty string, whitespace, non-strings
        assert _split_compound_locations("") == []
        assert _split_compound_locations("   ") == []
        assert _split_compound_locations(None) == []  # type: ignore

    def test_normalize_source_name_rules(self):
        """Verify normalization of mine biomes, mills, and shops."""
        # Biomes with 'The ' stripped
        assert normalize_source_name("The Upper Mines (Floors 1-19)") == "Upper Mines (Floors 1-19)"
        assert normalize_source_name("Upper Mines (Floors 1-19)") == "Upper Mines (Floors 1-19)"
        assert normalize_source_name("The Tide Caverns (Floors 21-39)") == "Tide Caverns (Floors 21-39)"
        assert normalize_source_name("The Deep Earth (Floors 41-59)") == "Deep Earth (Floors 41-59)"
        assert normalize_source_name("The Lava Caves (Floors 61-79)") == "Lava Caves (Floors 61-79)"
        assert normalize_source_name("The Ancient Ruins (Floors 81-99)") == "Ancient Ruins (Floors 81-99)"

        # Mill variations
        assert normalize_source_name("The Mill (Wheat)") == "The Mill"
        assert normalize_source_name("Mill (Corn)") == "The Mill"
        assert normalize_source_name("mill") == "The Mill"

        # Hayden Shop
        assert normalize_source_name("Hayden's Shop") == "Hayden's Ranch Shop"
        assert normalize_source_name("Hayden's Ranch") == "Hayden's Ranch Shop"

        # Smelter and Forge
        assert normalize_source_name("Blacksmith Smelter (Iron Ore)") == "Blacksmith Smelter"
        assert normalize_source_name("The Dragon Forge (Steel)") == "The Dragon Forge"

    def test_classify_source_tier_all_types_and_keywords(self):
        """Stress test tier classification across all 12 alt_source types and primary keywords."""
        quick_types = [
            "shop", "inn", "market_stall", "festival", "mill",
            "quest", "museum", "date", "chicken_statue", "wishing_well"
        ]
        for st in quick_types:
            assert classify_source_tier("Any Source", source_type=st) == "Quick"

        grind_types = ["mimic", "fishing"]
        for st in grind_types:
            assert classify_source_tier("Any Source", source_type=st) == "Grind"

        farm_types = ["living_off_the_land"]
        for st in farm_types:
            assert classify_source_tier("Any Source", source_type=st) == "Farm"

        # Primary location keyword checks
        assert classify_source_tier("General Store") == "Quick"
        assert classify_source_tier("Balor's Wagon") == "Quick"
        assert classify_source_tier("The Mill") == "Quick"
        assert classify_source_tier("Blacksmith Smelter") == "Quick"
        assert classify_source_tier("Sleeping Dragon Inn") == "Quick"
        assert classify_source_tier("Catching (The Narrows)") == "Quick"

        assert classify_source_tier("Upper Mines (Floors 1-19)") == "Grind"
        assert classify_source_tier("Tide Caverns (Floors 21-39)") == "Grind"
        assert classify_source_tier("Foraging (Spring - Eastern Road)") == "Grind"
        assert classify_source_tier("Digging") == "Grind"
        assert classify_source_tier("Diving") == "Grind"

        assert classify_source_tier("Farm (Spring Crop)") == "Farm"
        assert classify_source_tier("Ranch (Cows)") == "Farm"
        assert classify_source_tier("Orchard (Fall Fruit Tree)") == "Farm"

    def test_json_exporter_plan_to_json_source_priority(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """Verify plan_to_json preserves source_priority and adds sprite_url."""
        from companion.config import CompanionConfig

        config = CompanionConfig(
            focus_mode_enabled=True,
            focus_npcs="adeline,balor",
        )
        plan = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs="adeline,balor",
        )

        json_payload = plan_to_json(
            save=sample_save,
            plan_results=plan,
            metadata=game_data["item_metadata"],
            save_path=None,
            config=config,
        )
        assert "source_priority" in json_payload
        assert isinstance(json_payload["source_priority"], list)

        if json_payload["source_priority"]:
            first_source = json_payload["source_priority"][0]
            assert "source_name" in first_source
            assert "tier" in first_source
            assert "total_score" in first_source
            assert "items" in first_source
            assert "benefited_npcs" in first_source

            for item in first_source["items"]:
                assert "item_id" in item
                assert "item_name" in item
                assert "deficit" in item
                assert "blocked_pairs" in item
                assert "sprite_url" in item
                assert item["sprite_url"].startswith("/assets/sprites/items/")

        # Test JSON serializability
        serialized = json.dumps(json_payload)
        assert len(serialized) > 0


# ============================================================================
# Area 4: Advanced Adversarial Edge Cases & Fuzzing
# ============================================================================

class TestAdversarialStressCases:
    """
    Hostile environment stress testing:
    - Same-source deduplication (item matching primary and alt sources for same vendor)
    - Tree item aliases resolution
    - Random NPC subset fuzzing
    - Complex compound location string fuzzing
    """

    def test_same_source_deduplication(self):
        """
        If an item matches the same source via both primary and alternate sources,
        it must NOT be duplicated in that source's item list, and its score must NOT be double-counted.
        """
        focus_suggestions = [
            {
                "item_id": "hay",
                "item_name": "Hay",
                "deficit": 10,
                "blocked_pairs": 5,
                "blocked_npcs": ["hayden"],
            }
        ]
        # Primary location maps to Hayden's Shop
        item_locations = {"hay": "Hayden's Shop / Cutting Grass"}
        # Alt sources also maps to Hayden's Ranch Shop
        alt_sources = {
            "hay": [
                {"type": "shop", "vendor": "Hayden's Ranch Shop", "cost": 50},
                {"type": "shop", "vendor": "Hayden's Shop", "cost": 50},
            ]
        }
        npc_names = {"hayden": "Hayden"}

        result = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources=alt_sources,
            npc_names=npc_names,
        )

        hayden_entries = [s for s in result if s["source_name"] == "Hayden's Ranch Shop"]
        assert len(hayden_entries) == 1, "Hayden's Ranch Shop must only appear once"
        hayden_source = hayden_entries[0]

        # Item must appear only once under this source
        assert len(hayden_source["items"]) == 1
        assert hayden_source["items"][0]["item_id"] == "hay"
        # Total score must be exactly 5, NOT 10 or 15
        assert hayden_source["total_score"] == 5
        assert hayden_source["benefited_npcs"] == ["Hayden"]

    def test_tree_item_aliases_resolution(self):
        """
        Verify that items with aliases like 'cow_milk' / 'milk' correctly resolve
        locations and alt_sources regardless of which alias is in focus_suggestions.
        """
        # Suggestion using 'cow_milk' (alias for 'milk')
        focus_suggestions = [
            {
                "item_id": "cow_milk",
                "item_name": "Cow Milk",
                "deficit": 2,
                "blocked_pairs": 4,
                "blocked_npcs": ["adeline"],
            }
        ]
        # Location only has 'milk', alt_sources only has 'milk'
        item_locations = {"milk": "Ranch (Cows)"}
        alt_sources = {
            "milk": [{"type": "shop", "vendor": "Balor's Wagon"}]
        }
        result = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources=alt_sources,
            npc_names={"adeline": "Adeline"},
        )

        source_names = {s["source_name"] for s in result}
        assert "Balor's Wagon" in source_names
        assert "Ranch (Cows)" in source_names

    def test_random_npc_subsets_fuzzing(
        self, sample_save: SaveData, game_data: Dict[str, Any]
    ):
        """
        Fuzz test 15 randomly chosen NPC subsets of varying sizes.
        For each, verify:
        - bag_plan and target_npcs bit-for-bit invariance for both planners
        - All focus suggestion blocked_npcs are strictly subsets of selected NPCs
        - All source priority benefited_npcs are strictly subsets of selected NPCs
        """
        import random
        rng = random.Random(42)

        all_npcs = sorted(list(game_data["npc_gift_definitions"].keys()))
        npc_display_names = {
            nid: game_data["npc_gift_definitions"][nid].get("name", nid.capitalize())
            for nid in all_npcs
        }

        base_daily = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
        )
        base_max = plan_max_relationship(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
        )

        for _ in range(15):
            k = rng.randint(1, 10)
            subset = rng.sample(all_npcs, k)
            selected_set = set(subset)
            expected_display_names = {npc_display_names[n] for n in selected_set}

            # Daily planner test
            focus_daily = plan_daily_gift_bag(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                focus_mode_enabled=True,
                focus_npcs=subset,
            )
            assert focus_daily["bag_plan"] == base_daily["bag_plan"]
            assert focus_daily["target_npcs"] == base_daily["target_npcs"]

            for s in focus_daily["focus_suggestions"]:
                blocked = set(s.get("blocked_npcs", []))
                assert blocked.issubset(selected_set)

            for src in focus_daily["source_priority"]:
                for b_npc in src.get("benefited_npcs", []):
                    assert b_npc in expected_display_names

            # Max relationship planner test
            focus_max = plan_max_relationship(
                save=sample_save,
                npc_gift_definitions=game_data["npc_gift_definitions"],
                item_metadata=game_data["item_metadata"],
                item_locations=game_data["item_locations"],
                focus_mode_enabled=True,
                focus_npcs=subset,
            )
            assert focus_max["bag_plan"] == base_max["bag_plan"]
            assert focus_max["target_npcs"] == base_max["target_npcs"]

    def test_extreme_compound_location_strings(self):
        """Test edge cases with nested parentheses, slashes, and spaces."""
        s = "Balor's Wagon (Mon / Wed / Fri) / Hayden's Ranch (Summer / Fall) / The Mill (Wheat)"
        parts = _split_compound_locations(s)
        assert parts == [
            "Balor's Wagon (Mon / Wed / Fri)",
            "Hayden's Ranch (Summer / Fall)",
            "The Mill (Wheat)",
        ]

        normalized = [normalize_source_name(p) for p in parts]
        assert normalized == [
            "Balor's Wagon (Mon / Wed / Fri)",
            "Hayden's Ranch Shop",
            "The Mill",
        ]

        tiers = [classify_source_tier(n) for n in normalized]
        assert tiers == ["Quick", "Quick", "Quick"]

        # Degenerate delimiters do not crash
        res = _split_compound_locations(" / / / ")
        assert isinstance(res, list)
        assert _split_compound_locations("///") == ["///"]

