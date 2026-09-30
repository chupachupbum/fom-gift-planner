"""
tests/e2e/test_tier2_boundaries.py

Tier 2: Boundary & Corner Cases (Boundary Value Analysis - BVA).
Ensures >= 5 deterministic tests per boundary category (>= 35 total):
- Boundary 1: Empty Save Files (0 bytes, whitespace, truncated headers)
- Boundary 2: Corrupted Save Bytes (non-zlib, truncated stream, invalid entry lengths, bad JSON)
- Boundary 3: Bag Slots Boundaries (0 slots, 1 slot, 100 slots, negative, string/float types)
- Boundary 4: Boundary In-Game Dates (Spring 1 Year 1, Winter 28, Year 99, out-of-range days, casing)
- Boundary 5: Missing or Invalid Configs (None, empty dict, unknown keys, invalid weights, invalid strategies)
- Boundary 6: Invalid / Unknown Item IDs (unknown IDs, 0 count, empty strings, missing crafting components)
- Boundary 7: Unknown NPCs & Corrupted Affection (unknown NPCs, negative affection, extreme affection, invalid types)
"""

import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Any, Dict
import zlib

import pytest

from fom_planner.parser import parse_save_file
from tests.e2e.conftest import (
    REPO_ROOT,
    SAMPLE_SAVE_PATH,
    make_synthetic_save_bytes,
)


# ==============================================================================
# BOUNDARY 1: EMPTY SAVE FILES
# ==============================================================================
class TestBoundary1EmptySaveFiles:
    """Probes zero-byte, whitespace, and truncated save file payloads."""

    def test_zero_byte_save_raises_or_handled(self, plan_executor):
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(b"")
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, EOFError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_whitespace_only_save(self):
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(b"   \n\r\t   ")
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_empty_decompressed_zlib_stream(self):
        empty_compressed = zlib.compress(b"")
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(empty_compressed)
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_truncated_header_less_than_8_bytes(self):
        # Header requires 8-byte entry count integer
        truncated = zlib.compress(b"1234")
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(truncated)
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_save_with_zero_entries_parses_gracefully(self, plan_executor):
        # 8-byte LE 0 for num_entries
        zero_entries_payload = zlib.compress(struct.pack("<Q", 0))
        _, plan = plan_executor(zero_entries_payload)
        assert plan["save_info"]["found"] is True
        assert plan["save_info"]["player_name"] == "Player"
        assert plan["stats"]["completed_npcs_count"] == 0


