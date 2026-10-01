"""
tests/test_web_bridge_stress.py

Empirical stress and adversarial verification suite for web/py/web_bridge.py.
Covers:
1. Extreme configuration options (negative values, huge slots, invalid strings, None values, type conversions).
2. Date override boundaries (all 4 seasons, day 0, day 1, day 28, day 29, invalid festivals, Saturday keyword and rollover).
3. Corrupted and adversarial save bytes (zero-length, 1-byte, truncated, random binary, corrupt zlib).
4. Sequential stress & static cache immutability across 50+ runs, plus multi-threaded execution.
5. Strict canonical JSON schema compliance across all output paths.
"""

import concurrent.futures
import copy
import json
import os
from pathlib import Path
import zlib
import pytest

from fom_planner.models import InGameDate
from web.py import web_bridge
from web.py.web_bridge import (
    WebPlannerConfig,
    generate_plan,
    init_bridge,
    parse_date_override,
    run_plan_from_vfs,
)

CANONICAL_KEYS = (
    "generated_at",
    "save_info",
    "in_game_date",
    "config",
    "stats",
    "completed_npcs_details",
    "incomplete_npcs_details",
    "unobtained_recipes",
    "recipe_stats",
    "infused_items",
    "bag_plan",
    "focus_suggestions",
    "focus_trees",
    "source_priority",
    "npc_progress",
    "error",
)


@pytest.fixture(scope="module", autouse=True)
def setup_bridge():
    """Ensure static databases in web/data are pre-cached for all tests."""
    init_bridge("web/data")


@pytest.fixture
def sample_save_path():
    """Returns absolute path to bundled demo save fixture."""
    path = Path(__file__).resolve().parents[2] / "samples" / "sample_save.sav"
    assert path.exists(), f"Sample save fixture missing at {path}"
    return path


@pytest.fixture
def sample_save_bytes(sample_save_path):
    """Returns raw bytes of bundled demo save fixture."""
    return sample_save_path.read_bytes()


def assert_canonical_schema(data: dict):
    """Helper asserting strict presence of all 16 canonical keys."""
    assert isinstance(data, dict), f"Payload is not dict: {type(data)}"
    assert len(data.keys()) == 16, f"Expected 16 keys, found {len(data.keys())}: {list(data.keys())}"
    for k in CANONICAL_KEYS:
        assert k in data, f"Missing canonical key: '{k}'"
    assert isinstance(data["save_info"], dict)
    assert isinstance(data["in_game_date"], dict)
    assert isinstance(data["config"], dict)
    assert isinstance(data["stats"], dict)
    assert isinstance(data["completed_npcs_details"], list)
    assert isinstance(data["incomplete_npcs_details"], list)
    assert isinstance(data["unobtained_recipes"], list)
    assert isinstance(data["recipe_stats"], dict)
    assert isinstance(data["bag_plan"], list)
    assert isinstance(data["focus_suggestions"], list)
    assert isinstance(data["focus_trees"], list)
    assert isinstance(data["source_priority"], list)
    assert isinstance(data["npc_progress"], dict)


# ==============================================================================
# 1. Extreme Config Options
# ==============================================================================

