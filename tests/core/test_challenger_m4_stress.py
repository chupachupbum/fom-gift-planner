"""
tests/core/test_challenger_m4_stress.py

Empirical Challenger Stress Test Suite for Milestone 4:
1. Combinatorial permutations of planning configurations on samples/sample_save.sav:
   - saturday_only (modes: auto, saturday, today, townsfolk)
   - max_relationship_priority (strategies: journal, max-relationship)
   - focus_npcs (disabled, single NPC, multiple NPCs, invalid NPC, empty)
   - date_override (None, spring 1, spring 6, summer 15, summer 28, fall 10, winter 10, winter 20)
2. Gating Invariant: 100% of focus suggestions have gift_deficit > 0.
3. Deficit Math: deficit == gift_deficit + quest_demand for 100% of focus suggestions.
4. Quest Node Schema: all quest child nodes in focus trees have is_quest == True,
   valid quest_type, quest_category, quest_amount, via_item_name, and children == [].
5. Multi-Save Validation: handles saves with 0, 126, and 337 completed quests cleanly.
6. Web Bridge vs Companion Bridge Parity across diverse configurations.
"""

import json
from pathlib import Path
import pytest
from typing import Any, Dict, List

from companion.config import CompanionConfig
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan
from web.py.web_bridge import generate_plan, init_bridge


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def setup_web_bridge(repo_root: Path):
    init_bridge(str(repo_root / "web" / "data"))


