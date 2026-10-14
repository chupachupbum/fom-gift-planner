"""
tests/web/test_challenger_m3_tree_modal.py

Adversarial Challenger Empirical Stress Test Suite for Milestone 3:
- prepareTreeData quest grouping threshold (>4) and recipe child segregation.
- getCardHeight dynamic layout sizing (quest group 56px, quest cards 68-110px).
- D3 tree modal search and ancestor auto-expansion (expandMatches).
- Circular / deep tree stability with quest nodes attached.
- Focus cards split deficit badge and Future Quests row contracts.
- 100% implementation parity between companion/static/app.js and web/app.js.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

from fom_planner.optimizer import build_focus_crafting_trees

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPANION_APP_JS = REPO_ROOT / "companion" / "static" / "app.js"
WEB_APP_JS = REPO_ROOT / "web" / "app.js"

NODE_CANDIDATES = [
    shutil.which("node"),
    os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/node"),
    os.path.expanduser("~/.nvm/versions/node/v22.22.1/bin/node"),
    shutil.which("bun"),
]
NODE_BIN = next((p for p in NODE_CANDIDATES if p and os.path.exists(p)), None)


def run_node_snippet(script: str) -> str:
    """Executes a Node.js snippet and returns stdout."""
    assert NODE_BIN is not None, f"Node.js binary not found. Checked: {NODE_CANDIDATES}"
    res = subprocess.run(
        [NODE_BIN, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Node.js execution failed (code {res.returncode}):\n"
            f"STDOUT:\n{res.stdout}\n"
            f"STDERR:\n{res.stderr}\n"
            f"SCRIPT:\n{script}"
        )
    return res.stdout.strip()


class TestPrepareTreeDataGrouping:
    """Empirical verification of prepareTreeData grouping logic across both companion and web."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_grouping_threshold_strictly_greater_than_four(self, app_file):
        """
        Adversarially tests quest child grouping across counts: 0, 1, 2, 3, 4, 5, 10, 25.
        Asserts:
        - When count <= 4: NO is_quest_group is created; quest children remain direct children.
        - When count > 4: Exactly ONE is_quest_group is created, containing all quest children.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const prepMatch = content.match(/function prepareTreeData\\(rawTree\\) \\{{[\\s\\S]*?\\n\\}}/)[0];
const prepareTreeData = new Function('rawTree', prepMatch + '; return prepareTreeData(rawTree);');

const results = {{}};

const counts = [0, 1, 2, 3, 4, 5, 10, 25];
for (const count of counts) {{
  const quests = [];
  for (let i = 1; i <= count; i++) {{
    quests.push({{
      item_id: '_quest_' + i,
      item_name: 'Quest ' + i,
      is_quest: true,
      children: []
    }});
  }}
  const tree = {{
    item_id: 'ore_stone',
    item_name: 'Stone',
    children: quests
  }};

  const out = prepareTreeData(tree);
  const questGroups = out.children.filter(c => c.is_quest_group === true);
  const directQuests = out.children.filter(c => c.is_quest === true);

  results[count] = {{
    total_children: out.children.length,
    quest_group_count: questGroups.length,
    direct_quest_count: directQuests.length,
    group_name: questGroups[0] ? questGroups[0].item_name : null,
    grouped_children_count: questGroups[0] ? questGroups[0].children.length : 0,
    is_group_flag: questGroups[0] ? questGroups[0].is_group : false,
  }};
}}

console.log(JSON.stringify(results));
"""
        out = run_node_snippet(script)
        data = json.loads(out)

        # 0, 1, 2, 3, 4 must NOT group
        for c in [0, 1, 2, 3, 4]:
            assert data[str(c)]["quest_group_count"] == 0, f"Expected 0 quest groups for count {c}"
            assert data[str(c)]["direct_quest_count"] == c, f"Expected {c} direct quests for count {c}"

        # 5, 10, 25 MUST group into exactly 1 is_quest_group
        for c in [5, 10, 25]:
            assert data[str(c)]["quest_group_count"] == 1, f"Expected 1 quest group for count {c}"
            assert data[str(c)]["direct_quest_count"] == 0, f"Expected 0 direct quests for count {c}"
            assert data[str(c)]["total_children"] == 1, f"Expected 1 total child (the group) for count {c}"
            assert data[str(c)]["grouped_children_count"] == c, f"Expected group to contain {c} children"
            assert data[str(c)]["group_name"] == f"Quests ({c})"
            assert data[str(c)]["is_group_flag"] is True

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_recipe_children_never_bundled_into_quest_groups(self, app_file):
        """
        Adversarial test with mixed trees:
        - Crafting recipe intermediate children (children.length > 0)
        - Crafting recipe leaf children (children.length == 0)
        - Direct quest children (is_quest: true)
        Asserts:
        - Recipe children are NEVER bundled into quest groups.
        - Quest children are NEVER bundled into direct recipe groups.
        - When both recipe leaves (>5 + intermediate) and quests (>4) exist, two distinct groups are formed.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const prepMatch = content.match(/function prepareTreeData\\(rawTree\\) \\{{[\\s\\S]*?\\n\\}}/)[0];
const prepareTreeData = new Function('rawTree', prepMatch + '; return prepareTreeData(rawTree);');

// Scenario 1: 1 intermediate + 8 recipe leaves + 6 quest children
const intermediate = {{
  item_id: 'iron_ingot',
  item_name: 'Iron Ingot',
  children: [
    {{ item_id: 'iron_pickaxe', item_name: 'Iron Pickaxe', children: [] }}
  ]
}};
const recipeLeaves = Array.from({{ length: 8 }}, (_, i) => ({{
  item_id: 'recipe_leaf_' + i,
  item_name: 'Recipe Leaf ' + i,
  children: []
}}));
const questChildren = Array.from({{ length: 6 }}, (_, i) => ({{
  item_id: '_quest_' + i,
  item_name: 'Quest ' + i,
  is_quest: true,
  children: []
}}));

const mixedTree = {{
  item_id: 'ore_iron',
  item_name: 'Iron Ore',
  children: [intermediate, ...recipeLeaves, ...questChildren]
}};

const out = prepareTreeData(mixedTree);

const recipeGroups = out.children.filter(c => c.is_group && !c.is_quest_group);
const questGroups = out.children.filter(c => c.is_quest_group === true);
const intermediates = out.children.filter(c => !c.is_group && !c.is_quest);

const res = {{
  total_children: out.children.length,
  recipe_group_count: recipeGroups.length,
  quest_group_count: questGroups.length,
  intermediate_count: intermediates.length,
  recipe_group_name: recipeGroups[0]?.item_name,
  recipe_group_children: recipeGroups[0]?.children.map(c => c.item_id),
  quest_group_name: questGroups[0]?.item_name,
  quest_group_children: questGroups[0]?.children.map(c => c.item_id),
  has_quest_in_recipe_group: recipeGroups[0]?.children.some(c => c.is_quest),
  has_recipe_in_quest_group: questGroups[0]?.children.some(c => !c.is_quest)
}};

console.log(JSON.stringify(res));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["total_children"] == 3  # [intermediate, recipeGroup, questGroup]
        assert res["recipe_group_count"] == 1
        assert res["quest_group_count"] == 1
        assert res["intermediate_count"] == 1

        assert res["recipe_group_name"] == "Direct Recipes (8)"
        assert len(res["recipe_group_children"]) == 8
        assert res["has_quest_in_recipe_group"] is False

        assert res["quest_group_name"] == "Quests (6)"
        assert len(res["quest_group_children"]) == 6
        assert res["has_recipe_in_quest_group"] is False

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_nested_intermediate_quest_isolation(self, app_file):
        """
        Adversarially tests that quest grouping respects hierarchy:
        - Parent A has 2 direct quests (ungrouped).
        - Intermediate child B has 7 direct quests (grouped under B as Quests (7)).
        - Intermediate child B's quests do NOT spill into parent A.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const prepMatch = content.match(/function prepareTreeData\\(rawTree\\) \\{{[\\s\\S]*?\\n\\}}/)[0];
