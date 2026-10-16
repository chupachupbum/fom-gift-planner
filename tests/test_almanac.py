"""
tests/test_almanac.py

Comprehensive Automated Unit and Integration Test Suite for the Almanac Planner Engine:
1. Category Progress & Furniture Swatch Grouping (12 categories, "one_per_recipe" vs "all_swatches").
2. Synthetic Save Parsing & Acquisition State (SaveData.get_acquired_items, defensive unions).
3. Gift Bag Material Reservation (reserve_gifts toggle, synergy badges).
4. Ready-to-Craft Greedy Batch Queue with Intermediate Chaining (wheat -> flour -> bread -> sandwich).
5. Recursive Raw Material Breakdown & Blocker Trees (DAG decomposition, combined deficits, D3 tree modal format).
6. Unified Acquisition Source Priority & Seasonal Filtering (Quick/Grind/Farm tiers, season filter).
"""

import json
from pathlib import Path
import pytest

from fom_planner.data_loader import load_almanac_data
from fom_planner.almanac import plan_almanac
from fom_planner.models import SaveData
from fom_planner.parser import parse_save_file
from tests.fixtures import create_synthetic_save_file


@pytest.fixture(scope="module")
def almanac_data():
    data = load_almanac_data()
    assert len(data.get("categories", {})) == 12
    assert len(data.get("items", {})) == 2369
    return data


# ==============================================================================
# 1. CATEGORY PROGRESS & FURNITURE SWATCH GROUPING
# ==============================================================================
class TestAlmanacCategoryProgressAndFurniture:
    def test_all_12_categories_present_in_plan(self, almanac_data):
        res = plan_almanac(save=None, almanac_data=almanac_data)
        assert len(res["categories"]) == 12
        for cat in [
            "artifacts", "blacksmithing", "bugs", "cooked_dishes", "crops",
            "date_inspiration", "fish", "forageables", "furniture",
            "materials", "ranching", "song_crystal"
        ]:
            assert cat in res["categories"]
            assert res["categories"][cat]["total"] > 0
            assert res["categories"][cat]["obtained"] == 0

    def test_furniture_mode_one_per_recipe_counts(self, almanac_data):
        res = plan_almanac(save=None, almanac_data=almanac_data, furniture_mode="one_per_recipe")
        furn = res["categories"]["furniture"]
        assert furn["total"] == 1008
        assert furn["groups_total"] == 1008
        assert furn["entries_total"] == 1530

    def test_furniture_mode_all_swatches_counts(self, almanac_data):
        res = plan_almanac(save=None, almanac_data=almanac_data, furniture_mode="all_swatches")
        furn = res["categories"]["furniture"]
        assert furn["total"] == 1530
        assert furn["groups_total"] == 1008
        assert furn["entries_total"] == 1530

    def test_furniture_group_fulfilled_by_single_swatch_in_one_per_recipe(self, tmp_path, almanac_data):
        # basic_bed has basic_bed and basic_bed_walnut
        save_p = tmp_path / "save_bed.sav"
        create_synthetic_save_file(save_p, items_acquired=["basic_bed_walnut"])
        save = parse_save_file(save_p)

        res_one = plan_almanac(save, almanac_data, furniture_mode="one_per_recipe")
        res_all = plan_almanac(save, almanac_data, furniture_mode="all_swatches")

        furn_one = res_one["categories"]["furniture"]
        furn_all = res_all["categories"]["furniture"]

        assert furn_one["obtained"] == 1
        assert furn_all["obtained"] == 1
        # In one_per_recipe, basic_bed group is considered obtained
        group = next(g for g in furn_one["groups"] if g["group_key"] == "basic_bed")
        assert group["is_obtained"] is True


