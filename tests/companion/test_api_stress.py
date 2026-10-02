"""
tests/test_challenger_r3_2_api_stress.py

Adversarial Stress Testing Suite by Challenger R3-2:
1. POST /api/settings extreme payloads:
   - Empty strings, extra whitespace, mixed case NPC names, non-existent NPC names,
     lists vs strings, None values, and unexpected payload types.
2. plan_to_json() serialization resilience:
   - Valid sprite_url on every item in source_priority.
   - Resilience against Sets, Tuples, Enums, Paths, and nested heterogeneous collections.
3. UI DOM & CSS Consistency:
   - Verification of DOM IDs in index.html / app.js template generators.
   - CSS class definitions in style.css.
4. Asset Route Verification:
   - Sprite endpoints for all 34 NPCs and focus suggestion items.
"""

from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Set

import pytest
from starlette.testclient import TestClient

from companion.config import CompanionConfig, load_companion_config, save_companion_config
from companion.json_exporter import _to_serializable, plan_to_json
from companion.planner_bridge import execute_plan
from companion.server import app


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ============================================================================
# 1. POST /api/settings Extreme Payloads Stress Testing
# ============================================================================

class TestApiSettingsExtremePayloads:
    @pytest.fixture(autouse=True)
    def restore_config(self, repo_root: Path):
        original = load_companion_config(repo_root)
        yield
        # Restore original settings after test
        save_companion_config(original, repo_root)
        from companion.server import state
        state.config = load_companion_config(repo_root)

    @pytest.mark.parametrize(
        "label,payload,expected_focus_npcs,expected_error",
        [
            ("empty_string", {"focus_mode_enabled": True, "focus_npcs": ""}, "", False),
            ("whitespace_string", {"focus_mode_enabled": True, "focus_npcs": "   "}, "", False),
            ("mixed_case_whitespace", {"focus_mode_enabled": True, "focus_npcs": " Adeline , MARCH "}, "Adeline , MARCH", False),
            ("nonexistent_npc", {"focus_mode_enabled": True, "focus_npcs": "unknown_npc"}, "unknown_npc", False),
            ("mixed_valid_nonexistent", {"focus_mode_enabled": True, "focus_npcs": "Adeline, unknown_npc, MARCH"}, "Adeline, unknown_npc, MARCH", False),
            ("list_standard", {"focus_mode_enabled": True, "focus_npcs": ["adeline", "march"]}, "adeline,march", False),
            ("list_mixed_whitespace", {"focus_mode_enabled": True, "focus_npcs": ["  Adeline ", " MARCH  "]}, "Adeline,MARCH", False),
            ("list_nonexistent", {"focus_mode_enabled": True, "focus_npcs": ["unknown_npc_1", "unknown_npc_2"]}, "unknown_npc_1,unknown_npc_2", False),
            ("list_empty", {"focus_mode_enabled": True, "focus_npcs": []}, "", False),
            ("list_with_empty_strings", {"focus_mode_enabled": True, "focus_npcs": ["", "  ", "March"]}, "March", False),
            ("none_value", {"focus_mode_enabled": True, "focus_npcs": None}, None, False),
            ("int_type_coercion", {"focus_npcs": 12345}, "12345", False),
            ("bool_focus_npcs", {"focus_npcs": False}, "False", False),
        ],
    )
    def test_post_settings_extreme_payloads_never_crash(
        self,
        client: TestClient,
        label: str,
        payload: Dict[str, Any],
        expected_focus_npcs: Any,
        expected_error: bool,
    ):
        res = client.post("/api/settings", json=payload)
        assert res.status_code == 200, f"Failed on {label} with status {res.status_code}"
        data = res.json()
        assert data.get("success") is True, f"Failed on {label}: success != True"

        cfg = data.get("config", {})
        assert cfg.get("focus_npcs") == expected_focus_npcs, (
            f"Config focus_npcs mismatch on {label}: got {cfg.get('focus_npcs')}, expected {expected_focus_npcs}"
        )

        plan = data.get("plan", {})
        has_error = plan.get("error") is not None
        assert has_error is expected_error, f"Error mismatch on {label}: {plan.get('error')}"

        # Invariance check: bag_plan must always exist
        assert "bag_plan" in plan
        assert "focus_suggestions" in plan
        assert "source_priority" in plan

    def test_mixed_case_and_whitespace_correctly_filters(self, client: TestClient):
        payload = {"focus_mode_enabled": True, "focus_npcs": " Adeline , MARCH "}
        res = client.post("/api/settings", json=payload)
        assert res.status_code == 200
        plan = res.json().get("plan", {})
        suggestions = plan.get("focus_suggestions", [])

        # Every suggestion must strictly benefit Adeline or March
        for item in suggestions:
            blocked = {str(n).strip().lower() for n in item.get("blocked_npcs", [])}
            assert bool(blocked & {"adeline", "march"}), (
                f"Item {item.get('item_name')} blocked {blocked} not in target"
            )

    def test_nonexistent_npc_yields_zero_suggestions_without_error(self, client: TestClient):
        payload = {"focus_mode_enabled": True, "focus_npcs": "unknown_mythical_npc_999"}
        res = client.post("/api/settings", json=payload)
        assert res.status_code == 200
        plan = res.json().get("plan", {})
        assert plan.get("error") is None
        assert len(plan.get("focus_suggestions", [])) == 0
        assert len(plan.get("source_priority", [])) == 0


