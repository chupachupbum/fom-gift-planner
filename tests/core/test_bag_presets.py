"""
tests/core/test_bag_presets.py

Unit and regression tests for Bag Plan presets:
- Built-in Marriage Candidates mode ('marriage')
- Custom Presets mode ('custom') with user-specified custom_preset_npcs
- Calendar awareness for presets on weekdays vs. Saturdays
- Compatibility with both plan_daily_gift_bag and plan_max_relationship
- Configuration parsing in WebPlannerConfig and CompanionConfig
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fom_planner.constants import MARRIAGE_CANDIDATES, SATURDAY_MARKET_VENDORS
from fom_planner.data_loader import load_item_metadata, load_npc_preferences_from_json
from fom_planner.optimizer import plan_daily_gift_bag, plan_max_relationship
from fom_planner.parser import parse_save_file
from web.py.web_bridge import WebPlannerConfig
from companion.config import CompanionConfig


@pytest.fixture(scope="module")
def game_data():
    item_data_path = REPO_ROOT / "data" / "item_data.json"
    npcs_def, _ = load_npc_preferences_from_json(item_data_path)
    metadata = load_item_metadata(item_data_path)
    return npcs_def, metadata


@pytest.fixture(scope="module")
def sample_save():
    save_path = REPO_ROOT / "samples" / "sample_save.sav"
    if not save_path.exists():
        save_path = REPO_ROOT / "web" / "sample_save.sav"
    if save_path.exists():
        return parse_save_file(save_path)
    return None


def test_marriage_candidates_constant():
    """Verify the 12 canonical marriage candidates in Fields of Mistria."""
    expected = {
        "adeline", "balor", "caldarus", "celine", "eiland", "hayden",
        "juniper", "march", "reina", "ryis", "seridia", "valen"
    }
    assert MARRIAGE_CANDIDATES == expected
    assert len(MARRIAGE_CANDIDATES) == 12


def test_marriage_mode_plan_daily_gift_bag(game_data, sample_save):
    """Verify that mode='marriage' only targets canonical romanceable villagers."""
    npcs_def, metadata = game_data
    res = plan_daily_gift_bag(
        save=sample_save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode="marriage",
        max_slots=20,
    )

    target_npcs = res.get("target_npcs", set())
    assert target_npcs, "Expected at least some marriage candidates to be targeted"
    for nid in target_npcs:
        assert nid.lower() in MARRIAGE_CANDIDATES, f"Non-candidate {nid} was targeted in marriage mode"

    # Verify recipients in the resulting bag plan
    bag_plan = res.get("bag_plan", [])
    for slot in bag_plan:
        recipients = slot.get("all_recipients_today", [])
        for r in recipients:
            nid = r.get("npc_id", "").lower()
            assert nid in MARRIAGE_CANDIDATES, f"Recipient {nid} is not a marriage candidate"


def test_marriage_mode_plan_max_relationship(game_data, sample_save):
    """Verify that mode='marriage' works with max-relationship strategy."""
    npcs_def, metadata = game_data
    res = plan_max_relationship(
        save=sample_save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode="marriage",
        max_slots=20,
    )

    target_npcs = res.get("target_npcs", set())
    assert target_npcs
    for nid in target_npcs:
        assert nid.lower() in MARRIAGE_CANDIDATES


def test_custom_preset_plan_daily_gift_bag(game_data, sample_save):
    """Verify that mode='custom' with custom_preset_npcs only targets the specified NPCs."""
    npcs_def, metadata = game_data
    selected_npcs = ["march", "balor", "celine"]

    res = plan_daily_gift_bag(
        save=sample_save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode="custom",
        custom_preset_npcs="march,balor,celine",
        max_slots=20,
    )

    target_npcs = res.get("target_npcs", set())
    for nid in target_npcs:
        assert nid.lower() in selected_npcs, f"NPC {nid} was targeted but not in custom preset"

    bag_plan = res.get("bag_plan", [])
    for slot in bag_plan:
        for r in slot.get("all_recipients_today", []):
            assert r.get("npc_id", "").lower() in selected_npcs


from fom_planner.models import InGameDate


def test_custom_preset_calendar_awareness_weekday(game_data, sample_save):
    """
    On a weekday, a visiting vendor (Darcy) is off-map in Aldaria and should not be present,
    while a resident townsfolk (March) is present.
    """
    npcs_def, metadata = game_data
    if sample_save is not None:
        # Override save date to a weekday (Day 1 is Monday)
        sample_save.in_game_date = InGameDate(year=1, season="spring", day=1, time_str="06:00")

    res = plan_daily_gift_bag(
        save=sample_save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode="custom",
        custom_preset_npcs=["darcy", "march"],
        max_slots=20,
    )

    target_npcs = res.get("target_npcs", set())
    # Darcy is a Saturday Market vendor; on Day 1 (Monday), she must NOT be targeted
    assert "darcy" not in target_npcs, "Visiting vendor Darcy should not be present on a weekday"


def test_custom_preset_calendar_awareness_saturday(game_data, sample_save):
    """
    On Saturday Market (Day 6), Darcy IS in town and should be eligible if included in preset.
    """
    npcs_def, metadata = game_data
    if sample_save is not None:
        # Day 6 is Saturday
        sample_save.in_game_date = InGameDate(year=1, season="spring", day=6, time_str="06:00")

    res = plan_daily_gift_bag(
        save=sample_save,
        npc_gift_definitions=npcs_def,
        item_metadata=metadata,
        mode="custom",
        custom_preset_npcs="darcy,march",
        max_slots=20,
    )

    target_npcs = res.get("target_npcs", set())
    # On Saturday, both Darcy and March are eligible
    assert "darcy" in target_npcs or sample_save is None or not sample_save.is_npc_unlocked("darcy")


def test_web_planner_config_custom_preset():
    """Verify WebPlannerConfig parses custom_preset_npcs from string, list, and serializes."""
    cfg1 = WebPlannerConfig({"mode": "custom", "custom_preset_npcs": "march,balor,celine"})
    assert cfg1.custom_preset_npcs == "march,balor,celine"
    assert cfg1.to_dict()["custom_preset_npcs"] == "march,balor,celine"

    cfg2 = WebPlannerConfig({"mode": "custom", "custom_preset_npcs": ["adeline", "reina"]})
    assert cfg2.custom_preset_npcs == "adeline,reina"
    assert cfg2.to_dict()["custom_preset_npcs"] == "adeline,reina"


def test_companion_config_custom_preset():
    """Verify CompanionConfig handles custom_preset_npcs correctly."""
    cfg = CompanionConfig.from_dict({
        "mode": "custom",
        "custom_preset_npcs": ["hayden", "valen"]
    })
    assert cfg.custom_preset_npcs == "hayden,valen"
    assert cfg.to_dict()["custom_preset_npcs"] == "hayden,valen"