# ==============================================================================
# 2. SYNTHETIC SAVE PARSING & ACQUISITION STATE
# ==============================================================================
class TestAlmanacSaveAcquiredItemsIntegration:
    def test_synthetic_save_items_acquired_parsing(self, tmp_path, almanac_data):
        save_p = tmp_path / "save_acq.sav"
        create_synthetic_save_file(
            save_p,
            items_acquired=["acorn", "bread", "copper_ingot"],
            bag_items={"basic_wood": 10},
        )
        save = parse_save_file(save_p)
        res = plan_almanac(save, almanac_data)

        assert res["categories"]["forageables"]["obtained"] >= 1  # acorn
        assert res["categories"]["cooked_dishes"]["obtained"] >= 1  # bread
        assert res["categories"]["blacksmithing"]["obtained"] >= 1  # copper_ingot
        assert res["categories"]["materials"]["obtained"] >= 1  # basic_wood

    def test_defensive_union_with_bag_and_chests(self, tmp_path, almanac_data):
        save_p = tmp_path / "save_inv.sav"
        # Item not in items_acquired, but in chest
        create_synthetic_save_file(
            save_p,
            items_acquired=[],
            chests_by_location={"farm": [[{"item": {"item_id": "turnip"}, "count": 5}]]}
        )
        save = parse_save_file(save_p)
        res = plan_almanac(save, almanac_data)
        assert res["categories"]["crops"]["obtained"] >= 1

    def test_defensive_union_with_recipes_created(self, tmp_path, almanac_data):
        save_p = tmp_path / "save_crafted.sav"
        create_synthetic_save_file(
            save_p,
            items_acquired=[],
            recipes_created=["crop_faux_rice"],
        )
        save = parse_save_file(save_p)
        res = plan_almanac(save, almanac_data)
        assert res["categories"]["furniture"]["obtained"] >= 1


# ==============================================================================
# 3. GIFT BAG RESERVATION & SYNERGY
# ==============================================================================
class TestAlmanacGiftBagReservation:
    def test_reserve_gifts_enabled_deducts_inventory(self, almanac_data):
        gift_res = {
            "bag_plan": [
                {"item_id": "wood", "quantity_to_pack": 5, "status": "HAVE"}
            ],
            "focus_suggestions": []
        }

        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self): return {"wood": 10}
            def get_unlocked_recipe_ids(self): return set()
            in_game_date = None

        res_reserve = plan_almanac(MockSave(), almanac_data, gift_plan_result=gift_res, reserve_gifts=True)
        assert res_reserve["reserved_by_gifts"].get("wood") == 5

        res_no_reserve = plan_almanac(MockSave(), almanac_data, gift_plan_result=gift_res, reserve_gifts=False)
        assert len(res_no_reserve["reserved_by_gifts"]) == 0

    def test_reserve_gifts_craft_status_reservation(self, almanac_data):
        gift_res = {
            "bag_plan": [
                {
                    "item_id": "flour",
                    "quantity_to_pack": 2,
                    "status": "CRAFT",
                    "raw_materials_needed": {"wheat": 2}
                }
            ],
            "focus_suggestions": []
        }

        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self): return {"wheat": 5}
            def get_unlocked_recipe_ids(self): return {"flour"}
            in_game_date = None

        res_reserve = plan_almanac(MockSave(), almanac_data, gift_plan_result=gift_res, reserve_gifts=True)
        assert res_reserve["reserved_by_gifts"].get("wheat") == 2