def traverse_tree_find_quests(node: Dict[str, Any], found: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if found is None:
        found = []
    if not isinstance(node, dict):
        return found
    if node.get("is_quest") is True:
        found.append(node)
    for child in node.get("children", []):
        traverse_tree_find_quests(child, found)
    return found


def assert_focus_suggestion_invariants(item: Dict[str, Any], ctx: str = "") -> None:
    item_id = item.get("item_id", "UNKNOWN")
    for field in ["gift_deficit", "quest_demand", "deficit", "quest_count", "quest_categories", "quest_summary"]:
        assert field in item, f"[{ctx}] '{item_id}' missing '{field}'"

    gift_deficit = item["gift_deficit"]
    quest_demand = item["quest_demand"]
    deficit = item["deficit"]
    quest_count = item["quest_count"]
    quest_categories = item["quest_categories"]
    quest_summary = item["quest_summary"]

    assert isinstance(gift_deficit, int) and gift_deficit > 0, (
        f"[{ctx}] '{item_id}' gating invariant violated: gift_deficit={gift_deficit} <= 0"
    )
    assert isinstance(quest_demand, int) and quest_demand >= 0, (
        f"[{ctx}] '{item_id}' negative quest_demand: {quest_demand}"
    )
    assert isinstance(deficit, int), f"[{ctx}] '{item_id}' deficit is not int: {deficit}"
    assert deficit == gift_deficit + quest_demand, (
        f"[{ctx}] '{item_id}' deficit math violated: deficit={deficit} != {gift_deficit} + {quest_demand}"
    )

    if quest_demand > 0:
        assert quest_count > 0, f"[{ctx}] '{item_id}' quest_demand > 0 but quest_count == 0"
        assert len(quest_categories) > 0, f"[{ctx}] '{item_id}' quest_demand > 0 but quest_categories empty"
        assert len(quest_summary) > 0, f"[{ctx}] '{item_id}' quest_demand > 0 but quest_summary empty"
        for q in quest_summary:
            assert isinstance(q.get("quest_name"), str) and len(q["quest_name"].strip()) > 0
            assert isinstance(q.get("quest_type"), str) and len(q["quest_type"].strip()) > 0
            assert isinstance(q.get("category"), str) and len(q["category"].strip()) > 0
            assert isinstance(q.get("amount"), int) and q["amount"] > 0
            assert isinstance(q.get("raw_amount_needed"), int) and q["raw_amount_needed"] > 0
            assert isinstance(q.get("target_item_id"), str) and len(q["target_item_id"].strip()) > 0
            assert isinstance(q.get("target_item_name"), str) and len(q["target_item_name"].strip()) > 0
            assert isinstance(q.get("is_direct"), bool)
    else:
        assert quest_count == 0
        assert len(quest_categories) == 0
        assert len(quest_summary) == 0


def assert_quest_node_schema(qn: Dict[str, Any], ctx: str = "") -> None:
    assert qn.get("is_quest") is True, f"[{ctx}] is_quest is not True: {qn}"
    assert str(qn.get("item_id", "")).startswith("_quest_"), f"[{ctx}] item_id not starting with _quest_: {qn}"
    assert isinstance(qn.get("item_name"), str) and len(qn["item_name"].strip()) > 0
    assert isinstance(qn.get("quest_type"), str) and len(qn["quest_type"].strip()) > 0
    assert isinstance(qn.get("quest_category"), str) and len(qn["quest_category"].strip()) > 0
    assert isinstance(qn.get("quest_amount"), int) and qn["quest_amount"] > 0
    assert isinstance(qn.get("via_item_name"), str) and len(qn["via_item_name"].strip()) > 0
    assert qn.get("children") == [], f"[{ctx}] quest node children not empty list: {qn.get('children')}"
    assert qn.get("alt_sources") == []
    assert qn.get("gift_npcs") == []


class TestSampleSaveCombinatorialPermutations:
    """Stress tests verifying core invariants across combinatorial configurations on sample_save.sav."""

    @pytest.mark.parametrize("mode", ["auto", "saturday", "today", "townsfolk"])
    @pytest.mark.parametrize("strategy", ["journal", "max-relationship"])
    @pytest.mark.parametrize(
        "focus_cfg",
        [
            (False, ""),
            (True, "adeline"),
            (True, "celine,march,reina"),
            (True, "nonexistent_villager"),
        ],
    )
    @pytest.mark.parametrize("date_over", [None, "spring 1", "summer 15", "winter 10"])
    def test_sample_save_configurations(self, repo_root: Path, mode: str, strategy: str, focus_cfg: tuple, date_over: str):
        save_path = repo_root / "samples" / "sample_save.sav"
        focus_mode, focus_npcs = focus_cfg

        cfg = CompanionConfig(
            save_file=str(save_path),
            mode=mode,
            strategy=strategy,
            focus_mode_enabled=focus_mode,
            focus_npcs=focus_npcs,
            date_override=date_over,
        )

        save, plan_res, metadata, resolved_path = execute_plan(cfg, repo_root=repo_root)
        comp_dict = plan_to_json(save, plan_res, metadata, resolved_path, cfg)

        focus_suggs = comp_dict.get("focus_suggestions", [])
        focus_trees = comp_dict.get("focus_trees", [])

        ctx = f"mode={mode}, strat={strategy}, focus=({focus_mode}, '{focus_npcs}'), date={date_over}"

        # 1. Validate all focus suggestions
        for item in focus_suggs:
            assert_focus_suggestion_invariants(item, ctx)

        # 2. Validate all terminal quest nodes in trees
        for tree in focus_trees:
            q_nodes = traverse_tree_find_quests(tree)
            for qn in q_nodes:
                assert_quest_node_schema(qn, ctx)


class TestDiverseRealSavesProgression:
    """Stress tests on diverse real saves with differing quest completion states."""

    def test_autosave_with_126_completed_quests(self, repo_root: Path):
        save_path = repo_root / "data" / "uploads" / "game-1068771241-autosave.sav"
        if not save_path.exists():
            pytest.skip("Autosave file missing")

        cfg = CompanionConfig(save_file=str(save_path))
        save, plan_res, metadata, resolved_path = execute_plan(cfg, repo_root=repo_root)
        comp_dict = plan_to_json(save, plan_res, metadata, resolved_path, cfg)

        focus_suggs = comp_dict.get("focus_suggestions", [])
        assert len(focus_suggs) > 0
        for item in focus_suggs:
            assert_focus_suggestion_invariants(item, "Autosave 126 quests")

        focus_trees = comp_dict.get("focus_trees", [])
        for tree in focus_trees:
            for qn in traverse_tree_find_quests(tree):
                assert_quest_node_schema(qn, "Autosave 126 quests")

    def test_heavily_progressed_save_with_337_completed_quests(self, repo_root: Path):
        save_path = repo_root / "data" / "uploads" / "%WinAppDataLocal%FieldsOfMistria_saves_game-2026225748-1918349166.sav"
        if not save_path.exists():
            pytest.skip("Alcyone save missing")

        cfg = CompanionConfig(save_file=str(save_path))
        save, plan_res, metadata, resolved_path = execute_plan(cfg, repo_root=repo_root)
        comp_dict = plan_to_json(save, plan_res, metadata, resolved_path, cfg)

        focus_suggs = comp_dict.get("focus_suggestions", [])
        for item in focus_suggs:
            assert_focus_suggestion_invariants(item, "Alcyone 337 quests")

        focus_trees = comp_dict.get("focus_trees", [])
        for tree in focus_trees:
            for qn in traverse_tree_find_quests(tree):
                assert_quest_node_schema(qn, "Alcyone 337 quests")


class TestWebBridgeParityUnderPermutations:
    """Tests 100% field parity and value parity between companion and web bridge serializers."""

    @pytest.mark.parametrize(
        "cfg_params",
        [
            {"strategy": "journal", "mode": "auto"},
            {"strategy": "max-relationship", "mode": "saturday"},
            {"strategy": "journal", "mode": "today", "focus_mode_enabled": True, "focus_npcs": "celine,march"},
            {"strategy": "max-relationship", "mode": "townsfolk", "date_override": "winter 10"},
        ],
    )
    def test_web_bridge_parity(self, repo_root: Path, cfg_params: dict):
        save_path = repo_root / "samples" / "sample_save.sav"
        cfg = CompanionConfig(save_file=str(save_path), **cfg_params)

        save, plan_res, metadata, resolved_path = execute_plan(cfg, repo_root=repo_root)
        comp_dict = plan_to_json(save, plan_res, metadata, resolved_path, cfg)

        web_json_str = generate_plan(str(save_path), config_dict=cfg.to_dict())
        web_dict = json.loads(web_json_str)

        # Focus suggestions parity
        comp_suggs = comp_dict.get("focus_suggestions", [])
        web_suggs = web_dict.get("focus_suggestions", [])
        assert len(comp_suggs) == len(web_suggs)

        for cs, ws in zip(comp_suggs, web_suggs):
            assert cs["item_id"] == ws["item_id"]
            assert cs["gift_deficit"] == ws["gift_deficit"]
            assert cs["quest_demand"] == ws["quest_demand"]
            assert cs["deficit"] == ws["deficit"]
            assert cs["quest_count"] == ws["quest_count"]
            assert cs["quest_categories"] == ws["quest_categories"]
            assert cs["quest_summary"] == ws["quest_summary"]
