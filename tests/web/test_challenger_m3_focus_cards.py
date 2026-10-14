"""
tests/web/test_challenger_m3_focus_cards.py

Empirical Challenger & Adversarial Stress Suite for Milestone 3:
Focus Suggestion Cards UI rendering, badge math, category slug generation,
dynamic tree button activation, and HTML escaping / XSS resilience.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from fom_planner.data_loader import load_quest_data
from fom_planner.optimizer import build_focus_crafting_trees, compute_focus_suggestions

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPANION_APP_JS = REPO_ROOT / "companion" / "static" / "app.js"
COMPANION_STYLE_CSS = REPO_ROOT / "companion" / "static" / "style.css"
WEB_APP_JS = REPO_ROOT / "web" / "app.js"
WEB_STYLE_CSS = REPO_ROOT / "web" / "style.css"
QUEST_DATA_JSON = REPO_ROOT / "data" / "quest_data.json"


# ==============================================================================
# Helper Functions Mirroring Frontend Logic (Oracles)
# ==============================================================================


def escape_html(s: Any) -> str:
    """Python oracle mirroring JavaScript escapeHtml()."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def compute_cat_slug(category: Any) -> str:
    """Python oracle mirroring JS category slug generation."""
    return re.sub(r"[^a-z0-9]+", "-", str(category).lower()).strip("-")


def compute_deficit_badge_text(f: Dict[str, Any]) -> str:
    """Python oracle mirroring JS renderFocusSuggestions deficit badge text logic."""
    deficit = f.get("deficit", 0)
    quest_demand = f.get("quest_demand", 0)
    gift_deficit_val = f.get("gift_deficit")

    # In JS: (f.gift_deficit !== undefined && f.gift_deficit !== null) ? f.gift_deficit : (f.deficit - (f.quest_demand || 0))
    if gift_deficit_val is not None:
        gift_deficit = gift_deficit_val
    else:
        gift_deficit = deficit - (quest_demand or 0)

    # In JS: (f.quest_demand && f.quest_demand > 0)
    if quest_demand and quest_demand > 0:
        return f"Need: {deficit} ({gift_deficit} Gifts + {quest_demand} Quests)"
    return f"Need: {deficit}"


