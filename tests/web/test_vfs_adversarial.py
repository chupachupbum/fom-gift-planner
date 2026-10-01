"""
tests/test_tier5_adversarial_hardening.py

Milestone 5 Phase 2: Tier 5 Adversarial Coverage Hardening Suite.
Comprehensive white-box empirical stress and vulnerability testing for the
client-side Fields of Mistria gift planner web application:

1. Deep boundary values & malformed inputs:
   - Truncated gzip streams (from 1 to 20 bytes, cut off headers, mid-stream truncations).
   - Incomplete and corrupted length-prefixed binary save chunks.
   - Syntax-corrupted JSON within save blocks (header, player, npcs).
   - Extreme timestamps (negative infinity, calendar overflow, NaN strings, out-of-bounds clock).
   - Corrupted inventory item payloads (missing ids, negative/string counts, null items).
   - Corrupted NPC affection payloads (nulls, string values, extreme numbers, invalid flags).
   - Malformed configuration inputs (broken JSON, invalid types, oversized key payloads).

2. Pyodide VFS file collision & overwriting edge cases:
   - Sequential plan generation overwriting /tmp/upload.sav with alternating distinct saves.
   - Path traversal and directory escape attempts in save filenames (../../etc/passwd, subdir).
   - VFS file overwriting with shrinking payload sizes (preventing stale byte leaks).
   - Worker message protocol simulation in Node.js (consecutive plans, recomputes, error handling).

3. Complex crafting tree dependency cycles and unreachable items:
   - Direct 2-node cyclic recipe dependencies (A -> B -> A).
   - Self-referential recipe loops (A -> A).
   - Multi-node indirect cycles (A -> B -> C -> D -> A).
   - Deep crafting dependency chains (40 levels deep DAG).
   - Unreachable / fabricated ingredient items not present in any game database.
   - Recipes with zero and negative ingredient quantities.

4. Extreme settings combinations:
   - Bag slots: 0 slots, negative slots, 1 slot, 1000 slots, float/string representations.
   - Contradictory filters: overlapping focus_npcs and exclude_npcs with focus_mode_enabled.
   - Total NPC exclusion: all 35 townspeople excluded simultaneously.
   - Focus mode active with empty focus_npcs string.
   - Extreme and zero scoring multipliers (0 loved/liked weight, 0 boosts, 1,000,000x boosts).
   - Unrecognized strategy and mode strings (graceful fallbacks).

5. Character encoding / Unicode in save file names and player names:
   - Unicode in player name and farm name (Japanese Kanji/Kana, Vietnamese diacritics, Emoji, RTL Arabic).
   - HTML and XSS injection payloads in names (<script>, <img>).
   - Unicode and special symbols in save filenames.
   - Client-side SVG placeholder generator verification with Unicode and punctuation.
"""

import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET
import zlib

import pytest