class TestExtremeConfigOptions:
    """Stress tests extreme, boundary, and invalid configuration parameters."""

    def test_negative_and_zero_slots(self, sample_save_path):
        """Negative and zero slots should return valid schema with empty bag plan without crashing."""
        for slots in (-1, -100, 0):
            res = generate_plan(str(sample_save_path), config_dict={"slots": slots})
            data = json.loads(res)
            assert_canonical_schema(data)
            assert data["error"] is None
            assert data["stats"]["max_slots"] == slots
            assert len(data["bag_plan"]) == 0

    def test_huge_slots(self, sample_save_path):
        """Very large slot count (e.g. 1000, 99999) should pack all candidate gifts without overflow."""
        for slots in (1000, 99999):
            res = generate_plan(str(sample_save_path), config_dict={"slots": slots})
            data = json.loads(res)
            assert_canonical_schema(data)
            assert data["error"] is None
            assert data["stats"]["max_slots"] == slots
            assert len(data["bag_plan"]) > 0

    def test_negative_weights_and_boosts(self, sample_save_path):
        """Negative weights and boosts should not throw exceptions."""
        cfg = {
            "loved_weight": -10,
            "liked_weight": -5,
            "vendor_boost": -2.0,
            "seasonal_boost": -1.5,
        }
        res = generate_plan(str(sample_save_path), config_dict=cfg)
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is None

    def test_invalid_strategy_and_mode_strings(self, sample_save_path):
        """Unknown strategy and mode should gracefully fall back to default behavior."""
        cfg = {
            "strategy": "totally_unknown_strategy_xyz",
            "mode": "unrecognized_mode_123",
            "focus_sort": "nonexistent_sort",
        }
        res = generate_plan(str(sample_save_path), config_dict=cfg)
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is None
        assert len(data["bag_plan"]) > 0
        assert len(data["focus_suggestions"]) > 0

    def test_none_config_values_handled_gracefully(self, sample_save_path):
        """Passing None for fields expecting int/float should return canonical error payload without uncaught crash."""
        for bad_cfg in (
            {"slots": None},
            {"loved_weight": None},
            {"liked_weight": None},
            {"vendor_boost": None},
            {"seasonal_boost": None},
        ):
            res = generate_plan(str(sample_save_path), config_dict=bad_cfg)
            data = json.loads(res)
            assert_canonical_schema(data)
            assert data["error"] is not None
            assert "NoneType" in data["error"] or "TypeError" in data["error"] or "int" in data["error"]

    def test_malformed_npc_collections(self, sample_save_path):
        """Lists with None, numbers, or whitespace in NPC filters should be parsed safely."""
        cfg = {
            "focus_npcs": ["adeline", None, 12345, "   balor   ", ""],
            "exclude_npcs": ["celine", 6789, ""],
            "focus_mode_enabled": True,
        }
        res = generate_plan(str(sample_save_path), config_dict=cfg)
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is None
        assert "adeline" in data["config"]["focus_npcs"]
        assert "balor" in data["config"]["focus_npcs"]
        assert "celine" in data["config"]["exclude_npcs"]

    def test_string_numeric_conversion(self, sample_save_path):
        """Config values passed as numeric strings should be converted cleanly."""
        cfg = {
            "slots": "15",
            "loved_weight": "5",
            "liked_weight": "2",
            "vendor_boost": "2.5",
            "seasonal_boost": "3.0",
        }
        res = generate_plan(str(sample_save_path), config_dict=cfg)
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is None
        assert data["config"]["slots"] == 15
        assert data["config"]["vendor_boost"] == 2.5


# ==============================================================================
# 2. Date Override Boundaries & Special Keywords
# ==============================================================================

class TestDateOverridesStress:
    """Stress tests parse_date_override and date handling in generate_plan."""

    def test_all_four_seasons_boundaries(self):
        """Test Day 1 and Day 28 across Spring, Summer, Fall, Winter, and Autumn alias."""
        base_date = InGameDate(year=1, season="spring", day=1)
        cases = [
            ("spring 1", "spring", 1),
            ("spring 28", "spring", 28),
            ("summer 1", "summer", 1),
            ("summer 28", "summer", 28),
            ("fall 1", "fall", 1),
            ("fall 28", "fall", 28),
            ("winter 1", "winter", 1),
            ("winter 28", "winter", 28),
            ("autumn 15", "fall", 15),
        ]
        for text, expected_season, expected_day in cases:
            d = parse_date_override(text, base_date)
            assert d is not None, f"Failed to parse '{text}'"
            assert d.season.lower() == expected_season
            assert d.day == expected_day

    def test_out_of_range_days(self):
        """Days outside 1..28 like 0, 29, 30, 100 should not parse as valid in-range days."""
        base_date = InGameDate(year=1, season="spring", day=1)
        for bad_day in ("day 0", "day 29", "day 30", "day 100"):
            d = parse_date_override(bad_day, base_date)
            # Should either be None or clamped
            if d is not None:
                assert 1 <= d.day <= 28

    def test_negative_day_string(self):
        """Negative day string extracts available digit and stays bounded."""
        base_date = InGameDate(year=1, season="spring", day=1)
        d = parse_date_override("spring -5", base_date)
        assert d is not None
        assert 1 <= d.day <= 28

    def test_festival_keywords(self):
        """Verify all festival keywords map to designated in-game festival dates."""
        base_date = InGameDate(year=1, season="spring", day=1)
        festivals = [
            ("animal", "winter", 10),
            ("winter 10", "winter", 10),
            ("shooting", "summer", 28),
            ("summer 28", "summer", 28),
            ("harvest", "fall", 10),
            ("spring fest", "spring", 17),
        ]
        for kw, expected_season, expected_day in festivals:
            d = parse_date_override(kw, base_date)
            assert d is not None, f"Failed to parse festival keyword '{kw}'"
            assert d.season.lower() == expected_season
            assert d.day == expected_day

    def test_invalid_festivals_and_fake_strings(self):
        """Unrecognized festival strings or noise should return None (allowing fallback)."""
        base_date = InGameDate(year=1, season="spring", day=1)
        assert parse_date_override("fake festival xyz", base_date) is None
        assert parse_date_override("random gibberish", base_date) is None

    def test_saturday_keyword_month_and_year_rollover(self):
        """Verify Saturday keyword advances correctly, including month and year rollovers."""
        # Spring Day 28 (Sunday) -> next Saturday is next month Summer Day 6
        d_end_spring = InGameDate(year=1, season="spring", day=28)
        next_sat = parse_date_override("saturday", d_end_spring)
        assert next_sat is not None
        assert next_sat.season.lower() == "summer"
        assert next_sat.day == 6
        assert next_sat.year == 1

        # Winter Day 28 (Sunday) -> next Saturday rolls into next year Year 2 Spring Day 6
        d_end_winter = InGameDate(year=1, season="winter", day=28)
        next_sat_yr = parse_date_override("sat", d_end_winter)
        assert next_sat_yr is not None
        assert next_sat_yr.season.lower() == "spring"
        assert next_sat_yr.day == 6
        assert next_sat_yr.year == 2

    def test_json_date_override_boundaries(self):
        """JSON date overrides clamp day between 1 and 28 and handle autumn alias."""
        base_date = InGameDate(year=1, season="spring", day=1)

        d_valid = parse_date_override('{"season": "summer", "day": 15}', base_date)
        assert d_valid.season == "summer" and d_valid.day == 15

        d_autumn = parse_date_override('{"season": "autumn", "day": 28}', base_date)
        assert d_autumn.season == "fall" and d_autumn.day == 28

        d_clamp_high = parse_date_override('{"season": "winter", "day": 35}', base_date)
        assert d_clamp_high.day == 28

        d_clamp_low = parse_date_override('{"season": "spring", "day": -5}', base_date)
        assert d_clamp_low.day == 1

        # Malformed JSON should not crash
        assert parse_date_override("{malformed json", base_date) is None


