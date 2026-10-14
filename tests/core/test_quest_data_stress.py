"""
test_quest_data_stress.py

Adversarial stress-test harness for load_quest_data() in fom_planner/data_loader.py:
1. Verify 100% exclusion of all 12 Mission Quest entries.
2. Verify 100% exclusion of all 14 generic placeholder categories.
3. Verify bidirectional item alias lookup across canonical and alias keys.
4. Verify graceful handling of corrupt JSON, empty files, missing files, non-dict payloads.
5. Verify cryptographic hash parity across data/quest_data.json, web/data/quest_data.json,
   and source /home/tyrell/Minh/fom-gift-mod/data/quest_indicator_data.json.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from fom_planner.constants import DEFAULT_QUEST_DATA_PATH
from fom_planner.data_loader import (
    GENERIC_QUEST_PLACEHOLDERS,
    QUEST_ITEM_ALIASES,
    load_quest_data,
)

SOURCE_QUEST_DATA_PATH = Path("/home/tyrell/Minh/fom-gift-mod/data/quest_indicator_data.json")
CORE_QUEST_DATA_PATH = Path("data/quest_data.json")
WEB_QUEST_DATA_PATH = Path("web/data/quest_data.json")

MISSION_QUEST_KEYS = [
    "green_saplings",
    "any_rockclod",
    "green_mushroom",
    "blue_enchanterns",
    "green_stalagmites",
    "blue_essence_bats",
    "mimics",
    "flame_spirits",
    "lava_cats",
    "flying_tomes",
    "rock_stacks",
    "living_gryphon_statues",
]

REQUIRED_BIDIRECTIONAL_PAIRS = [
    ("cow_milk", "milk"),
    ("basic_wood", "wood"),
    ("ore_stone", "stone"),
    ("breath_of_fire", "breath_of_flame"),
    ("shards", "archeology_shard"),
    ("feather", "rooster_feather"),
]


# ==============================================================================
# 1. Mission Quest 100% Exclusion Tests
# ==============================================================================


class TestMissionQuestExclusion:
    """Stress tests ensuring Mission Quests are 100% excluded under all conditions."""

    def test_all_12_mission_quest_keys_absent_from_bundled_data(self):
        """Checks that all 12 known monster-hunt Mission Quest keys are 100% absent."""
        qd = load_quest_data()
        assert len(MISSION_QUEST_KEYS) == 12

        for key in MISSION_QUEST_KEYS:
            assert key not in qd, f"Mission Quest '{key}' unexpectedly found in returned dict"

    def test_no_returned_item_contains_mission_quest(self):
        """Iterates through every single quest in the entire returned dataset to assert 0 Mission Quests."""
        qd = load_quest_data()
        assert len(qd) > 0

        for item_id, item_info in qd.items():
            assert "quests" in item_info, f"Item {item_id} missing 'quests' list"
            assert "quest_types" in item_info, f"Item {item_id} missing 'quest_types' list"
            assert "Mission Quest" not in item_info["quest_types"], (
                f"Item {item_id} has 'Mission Quest' in quest_types: {item_info['quest_types']}"
            )
            for q in item_info["quests"]:
                cat = q.get("category")
                qtype = q.get("quest_type")
                assert cat != "Mission Quest", (
                    f"Item {item_id} has quest with category='Mission Quest': {q}"
                )
                assert qtype != "Mission Quest", (
                    f"Item {item_id} has quest with quest_type='Mission Quest': {q}"
                )

    def test_synthetic_mission_quest_purged_from_mixed_item(self, tmp_path: Path):
        """Item with mixed standard and Mission Quests has Mission Quests removed and totals updated."""
        mock_payload = {
            "item_quest_details": {
                "copper_ore": {
                    "name": "Copper Ore",
                    "total_required": 50,
                    "quest_types": ["Request", "Mission Quest"],
                    "quests": [
                        {
                            "quest_name": "Slay 10 Mimics",
                            "quest_type": "Mission Quest",
                            "category": "Mission Quest",
                            "amount": 10,
                        },
                        {
                            "quest_name": "Request for Copper Ore",
                            "quest_type": "Request",
                            "category": "Request",
                            "amount": 40,
                            "requester": "Olric",
                        },
                    ],
                }
            }
        }
        test_file = tmp_path / "mixed_quests.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert "copper_ore" in res
        entry = res["copper_ore"]
        assert entry["total_required"] == 40
        assert entry["quest_types"] == ["Request"]
        assert len(entry["quests"]) == 1
        assert entry["quests"][0]["quest_name"] == "Request for Copper Ore"

    def test_synthetic_item_with_only_mission_quests_discarded(self, tmp_path: Path):
        """If an item contains only Mission Quests, it must be omitted completely from result."""
        mock_payload = {
            "item_quest_details": {
                "mimic_hunter": {
                    "name": "Mimic Hunter",
                    "total_required": 15,
                    "quest_types": ["Mission Quest"],
                    "quests": [
                        {
                            "quest_name": "Defeat 15 Mimics",
                            "quest_type": "Mission Quest",
                            "category": "Mission Quest",
                            "amount": 15,
                        }
                    ],
                }
            }
        }
        test_file = tmp_path / "only_mission.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert "mimic_hunter" not in res
        assert res == {}


# ==============================================================================
# 2. Generic Placeholder 100% Exclusion Tests
# ==============================================================================


class TestGenericPlaceholderExclusion:
    """Stress tests ensuring generic placeholders are excluded from returned dict."""

    def test_placeholder_set_has_14_entries(self):
        """Verifies exactly 14 placeholder categories are registered."""
        assert len(GENERIC_QUEST_PLACEHOLDERS) == 14
        expected_placeholders = {
            "crop",
            "berry",
            "fish",
            "flower",
            "soup",
            "mine_forageable",
            "monster_part",
            "baked_dishes",
            "wool",
            "copper_tool",
            "dining_tables",
            "dining_chairs",
            "stone_path",
            "feather",
        }
        assert GENERIC_QUEST_PLACEHOLDERS == expected_placeholders

    def test_all_13_pure_generic_placeholders_absent_from_bundled_data(self):
        """Verifies that none of the 13 pure generic placeholders appear in load_quest_data()."""
        qd = load_quest_data()
        pure_placeholders = [p for p in GENERIC_QUEST_PLACEHOLDERS if p != "feather"]
        assert len(pure_placeholders) == 13

        for placeholder in pure_placeholders:
            assert placeholder not in qd, f"Pure generic placeholder '{placeholder}' found in quest data"

    def test_generic_feather_crown_request_purged(self):
        """
        Verifies that the generic placeholder entry for 'feather' (Crown Request: Animal Materials,
        amount 10) was 100% eliminated, and only Josephine's specific 'rooster_feather' quest remains.
        """
        qd = load_quest_data()
        assert "feather" in qd
        feather_entry = qd["feather"]

        # Ensure no Crown Request appears on feather
        for q in feather_entry["quests"]:
            assert q.get("category") != "Crown Request"
            assert "Animal Materials" not in q.get("quest_name", "")
            assert "Rooster Feathers" in q.get("quest_name", "")
            assert q.get("amount") == 4

        assert feather_entry["total_required"] == 4

    def test_synthetic_all_14_placeholders_only_yields_empty_dict(self, tmp_path: Path):
        """
        When given a synthetic dataset containing ONLY the 14 generic placeholders
        (and no specific rooster_feather quest), load_quest_data() must return exactly {}.
        """
        mock_payload = {
            "item_quest_details": {
                p: {
                    "name": p.replace("_", " ").title(),
                    "total_required": 10,
                    "quest_types": ["Crown Request"],
                    "quests": [
                        {
                            "quest_name": f"Crown Request: {p}",
                            "quest_type": "Crown Request",
                            "category": "Crown Request",
                            "amount": 10,
                            "requester": "Adeline",
                        }
                    ],
                }
                for p in GENERIC_QUEST_PLACEHOLDERS
            }
        }
        test_file = tmp_path / "all_placeholders.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert res == {}, f"Expected empty dict for pure placeholders, got keys: {list(res.keys())}"

    def test_whitespace_and_casing_in_placeholders(self, tmp_path: Path):
        """Placeholder matching strips whitespace and is case-insensitive."""
        mock_payload = {
            "item_quest_details": {
                "  Crop  ": {
                    "name": "Crop",
                    "total_required": 5,
                    "quests": [{"quest_name": "Req", "quest_type": "Request", "amount": 5}],
                },
                "BERRY": {
                    "name": "Berry",
                    "total_required": 5,
                    "quests": [{"quest_name": "Req", "quest_type": "Request", "amount": 5}],
                },
                "Fish": {
                    "name": "Fish",
                    "total_required": 5,
                    "quests": [{"quest_name": "Req", "quest_type": "Request", "amount": 5}],
                },
            }
        }
        test_file = tmp_path / "cased_placeholders.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert res == {}


# ==============================================================================
# 3. Item Alias Bidirectional Lookup Tests
# ==============================================================================


class TestItemAliasBidirectionalLookup:
    """Stress tests verifying bidirectional lookup between Wiki IDs and planner canonical IDs."""

    @pytest.mark.parametrize("canonical_key,alias_key", REQUIRED_BIDIRECTIONAL_PAIRS)
    def test_required_bidirectional_pairs(self, canonical_key: str, alias_key: str):
        """Checks both keys exist, equal each other, and point to the same object."""
        qd = load_quest_data()

        assert canonical_key in qd, f"Canonical key '{canonical_key}' missing from quest data"
        assert alias_key in qd, f"Alias key '{alias_key}' missing from quest data"

        # Content equality
        assert qd[canonical_key] == qd[alias_key], (
            f"Content mismatch between '{canonical_key}' and '{alias_key}'"
        )
        # Object identity (pointing to identical dictionary in memory)
        assert qd[canonical_key] is qd[alias_key], (
            f"Object identity mismatch: '{canonical_key}' and '{alias_key}' do not share dict reference"
        )

    def test_all_registered_aliases_bidirectional_in_bundled_data(self):
        """Checks all registered aliases present in bundled data are bidirectional."""
        qd = load_quest_data()

        checked_count = 0
        for alias_key, canonical_key in QUEST_ITEM_ALIASES.items():
            if alias_key in qd or canonical_key in qd:
                assert alias_key in qd, f"Registered alias '{alias_key}' missing while canonical present"
                assert canonical_key in qd, f"Canonical '{canonical_key}' missing while alias present"
                assert qd[alias_key] is qd[canonical_key]
                checked_count += 1

        assert checked_count >= 20, f"Expected at least 20 aliases active, found {checked_count}"

    def test_reverse_direction_synthetic_canonical_only(self, tmp_path: Path):
        """
        When input JSON provides only canonical key (e.g. 'cow_milk'),
        load_quest_data() must automatically populate the alias key ('milk') as well.
        """
        mock_payload = {
            "item_quest_details": {
                "cow_milk": {
                    "name": "Cow's Milk",
                    "total_required": 3,
                    "quest_types": ["Request"],
                    "quests": [
                        {
                            "quest_name": "Request for Milk",
                            "quest_type": "Request",
                            "category": "Request",
                            "amount": 3,
                            "requester": "Darcy",
                        }
                    ],
                }
            }
        }
        test_file = tmp_path / "canonical_input.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert "cow_milk" in res
        assert "milk" in res
        assert res["milk"] is res["cow_milk"]
        assert res["milk"]["total_required"] == 3

    def test_alias_merging_synthetic(self, tmp_path: Path):
        """
        When input JSON contains both alias and canonical keys with separate quests,
        they must be merged cleanly without duplicates.
        """
        mock_payload = {
            "item_quest_details": {
                "wood": {
                    "name": "Wood",
                    "total_required": 10,
                    "quest_types": ["Request"],
                    "quests": [
                        {
                            "quest_name": "Repair Wood Fence",
                            "quest_type": "Request",
                            "category": "Request",
                            "amount": 10,
                            "requester": "Celine",
                        }
                    ],
                },
                "basic_wood": {
                    "name": "Basic Wood",
                    "total_required": 25,
                    "quest_types": ["Story Quest"],
                    "quests": [
                        {
                            "quest_name": "Bridge Rebuilding",
                            "quest_type": "Story Quest",
                            "category": "Story Quest",
                            "amount": 25,
                            "requester": "Adeline",
                        }
                    ],
                },
            }
        }
        test_file = tmp_path / "merge_input.json"
        test_file.write_text(json.dumps(mock_payload), encoding="utf-8")

        res = load_quest_data(test_file)
        assert "wood" in res
        assert "basic_wood" in res
        assert res["wood"] is res["basic_wood"]

        merged = res["basic_wood"]
        assert merged["total_required"] == 35
        assert merged["quest_types"] == ["Request", "Story Quest"]
        assert len(merged["quests"]) == 2


# ==============================================================================
# 4. Corrupted JSON, Empty Files, Missing Files, Non-Dict Payloads
# ==============================================================================


class TestCorruptAndEdgeCaseFallback:
    """Stress tests ensuring graceful fallback to {} without uncaught exceptions."""

    def test_missing_file_paths(self):
        """Verifies nonexistent paths return {}."""
        assert load_quest_data("/nonexistent/path/file.json") == {}
        assert load_quest_data("does_not_exist_at_all.json") == {}

    def test_directory_passed_as_path(self, tmp_path: Path):
        """Passing a directory instead of a regular file returns {}."""
        sub_dir = tmp_path / "sub_directory"
        sub_dir.mkdir()
        assert load_quest_data(sub_dir) == {}

    def test_empty_file_0_bytes(self, tmp_path: Path):
        """Zero-byte file returns {}."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_bytes(b"")
        assert load_quest_data(empty_file) == {}

    def test_single_byte_corruptions(self, tmp_path: Path):
        """Single non-printable or invalid byte returns {}."""
        for byte_val in [b"\x00", b"\x80", b"\xff", b"\n", b" ", b"{"]:
            f = tmp_path / f"byte_{hash(byte_val)}.json"
            f.write_bytes(byte_val)
            assert load_quest_data(f) == {}

    def test_truncated_json_syntax(self, tmp_path: Path):
        """Truncated JSON syntax returns {}."""
        truncated_payloads = [
            '{"item_quest_details": {',
            '{"item_quest_details": {"wood": {"name": "Wood"',
            '{"item_quest_details": {"wood": {"quests": [',
            '{"item_quest_details": {"wood": {"quests": [{"quest_name": "foo"',
            '{"item_quest_details":',
            "{",
            "[",
        ]
        for idx, payload in enumerate(truncated_payloads):
            f = tmp_path / f"trunc_{idx}.json"
            f.write_text(payload, encoding="utf-8")
            assert load_quest_data(f) == {}

    def test_malformed_syntax_garbage(self, tmp_path: Path):
        """Arbitrary non-JSON text returns {}."""
        f = tmp_path / "garbage.json"
        f.write_text("<<<XML><HTML>This is definitely not JSON!!!</HTML></XML>", encoding="utf-8")
        assert load_quest_data(f) == {}

    def test_non_dict_root_payloads(self, tmp_path: Path):
        """JSON primitives and arrays as root return {}."""
        primitive_payloads = [
            "[]",
            "[1, 2, 3]",
            '["a", "b", "c"]',
            '""',
            '"hello world"',
            "12345",
            "3.14159",
            "true",
            "false",
            "null",
        ]
        for idx, payload in enumerate(primitive_payloads):
            f = tmp_path / f"primitive_{idx}.json"
            f.write_text(payload, encoding="utf-8")
            assert load_quest_data(f) == {}

    def test_malformed_item_quest_details_field(self, tmp_path: Path):
        """Non-dict item_quest_details field returns {}."""
        details_values = [
            None,
            "not a dict",
            12345,
            3.14,
            True,
            False,
            [],
            [{"name": "wood"}],
        ]
        for idx, val in enumerate(details_values):
            f = tmp_path / f"malformed_details_{idx}.json"
            f.write_text(json.dumps({"item_quest_details": val}), encoding="utf-8")
            assert load_quest_data(f) == {}

    def test_item_quest_details_contains_non_dict_elements(self, tmp_path: Path):
        """Elements inside item_quest_details that are not dicts are skipped gracefully."""
        payload = {
            "item_quest_details": {
                "item_null": None,
                "item_int": 42,
                "item_str": "string",
                "item_list": [1, 2, 3],
                "valid_item": {
                    "name": "Valid Item",
                    "quests": [
                        {"quest_name": "Valid Quest", "quest_type": "Request", "amount": 2}
                    ],
                },
            }
        }
        f = tmp_path / "mixed_elements.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        res = load_quest_data(f)
        assert len(res) == 1
        assert "valid_item" in res
        assert res["valid_item"]["total_required"] == 2

    def test_item_with_malformed_quests_list(self, tmp_path: Path):
        """Item with non-list or malformed quests list handled gracefully."""
        payload = {
            "item_quest_details": {
                "item_no_quests": {"name": "No Quests"},
                "item_quests_null": {"name": "Null Quests", "quests": None},
                "item_quests_str": {"name": "Str Quests", "quests": "not a list"},
                "item_quests_int": {"name": "Int Quests", "quests": 123},
                "item_quests_empty": {"name": "Empty Quests", "quests": []},
                "item_quests_non_dict_elems": {
                    "name": "Bad Elems",
                    "quests": [None, 123, "string", []],
                },
            }
        }
        f = tmp_path / "bad_quests_list.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        res = load_quest_data(f)
        assert res == {}

    def test_item_with_non_integer_amounts_caught_by_fallback(self, tmp_path: Path):
        """
        When quest amount cannot be parsed as integer, the try/except block
        safely catches the exception and returns {} without crashing.
        """
        payload = {
            "item_quest_details": {
                "bad_item": {
                    "name": "Bad Item",
                    "quests": [
                        {
                            "quest_name": "Bad Quest",
                            "quest_type": "Request",
                            "amount": "not_an_int",
                        }
                    ],
                }
            }
        }
        f = tmp_path / "bad_amount.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        res = load_quest_data(f)
        assert res == {}