from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import (
    build_focus_crafting_trees,
    plan_daily_gift_bag,
    plan_max_relationship,
    resolve_root_raw_materials,
)
from fom_planner.parser import parse_save_file
from web.py import web_bridge
from web.py.web_bridge import (
    WebPlannerConfig,
    generate_plan,
    init_bridge,
    parse_date_override,
    plan_to_json,
    run_plan_from_vfs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SAVE_PATH = REPO_ROOT / "samples" / "sample_save.sav"
WEB_WORKER_PATH = REPO_ROOT / "web" / "planner.worker.js"
WEB_APP_PATH = REPO_ROOT / "web" / "app.js"

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

# Detect Node.js binary
NODE_CANDIDATES = [
    shutil.which("node"),
    os.path.expanduser("~/.nvm/versions/node/v22.22.1/bin/node"),
    os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/node"),
]
NODE_BIN = next((p for p in NODE_CANDIDATES if p and os.path.exists(p)), None)


@pytest.fixture(scope="module", autouse=True)
def ensure_bridge_initialized():
    """Ensure in-memory game databases are initialized."""
    init_bridge("web/data")


def assert_canonical_schema(payload: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Helper asserting valid JSON and presence of all 16 canonical schema keys."""
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except Exception as e:
            pytest.fail(f"Payload is not valid JSON: {e}\nContent snippet: {payload[:200]}")
    else:
        data = payload

    assert isinstance(data, dict), f"Plan payload is not a dict: {type(data)}"
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
    return data


def build_raw_synthetic_save(
    header_json: Optional[str] = None,
    player_json: Optional[str] = None,
    npcs_json: Optional[str] = None,
    gamedata_json: Optional[str] = None,
    player_name: str = "TestHero",
    farm_name: str = "SunnyFarm",
    calendar_time: int = 0,
    inventory: Optional[List[Dict[str, Any]]] = None,
    npc_dict: Optional[Dict[str, Any]] = None,
) -> bytes:
    """Constructs a binary compressed .sav file with customizable raw JSON blocks."""
    if header_json is None:
        header_json = json.dumps({
            "name": player_name,
            "farm_name": farm_name,
            "calendar_time": calendar_time,
            "clock_time": 36000,
            "playtime": 18000.0,
        })

    if player_json is None:
        player_json = json.dumps({
            "name": player_name,
            "farm_name": farm_name,
            "inventory": inventory or [],
        })

    if npcs_json is None:
        npcs_json = json.dumps(npc_dict or {})

    if gamedata_json is None:
        gamedata_json = json.dumps({"date": calendar_time})

    raw_blocks: Dict[str, str] = {
        "header": header_json,
        "player": player_json,
        "npcs": npcs_json,
        "gamedata": gamedata_json,
        "game_stats": "{}",
        "quests": "{}",
        "info": "{}",
    }

    body = bytearray()
    body.extend(struct.pack("<Q", len(raw_blocks)))
    for key, val_str in raw_blocks.items():
        kb = key.encode("utf-8")
        vb = val_str.encode("utf-8")
        body.extend(struct.pack("<Q", len(kb)))
        body.extend(kb)
        body.extend(struct.pack("<Q", len(vb)))
        body.extend(vb)

    return zlib.compress(bytes(body))


# ==============================================================================
# SECTION 1: Deep Boundary Values & Malformed Inputs
# ==============================================================================

class TestDeepBoundaryValuesAndMalformedInputs:
    """Stress tests truncated binary streams, corrupted JSON blocks, extreme numbers, and bad types."""

    @pytest.mark.parametrize("length", [1, 2, 5, 10, 15, 20])
    def test_truncated_gzip_stream_prefixes(self, length: int):
        """Truncated gzip streams must be caught safely, returning valid 16-key JSON error schema."""
        full_bytes = build_raw_synthetic_save()
        truncated = full_bytes[:length]

        raw_json = generate_plan(truncated, filename="truncated.sav")
        data = assert_canonical_schema(raw_json)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False
        assert data["save_info"]["filename"] == "truncated.sav"
        assert len(data["bag_plan"]) == 0

    def test_corrupted_gzip_crc_and_payload_tail(self):
        """Valid gzip header with garbage tail payload."""
        full_bytes = build_raw_synthetic_save()
        # Keep first 12 bytes of valid gzip header, replace rest with random garbage
        corrupted = full_bytes[:12] + b"\xff\x00\xaa\x55" * 16

        raw_json = generate_plan(corrupted, filename="bad_crc.sav")
        data = assert_canonical_schema(raw_json)
        assert data["error"] is not None
        assert data["save_info"]["found"] is False

    def test_corrupted_length_prefixed_binary_chunks(self):
        """Save stream with invalid chunk length claiming 100MB of data when only 10 bytes exist.
        parse_save_file defends against truncated chunks by breaking gracefully.
        """
        # Uncompressed body with bogus block length
        body = bytearray()
        body.extend(struct.pack("<Q", 5))  # Claims 5 blocks
        body.extend(struct.pack("<Q", 9999999))  # Key length 9,999,999 bytes
        body.extend(b"short_key")
        bogus_bytes = zlib.compress(bytes(body))

        raw_json = generate_plan(bogus_bytes, filename="bogus_lengths.sav")
        data = assert_canonical_schema(raw_json)
        # Parser gracefully breaks loop without crashing, returning default save
        assert data["error"] is None
        assert data["save_info"]["found"] is True

    def test_syntax_corrupted_json_in_header_block(self):
        """Gzip structure is valid, but 'header' block contains malformed JSON syntax.
        SaveData._safe_json falls back to empty dict, and player_name falls back to player block or 'Player'.
        """
        # 1. Header broken, player valid -> recovers player_name from player block
        broken_header_save = build_raw_synthetic_save(header_json='{"name": "Broken", "unclosed_string: 123')
        data1 = assert_canonical_schema(generate_plan(broken_header_save, filename="broken_header.sav"))
        assert data1["error"] is None
        assert data1["save_info"]["player_name"] in ("Player", "TestHero")

        # 2. Both header and player broken -> falls back to 'Player'
        both_broken_save = build_raw_synthetic_save(
            header_json='{"name": "Broken',
            player_json='{"name": "Broken',
        )
        data2 = assert_canonical_schema(generate_plan(both_broken_save, filename="both_broken.sav"))
        assert data2["error"] is None
        assert data2["save_info"]["player_name"] == "Player"
        assert data2["save_info"]["farm_name"] == "Farm"

    def test_syntax_corrupted_json_in_player_block(self):
        """Player block has syntax error. SaveData._safe_json gracefully recovers."""
        broken_save = build_raw_synthetic_save(player_json='{"name": "Hero", "inventory": [not_json]}')
        raw_json = generate_plan(broken_save, filename="broken_player.sav")
        data = assert_canonical_schema(raw_json)
        assert data["error"] is None
        assert data["save_info"]["found"] is True

    def test_extreme_and_overflow_timestamps(self):
        """Stress-test extreme calendar timestamps: negative, gigantic overflow, and zero."""
        # Calendar time: negative 10 million seconds
        neg_save = build_raw_synthetic_save(calendar_time=-10_000_000)
        data_neg = assert_canonical_schema(generate_plan(neg_save, filename="neg_time.sav"))
        assert data_neg["error"] is None
        assert data_neg["save_info"]["found"] is True

        # Calendar time: Year 50,000+
        huge_time = 50_000 * 112 * 86400
        huge_save = build_raw_synthetic_save(calendar_time=huge_time)
        data_huge = assert_canonical_schema(generate_plan(huge_save, filename="huge_time.sav"))
        assert data_huge["error"] is None
        assert data_huge["in_game_date"]["year"] >= 50000

    def test_malformed_inventory_items(self):
        """Inventory contains null items, items missing IDs, and non-numeric counts."""
        corrupted_inventory = [
            {"count": -10, "item": {"item_id": "turnip"}},
            {"count": "many", "item": {"item_id": "cabbage"}},
            {"count": 5, "item": None},
            {"count": 2, "item": {"item_id": None}},
            {"count": 0, "item": {"item_id": "wood"}},
            {"count": 1, "item": {"item_id": "chocolate"}},
        ]
        save_bytes = build_raw_synthetic_save(inventory=corrupted_inventory)
        raw_json = generate_plan(save_bytes, filename="bad_inventory.sav")
        data = assert_canonical_schema(raw_json)
        # Should not crash; valid items (chocolate) should still be handled
        assert data["error"] is None
        assert data["save_info"]["found"] is True

    def test_corrupted_affection_payloads(self):
        """NPC affection data has extreme numbers and invalid types."""
        # 1. Extreme numbers in valid dicts should succeed cleanly
        numeric_extreme_npcs = {
            "adeline": {"heart_points": -999.0, "affection": -999.0, "gift_flag": False},
            "celine": {"heart_points": 1e12, "affection": 1e12, "gift_flag": True},
        }
        save_bytes1 = build_raw_synthetic_save(npc_dict=numeric_extreme_npcs)
        data1 = assert_canonical_schema(generate_plan(save_bytes1, filename="num_npcs.sav"))
        assert data1["error"] is None
        assert "adeline" in data1["npc_progress"]

        # 2. Non-dict NPC entry causes core model AttributeError, captured safely by bridge
        bad_npcs = {
            "adeline": {"heart_points": 500.0, "affection": 500.0, "gift_flag": True},
            "march": "not_even_a_dict",
        }
        save_bytes2 = build_raw_synthetic_save(npc_dict=bad_npcs)
        data2 = assert_canonical_schema(generate_plan(save_bytes2, filename="bad_npcs.sav"))
        # Bridge catches exception from models.py and emits canonical schema with error recorded
        assert data2["error"] is not None

    def test_malformed_and_bloated_config_payloads(self):
        """Invalid JSON config strings, invalid types, and bloated configurations."""
        save_bytes = build_raw_synthetic_save()

        # Broken JSON string
        raw1 = generate_plan(save_bytes, config_dict="{invalid_json_here")
        assert_canonical_schema(raw1)

        # Config with wrong data types
        raw2 = generate_plan(
            save_bytes,
            config_dict={
                "slots": "not_an_int",
                "loved_weight": "heavy",
                "vendor_boost": [1, 2, 3],
                "force_all_npcs": "yes",
            },
        )
        assert_canonical_schema(raw2)

        # Huge config payload with 1,000 extra dummy keys
        bloated_config = {f"dummy_key_{i}": f"value_{i}" * 10 for i in range(1000)}
        bloated_config["slots"] = 15
        raw3 = generate_plan(save_bytes, config_dict=bloated_config)
        data3 = assert_canonical_schema(raw3)
        assert data3["stats"]["max_slots"] == 15


# ==============================================================================
# SECTION 2: Pyodide VFS File Collision & Overwriting Edge Cases
# ==============================================================================

class TestPyodideVFSCollisionsAndOverwriting:
    """Verifies filesystem isolation, sequential overwrites, directory escape, and worker protocol."""

    def test_sequential_save_overwriting_same_vfs_path(self):
        """
        Rapid sequential writes to /tmp/upload.sav with completely different save files.
        Ensures Plan B never contains residual data from Plan A.
        """
        # Save A: Player "AlphaHero", Spring 1, Inventory Turnip
        save_a = build_raw_synthetic_save(
            player_name="AlphaHero",
            farm_name="AlphaFarm",
            calendar_time=0,  # Spring 1 Year 1
            inventory=[{"count": 10, "item": {"item_id": "turnip"}}],
        )

        # Save B: Player "OmegaHero", Fall 20, Inventory Diamond
        save_b = build_raw_synthetic_save(
            player_name="OmegaHero",
            farm_name="OmegaFarm",
            calendar_time=75 * 86400,  # Fall 20 Year 1
            inventory=[{"count": 5, "item": {"item_id": "ore_diamond"}}],
        )

        plan_a_json = generate_plan(save_a, filename="upload.sav")
        plan_a = assert_canonical_schema(plan_a_json)
        assert plan_a["save_info"]["player_name"] == "AlphaHero"
        assert plan_a["save_info"]["farm_name"] == "AlphaFarm"
        assert plan_a["in_game_date"]["season"] == "Spring"

        # Overwrite with Save B using same filename and default path
        plan_b_json = generate_plan(save_b, filename="upload.sav")
        plan_b = assert_canonical_schema(plan_b_json)
        assert plan_b["save_info"]["player_name"] == "OmegaHero"
        assert plan_b["save_info"]["farm_name"] == "OmegaFarm"
        assert plan_b["in_game_date"]["season"] in ("Autumn", "Fall")
        assert plan_b["save_info"]["player_name"] != plan_a["save_info"]["player_name"]

    def test_vfs_file_overwriting_with_shrinking_payload_size(self):
        """
        Writing a large save file followed by a much smaller save file.
        Verifies that file truncation is complete and no tail bytes from the large save persist.
        """
        # Large save: 100 inventory items
        large_inv = [{"count": i + 1, "item": {"item_id": f"item_{i}"}} for i in range(100)]
        large_save = build_raw_synthetic_save(player_name="LargeHero", inventory=large_inv)

        # Small save: 0 inventory items
        small_save = build_raw_synthetic_save(player_name="SmallHero", inventory=[])

        assert len(large_save) > len(small_save)

        res_large = assert_canonical_schema(generate_plan(large_save, filename="shrink_test.sav"))
        assert res_large["save_info"]["player_name"] == "LargeHero"

        res_small = assert_canonical_schema(generate_plan(small_save, filename="shrink_test.sav"))
        assert res_small["save_info"]["player_name"] == "SmallHero"
        assert res_small["error"] is None

    @pytest.mark.parametrize(
        "escape_name",
        [
            "../../etc/passwd",
            "../upload.sav",
            "/tmp/upload.sav",
            "subdir/nested.sav",
            "nested\\win\\save.sav",
            "save_with_null\x00.sav",
        ],
    )
    def test_filename_path_traversal_and_directory_escape(self, escape_name: str):
        """Filename path traversal attempts must be handled safely without unhandled OS error."""
        save_bytes = build_raw_synthetic_save()
        res_json = generate_plan(save_bytes, filename=escape_name)
        data = assert_canonical_schema(res_json)
        # Must return valid schema, not crash or escape
        assert data["save_info"]["filename"] == escape_name or data["error"] is not None

    def test_run_plan_from_vfs_nonexistent_path(self):
        """Calling run_plan_from_vfs with non-existent path handles error cleanly."""
        res_json = run_plan_from_vfs("/tmp/does_not_exist_at_all_99999.sav")
        data = assert_canonical_schema(res_json)
        assert data["save_info"]["found"] is False
        assert isinstance(data["bag_plan"], list)

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available in environment")
    def test_node_worker_vfs_sequential_plan_and_recompute(self):
        """
        Executes Node.js harness against web/planner.worker.js simulating Pyodide worker runtime:
        1. handlePlan(SaveA)
        2. handlePlan(SaveB) with identical filename upload.sav (collision)
        3. handleRecompute() verifying SaveB's state is preserved.
        """
        node_script = f"""
        const fs = require('fs');
        const vm = require('vm');

        const workerCode = fs.readFileSync('{WEB_WORKER_PATH.as_posix()}', 'utf8');

        const messages = [];
        const vfs = {{}};

        const mockPyodide = {{
          FS: {{
            mkdirTree: (p) => {{}},
            writeFile: (p, data) => {{ vfs[p] = data; }},
            analyzePath: (p) => ({{ exists: p in vfs }}),
          }},
          loadPackage: async () => {{}},
          pyimport: (name) => {{
            if (name === 'micropip') return {{ install: async () => {{}} }};
            if (name === 'web_bridge') {{
              return {{
                generate_plan: (filePath, configStr, filename) => {{
                  const bytes = vfs[filePath];
                  const isSaveB = bytes && bytes[0] === 0x42; // Tag byte 'B'
                  return JSON.stringify({{
                    generated_at: new Date().toISOString(),
                    save_info: {{ found: true, filename: filename, player_name: isSaveB ? "PlayerB" : "PlayerA" }},
                    in_game_date: {{ year: 1, season: "Spring", day: 1 }},
                    config: {{}},
                    stats: {{ max_slots: 20, slots_used: 0 }},
                    completed_npcs_details: [],
                    incomplete_npcs_details: [],
                    unobtained_recipes: [],
                    recipe_stats: {{}},
                    infused_items: [],
                    bag_plan: [],
                    focus_suggestions: [],
                    focus_trees: [],
                    source_priority: [],
                    npc_progress: {{}},
                    error: null
                  }});
                }}
              }};
            }}
            return {{}};
          }},
          runPython: () => {{}}
        }};

        const context = {{
          self: {{
            location: {{ href: 'http://localhost:8000/web/' }},
            postMessage: (msg) => messages.push(msg),
            importScripts: () => {{}},
          }},
          loadPyodide: async () => mockPyodide,
          fetch: async (url) => ({{
            ok: true,
            status: 200,
            text: async () => url.endsWith('web_bridge.py') ? 'def generate_plan(): pass' : '{{}}'
          }}),
          performance: {{ now: () => Date.now() }},
          console: console,
          Uint8Array: Uint8Array,
          JSON: JSON,
          URL: URL,
          Promise: Promise,
          Error: Error,
        }};

        vm.createContext(context);
        vm.runInContext(workerCode, context);

        async function run() {{
          // 1. Init
          await context.self.onmessage({{ data: {{ action: 'init' }} }});

          // 2. Plan Save A
          const saveA = new Uint8Array([0x41, 0x01, 0x02]);
          await context.self.onmessage({{ data: {{ action: 'plan', saveBytes: saveA, filename: 'upload.sav' }} }});

          // 3. Plan Save B (collision on upload.sav)
          const saveB = new Uint8Array([0x42, 0x03, 0x04]);
          await context.self.onmessage({{ data: {{ action: 'plan', saveBytes: saveB, filename: 'upload.sav' }} }});

          // 4. Recompute with new config
          await context.self.onmessage({{ data: {{ action: 'recompute', config: {{ slots: 25 }} }} }});

          // 5. Error path: plan with missing saveBytes
          await context.self.onmessage({{ data: {{ action: 'plan' }} }});

          console.log(JSON.stringify(messages));
        }}

        run().catch(err => {{
          console.error(err);
          process.exit(1);
        }});
        """
        proc = subprocess.run([NODE_BIN, "-e", node_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node worker simulation failed:\n{proc.stderr}"
        messages = json.loads(proc.stdout)

        actions = [m.get("action") for m in messages]
        assert "ready" in actions
        results = [m for m in messages if m.get("action") == "result"]
        assert len(results) == 3

        # First result is PlayerA
        assert results[0]["plan"]["save_info"]["player_name"] == "PlayerA"
        # Second result is PlayerB
        assert results[1]["plan"]["save_info"]["player_name"] == "PlayerB"
        # Third result (recompute) retains PlayerB, not PlayerA!
        assert results[2]["plan"]["save_info"]["player_name"] == "PlayerB"

        # Fifth call triggered error action
        errors = [m for m in messages if m.get("action") == "error"]
        assert len(errors) >= 1
        assert "saveBytes" in errors[0]["message"]


# ==============================================================================
# SECTION 3: Crafting Dependency Cycles & Unreachable Items
# ==============================================================================

class TestCraftingDependencyCyclesAndUnreachableItems:
    """Stress tests circular recipes, self-loops, deep chains, and fabricated ingredients."""

    def test_synthetic_direct_2_node_recipe_cycle(self):
        """
        Recipe A produces item_alpha requiring item_beta.
        Recipe B produces item_beta requiring item_alpha.
        Both resolve_root_raw_materials and build_focus_crafting_trees must terminate without RecursionError.
        """
        cyclic_recipes = {
            "item_alpha": {
                "item_id": "item_alpha",
                "display_name": "Alpha Item",
                "ingredients": [{"item_id": "item_beta", "count": 1}],
            },
            "item_beta": {
                "item_id": "item_beta",
                "display_name": "Beta Item",
                "ingredients": [{"item_id": "item_alpha", "count": 1}],
            },
        }

        # 1. Test root raw materials resolver
        roots_alpha = resolve_root_raw_materials("item_alpha", cyclic_recipes)
        assert isinstance(roots_alpha, dict)

        # 2. Test focus crafting trees builder
        focus_suggestions = [
            {"item_id": "item_alpha", "deficit": 2, "impact_score": 10},
            {"item_id": "item_beta", "deficit": 1, "impact_score": 5},
        ]
        trees = build_focus_crafting_trees(focus_suggestions, recipes=cyclic_recipes)
        assert isinstance(trees, list)
        assert len(trees) == 2

    def test_synthetic_self_referential_cycle(self):
        """Recipe requires itself as an ingredient (A -> A)."""
        ouroboros_recipes = {
            "ouroboros": {
                "item_id": "ouroboros",
                "display_name": "Ouroboros",
                "ingredients": [{"item_id": "ouroboros", "count": 2}],
            }
        }
        roots = resolve_root_raw_materials("ouroboros", ouroboros_recipes)
        assert isinstance(roots, dict)

        focus_suggestions = [{"item_id": "ouroboros", "deficit": 1, "impact_score": 5}]
        trees = build_focus_crafting_trees(focus_suggestions, recipes=ouroboros_recipes)
        assert len(trees) == 1
        assert trees[0]["item_id"] == "ouroboros"

    def test_multi_node_indirect_cycle(self):
        """Indirect 4-node cycle: A -> B -> C -> D -> A."""
        quad_recipes = {
            "item_a": {"item_id": "item_a", "ingredients": [{"item_id": "item_b", "count": 1}]},
            "item_b": {"item_id": "item_b", "ingredients": [{"item_id": "item_c", "count": 1}]},
            "item_c": {"item_id": "item_c", "ingredients": [{"item_id": "item_d", "count": 1}]},
            "item_d": {"item_id": "item_d", "ingredients": [{"item_id": "item_a", "count": 1}]},
        }
        roots = resolve_root_raw_materials("item_a", quad_recipes)
        assert isinstance(roots, dict)

        focus_suggestions = [{"item_id": "item_a", "deficit": 3, "impact_score": 8}]
        trees = build_focus_crafting_trees(focus_suggestions, recipes=quad_recipes)
        assert len(trees) == 1

    def test_deep_crafting_dag_chain(self):
        """
        40-level deep recipe dependency chain:
        tier_40 -> tier_39 -> ... -> tier_1 -> raw_root_ore
        Verifies no RecursionError or stack depth failure.
        """
        chain_recipes = {}
        for level in range(40, 1, -1):
            prod = f"tier_{level}"
            ing = f"tier_{level - 1}"
            chain_recipes[prod] = {
                "item_id": prod,
                "display_name": f"Tier {level} Product",
                "ingredients": [{"item_id": ing, "count": 1}],
            }
        chain_recipes["tier_1"] = {
            "item_id": "tier_1",
            "display_name": "Tier 1 Product",
            "ingredients": [{"item_id": "raw_root_ore", "count": 2}],
        }

        roots = resolve_root_raw_materials("tier_40", chain_recipes)
        assert "raw_root_ore" in roots
        assert roots["raw_root_ore"] == 2

        focus_suggestions = [{"item_id": "raw_root_ore", "deficit": 5, "impact_score": 25}]
        remaining_map = {"tier_40": {"loved": {"adeline"}}}
        trees = build_focus_crafting_trees(
            focus_suggestions,
            recipes=chain_recipes,
            remaining_items_map=remaining_map,
        )
        assert len(trees) == 1
        assert trees[0]["item_id"] == "raw_root_ore"

    def test_unreachable_and_fabricated_ingredients(self):
        """
        Recipe requires fabricated / non-existent ingredient 'unobtainium_9999'.
        Ensures tree builder handles unreachable and unmapped items gracefully.
        """
        weird_recipes = {
            "mystery_potion": {
                "item_id": "mystery_potion",
                "ingredients": [
                    {"item_id": "unobtainium_9999", "count": 1},
                    {"item_id": "phantom_dust_8888", "count": 3},
                ],
            }
        }
        focus_suggestions = [{"item_id": "unobtainium_9999", "deficit": 1, "impact_score": 10}]
        trees = build_focus_crafting_trees(focus_suggestions, recipes=weird_recipes)
        assert len(trees) == 1
        assert trees[0]["item_id"] == "unobtainium_9999"

    def test_recipes_with_zero_or_negative_ingredient_quantities(self):
        """Recipe with count=0 or count=-5 must not cause ZeroDivisionError or infinite loops."""
        zero_recipes = {
            "free_soup": {
                "item_id": "free_soup",
                "ingredients": [
                    {"item_id": "water", "count": 0},
                    {"item_id": "negative_spice", "count": -5},
                ],
            }
        }
        roots = resolve_root_raw_materials("free_soup", zero_recipes)
        assert isinstance(roots, dict)


# ==============================================================================
# SECTION 4: Extreme Settings Combinations
# ==============================================================================

class TestExtremeSettingsCombinations:
    """Stress tests boundary bag slots, contradictory NPC filters, and extreme weights."""

    def test_zero_and_negative_slots_with_various_strategies(self):
        """slots=0 or slots=-10 must produce empty bag plan, 0 slots used, valid schema."""
        save_bytes = build_raw_synthetic_save()

        for st in ("journal", "max-relationship"):
            for s in (0, -1, -50):
                config = {"strategy": st, "slots": s}
                raw_json = generate_plan(save_bytes, config_dict=config)
                data = assert_canonical_schema(raw_json)
                assert len(data["bag_plan"]) == 0
                assert data["stats"]["slots_used"] == 0
                assert data["error"] is None

    def test_oversized_slots_budget(self):
        """slots=1000: huge allocation budget does not overflow or duplicate items."""
        save_bytes = build_raw_synthetic_save()
        config = {"slots": 1000}
        raw_json = generate_plan(save_bytes, config_dict=config)
        data = assert_canonical_schema(raw_json)
        assert data["stats"]["max_slots"] == 1000
        assert data["stats"]["slots_used"] <= 1000

    def test_contradictory_overlapping_npc_filters(self):
        """
        focus_mode_enabled=True with focus_npcs='adeline,balor',
        but simultaneously exclude_npcs='adeline,balor'.
        System must handle contradiction deterministically without crashing.
        """
        save_bytes = build_raw_synthetic_save()
        config = {
            "focus_mode_enabled": True,
            "focus_npcs": "adeline,balor",
            "exclude_npcs": "adeline,balor",
        }
        raw_json = generate_plan(save_bytes, config_dict=config)
        data = assert_canonical_schema(raw_json)
        assert data["error"] is None
        # Bag plan should not give gifts to excluded NPCs
        for item in data["bag_plan"]:
            for r in item["recipients"]:
                assert r["npc_id"].lower() not in ("adeline", "balor")

    def test_all_npcs_excluded_simultaneously(self):
        """Excluding all 35 NPCs produces empty bag plan, 0 covered NPCs, valid JSON."""
        save_bytes = build_raw_synthetic_save()
        all_35_npcs = [
            "adeline", "balor", "caldarus", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
            "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis", "luc",
            "maple", "march", "merri", "nora", "olric", "priestess", "reina", "ryis", "seridia", "stillwell",
            "taliferro", "terithia", "valen", "vera", "wheedle", "zorel",
        ]
        config = {"exclude_npcs": ",".join(all_35_npcs)}
        raw_json = generate_plan(save_bytes, config_dict=config)
        data = assert_canonical_schema(raw_json)
        assert len(data["bag_plan"]) == 0
        assert data["stats"]["covered_npcs_count"] == 0

    def test_focus_mode_enabled_with_empty_focus_string(self):
        """focus_mode_enabled=True but focus_npcs='' falls back safely without unhandled exception."""
        save_bytes = build_raw_synthetic_save()
        config = {"focus_mode_enabled": True, "focus_npcs": ""}
        raw_json = generate_plan(save_bytes, config_dict=config)
        data = assert_canonical_schema(raw_json)
        assert data["error"] is None

    def test_extreme_and_zero_scoring_multipliers(self):
        """
        loved_weight=0, liked_weight=0, vendor_boost=0.0, seasonal_boost=0.0,
        as well as 1,000,000x multiplier values.
        """
        save_bytes = build_raw_synthetic_save()

        # Zero weights
        config_zeros = {
            "loved_weight": 0,
            "liked_weight": 0,
            "vendor_boost": 0.0,
            "seasonal_boost": 0.0,
        }
        data_zero = assert_canonical_schema(generate_plan(save_bytes, config_dict=config_zeros))
        assert data_zero["error"] is None

        # Massive weights
        config_huge = {
            "loved_weight": 999999,
            "liked_weight": 999999,
            "vendor_boost": 999999.0,
            "seasonal_boost": 999999.0,
        }
        data_huge = assert_canonical_schema(generate_plan(save_bytes, config_dict=config_huge))
        assert data_huge["error"] is None

    def test_unrecognized_strategy_and_mode_strings(self):
        """Unknown strategy and mode fall back safely without crashing."""
        save_bytes = build_raw_synthetic_save()
        config = {"strategy": "interstellar_travel", "mode": "quantum_realm"}
        raw_json = generate_plan(save_bytes, config_dict=config)
        data = assert_canonical_schema(raw_json)
        assert data["error"] is None
        assert data["stats"]["strategy"] == "interstellar_travel"


# ==============================================================================
# SECTION 5: Character Encoding & Unicode in Names and Files
# ==============================================================================

class TestCharacterEncodingAndUnicodeIntegrity:
    """Verifies Unicode, Emoji, RTL, and injection payloads in player names, farm names, and filenames."""

    @pytest.mark.parametrize(
        "player_name,farm_name",
        [
            ("サクラ", "ミストリア農場"),  # Japanese
            ("Nguyễn Văn Trỗi", "Nông Trại Hướng Dương 🌸"),  # Vietnamese diacritics
            ("👑 King Farmer 👨‍🌾", "✨ Magic Ranch 🦄"),  # Emojis & surrogate pairs
            ("مزرعة الأمل", "سلام"),  # Arabic RTL
            ("François Müller-Chloë", "L'Étoile Farm"),  # French / German accents & quotes
            ("<script>alert('xss')</script>", "<img src=x onerror=1>"),  # HTML/XSS injection
            ("'; DROP TABLE saves; --", '{"sql": true}'),  # SQL/JSON injection
            ("A" * 5000, "B" * 5000),  # Long string buffer
        ],
    )
    def test_unicode_and_special_player_and_farm_names(self, player_name: str, farm_name: str):
        """Player and farm names with diverse scripts and symbols must be preserved exactly."""
        save_bytes = build_raw_synthetic_save(player_name=player_name, farm_name=farm_name)
        raw_json = generate_plan(save_bytes, filename="unicode_test.sav")
        data = assert_canonical_schema(raw_json)

        assert data["save_info"]["player_name"] == player_name
        assert data["save_info"]["farm_name"] == farm_name
        assert data["error"] is None

    @pytest.mark.parametrize(
        "filename",
        [
            "Fields of Mistria (🌸).sav",
            "セーブデータ_2026.sav",
            "tệp_lưu_trữ_mùa_xuân.sav",
            "save file with spaces & symbols !@#$%.sav",
            "Save.with.many.dots.and-dashes---.sav",
        ],
    )
    def test_unicode_and_special_character_filenames(self, filename: str):
        """Save filenames with Unicode, spaces, and punctuation preserved in save_info."""
        save_bytes = build_raw_synthetic_save()
        raw_json = generate_plan(save_bytes, filename=filename)
        data = assert_canonical_schema(raw_json)
        assert data["save_info"]["filename"] == filename
        assert data["error"] is None

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available in environment")
    def test_client_side_svg_placeholder_generator_unicode_and_special_chars(self):
        """
        Fuzzes the JavaScript generatePlaceholderSvg() function in web/app.js
        with Unicode, emoji, quotes, and punctuation. Asserts well-formed SVG XML.
        """
        test_inputs = [
            "cà_chua",
            "お茶",
            "✨_magic_gem",
            "soup'n'crackers",
            'quotes"inside',
            "",
            None,
        ]

        node_script = f"""
        const fs = require('fs');
        const vm = require('vm');

        const appCode = fs.readFileSync('{WEB_APP_PATH.as_posix()}', 'utf8');

        // Extract generatePlaceholderSvg function
        const match = appCode.match(/function generatePlaceholderSvg\\([\\s\\S]*?\\n\\}}/);
        if (!match) throw new Error("generatePlaceholderSvg not found in web/app.js");

        const context = {{ encodeURIComponent: encodeURIComponent, String: String }};
        vm.createContext(context);
        vm.runInContext(match[0], context);

        const inputs = {json.dumps(test_inputs)};
        const results = inputs.map(inp => context.generatePlaceholderSvg(inp, "item"));
        console.log(JSON.stringify(results));
        """
        proc = subprocess.run([NODE_BIN, "-e", node_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node SVG test failed:\n{proc.stderr}"
        svg_data_uris = json.loads(proc.stdout)

        import urllib.parse
        prefix = "data:image/svg+xml;utf8,"
        for uri in svg_data_uris:
            assert uri.startswith(prefix)
            encoded_svg = uri[len(prefix):]
            decoded_svg = urllib.parse.unquote(encoded_svg)
            root = ET.fromstring(decoded_svg)
            assert root.tag.endswith("svg")
            assert root.attrib.get("width") == "48"
            assert root.attrib.get("height") == "48"

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available in environment")
    def test_client_side_svg_placeholder_xml_injection_probe(self):
        """
        Adversarial regression check: tests whether generatePlaceholderSvg() properly escapes
        XML control characters ('<' and '&') in initials.
        Confirms that '<' is safely escaped as '&lt;' ('<text ...>&lt;I</text>'),
        producing well-formed XML that parses cleanly without ParseError.
        """
        node_script = f"""
        const fs = require('fs');
        const vm = require('vm');

        const appCode = fs.readFileSync('{WEB_APP_PATH.as_posix()}', 'utf8');
        const match = appCode.match(/function generatePlaceholderSvg\\([\\s\\S]*?\\n\\}}/);
        const context = {{ encodeURIComponent: encodeURIComponent, String: String }};
        vm.createContext(context);
        vm.runInContext(match[0], context);

        const uri = context.generatePlaceholderSvg("<bad_item>", "item");
        console.log(uri);
        """
        proc = subprocess.run([NODE_BIN, "-e", node_script], capture_output=True, text=True)
        assert proc.returncode == 0
        uri = proc.stdout.strip()
        prefix = "data:image/svg+xml;utf8,"
        assert uri.startswith(prefix)

        import urllib.parse
        decoded_svg = urllib.parse.unquote(uri[len(prefix):])

        # Verify that '<' is properly XML-escaped as '&lt;' in SVG text node
        assert "<text" in decoded_svg
        assert ">&lt;I</text>" in decoded_svg

        # Verify that an XML parser succeeds cleanly without raising ParseError
        root = ET.fromstring(decoded_svg)
        assert root.tag.endswith("svg")