# ==============================================================================
# 4. READY TO CRAFT GREEDY BATCH QUEUE & INTERMEDIATE CHAINING
# ==============================================================================
class TestGreedyBatchCraftingQueue:
    def test_intermediate_chaining_wheat_flour_bread_sandwich(self, almanac_data):
        # Player has 1 wheat, 1 cucumber, 1 mayonnaise, 1 cheese
        # All 3 recipes unlocked; all 3 unobtained in Almanac
        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self):
                return {"wheat": 1, "cucumber": 1, "mayonnaise": 1, "cheese": 1}
            def get_unlocked_recipe_ids(self):
                return {"flour", "bread", "cucumber_sandwich"}
            in_game_date = None

        res = plan_almanac(MockSave(), almanac_data)
        craftable = res["ready_to_craft"]

        # All 3 steps must be present in queue
        item_ids = [step["item_id"] for step in craftable]
        assert "flour" in item_ids
        assert "bread" in item_ids
        assert "cucumber_sandwich" in item_ids

        # Chronological execution order: flour -> bread -> cucumber_sandwich
        assert item_ids.index("flour") < item_ids.index("bread")
        assert item_ids.index("bread") < item_ids.index("cucumber_sandwich")

        # Intermediate items tagged properly
        flour_step = next(s for s in craftable if s["item_id"] == "flour")
        bread_step = next(s for s in craftable if s["item_id"] == "bread")
        sandwich_step = next(s for s in craftable if s["item_id"] == "cucumber_sandwich")

        assert flour_step["unlocks_almanac"] is True
        assert flour_step["is_intermediate"] is True
        assert flour_step["station"] == "milling"

        assert bread_step["unlocks_almanac"] is True
        assert bread_step["is_intermediate"] is True
        assert bread_step["station"] == "cooking"

        assert sandwich_step["unlocks_almanac"] is True
        assert sandwich_step["is_intermediate"] is False
        assert sandwich_step["station"] == "cooking"

    def test_no_double_counting_of_intermediate_ingredients(self, almanac_data):
        # 1 wheat produces 1 flour -> 1 bread -> 1 sandwich.
        # Total wheat consumed must be exactly 1, not 3!
        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self):
                return {"wheat": 1, "cucumber": 1, "mayonnaise": 1, "cheese": 1}
            def get_unlocked_recipe_ids(self):
                return {"flour", "bread", "cucumber_sandwich"}
            in_game_date = None

        res = plan_almanac(MockSave(), almanac_data)
        # Should unlock 3 Almanac items
        unlocked_items = [s["item_id"] for s in res["ready_to_craft"] if s["unlocks_almanac"]]
        assert len(unlocked_items) == 3


# ==============================================================================
# 5. RECURSIVE RAW MATERIAL BREAKDOWN & DAG TREES
# ==============================================================================
class TestRecursiveRawMaterialBreakdownAndDAG:
    def test_missing_craftables_decompose_to_root_materials(self, almanac_data):
        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self): return {}
            def get_unlocked_recipe_ids(self): return set()
            in_game_date = None

        res = plan_almanac(MockSave(), almanac_data)
        blockers = res["raw_material_blockers"]
        assert len(blockers) > 0

        # ore_stone, ore_copper, wheat should appear as blockers
        blocker_ids = {b["item_id"] for b in blockers}
        assert "ore_stone" in blocker_ids or "stone" in blocker_ids or "wheat" in blocker_ids

    def test_d3_tree_modal_schema_compatibility(self, almanac_data):
        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self): return {}
            def get_unlocked_recipe_ids(self): return set()
            in_game_date = None

        res = plan_almanac(MockSave(), almanac_data)
        blockers = res["raw_material_blockers"]
        for b in blockers[:5]:
            tree = b.get("tree")
            assert tree is not None
            assert "item_id" in tree
            assert "item_name" in tree
            assert "children" in tree
            assert isinstance(tree["children"], list)
            assert "sprite_url" in tree

    def test_include_locked_recipes_toggle(self, almanac_data):
        class MockSave:
            def get_acquired_items(self): return set()
            def get_all_available_items(self): return {}
            def get_unlocked_recipe_ids(self): return set()  # Only default recipes unlocked
            in_game_date = None

        res_locked_included = plan_almanac(MockSave(), almanac_data, include_locked_recipes=True)
        res_locked_excluded = plan_almanac(MockSave(), almanac_data, include_locked_recipes=False)

        assert len(res_locked_included["raw_material_blockers"]) > len(res_locked_excluded["raw_material_blockers"])