# ==============================================================================
# 5. Cryptographic Hash Parity Verification
# ==============================================================================


class TestDatasetHashParity:
    """Verifies that data/quest_data.json and web/data/quest_data.json match source."""

    def _compute_hashes(self, path: Path):
        md5 = hashlib.md5()
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                md5.update(chunk)
                sha256.update(chunk)
        return md5.hexdigest(), sha256.hexdigest()

    def test_source_and_target_files_exist(self):
        """All three files must exist and be regular non-empty files."""
        assert SOURCE_QUEST_DATA_PATH.exists(), f"Source path {SOURCE_QUEST_DATA_PATH} not found"
        assert CORE_QUEST_DATA_PATH.exists(), f"Core path {CORE_QUEST_DATA_PATH} not found"
        assert WEB_QUEST_DATA_PATH.exists(), f"Web path {WEB_QUEST_DATA_PATH} not found"

        assert SOURCE_QUEST_DATA_PATH.stat().st_size > 50000
        assert CORE_QUEST_DATA_PATH.stat().st_size > 50000
        assert WEB_QUEST_DATA_PATH.stat().st_size > 50000

    def test_md5sum_parity(self):
        """Verifies exact MD5 match across all three datasets."""
        source_md5, source_sha = self._compute_hashes(SOURCE_QUEST_DATA_PATH)
        core_md5, core_sha = self._compute_hashes(CORE_QUEST_DATA_PATH)
        web_md5, web_sha = self._compute_hashes(WEB_QUEST_DATA_PATH)

        assert core_md5 == source_md5, f"Core MD5 {core_md5} != source MD5 {source_md5}"
        assert web_md5 == source_md5, f"Web MD5 {web_md5} != source MD5 {source_md5}"
        assert core_sha == source_sha, f"Core SHA256 {core_sha} != source SHA256 {source_sha}"
        assert web_sha == source_sha, f"Web SHA256 {web_sha} != source SHA256 {source_sha}"

        # Expected source md5 recorded in spec
        assert source_md5 == "8757d9a391a67e456942c799fb390f71"