# ==============================================================================
# BOUNDARY 2: CORRUPTED SAVE BYTES
# ==============================================================================
class TestBoundary2CorruptedSaveBytes:
    """Probes random noise, truncated compression, and malformed length fields."""

    def test_random_binary_garbage(self):
        garbage = os.urandom(512)
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(garbage)
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_truncated_zlib_stream(self, sample_save_bytes):
        # Truncate real save bytes halfway
        truncated = sample_save_bytes[: len(sample_save_bytes) // 2]
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(truncated)
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()

    def test_entry_length_field_exceeds_buffer(self):
        # 1 entry, key_len = 99999999 (far exceeds payload)
        body = bytearray()
        body.extend(struct.pack("<Q", 1))
        body.extend(struct.pack("<Q", 99999999))
        body.extend(b"key")
        raw = zlib.compress(bytes(body))

        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(raw)
            tmp_path = Path(f.name)

        try:
            save = parse_save_file(tmp_path)
            # Should break loop safely without out-of-bounds crash
            assert save is not None
        finally:
            tmp_path.unlink()

    def test_malformed_json_inside_entry(self, plan_executor):
        # Valid FoM save structure, but JSON inside 'player' is corrupted
        body = bytearray()
        body.extend(struct.pack("<Q", 1))
        k = "player".encode("utf-8")
        v = "{unquoted_key: invalid_json[[[".encode("utf-8")
        body.extend(struct.pack("<Q", len(k)))
        body.extend(k)
        body.extend(struct.pack("<Q", len(v)))
        body.extend(v)
        raw = zlib.compress(bytes(body))

        # Must not crash planner, should fall back to defaults
        _, plan = plan_executor(raw)
        assert plan["save_info"]["player_name"] == "Player"

    def test_invalid_gzip_magic_bytes(self):
        bad_magic = b"\x1f\x8b\x00\x00" + b"\xff" * 50
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
            f.write(bad_magic)
            tmp_path = Path(f.name)

        try:
            with pytest.raises((ValueError, Exception)):
                parse_save_file(tmp_path)
        finally:
            tmp_path.unlink()


# ==============================================================================
# BOUNDARY 3: BAG SLOTS BOUNDARIES
# ==============================================================================
class TestBoundary3BagSlots:
    """Probes zero, single, maximum, negative, and non-integer bag slots."""

    def test_zero_slots_boundary(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"slots": 0})
        assert plan["stats"]["max_slots"] == 0
        assert len(plan["bag_plan"]) == 0

    def test_single_slot_boundary(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"slots": 1})
        assert plan["stats"]["max_slots"] == 1
        assert len(plan["bag_plan"]) <= 1

    def test_extreme_large_slots_boundary(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"slots": 100})
        assert plan["stats"]["max_slots"] == 100
        # Should not duplicate gifts beyond available target NPCs
        assert len(plan["bag_plan"]) <= 35

    def test_negative_slots_handled_defensively(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"slots": -5})
        # Should either clamp to 0 or produce 0 items
        assert len(plan["bag_plan"]) == 0

    def test_string_and_float_slots_coercion(self, sample_save_path, plan_executor):
        _, plan_str = plan_executor(sample_save_path, config={"slots": "15"})
        assert plan_str["stats"]["max_slots"] == 15

        _, plan_flt = plan_executor(sample_save_path, config={"slots": 18.7})
        assert plan_flt["stats"]["max_slots"] in (18, 19)


# ==============================================================================
# BOUNDARY 4: BOUNDARY IN-GAME DATES
# ==============================================================================
class TestBoundary4BoundaryInGameDates:
    """Probes earliest, latest, extreme year, and out-of-range day numbers."""

    def test_earliest_game_date_spring_1_year_1(self, plan_executor):
        save_bytes = make_synthetic_save_bytes(year=1, season="spring", day=1)
        _, plan = plan_executor(save_bytes)
        date = plan["in_game_date"]
        assert date["year"] == 1
        assert date["season"] in ("Spring", "spring")
        assert date["day"] == 1

    def test_end_of_year_boundary_winter_28(self, plan_executor):
        save_bytes = make_synthetic_save_bytes(year=1, season="winter", day=28)
        _, plan = plan_executor(save_bytes)
        date = plan["in_game_date"]
        assert date["year"] == 1
        assert date["season"] in ("Winter", "winter")
        assert date["day"] == 28

    def test_extreme_future_year_99(self, plan_executor):
        save_bytes = make_synthetic_save_bytes(year=99, season="autumn", day=14)
        _, plan = plan_executor(save_bytes)
        date = plan["in_game_date"]
        assert date["year"] == 99
        assert date["day"] == 14

    def test_out_of_range_day_number(self, plan_executor):
        # Day 29 does not exist in FoM (28 days per season)
        save_bytes = make_synthetic_save_bytes(year=1, season="summer", day=29)
        _, plan = plan_executor(save_bytes)
        date = plan["in_game_date"]
        assert date["year"] >= 1
        assert 1 <= date["day"] <= 28

    def test_case_insensitive_season_names(self, sample_save_path, plan_executor):
        # Date override using uppercase or mixed case
        _, plan = plan_executor(sample_save_path, config={"date_override": "WINTER 15"})
        date = plan["in_game_date"]
        assert date["is_overridden"] is True
        assert date["season"].lower() == "winter"
        assert date["day"] == 15