# ==============================================================================
# 6. UNIFIED SOURCE PRIORITY & SEASONAL FILTERING
# ==============================================================================
class TestUnifiedSourcePriorityAndSeasonalFilter:
    def test_source_tiers_classified_into_quick_grind_farm(self, almanac_data):
        res = plan_almanac(save=None, almanac_data=almanac_data)
        tiers = res["sources_by_tier"]
        assert "quick" in tiers
        assert "grind" in tiers
        assert "farm" in tiers

        for tier_name in ("quick", "grind", "farm"):
            for src in tiers[tier_name]:
                assert "source" in src
                assert "total_impact" in src
                assert src["total_impact"] >= 0

    def test_seasonal_filtering_filters_gatherables(self, almanac_data):
        res_spring = plan_almanac(save=None, almanac_data=almanac_data, season_filter="spring")
        res_winter = plan_almanac(save=None, almanac_data=almanac_data, season_filter="winter")

        # Sources and unobtained items differ across seasons
        assert res_spring != res_winter

    def test_category_filtering(self, almanac_data):
        res_all = plan_almanac(save=None, almanac_data=almanac_data, category_filter="all")
        res_fish = plan_almanac(save=None, almanac_data=almanac_data, category_filter="fish")

        # In fish-only category filter, direct collectibles must be fish
        fish_collectibles = []
        for src in res_fish["source_priority"]:
            for item in src["direct_collectibles"]:
                fish_collectibles.append(item)
        assert len(fish_collectibles) > 0
        for item in fish_collectibles:
            assert item["category"] == "fish"

        # Assert no unblocked craftables are from non-fish categories
        for src in res_fish["source_priority"]:
            for item in src["unblocked_craftables"]:
                assert item["category"] == "fish", f"Leaked non-fish craftable: {item}"

        # Assert Tackle Shop ranks as top Quick source for fish
        quick_sources = res_fish["sources_by_tier"]["quick"]
        assert len(quick_sources) > 0
        assert quick_sources[0]["source"] == "Tackle Shop"

        # Assert cross-category shops (Eastern Woodworks, Blacksmith) do not appear in fish quick tier
        quick_source_names = [s["source"] for s in quick_sources]
        assert "Eastern Woodworks" not in quick_source_names
        assert "Blacksmith" not in quick_source_names

    def test_category_filter_source_priority_isolation(self, almanac_data):
        """
        Adversarial regression test for Finding 1 (Reviewer 1):
        When category_filter != "all":
        1. Tackle Shop ranks at #1 among Quick sources and outranks Eastern Woodworks.
        2. unblocked_craftables in each source only contains items matching the filtered category.
        3. Sources with 0 impact in the filtered category are omitted.
        4. Categories with craftable items (e.g. cooked_dishes) strictly isolate craftables.
        """
        # ======================================================================
        # Part 1: category_filter="fish"
        # ======================================================================
        res_fish = plan_almanac(save=None, almanac_data=almanac_data, category_filter="fish")

        # Non-craftable category like fish must produce 0 raw_material_blockers
        assert len(res_fish["raw_material_blockers"]) == 0

        quick_sources = res_fish["sources_by_tier"]["quick"]
        assert len(quick_sources) > 0, "Expected at least one Quick source for fish (Tackle Shop)"

        # 1. Tackle Shop ranks at #1 among Quick sources
        top_quick = quick_sources[0]
        assert top_quick["source"] == "Tackle Shop", (
            f"Expected Tackle Shop at #1 Quick source for fish, got '{top_quick['source']}'"
        )
        assert top_quick["total_impact"] > 0
        assert top_quick["total_impact"] == len(top_quick["direct_collectibles"]) + len(top_quick["unblocked_craftables"])

        # 2. Tackle Shop outranks Eastern Woodworks (Eastern Woodworks must be omitted or rank lower)
        quick_source_names = [s["source"] for s in quick_sources]
        assert "Eastern Woodworks" not in quick_source_names, (
            "Eastern Woodworks has 0 fish impact and should be omitted from Quick sources when filtering by fish"
        )
        all_fish_source_names = {s["source"] for s in res_fish["source_priority"]}
        assert "Eastern Woodworks" not in all_fish_source_names
        assert "Balor's Wagon" not in all_fish_source_names
        assert "Blacksmith" not in all_fish_source_names

        # 3. unblocked_craftables in each source only contains items matching the filtered category
        for s in res_fish["source_priority"]:
            for u in s["unblocked_craftables"]:
                assert u["category"] == "fish", (
                    f"Leaked non-fish item '{u['item_id']}' (category='{u.get('category')}') "
                    f"in source '{s['source']}'"
                )

        # 4. Sources with 0 impact in the filtered category are omitted
        for tier_name, sources in res_fish["sources_by_tier"].items():
            for s in sources:
                assert s["total_impact"] > 0, (
                    f"Source '{s['source']}' in tier '{tier_name}' has 0 impact but was not omitted"
                )

        for s in res_fish["source_priority"]:
            assert s["total_impact"] > 0, (
                f"Source '{s['source']}' in source_priority has 0 impact but was not omitted"
            )

        # Fish cannot be farmed on farm plots or ranched; farm tier must be empty
        assert len(res_fish["sources_by_tier"]["farm"]) == 0, (
            "Expected 0 farm sources for fish category filter"
        )

        # ======================================================================
        # Part 2: category_filter="cooked_dishes" (category with craftables)
        # ======================================================================
        res_cook = plan_almanac(save=None, almanac_data=almanac_data, category_filter="cooked_dishes")

        # Cooked dishes category must produce cooking blockers with 100% tree reachability
        assert len(res_cook["raw_material_blockers"]) > 0
        for b in res_cook["raw_material_blockers"]:
            for u in b["unblocked_almanac_items"]:
                assert u["category"] == "cooked_dishes"
            target_ids = {u["item_id"] for u in b["unblocked_almanac_items"]}
            reached_ids = set()

            def walk(node):
                if node["item_id"] in target_ids:
                    reached_ids.add(node["item_id"])
                for child in node.get("children", []):
                    walk(child)

            walk(b["tree"])
            assert target_ids == reached_ids, f"Tree reachability mismatch for {b['item_id']}"

        cook_sources = res_cook["source_priority"]
        assert len(cook_sources) > 0

        # Unblocked craftables must exist for cooked dishes and strictly belong to cooked_dishes
        total_cook_unblocked = sum(len(s["unblocked_craftables"]) for s in cook_sources)
        assert total_cook_unblocked > 0, (
            "Expected unblocked craftables to be populated for cooked_dishes"
        )

        for s in cook_sources:
            assert s["total_impact"] > 0, f"Source '{s['source']}' has 0 impact in cooked_dishes"
            for u in s["unblocked_craftables"]:
                assert u["category"] == "cooked_dishes", (
                    f"Leaked non-cooked item '{u['item_id']}' (category='{u.get('category')}') "
                    f"in source '{s['source']}'"
                )

        # Non-food sources like Eastern Woodworks and Blacksmith must be omitted
        cook_source_names = {s["source"] for s in cook_sources}
        assert "Eastern Woodworks" not in cook_source_names
        assert "Blacksmith" not in cook_source_names

        # Nonexistent category produces empty source lists across all tiers
        res_none = plan_almanac(save=None, almanac_data=almanac_data, category_filter="nonexistent")
        assert len(res_none["sources_by_tier"]["quick"]) == 0
        assert len(res_none["sources_by_tier"]["grind"]) == 0
        assert len(res_none["sources_by_tier"]["farm"]) == 0
        assert len(res_none["source_priority"]) == 0
        assert len(res_none["raw_material_blockers"]) == 0