# ============================================================================
# 2. plan_to_json() Serialization Resilience & Sprite URL Validation
# ============================================================================

class TestPlanToJsonSerializationAndSprites:
    class DummyStatus(Enum):
        ACTIVE = "active"
        PENDING = "pending"

    def test_every_item_in_source_priority_has_valid_sprite_url(self, repo_root: Path):
        cfg = CompanionConfig()
        save, plan_res, metadata, save_path = execute_plan(cfg, repo_root)
        exported = plan_to_json(save, plan_res, metadata, save_path, cfg)

        sources = exported.get("source_priority", [])
        assert len(sources) > 0, "No sources returned in baseline plan"

        inspected_count = 0
        for s in sources:
            items = s.get("items", [])
            for it in items:
                inspected_count += 1
                item_id = str(it.get("item_id", "")).strip().lower()
                sprite_url = it.get("sprite_url")
                assert sprite_url is not None, f"Item {item_id} in {s.get('source_name')} missing sprite_url"
                assert sprite_url == f"/assets/sprites/items/{item_id}", (
                    f"Invalid sprite_url {sprite_url} for item {item_id}"
                )

        assert inspected_count > 0, "Zero items inspected in source_priority"

    def test_to_serializable_handles_sets_tuples_paths_enums_and_heterogeneous(self):
        complex_data = {
            "set_str": {"apple", "banana"},
            "set_hetero": {"hello", 42, None},
            "tuple_nested": (1, ("inner", {Path("/a/b"), 10})),
            "enum_field": self.DummyStatus.ACTIVE,
            "path_field": Path("companion/static/app.js"),
            "frozenset_field": frozenset(["x", "y"]),
        }
        res = _to_serializable(complex_data)
        serialized = json.dumps(res)
        assert len(serialized) > 0

        restored = json.loads(serialized)
        assert restored["set_str"] == ["apple", "banana"]
        assert restored["enum_field"] == "active"
        assert restored["path_field"] == "companion/static/app.js"
        assert sorted(restored["frozenset_field"]) == ["x", "y"]

    def test_plan_to_json_survives_adversarial_types_in_plan_results(self):
        cfg = CompanionConfig()
        adversarial_plan = {
            "overall_stats": {
                "covered_npcs": {"adeline", "march"},
                "locked_npcs": ("dozy", "ebon"),
                "status_enum": self.DummyStatus.ACTIVE,
            },
            "bag_plan": [
                {
                    "item_id": "apple",
                    "npc_recipients": {"adeline", "celine"},
                    "qualities": (1, 2),
                }
            ],
            "focus_suggestions": [
                {
                    "item_id": "copper_ore",
                    "blocked_npcs": {"march", "valen"},
                    "tags": frozenset(["mine", "metal"]),
                    "coords": (10, 20),
                }
            ],
            "source_priority": [
                {
                    "source_name": "The Mines",
                    "tier": "Grind",
                    "total_score": 10,
                    "items": [
                        {
                            "item_id": "copper_ore",
                            "deficit": 5,
                            "blocked_pairs": 10,
                            "sub_sources": {"Floor 1-20", "Mimics"},
                            "range": (1, 20),
                        }
                    ],
                    "benefited_npcs": {"March", "Valen"},
                }
            ],
            "npc_progress": {
                "Adeline": {
                    "loved": {"coffee", "tea"},
                    "liked": ("cookie",),
                }
            },
        }

        res = plan_to_json(None, adversarial_plan, {}, None, cfg)
        serialized = json.dumps(res)
        assert len(serialized) > 0

        # Verify source_priority inner item has valid sprite_url and serialized sets
        item = res["source_priority"][0]["items"][0]
        assert item["sprite_url"] == "/assets/sprites/items/copper_ore"
        assert isinstance(item["sub_sources"], list)
        assert isinstance(item["range"], list)
        assert isinstance(res["source_priority"][0]["benefited_npcs"], list)