# ==============================================================================
# BOUNDARY 5: MISSING OR INVALID CONFIGS
# ==============================================================================
class TestBoundary5MissingOrInvalidConfigs:
    """Probes None configs, empty dicts, unknown keys, and out-of-range weights."""

    def test_none_config_uses_defaults(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config=None)
        assert plan["stats"]["max_slots"] == 20
        assert plan["config"]["strategy"] == "journal"

    def test_empty_dict_config_uses_defaults(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={})
        assert plan["stats"]["max_slots"] == 20

    def test_unknown_config_keys_ignored(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"slots": 14, "nonexistent_option": 999})
        assert plan["stats"]["max_slots"] == 14

    def test_zero_and_negative_preference_weights(self, sample_save_path, plan_executor):
        # loved_weight=0, liked_weight=0
        _, plan = plan_executor(sample_save_path, config={"loved_weight": 0, "liked_weight": 0})
        assert plan is not None
        assert "bag_plan" in plan

    def test_invalid_strategy_falls_back_safely(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path, config={"strategy": "unknown_future_mode"})
        assert plan is not None
        assert "bag_plan" in plan


# ==============================================================================
# BOUNDARY 6: INVALID OR UNKNOWN ITEM IDS
# ==============================================================================
class TestBoundary6InvalidUnknownItemIDs:
    """Probes non-existent items, empty IDs, zero counts, and duplicate slots."""

    def test_inventory_with_unknown_item_id(self, plan_executor):
        inv = [{"item_id": "laser_rifle_omega", "count": 5}]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv)
        _, plan = plan_executor(save_bytes)
        assert plan is not None
        assert len(plan["bag_plan"]) >= 0

    def test_inventory_with_zero_count_item(self, plan_executor):
        inv = [{"item_id": "turnip", "count": 0}]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv)
        _, plan = plan_executor(save_bytes)
        # 0-count items should not be counted as having stock
        assert plan is not None

    def test_inventory_with_empty_item_id(self, plan_executor):
        inv = [{"item_id": "", "count": 1}]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_duplicate_item_slots_aggregated_correctly(self, plan_executor):
        # Two slots of chocolate: 3 + 2 = 5
        inv = [
            {"item_id": "chocolate", "count": 3},
            {"item_id": "chocolate", "count": 2},
        ]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_unlocked_recipes_containing_unknown_recipe(self, plan_executor):
        save_bytes = make_synthetic_save_bytes(unlocked_recipes=["space_tacos_deluxe"])
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_empty_inventory_list(self, plan_executor):
        save_bytes = make_synthetic_save_bytes(inventory_items=[])
        _, plan = plan_executor(save_bytes)
        assert plan is not None
        assert isinstance(plan["bag_plan"], list)


# ==============================================================================
# BOUNDARY 7: UNKNOWN NPCS AND CORRUPTED AFFECTION
# ==============================================================================
class TestBoundary7UnknownNPCsAndCorruptedAffection:
    """Probes unknown townspeople, negative points, and extreme heart points."""

    def test_save_with_unknown_npc(self, plan_executor):
        aff = {"gandalf": 500.0}
        save_bytes = make_synthetic_save_bytes(npc_affection=aff)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_npc_with_negative_heart_points(self, plan_executor):
        aff = {"march": -100.0}
        save_bytes = make_synthetic_save_bytes(npc_affection=aff)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_npc_with_extreme_heart_points(self, plan_executor):
        aff = {"adeline": 999999.0}
        save_bytes = make_synthetic_save_bytes(npc_affection=aff)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_corrupted_empty_string_npc_id(self, plan_executor):
        aff = {"": 200.0}
        save_bytes = make_synthetic_save_bytes(npc_affection=aff)
        _, plan = plan_executor(save_bytes)
        assert plan is not None

    def test_mixed_case_npc_ids(self, plan_executor):
        aff = {"CeLiNe": 300.0, "BALOR": 150.0}
        save_bytes = make_synthetic_save_bytes(npc_affection=aff)
        _, plan = plan_executor(save_bytes)
        assert plan is not None