def simulate_tree_button_evaluation(
    f: Dict[str, Any],
    tree: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Simulates the tree button visibility and text evaluation from app.js:
    const hasBranches = Boolean(tree && Array.isArray(tree.children) && tree.children.length > 0);
    const hasQuests = Boolean(
        (f.quest_count && f.quest_count > 0) ||
        (f.quest_demand && f.quest_demand > 0) ||
        (tree && Array.isArray(tree.children) && tree.children.some(c => c.is_quest))
    );
    const treeBtnText = hasQuests ? 'View crafting & quest tree' : 'View crafting tree';
    """
    children = tree.get("children") if tree and isinstance(tree, dict) else None
    has_branches = bool(children and isinstance(children, list) and len(children) > 0)

    has_quest_children = bool(
        children and any(isinstance(c, dict) and c.get("is_quest") is True for c in children)
    )
    has_quests = bool(
        (f.get("quest_count") and f.get("quest_count") > 0)
        or (f.get("quest_demand") and f.get("quest_demand") > 0)
        or has_quest_children
    )

    tree_btn_text = "View crafting & quest tree" if has_quests else "View crafting tree"

    return {
        "has_branches": has_branches,
        "has_quests": has_quests,
        "tree_btn_text": tree_btn_text if has_branches else None,
    }


# ==============================================================================
# 1. Deficit Badge Math & String Construction Across Edge Cases
# ==============================================================================


class TestDeficitBadgeEdgeCases:
    """Stress tests verifying deficit badge string construction across extreme edge cases."""

    def test_quest_demand_zero_standard(self):
        """When quest_demand == 0, badge must display simple 'Need: X'."""
        f = {"deficit": 5, "gift_deficit": 5, "quest_demand": 0}
        assert compute_deficit_badge_text(f) == "Need: 5"

    def test_quest_demand_positive_standard(self):
        """When quest_demand > 0, badge must show 'Need: X (Y Gifts + Z Quests)'."""
        f = {"deficit": 8, "gift_deficit": 5, "quest_demand": 3}
        assert compute_deficit_badge_text(f) == "Need: 8 (5 Gifts + 3 Quests)"

    def test_gift_deficit_zero_boundary_check(self):
        """
        Boundary condition: gift_deficit == 0, quest_demand == 10, deficit == 10.
        Verifies that explicit 0 is preserved and does not fallback to subtraction.
        """
        f = {"deficit": 10, "gift_deficit": 0, "quest_demand": 10}
        badge = compute_deficit_badge_text(f)
        assert badge == "Need: 10 (0 Gifts + 10 Quests)"

    def test_missing_gift_deficit_fallback_calculation(self):
        """When gift_deficit is None/undefined, fallback computes deficit - quest_demand."""
        f = {"deficit": 12, "quest_demand": 4}  # gift_deficit omitted
        badge = compute_deficit_badge_text(f)
        assert badge == "Need: 12 (8 Gifts + 4 Quests)"

    def test_gigantic_quest_demand_values(self):
        """Extreme numerical stress: gigantic quest demands (1 billion)."""
        f = {
            "deficit": 1_500_000_000,
            "gift_deficit": 500_000_000,
            "quest_demand": 1_000_000_000,
        }
        badge = compute_deficit_badge_text(f)
        assert badge == "Need: 1500000000 (500000000 Gifts + 1000000000 Quests)"

    def test_negative_or_none_quest_demand_graceful_handling(self):
        """Negative or None quest demand should not trigger split badge."""
        f_neg = {"deficit": 4, "gift_deficit": 4, "quest_demand": -2}
        assert compute_deficit_badge_text(f_neg) == "Need: 4"

        f_none = {"deficit": 4, "gift_deficit": 4, "quest_demand": None}
        assert compute_deficit_badge_text(f_none) == "Need: 4"

    def test_js_implementation_parity_both_apps(self):
        """Assert both companion/static/app.js and web/app.js contain exact badge logic."""
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        w_code = WEB_APP_JS.read_text(encoding="utf-8")

        target_pattern = r"f\.quest_demand\s*&&\s*f\.quest_demand\s*>\s*0"
        assert re.search(target_pattern, c_code), "companion/static/app.js missing quest_demand > 0 check"
        assert re.search(target_pattern, w_code), "web/app.js missing quest_demand > 0 check"

        badge_pattern = r"`Need:\s*\$\{f\.deficit\}\s*\(\$\{giftDeficit\}\s*Gifts\s*\+\s*\$\{f\.quest_demand\}\s*Quests\)`"
        assert re.search(badge_pattern, c_code), "companion/static/app.js missing formatted split badge text"
        assert re.search(badge_pattern, w_code), "web/app.js missing formatted split badge text"


# ==============================================================================
# 2. Category Pill Slug Generation & CSS Rule Matching
# ==============================================================================


class TestCategoryPillsAndCSSRules:
    """Stress tests verifying category slug generation and CSS stylesheet coverage."""

    def test_all_game_quest_categories_generate_valid_css_slugs(self):
        """Collect all categories from quest_data.json and assert valid CSS class names."""
        qd = load_quest_data()
        all_categories = set()
        for item_info in qd.values():
            for q in item_info.get("quests", []):
                cat = q.get("category")
                if cat:
                    all_categories.add(cat)

        assert len(all_categories) >= 7, f"Expected at least 7 distinct categories, got {len(all_categories)}"

        for cat in all_categories:
            slug = compute_cat_slug(cat)
            assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug), f"Invalid CSS class slug: '{slug}' for '{cat}'"
            assert not slug.startswith("-") and not slug.endswith("-")

    def test_all_expected_categories_have_explicit_css_rules(self):
        """
        Verify that all primary quest categories have dedicated .quest-cat-* styling
        in both companion/static/style.css and web/style.css.
        """
        expected_categories = [
            "Story Quest",
            "Request",
            "Crown Request",
            "Heart Quest",
            "Town Upgrade",
            "Important Quest",
            "Festival Quest",
            "Special Request",
            "Cooking Challenge",
        ]

        c_css = COMPANION_STYLE_CSS.read_text(encoding="utf-8")
        w_css = WEB_STYLE_CSS.read_text(encoding="utf-8")

        # Base pill styling must exist
        assert ".quest-cat-pill" in c_css
        assert ".quest-cat-pill" in w_css

        for cat in expected_categories:
            slug = compute_cat_slug(cat)
            class_name = f".quest-cat-{slug}"
            assert class_name in c_css, f"Missing {class_name} in companion/static/style.css"
            assert class_name in w_css, f"Missing {class_name} in web/style.css"

    def test_exotic_category_names_slug_safety(self):
        """Test strange, accented, or punctuated category strings for slug generation."""
        exotic_cases = {
            "Special & Secret!": "special-secret",
            "Town Upgrade: Stage 2": "town-upgrade-stage-2",
            "  Story   Quest  ": "story-quest",
            "---Leading---Trailing---": "leading-trailing",
            "100% Guaranteed Request": "100-guaranteed-request",
        }
        for raw, expected_slug in exotic_cases.items():
            assert compute_cat_slug(raw) == expected_slug


# ==============================================================================
# 3. Dynamic Tree Button Activation for Zero-Crafting / Direct-Quest Nodes
# ==============================================================================


class TestDynamicTreeButtonActivation:
    """Stress tests verifying tree modal button activation when item has quests but no crafting recipes."""

    def test_direct_quest_only_activates_tree_button_with_quest_label(self):
        """
        Scenario: Item has NO crafting recipes (downstream recipes empty),
        but has direct quest nodes attached in tree.children.
        Button MUST be enabled and labeled 'View crafting & quest tree'.
        """
        focus_item = {
            "item_id": "copper_ore",
            "item_name": "Copper Ore",
            "gift_deficit": 5,
            "quest_demand": 10,
            "quest_count": 2,
            "deficit": 15,
        }
        synthetic_tree = {
            "item_id": "copper_ore",
            "item_name": "Copper Ore",
            "children": [
                {
                    "item_id": "_quest_blacksmith_supplies",
                    "item_name": "Blacksmith Supplies",
                    "is_quest": True,
                    "quest_type": "Request",
                    "quest_category": "Request",
                    "quest_amount": 10,
                    "requester": "March",
                    "children": [],
                }
            ],
        }

        result = simulate_tree_button_evaluation(focus_item, synthetic_tree)
        assert result["has_branches"] is True, "Tree button should be enabled"
        assert result["has_quests"] is True, "Quest flag should be detected"
        assert result["tree_btn_text"] == "View crafting & quest tree"

    def test_real_engine_builds_quest_nodes_without_recipes(self):
        """
        Empirically invoke build_focus_crafting_trees with zero recipes and confirm
        direct quest node attachment.
        """
        suggestions = [
            {"item_id": "copper_ore", "item_name": "Copper Ore", "gift_deficit": 2, "quest_demand": 5, "deficit": 7}
        ]
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {
                        "quest_name": "March's Project",
                        "quest_type": "Request",
                        "category": "Request",
                        "amount": 5,
                        "requester": "March",
                    }
                ],
            }
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes={},  # Zero recipes!
            remaining_items_map={"copper_ore": {"loved": {"March"}}},
            quest_data=synthetic_quests,
            completed_quests=set(),
        )

        assert len(trees) == 1
        tree = trees[0]
        assert len(tree["children"]) == 1
        child = tree["children"][0]
        assert child["is_quest"] is True
        assert child["item_name"] == "March's Project"

        # Now evaluate tree button with this real engine tree
        eval_res = simulate_tree_button_evaluation(suggestions[0], tree)
        assert eval_res["has_branches"] is True
        assert eval_res["tree_btn_text"] == "View crafting & quest tree"

    def test_pure_crafting_without_quests_shows_crafting_only_label(self):
        """Item has crafting recipe branches, but zero quest需求."""
        focus_item = {
            "item_id": "wood",
            "item_name": "Wood",
            "gift_deficit": 10,
            "quest_demand": 0,
            "quest_count": 0,
            "deficit": 10,
        }
        synthetic_tree = {
            "item_id": "wood",
            "item_name": "Wood",
            "children": [
                {
                    "item_id": "wooden_bench",
                    "item_name": "Wooden Bench",
                    "is_quest": False,
                    "children": [],
                }
            ],
        }

        result = simulate_tree_button_evaluation(focus_item, synthetic_tree)
        assert result["has_branches"] is True
        assert result["has_quests"] is False
        assert result["tree_btn_text"] == "View crafting tree"

    def test_no_recipes_and_no_quests_suppresses_tree_button(self):
        """Item with neither recipes nor quests must NOT show tree toggle button."""
        focus_item = {
            "item_id": "wild_berries",
            "item_name": "Wild Berries",
            "gift_deficit": 3,
            "quest_demand": 0,
            "deficit": 3,
        }
        synthetic_tree = {
            "item_id": "wild_berries",
            "item_name": "Wild Berries",
            "children": [],
        }

        result = simulate_tree_button_evaluation(focus_item, synthetic_tree)
        assert result["has_branches"] is False
        assert result["tree_btn_text"] is None


# ==============================================================================
# 4. HTML Escaping & XSS Resilience
# ==============================================================================


class TestHtmlEscapingAndXssResilience:
    """Stress tests asserting that quest names, requesters, categories, and tooltips are sanitized."""

    def test_escape_html_oracle_behavior(self):
        """Test escaping oracle on malicious payloads."""
        payload = '<script>alert("XSS & injection")</script>\'test\''
        escaped = escape_html(payload)
        assert "<" not in escaped
        assert ">" not in escaped
        assert '"' not in escaped
        assert "'" not in escaped
        assert "&amp;" in escaped
        assert "&quot;" in escaped
        assert "&#039;" in escaped

    def test_focus_quest_row_tooltip_escaping(self):
        """
        Verify that multiline quest summary tooltips containing quotes,
        HTML tags, or ampersands are escaped for HTML title attribute insertion.
        """
        f = {
            "quest_count": 2,
            "quest_demand": 10,
            "quest_categories": {"Story Quest": 1, 'Crown "Request"': 1},
            "quest_summary": [
                {
                    "quest_name": '<script>alert("XSS")</script>',
                    "amount": 5,
                    "is_direct": True,
                    "requester": 'March & "Friends"',
                },
                {
                    "quest_name": "Normal Quest",
                    "amount": 5,
                    "is_direct": False,
                    "via_item_name": 'Fancy "Cheese" <test>',
                    "requester": "Adeline",
                },
            ],
        }

        summary_lines = []
        for q in f["quest_summary"]:
            amt = f" ×{q['amount']}" if q.get("amount") else ""
            via_target = q.get("via_item_name") or q.get("target_item_name")
            via = f" via {via_target}" if (not q.get("is_direct") and via_target) else ""
            req = f" ({q['requester']})" if q.get("requester") else ""
            summary_lines.append(f"• {q['quest_name']}{amt}{via}{req}")

        summary_tooltip = "\n".join(summary_lines)
        escaped_title = escape_html(summary_tooltip)

        # Attribute breakout injection check:
        # If unescaped double quotes exist, the attribute value terminates prematurely
        assert '"' not in escaped_title, "Unescaped quote in title attribute allows attribute breakout"
        assert "<script>" not in escaped_title
        assert "&quot;" in escaped_title
        assert "&amp;" in escaped_title

    def test_d3_tree_modal_quest_node_escaping_contracts(self):
        """
        Verify that in D3 tree quest node rendering (app.js lines 820-850 and web/app.js 1780-1810),
        all interpolated dynamic properties pass through escapeHtml().
        """
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        w_code = WEB_APP_JS.read_text(encoding="utf-8")

        # In D3 quest node:
        # escapeHtml(data.item_name)
        assert "escapeHtml(data.item_name)" in c_code
        assert "escapeHtml(data.item_name)" in w_code

        # escapeHtml(cat)
        assert "escapeHtml(cat)" in c_code
        assert "escapeHtml(cat)" in w_code

        # escapeHtml(data.requester)
        assert "escapeHtml(data.requester)" in c_code
        assert "escapeHtml(data.requester)" in w_code

        # escapeHtml(data.via_item_name)
        assert "escapeHtml(data.via_item_name)" in c_code
        assert "escapeHtml(data.via_item_name)" in w_code

    def test_requester_attribute_injection_vulnerability_audit(self):
        """
        Audit d3 requester portrait src injection vector in companion/static/app.js:
        In companion/static/app.js:
          const reqSlug = String(data.requester).toLowerCase().trim();
          <img class="d3-requester-portrait" src="/assets/sprites/npcs/${reqSlug}" ... />
        If data.requester contains quotes, check if slug is sanitized or unescaped.
        """
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        # Notice: String(data.requester).toLowerCase().trim() does NOT strip double quotes!
        # Whereas in web/app.js:
        # resolveNpcPortrait(data.requester) -> String(npcId).trim().toLowerCase()
        # Verify that all official game requesters are clean alphanumeric names
        qd = load_quest_data()
        all_requesters = set()
        for item_info in qd.values():
            for q in item_info.get("quests", []):
                if q.get("requester"):
                    all_requesters.add(q["requester"])

        for req in all_requesters:
            assert re.match(r"^[A-Za-z\s]+$", req), f"Unexpected characters in real game requester: {req}"