# ============================================================================
# 3. UI DOM & CSS Consistency
# ============================================================================

class TestUiDomAndCssConsistency:
    def test_referenced_dom_ids_exist_in_index_or_app_template(self, repo_root: Path):
        index_html = (repo_root / "companion" / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (repo_root / "companion" / "static" / "app.js").read_text(encoding="utf-8")

        # 1. sourceSummaryPanel must exist in index.html
        assert 'id="sourceSummaryPanel"' in index_html, "sourceSummaryPanel not found in index.html"

        # 2. Dynamic controls must exist in app.js templates
        required_app_ids = [
            'id="focusNpcContainer"',
            'id="focusNpcGrid"',
            'id="focusNpcSelectAll"',
            'id="focusNpcDeselectAll"',
            'id="focusNpcCounterBadge"',
        ]
        for dom_id in required_app_ids:
            assert dom_id in app_js, f"Expected template element {dom_id} not found in app.js"

    def test_css_classes_presence_in_style_css(self, repo_root: Path):
        style_css = (repo_root / "companion" / "static" / "style.css").read_text(encoding="utf-8")

        critical_classes = [
            "source-summary-panel",
            "source-tier-accordion",
            "source-tier-summary",
            "tier-summary-title",
            "tier-stat-badge",
            "tier-score-badge",
            "tier-chevron",
            "source-tier-content",
            "source-card",
            "source-card-header",
            "source-card-title",
            "source-card-badges",
            "tier-badge-pill",
            "tier-pill-quick",
            "tier-pill-grind",
            "tier-pill-farm",
            "source-score-badge",
            "source-label",
            "source-items-chips",
            "source-item-chip",
            "source-item-sprite",
            "source-item-name",
            "source-item-deficit",
            "source-item-pairs",
            "source-benefited-section",
            "source-npcs-chips",
            "focus-npc-picker-group",
            "focus-npc-container",
            "focus-npc-toolbar",
            "focus-npc-actions",
            "focus-npc-btn",
            "focus-npc-counter",
            "focus-npc-grid",
            "focus-npc-card",
            "focus-npc-cb",
            "focus-npc-portrait",
            "focus-npc-name",
            "is-checked",
        ]

        missing = [c for c in critical_classes if not re.search(rf"\.{re.escape(c)}\b", style_css)]
        assert len(missing) == 0, f"Critical CSS classes missing from style.css: {missing}"


# ============================================================================
# 4. Asset Sprite Endpoints for 34 NPCs and Plan Items
# ============================================================================

class TestAssetSpriteEndpoints:
    DEFAULT_34_NPCS = [
        "adeline", "balor", "caldarus", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis", "luc", "maple",
        "march", "merri", "nora", "olric", "reina", "ryis", "seridia", "stillwell", "taliferro", "terithia",
        "valen", "vera", "wheedle", "zorel"
    ]

    def test_all_34_npc_sprites_respond_with_200_png(self, client: TestClient):
        for nid in self.DEFAULT_34_NPCS:
            res = client.get(f"/assets/sprites/npcs/{nid}")
            assert res.status_code == 200, f"Failed sprite for NPC: {nid}"
            assert "image/png" in res.headers.get("content-type", ""), f"NPC {nid} not served as PNG"

    def test_plan_item_sprites_respond_with_200(self, client: TestClient):
        res = client.get("/api/plan")
        assert res.status_code == 200
        plan = res.json()
        sources = plan.get("source_priority", [])

        checked_urls = set()
        for s in sources:
            for it in s.get("items", []):
                url = it.get("sprite_url")
                if url and url not in checked_urls:
                    checked_urls.add(url)
                    r = client.get(url)
                    assert r.status_code == 200, f"Item sprite failed: {url}"