const prepareTreeData = new Function('rawTree', prepMatch + '; return prepareTreeData(rawTree);');

const childB = {{
  item_id: 'item_b',
  item_name: 'Item B',
  children: Array.from({{ length: 7 }}, (_, i) => ({{
    item_id: '_quest_b_' + i,
    item_name: 'Quest B ' + i,
    is_quest: true,
    children: []
  }}))
}};

const parentA = {{
  item_id: 'item_a',
  item_name: 'Item A',
  children: [
    childB,
    {{ item_id: '_quest_a_1', item_name: 'Quest A 1', is_quest: true, children: [] }},
    {{ item_id: '_quest_a_2', item_name: 'Quest A 2', is_quest: true, children: [] }}
  ]
}};

const out = prepareTreeData(parentA);

const parentQuestGroups = out.children.filter(c => c.is_quest_group);
const parentDirectQuests = out.children.filter(c => c.is_quest);
const processedChildB = out.children.find(c => c.item_id === 'item_b');
const childBQuestGroups = processedChildB.children.filter(c => c.is_quest_group);
const childBDirectQuests = processedChildB.children.filter(c => c.is_quest);

console.log(JSON.stringify({{
  parent_quest_groups: parentQuestGroups.length,
  parent_direct_quests: parentDirectQuests.length,
  child_b_quest_groups: childBQuestGroups.length,
  child_b_direct_quests: childBDirectQuests.length,
  child_b_group_name: childBQuestGroups[0]?.item_name,
  child_b_group_count: childBQuestGroups[0]?.children.length
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["parent_quest_groups"] == 0
        assert res["parent_direct_quests"] == 2
        assert res["child_b_quest_groups"] == 1
        assert res["child_b_direct_quests"] == 0
        assert res["child_b_group_name"] == "Quests (7)"
        assert res["child_b_group_count"] == 7

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_null_and_empty_edge_cases(self, app_file):
        """Tests robustness on null, empty, or undefined trees."""
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const prepMatch = content.match(/function prepareTreeData\\(rawTree\\) \\{{[\\s\\S]*?\\n\\}}/)[0];
const prepareTreeData = new Function('rawTree', prepMatch + '; return prepareTreeData(rawTree);');

const rNull = prepareTreeData(null);
const rUndefined = prepareTreeData(undefined);
const rEmpty = prepareTreeData({{ item_id: 'x', item_name: 'X' }});
const rNoChildren = prepareTreeData({{ item_id: 'y', item_name: 'Y', children: [] }});

console.log(JSON.stringify({{
  rNull: rNull === null,
  rUndefined: rUndefined === null,
  rEmptyChildren: Array.isArray(rEmpty.children) && rEmpty.children.length === 0,
  rNoChildrenLen: rNoChildren.children.length
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)
        assert res["rNull"] is True
        assert res["rUndefined"] is True
        assert res["rEmptyChildren"] is True
        assert res["rNoChildrenLen"] == 0


class TestGetCardHeightCalculations:
    """Empirical verification of getCardHeight returns and dynamic sizing."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_all_card_height_permutations(self, app_file):
        """
        Tests exact card heights across all permutations:
        1. Quest group: exactly 56px
        2. Recipe group: exactly 56px
        3. Quest plain (no requester, no via): 44 + 24 = 68px
        4. Quest with requester (no via): 44 + 24 + 24 = 92px
        5. Quest with via (no requester): 44 + 24 + 18 = 86px
        6. Quest with requester AND via: 44 + 24 + 24 + 18 = 110px
        7. Standard root item with deficit: 44 + 24 = 68px
        8. Standard item minimum clamp: 60px
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const getCardHeightMatch = content.match(/function getCardHeight\\(d\\) \\{{[\\s\\S]*?\\n  \\}}/)[0];
const getCardHeight = new Function('d', 'deficit', getCardHeightMatch + '; return getCardHeight(d);');

const testCases = [
  {{ key: 'quest_group', d: {{ depth: 1, data: {{ is_quest_group: true }} }}, deficit: null }},
  {{ key: 'recipe_group', d: {{ depth: 1, data: {{ is_group: true }} }}, deficit: null }},
  {{ key: 'quest_plain', d: {{ depth: 1, data: {{ is_quest: true, item_name: 'Q' }} }}, deficit: null }},
  {{ key: 'quest_req', d: {{ depth: 1, data: {{ is_quest: true, item_name: 'Q', requester: 'March' }} }}, deficit: null }},
  {{ key: 'quest_via', d: {{ depth: 1, data: {{ is_quest: true, item_name: 'Q', via_item_name: 'Copper Bar' }} }}, deficit: null }},
  {{ key: 'quest_both', d: {{ depth: 1, data: {{ is_quest: true, item_name: 'Q', requester: 'March', via_item_name: 'Copper Bar' }} }}, deficit: null }},
  {{ key: 'standard_root_deficit', d: {{ depth: 0, data: {{ item_id: 'stone', item_name: 'Stone' }} }}, deficit: 10 }},
  {{ key: 'standard_item_min', d: {{ depth: 1, data: {{ item_id: 'stone', item_name: 'Stone' }} }}, deficit: null }},
  {{ key: 'standard_item_npcs', d: {{ depth: 1, data: {{ item_id: 'strawberry', item_name: 'Strawberry', gift_npcs: ['Adeline', 'Celine'] }} }}, deficit: null }},
  {{ key: 'standard_item_alts', d: {{ depth: 1, data: {{ item_id: 'strawberry', item_name: 'Strawberry', alt_sources: [{{ type: 'shop' }}, {{ type: 'inn' }}] }} }}, deficit: null }},
];

const results = {{}};
for (const tc of testCases) {{
  results[tc.key] = getCardHeight(tc.d, tc.deficit);
}}

console.log(JSON.stringify(results));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["quest_group"] == 56
        assert res["recipe_group"] == 56
        assert res["quest_plain"] == 68
        assert res["quest_req"] == 92
        assert res["quest_via"] == 86
        assert res["quest_both"] == 110
        assert res["standard_root_deficit"] == 68
        assert res["standard_item_min"] == 60
        # 44 + (1 row of 2 npcs: 1 * 22 + 4 = 26) = 70
        assert res["standard_item_npcs"] == 70
        # 44 + (2 alt sources: 2 * 26 + 4 = 56) = 100
        assert res["standard_item_alts"] == 100

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_quest_height_bounds_clamped_strictly_between_68_and_110(self, app_file):
        """Asserts that quest card heights can never fall below 68px or exceed 110px."""
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const getCardHeightMatch = content.match(/function getCardHeight\\(d\\) \\{{[\\s\\S]*?\\n  \\}}/)[0];
const getCardHeight = new Function('d', 'deficit', getCardHeightMatch + '; return getCardHeight(d);');

// Even if data has strange properties, is_quest node must be within [68, 110]
const minimalQuest = {{ depth: 1, data: {{ is_quest: true }} }};
const maximalQuest = {{ depth: 1, data: {{ is_quest: true, requester: 'Long Name', via_item_name: 'Long Item', alt_sources: [1,2,3], gift_npcs: ['A','B','C'] }} }};

const hMin = getCardHeight(minimalQuest, null);
const hMax = getCardHeight(maximalQuest, null);

console.log(JSON.stringify({{ hMin, hMax }}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)
        assert res["hMin"] >= 68
        assert res["hMax"] <= 110


class TestSearchAndExpandMatches:
    """Empirical verification of modal search matching and ancestor auto-expansion."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_search_matches_all_quest_attributes(self, app_file):
        """
        Adversarially tests search matching against:
        - Quest title (e.g. 'Water Tablet')
        - Quest type (e.g. 'Story Quest')
        - Quest category (e.g. 'Crown Request')
        - Requester (e.g. 'March')
        - Via intermediate item (e.g. 'Iron Ingot')
        - Case insensitivity ('water', 'MARCH', 'story')
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const matchFnStr = content.match(/function isNodeMatch\\(data\\) \\{{[\\s\\S]*?\\n      \\}}/)[0];

const isMatchRunner = new Function('inputTerm', 'data',
  'const term = (inputTerm || \"\").trim().toLowerCase();\\n' +
  matchFnStr + ';\\n' +
  'return isNodeMatch(data);'
);

const questData = {{
  item_id: '_quest_water_tablet',
  item_name: 'Water Tablet',
  is_quest: true,
  quest_type: 'Story Quest',
  quest_category: 'Crown Request',
  quest_amount: 1,
  requester: 'March',
  via_item_name: 'Iron Ingot',
  gift_npcs: [],
  alt_sources: []
}};

const tests = {{
  exact_name: isMatchRunner('Water Tablet', questData),
  partial_lower_name: isMatchRunner('water', questData),
  uppercase_name: isMatchRunner('TABLET', questData),
  quest_type: isMatchRunner('Story Quest', questData),
  quest_type_partial: isMatchRunner('story', questData),
  quest_cat: isMatchRunner('Crown Request', questData),
  quest_cat_partial: isMatchRunner('crown', questData),
  requester_exact: isMatchRunner('March', questData),
  requester_lower: isMatchRunner('march', questData),
  via_item: isMatchRunner('Iron Ingot', questData),
  via_partial: isMatchRunner('ingot', questData),
  negative_celine: isMatchRunner('Celine', questData),
  negative_xyz: isMatchRunner('xyz123', questData),
}};

console.log(JSON.stringify(tests));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["exact_name"] is True
        assert res["partial_lower_name"] is True
        assert res["uppercase_name"] is True
        assert res["quest_type"] is True
        assert res["quest_type_partial"] is True
        assert res["quest_cat"] is True
        assert res["quest_cat_partial"] is True
        assert res["requester_exact"] is True
        assert res["requester_lower"] is True
        assert res["via_item"] is True
        assert res["via_partial"] is True
        assert res["negative_celine"] is False
        assert res["negative_xyz"] is False

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_expand_matches_unfolds_collapsed_ancestors(self, app_file):
        """
        Adversarial test:
        Construct a 4-level deep collapsed tree where target quest node is collapsed under:
        root -> intermediate -> questGroup -> targetQuestNode.
        Assert that expandMatches() traverses, discovers targetQuestNode,
        and expands root, intermediate, and questGroup, moving _children to children.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const matchFnStr = content.match(/function isNodeMatch\\(data\\) \\{{[\\s\\S]*?\\n      \\}}/)[0];
const expandFnStr = content.match(/function expandMatches\\(n\\) \\{{[\\s\\S]*?\\n      \\}}/)[0];

const runner = new Function('inputTerm', 'rootNode',
  'const term = (inputTerm || \"\").trim().toLowerCase();\\n' +
  matchFnStr + ';\\n' +
  expandFnStr + ';\\n' +
  'const matched = expandMatches(rootNode);\\n' +
  'return {{ matched }};'
);

const targetQuest = {{
  data: {{
    item_id: '_quest_deep_march',
    item_name: 'Water Tablet',
    is_quest: true,
    requester: 'March',
    children: []
  }},
  children: null,
  _children: null
}};

const otherQuest = {{
  data: {{
    item_id: '_quest_deep_other',
    item_name: 'Spring Salad',
    is_quest: true,
    requester: 'Celine',
    children: []
  }},
  children: null,
  _children: null
}};

const questGroup = {{
  data: {{
    item_id: '_group_quests_bar',
    item_name: 'Quests (5)',
    is_group: true,
    is_quest_group: true
  }},
  children: null,
  _children: [targetQuest, otherQuest]
}};

const intermediate = {{
  data: {{
    item_id: 'copper_bar',
    item_name: 'Copper Bar'
  }},
  children: null,
  _children: [questGroup]
}};

const root = {{
  data: {{
    item_id: 'copper_ore',
    item_name: 'Copper Ore'
  }},
  children: null,
  _children: [intermediate]
}};

const res = runner('March', root);

console.log(JSON.stringify({{
  matched: res.matched,
  root_expanded: root.children !== null && root._children === null,
  intermediate_expanded: intermediate.children !== null && intermediate._children === null,
  quest_group_expanded: questGroup.children !== null && questGroup._children === null,
  target_visible: questGroup.children?.some(c => c.data.item_id === '_quest_deep_march')
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["matched"] is True
        assert res["root_expanded"] is True
        assert res["intermediate_expanded"] is True
        assert res["quest_group_expanded"] is True
        assert res["target_visible"] is True


class TestCircularAndDeepTreeStability:
    """Stress tests verifying algorithmic stability on deep trees and circular recipes."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_deep_tree_100_levels_stability(self, app_file):
        """
        Stress tests a 100-level deep hierarchy with quest children at every level:
        - Verifies prepareTreeData executes cleanly without stack overflow.
        - Verifies expandMatches navigates 100 levels deep without recursion failure.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');
const prepMatch = content.match(/function prepareTreeData\\(rawTree\\) \\{{[\\s\\S]*?\\n\\}}/)[0];
const prepareTreeData = new Function('rawTree', prepMatch + '; return prepareTreeData(rawTree);');
const matchFnStr = content.match(/function isNodeMatch\\(data\\) \\{{[\\s\\S]*?\\n      \\}}/)[0];
const expandFnStr = content.match(/function expandMatches\\(n\\) \\{{[\\s\\S]*?\\n      \\}}/)[0];
const searchRunner = new Function('inputTerm', 'node',
  'const term = (inputTerm || \"\").trim().toLowerCase();\\n' +
  matchFnStr + ';\\n' +
  expandFnStr + ';\\n' +
  'return expandMatches(node);'
);

let current = {{
  item_id: 'level_100',
  item_name: 'Level 100 Product',
  children: [
    {{
      item_id: '_quest_deepest',
      item_name: 'Deepest Dragon Quest',
      is_quest: true,
      requester: 'Dell',
      children: []
    }}
  ]
}};

for (let lvl = 99; lvl >= 0; lvl--) {{
  current = {{
    item_id: 'level_' + lvl,
    item_name: 'Level ' + lvl + ' Intermediate',
    children: [
      current,
      {{ item_id: 'leaf_' + lvl, item_name: 'Leaf ' + lvl, children: [] }},
      {{
        item_id: '_quest_' + lvl,
        item_name: 'Quest ' + lvl,
        is_quest: true,
        requester: 'March',
        children: []
      }}
    ]
  }};
}}

const t0 = Date.now();
const prepared = prepareTreeData(current);
const t1 = Date.now();

function makeHierarchy(data) {{
  const node = {{ data: data, children: null, _children: null }};
  if (data.children && data.children.length > 0) {{
    node._children = data.children.map(makeHierarchy);
  }}
  return node;
}}

const rootHierarchy = makeHierarchy(prepared);
const matchFound = searchRunner('Deepest Dragon Quest', rootHierarchy);

let depth = 0;
let ptr = rootHierarchy;
while (ptr && ptr.children) {{
  depth++;
  ptr = ptr.children.find(c => c.data.item_id.startsWith('level_'));
}}

console.log(JSON.stringify({{
  prep_time_ms: t1 - t0,
  matchFound,
  expanded_depth: depth
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["prep_time_ms"] < 250, "prepareTreeData took too long on 100 levels"
        assert res["matchFound"] is True
        assert res["expanded_depth"] == 101

    def test_backend_optimizer_circular_recipe_defense(self):
        """
        Adversarially feeds a circular crafting graph (A -> B -> C -> A)
        with quest nodes attached to all items into build_focus_crafting_trees().
        Verifies that cycle detection cleanly prunes back-edges and attaches terminal quests.
        """
        recipes = {
            "item_a": {"item_id": "item_a", "display_name": "Item A", "ingredients": [{"item_id": "item_b"}]},
            "item_b": {"item_id": "item_b", "display_name": "Item B", "ingredients": [{"item_id": "item_c"}]},
            "item_c": {"item_id": "item_c", "display_name": "Item C", "ingredients": [{"item_id": "item_a"}]},
        }
        remaining = {"item_a": {"loved": {"Adeline"}}}
        quest_data = {
            "item_a": {"quests": [{"quest_name": "Quest A", "quest_type": "Request", "amount": 1, "requester": "March"}]},
            "item_b": {"quests": [{"quest_name": "Quest B", "quest_type": "Story Quest", "amount": 2, "requester": "Celine"}]},
            "item_c": {"quests": [{"quest_name": "Quest C", "quest_type": "Crown Request", "amount": 3, "requester": "Adeline"}]},
        }
        focus = [{"item_id": "item_c", "item_name": "Item C", "deficit": 5}]

        trees = build_focus_crafting_trees(
            focus_suggestions=focus,
            recipes=recipes,
            remaining_items_map=remaining,
            quest_data=quest_data,
        )

        assert len(trees) == 1
        root = trees[0]
        assert root["item_id"] == "item_c"

        # Walk tree and collect visited nodes to confirm finite acyclic structure
        visited_nodes = []
        quest_nodes = []

        def traverse(n):
            visited_nodes.append(n["item_id"])
            if n.get("is_quest"):
                quest_nodes.append(n["item_name"])
            for child in n.get("children", []):
                traverse(child)

        traverse(root)
        # item_c -> item_b -> item_a -> quests
        assert len(visited_nodes) == 6  # root(c), b, a, quest_a, quest_b, quest_c
        assert set(quest_nodes) == {"Quest A", "Quest B", "Quest C"}


class TestCodeParityBetweenCompanionAndWeb:
    """Empirical verification that companion/static/app.js and web/app.js have zero drift."""

    def test_prepare_tree_data_identical(self):
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        w_code = WEB_APP_JS.read_text(encoding="utf-8")

        import re
        c_fn = re.search(r"function prepareTreeData\(rawTree\) \{[\s\S]*?\n\}", c_code).group(0)
        w_fn = re.search(r"function prepareTreeData\(rawTree\) \{[\s\S]*?\n\}", w_code).group(0)

        assert c_fn == w_fn, "prepareTreeData has drifted between companion and web!"

    def test_get_card_height_identical(self):
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        w_code = WEB_APP_JS.read_text(encoding="utf-8")

        import re
        c_fn = re.search(r"function getCardHeight\(d\) \{[\s\S]*?\n  \}", c_code).group(0)
        w_fn = re.search(r"function getCardHeight\(d\) \{[\s\S]*?\n  \}", w_code).group(0)

        assert c_fn == w_fn, "getCardHeight has drifted between companion and web!"

    def test_search_functions_identical(self):
        c_code = COMPANION_APP_JS.read_text(encoding="utf-8")
        w_code = WEB_APP_JS.read_text(encoding="utf-8")

        import re
        c_match = re.search(r"function isNodeMatch\(data\) \{[\s\S]*?\n      \}", c_code).group(0)
        w_match = re.search(r"function isNodeMatch\(data\) \{[\s\S]*?\n      \}", w_code).group(0)
        assert c_match == w_match, "isNodeMatch has drifted between companion and web!"

        c_expand = re.search(r"function expandMatches\(n\) \{[\s\S]*?\n      \}", c_code).group(0)
        w_expand = re.search(r"function expandMatches\(n\) \{[\s\S]*?\n      \}", w_code).group(0)
        assert c_expand == w_expand, "expandMatches has drifted between companion and web!"


class TestFocusCardsQuestUIContracts:
    """Empirical verification of Focus Suggestion card rendering contracts."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_split_deficit_and_quest_reminder_row_rendering(self, app_file):
        """
        Verifies that focus cards render:
        1. Split deficit 'Need: 12 (8 Gifts + 4 Quests)' when quest_demand > 0.
        2. Simple deficit 'Need: 8' when quest_demand is 0 or absent.
        3. '.focus-quest-row' with category pills and rich tooltips when quests exist.
        4. Dynamic tree button text toggling between 'View crafting & quest tree' and 'View crafting tree'.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');

// Isolate escapeHtml and renderFocusSuggestions
const escapeHtmlMatch = content.match(/function escapeHtml\\(str\\) \\{{[\\s\\S]*?\\n\\}}/)[0];

// Simple mock for external rendering functions
const mockEnv = `
${{escapeHtmlMatch}}
function renderSourceSummary() {{}}
function renderBlockedNpcs() {{ return ''; }}
function resolveItemSprite(id) {{ return 'icons/' + id + '.png'; }}
function resolveLocationIcon(id) {{ return 'icons/' + id + '.png'; }}
let window = {{ _craftingTreeData: {{}} }};
`;

const renderFnMatch = content.match(/function renderFocusSuggestions\\(focusItems[\\s\\S]*?\\n\\}}/)[0];

const runner = new Function('focusItems', 'focusTrees',
  mockEnv + '\\n' +
  'let grid = {{ innerHTML: \"\" }};\\n' +
  'let document = {{ getElementById: () => grid }};\\n' +
  renderFnMatch + ';\\n' +
  'renderFocusSuggestions(focusItems, focusTrees);\\n' +
  'return {{ html: grid.innerHTML, treeData: window._craftingTreeData }};'
);

// Focus item 1: Has both gifts and quests
const itemWithQuests = {{
  item_id: 'ore_stone',
  item_name: 'Stone',
  deficit: 12,
  gift_deficit: 8,
  quest_demand: 4,
  quest_count: 2,
  quest_categories: {{ 'Story Quest': 1, 'Request': 1 }},
  quest_summary: [
    {{ quest_name: 'Water Tablet', amount: 1, is_direct: true, requester: 'March' }},
    {{ quest_name: 'Stone Lantern', amount: 3, is_direct: false, target_item_name: 'Lantern', requester: 'Adeline' }}
  ],
  sprite_url: 'icons/stone.png'
}};

const treeWithQuests = {{
  item_id: 'ore_stone',
  children: [
    {{ item_id: '_quest_1', item_name: 'Water Tablet', is_quest: true, children: [] }}
  ]
}};

// Focus item 2: Gifts only (no quests)
const itemGiftsOnly = {{
  item_id: 'strawberry',
  item_name: 'Strawberry',
  deficit: 5,
  gift_deficit: 5,
  quest_demand: 0,
  quest_count: 0,
  sprite_url: 'icons/strawberry.png'
}};

const treeGiftsOnly = {{
  item_id: 'strawberry',
  children: [
    {{ item_id: 'strawberry_cake', item_name: 'Strawberry Cake', children: [] }}
  ]
}};

const res1 = runner([itemWithQuests], [treeWithQuests]);
const res2 = runner([itemGiftsOnly], [treeGiftsOnly]);

console.log(JSON.stringify({{
  card1_has_split_badge: res1.html.includes('Need: 12 (8 Gifts + 4 Quests)'),
  card1_has_quest_row: res1.html.includes('focus-quest-row'),
  card1_has_story_pill: res1.html.includes('quest-cat-story-quest'),
  card1_has_request_pill: res1.html.includes('quest-cat-request'),
  card1_has_tooltip_march: res1.html.includes('Water Tablet ×1 (March)'),
  card1_has_tooltip_via: res1.html.includes('Stone Lantern ×3 via Lantern (Adeline)'),
  card1_button_text: res1.html.includes('View crafting &amp; quest tree') || res1.html.includes('View crafting & quest tree'),

  card2_has_simple_badge: res2.html.includes('Need: 5') && !res2.html.includes('Gifts +'),
  card2_has_no_quest_row: !res2.html.includes('focus-quest-row'),
  card2_button_text: res2.html.includes('View crafting tree') && !res2.html.includes('& quest tree') && !res2.html.includes('&amp; quest tree')
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert res["card1_has_split_badge"] is True
        assert res["card1_has_quest_row"] is True
        assert res["card1_has_story_pill"] is True
        assert res["card1_has_request_pill"] is True
        assert res["card1_has_tooltip_march"] is True
        assert res["card1_has_tooltip_via"] is True
        assert res["card1_button_text"] is True

        assert res["card2_has_simple_badge"] is True
        assert res["card2_has_no_quest_row"] is True
        assert res["card2_button_text"] is True


class TestTreeModalCardDOMRendering:
    """Empirical verification of SVG foreignObject HTML generation in D3 tree modal."""

    @pytest.mark.parametrize("app_file", ["companion/static/app.js", "web/app.js"])
    def test_quest_and_quest_group_node_card_markup(self, app_file):
        """
        Verifies that nodeEnter foreignObject card rendering generates:
        1. For is_quest: '.d3-tree-node.is-quest', scroll emoji 📜, category badge, Required: ×N, requester chip, via note.
        2. For is_quest_group: '.d3-tree-node.is-group.is-quest-group', scroll emoji 📜, Quests (N), '▶ N quests' toggle pill.
        3. For recipe group: '.d3-tree-node.is-group', recipe icon, Direct Recipes (N), '▶ N products' toggle pill.
        """
        script = f"""
const fs = require('fs');
const content = fs.readFileSync('{app_file}', 'utf8');

// Extract escapeHtml
const escapeHtmlMatch = content.match(/function escapeHtml\\(str\\) \\{{[\\s\\S]*?\\n\\}}/)[0];

// Extract the node rendering branch inside openCraftingTreeModal
const openFnMatch = content.match(/function openCraftingTreeModal\\([\\s\\S]*?\\n\\}}/)[0];

// Isolate the card HTML building logic from nodeEnter.each(...)
// Lines ~773-860
const eachMatch = openFnMatch.match(/nodeEnter\\.each\\(function\\(d\\) \\{{([\\s\\S]*?)\\n    \\}}\\);/);
if (!eachMatch) throw new Error('nodeEnter.each not found in ' + '{app_file}');

// Extract getCardHeight
const getCardHeightMatch = content.match(/function getCardHeight\\(d\\) \\{{[\\s\\S]*?\\n  \\}}/)[0];

const cardBuilder = new Function('d', 'deficit',
  escapeHtmlMatch + '\\n' +
  'const CARD_W = 220;\\n' +
  getCardHeightMatch + '\\n' +
  'function resolveNpcPortrait(r) {{ return \"icons/npc_\" + r + \".png\"; }}\\n' +
  'function resolveItemSprite(i) {{ return \"icons/item_\" + i + \".png\"; }}\\n' +
  'function generatePlaceholderSvg() {{ return \"\"; }}\\n' +
  'let capturedHtml = \"\";\\n' +
  'const mockDiv = {{ html: (h) => {{ capturedHtml = h; }}, text: () => mockDiv, classed: () => mockDiv, empty: () => false }};\\n' +
  'const mockSel = {{\\n' +
  '  append: () => mockSel,\\n' +
  '  attr: () => mockSel,\\n' +
  '  style: () => mockSel,\\n' +
  '  on: () => mockSel,\\n' +
  '  html: (h) => {{ capturedHtml = h; return mockSel; }},\\n' +
  '  select: () => mockDiv\\n' +
  '}};\\n' +
  'const d3 = {{ select: () => mockSel }};\\n' +
  eachMatch[1] + '\\n' +
  'return {{ cardClass, bodyHtml: capturedHtml }};'
);

// 1. Quest node with all details
const questNode = {{
  depth: 1,
  data: {{
    item_id: '_quest_iron_tablet',
    item_name: 'Iron Tablet Quest',
    is_quest: true,
    quest_category: 'Story Quest',
    quest_amount: 3,
    requester: 'March',
    via_item_name: 'Iron Ingot'
  }}
}};

// 2. Quest group node
const questGroupNode = {{
  depth: 1,
  data: {{
    item_id: '_group_quests_iron',
    item_name: 'Quests (5)',
    is_group: true,
    is_quest_group: true
  }},
  _children: [1,2,3,4,5]
}};

// 3. Recipe group node
const recipeGroupNode = {{
  depth: 1,
  data: {{
    item_id: '_group_direct_iron',
    item_name: 'Direct Recipes (7)',
    is_group: true
  }},
  _children: [1,2,3,4,5,6,7]
}};

const r1 = cardBuilder(questNode, null);
const r2 = cardBuilder(questGroupNode, null);
const r3 = cardBuilder(recipeGroupNode, null);

console.log(JSON.stringify({{
  r1_class: r1.cardClass,
  r1_has_scroll: r1.bodyHtml.includes('📜'),
  r1_has_cat_badge: r1.bodyHtml.includes('quest-cat-story-quest') && r1.bodyHtml.includes('Story Quest'),
  r1_has_amount: r1.bodyHtml.includes('Required: ×3'),
  r1_has_requester: r1.bodyHtml.includes('d3-requester-name') && r1.bodyHtml.includes('March'),
  r1_has_via: r1.bodyHtml.includes('via Iron Ingot'),

  r2_class: r2.cardClass,
  r2_has_scroll: r2.bodyHtml.includes('📜'),
  r2_has_title: r2.bodyHtml.includes('Quests (5)'),
  r2_toggle_text: r2.bodyHtml.includes('5 quests'),

  r3_class: r3.cardClass,
  r3_has_title: r3.bodyHtml.includes('Direct Recipes (7)'),
  r3_toggle_text: r3.bodyHtml.includes('7 products')
}}));
"""
        out = run_node_snippet(script)
        res = json.loads(out)

        assert "is-quest" in res["r1_class"]
        assert res["r1_has_scroll"] is True
        assert res["r1_has_cat_badge"] is True
        assert res["r1_has_amount"] is True
        assert res["r1_has_requester"] is True
        assert res["r1_has_via"] is True

        assert "is-quest-group" in res["r2_class"]
        assert res["r2_has_scroll"] is True
        assert res["r2_has_title"] is True
        assert res["r2_toggle_text"] is True

        assert "is-group" in res["r3_class"]
        assert "is-quest-group" not in res["r3_class"]
        assert res["r3_has_title"] is True
        assert res["r3_toggle_text"] is True