# ==============================================================================
# 3. Corrupted and Adversarial Save Bytes
# ==============================================================================

class TestCorruptedAndAdversarialBytes:
    """Stress tests generate_plan against malformed, zero-length, and non-zlib binary data."""

    def test_zero_length_bytes(self):
        """Zero-length bytes should return canonical error schema with found=False."""
        res = generate_plan(b"", filename="zero_length.sav")
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False
        assert data["save_info"]["filename"] == "zero_length.sav"
        assert data["bag_plan"] == []

    def test_single_byte(self):
        """Single byte b'\x00' should return canonical error schema with found=False."""
        res = generate_plan(b"\x00", filename="single_byte.sav")
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False

    def test_random_binary_bytes(self):
        """Random binary stream should return canonical error schema with found=False."""
        random_bytes = os.urandom(128)
        res = generate_plan(random_bytes, filename="random.sav")
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False

    def test_truncated_save_bytes(self, sample_save_bytes):
        """Truncating a valid save file at various lengths should result in graceful error handling."""
        for length in (10, 50, 100, len(sample_save_bytes) // 2):
            res = generate_plan(sample_save_bytes[:length], filename=f"trunc_{length}.sav")
            data = json.loads(res)
            assert_canonical_schema(data)
            assert data["error"] is not None
            assert data["save_info"]["found"] is False

    def test_zlib_decompressed_corrupt_data(self):
        """Valid zlib stream containing empty data should be caught by parser and return canonical error."""
        compressed_empty = zlib.compress(b"")
        res = generate_plan(compressed_empty, filename="compressed_empty.sav")
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False

    def test_zlib_header_with_garbage(self):
        """Valid zlib magic header followed by random garbage."""
        corrupt_zlib = b"\x78\x9c" + os.urandom(64)
        res = generate_plan(corrupt_zlib, filename="corrupt_zlib.sav")
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False


# ==============================================================================
# 4. Sequential Stability, Memory Consistency & Cache Immutability
# ==============================================================================

class TestCacheStabilityAndSequentialStress:
    """Stress tests static database cache immutability and multi-run stability."""

    def test_static_cache_immutability_50_runs(self, sample_save_path):
        """Verify _CACHED_DATA is not mutated or polluted across 50 diverse sequential runs."""
        init_bridge("web/data")

        # Snapshot cache lengths before
        before_state = {
            "all_recipes": len(web_bridge._CACHED_DATA["all_recipes"]),
            "item_locations": len(web_bridge._CACHED_DATA["item_locations"]),
            "recipe_sources": len(web_bridge._CACHED_DATA["recipe_sources"]),
            "item_seasons": len(web_bridge._CACHED_DATA["item_seasons"]),
            "alt_sources": len(web_bridge._CACHED_DATA["alt_sources"]),
            "npc_definitions": len(web_bridge._CACHED_DATA["npc_definitions"]),
            "metadata": len(web_bridge._CACHED_DATA["metadata"]),
        }

        # Run 50 iterations with varying configs, date overrides, focus mode, and bad bytes
        for i in range(50):
            cfg = {
                "slots": (i % 25) + 1,
                "strategy": "max-relationship" if i % 2 == 0 else "journal",
                "date_override": f"fall {(i % 28) + 1}",
                "focus_mode_enabled": (i % 3 == 0),
                "focus_npcs": "adeline,balor" if i % 3 == 0 else "",
                "exclude_npcs": "celine" if i % 4 == 0 else "",
                "all_seasons": (i % 5 == 0),
            }
            if i % 10 == 0:
                res = generate_plan(b"corrupted_bytes_stream", config_dict=cfg)
            else:
                res = generate_plan(str(sample_save_path), config_dict=cfg)
            data = json.loads(res)
            assert_canonical_schema(data)

        # Snapshot cache lengths after
        after_state = {
            "all_recipes": len(web_bridge._CACHED_DATA["all_recipes"]),
            "item_locations": len(web_bridge._CACHED_DATA["item_locations"]),
            "recipe_sources": len(web_bridge._CACHED_DATA["recipe_sources"]),
            "item_seasons": len(web_bridge._CACHED_DATA["item_seasons"]),
            "alt_sources": len(web_bridge._CACHED_DATA["alt_sources"]),
            "npc_definitions": len(web_bridge._CACHED_DATA["npc_definitions"]),
            "metadata": len(web_bridge._CACHED_DATA["metadata"]),
        }

        assert before_state == after_state, f"Cache mutation detected! Before: {before_state}, After: {after_state}"

    def test_concurrent_execution_unique_filenames(self, sample_save_bytes):
        """Verify concurrent execution across 8 threads with distinct filenames completes with 100% success."""
        def run_task(idx):
            cfg = {"slots": 10 + (idx % 5)}
            res = generate_plan(
                sample_save_bytes,
                config_dict=cfg,
                filename=f"concurrent_test_{idx}.sav",
            )
            data = json.loads(res)
            assert_canonical_schema(data)
            assert data["error"] is None
            return data["stats"]["max_slots"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(run_task, i) for i in range(32)]
            results = [f.result() for f in futures]

        assert len(results) == 32

    def test_concurrent_shared_filename_resilience(self, sample_save_bytes):
        """When multiple threads share the same filename and encounter I/O collision, verify no uncaught crash."""
        def run_task(idx):
            res = generate_plan(
                sample_save_bytes,
                config_dict={"slots": 10},
                filename="shared_concurrent.sav",
            )
            data = json.loads(res)
            assert_canonical_schema(data)
            # Response is either successful plan or canonical error payload; never an uncaught crash
            return data["error"] is None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(run_task, i) for i in range(24)]
            # Check all tasks returned valid parseable data without unhandled exception
            completed = [f.result() for f in futures]

        assert len(completed) == 24


# ==============================================================================
# 5. Strict Canonical JSON Schema Conformance
# ==============================================================================

class TestStrictJsonSchemaConformance:
    """Verifies strict adherence to canonical PlanData JSON structure."""

    def test_all_outputs_json_parseable_and_dumpable(self, sample_save_path):
        """Verify json.loads and json.dumps roundtrip for normal and date override plans."""
        for override in (None, "spring 10", "winter 28"):
            res = generate_plan(str(sample_save_path), config_dict={"date_override": override})
            data = json.loads(res)
            assert_canonical_schema(data)
            # Verify clean re-serialization
            dumped = json.dumps(data)
            assert len(dumped) > 100

    def test_no_save_provided_synthesizes_valid_plan(self):
        """When save_data is None, generate_plan should produce valid canonical JSON without raising."""
        res = generate_plan(None, config_dict={"slots": 10})
        data = json.loads(res)
        assert_canonical_schema(data)
        assert data["save_info"]["found"] is False
        assert data["save_info"]["player_name"] == "Player"
        assert len(data["bag_plan"]) > 0
