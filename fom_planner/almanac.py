"""
almanac.py

Core Almanac Planning Engine for Fields of Mistria:
1. 12-Category Progress & Furniture Swatch Grouping ("one_per_recipe" vs "all_swatches")
2. Available Inventory Pooling & Gift Bag Reservation Deduction
3. Ready to Craft Now (Greedy Batch Queue with Intermediate Chaining & Station Badging)
4. Recursive Raw Material DAG Breakdown, Combined Deficits & D3 Crafting Trees for #treeModal
5. Unified Acquisition Source Priority (Quick / Grind / Farm scored by Total Almanac Impact)
"""

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fom_planner.constants import AvailabilityTier, MARRIAGE_EXCLUSIVE_QUEST_NAMES
from fom_planner.crafting import (
    CraftingPlan,
    CraftingStep,
    deduct_crafting_materials,
    evaluate_craftability,
    load_recipes,
)
from fom_planner.data_loader import (
    load_almanac_data,
    load_alt_sources,
    load_item_locations,
    load_quest_data,
)
from fom_planner.models import SaveData, _normalize_quest_key
from fom_planner.optimizer import (
    classify_source_tier,
    normalize_source_name,
    resolve_root_raw_materials,
)

CANONICAL_ALMANAC_CATEGORIES = [
    "artifacts",
    "blacksmithing",
    "bugs",
    "cooked_dishes",
    "crops",
    "date_inspiration",
    "fish",
    "forageables",
    "furniture",
    "materials",
    "ranching",
    "song_crystal",
]


def normalize_season(season_filter: str, save: Optional[Any] = None) -> str:
    """
    Normalizes season filter string into canonical season ('spring', 'summer', 'fall', 'winter', 'all').
    If season_filter is 'current', resolves current save season (mapping autumn -> fall).
    """
    s = str(season_filter).strip().lower()
    if s == "current":
        if save is not None and hasattr(save, "in_game_date") and save.in_game_date:
            cur_season = getattr(save.in_game_date, "season", None)
            if cur_season:
                s = str(cur_season).strip().lower()
            else:
                s = "all"
        else:
            s = "all"

    if s in ("all", "all seasons", "all-seasons", ""):
        return "all"
    if s == "autumn":
        return "fall"
    if s in ("spring", "summer", "fall", "winter"):
        return s
    return "all"


def is_item_in_season(item_info: Dict[str, Any], effective_season: str) -> bool:
    """
    Checks if an item is available in effective_season.
    Items without seasonal restrictions (empty seasons list) are available in all seasons.
    """
    if effective_season == "all":
        return True
    raw_seasons = item_info.get("seasons", [])
    if not raw_seasons or not isinstance(raw_seasons, list):
        return True
    seasons = [str(x).strip().lower().replace("autumn", "fall") for x in raw_seasons if x]
    if not seasons:
        return True
    return effective_season in seasons


def is_recipe_unlocked(
    item_id: str,
    recipe_key: Optional[str],
    recipe: Dict[str, Any],
    unlocked_recipe_ids: Optional[Set[str]],
) -> bool:
    """
    Determines whether a crafting recipe is unlocked for the player.
    Default recipes and milling station recipes are always unlocked.
    If unlocked_recipe_ids is None (e.g. stripped save or uninspected), defaults to True.
    """
    if recipe.get("is_default") is True:
        return True
    if str(recipe.get("station", "")).strip().lower() == "milling":
        return True
    if unlocked_recipe_ids is None:
        return True

    iid_clean = item_id.strip().lower()
    if iid_clean in unlocked_recipe_ids:
        return True
    if recipe_key and str(recipe_key).strip().lower() in unlocked_recipe_ids:
        return True
    return False


def get_gift_synergy_tags(item_id: str, remaining_items_map: Dict[str, Any]) -> List[str]:
    """
    Returns human-readable gift synergy badges for an item, e.g. ['Celine (Loved)'].
    """
    if not remaining_items_map:
        return []
    entry = remaining_items_map.get(item_id, {})
    loved = entry.get("loved", [])
    liked = entry.get("liked", [])
    tags: List[str] = []
    for npc in sorted(loved):
        tags.append(f"{str(npc).capitalize()} (Loved)")
    for npc in sorted(liked):
        tags.append(f"{str(npc).capitalize()} (Liked)")
    return tags


def get_quest_synergy_tags(
    item_id: str,
    quest_data: Dict[str, Any],
    completed_quests: Set[str],
) -> List[str]:
    """
    Returns human-readable active quest synergy badges for an item, e.g. ['Request for Copper (March)'].
    """
    if not quest_data or item_id not in quest_data:
        return []
    q_entry = quest_data.get(item_id, {})
    quests = q_entry.get("quests", [])
    tags: List[str] = []
    for q in quests:
        q_name = q.get("quest_name", "")
        if not q_name:
            continue
        if _normalize_quest_key(q_name) in completed_quests:
            continue
        req = q.get("requester")
        req_suffix = f" ({req.capitalize()})" if req else ""
        tags.append(f"{q_name}{req_suffix}")
    return tags


def get_item_physical_sources(
    item_id: str,
    item_info: Dict[str, Any],
    item_locations: Dict[str, str],
    alt_sources: Dict[str, List[Dict[str, Any]]],
) -> List[Tuple[str, str]]:
    """
    Resolves physical acquisition sources and their Quick/Grind/Farm tiers for an item.
    Returns list of (normalized_source_name, tier).
    """
    results: List[Tuple[str, str]] = []

    # 1. Inspect explicit sources in almanac_data item metadata
    raw_sources = item_info.get("sources")
    if isinstance(raw_sources, list) and raw_sources:
        for s in raw_sources:
            if not isinstance(s, dict):
                continue
            loc = s.get("location")
            if not loc:
                continue
            norm = normalize_source_name(str(loc))
            tier = s.get("tier")
            if not tier or str(tier).lower() not in ("quick", "grind", "farm"):
                tier = classify_source_tier(norm, s.get("type")).lower()
            else:
                tier = str(tier).lower()
            results.append((norm, tier))

    # 2. Inspect alternate sources
    if item_id in alt_sources:
        for alt in alt_sources[item_id]:
            loc = alt.get("location")
            if not loc:
                continue
            norm = normalize_source_name(str(loc))
            tier = alt.get("tier")
            if not tier or str(tier).lower() not in ("quick", "grind", "farm"):
                tier = classify_source_tier(norm, alt.get("type")).lower()
            else:
                tier = str(tier).lower()
            results.append((norm, tier))

    # 3. Fallback to item_locations.json
    if not results and item_id in item_locations:
        loc = item_locations[item_id]
        if loc:
            norm = normalize_source_name(loc)
            tier = classify_source_tier(norm).lower()
            results.append((norm, tier))

    # 4. Canonical category fallbacks
    if not results:
        cat = item_info.get("category", "")
        if cat == "furniture":
            results.append(("Furniture Shop / Carpentry", "quick"))
        elif cat == "fish":
            results.append(("Fishing & Diving", "grind"))
        elif cat == "bugs":
            results.append(("Bug Catching", "quick"))
        elif cat == "artifacts":
            results.append(("Archaeology / Dig Sites", "grind"))
        elif cat == "crops":
            results.append(("Farm Crops", "farm"))
        elif cat == "ranching":
            results.append(("Hayden's Ranch", "farm"))
        elif cat == "forageables":
            results.append(("Wild Foraging", "grind"))
        else:
            results.append(("General Exploration", "grind"))

    # Deduplicate while preserving order
    deduped: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for norm, tier in results:
        if norm not in seen:
            seen.add(norm)
            deduped.append((norm, tier))

    return deduped


def deduct_gift_bag_reservations(
    inventory: Dict[str, int],
    gift_plan_result: Optional[Dict[str, Any]],
    recipes: Dict[str, Any],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Deducts materials reserved by Today's Gift Bag (bag_plan) from available stock
    before Almanac batch crafting and deficit calculations.
    Returns (updated_inventory, reserved_by_gifts).
    """
    updated_inv = {k.strip().lower(): int(v) for k, v in inventory.items() if v > 0}
    reserved_by_gifts: Dict[str, int] = {}

    if not gift_plan_result or not isinstance(gift_plan_result, dict):
        return updated_inv, reserved_by_gifts

    bag_plan = gift_plan_result.get("bag_plan")
    if not isinstance(bag_plan, list) or not bag_plan:
        return updated_inv, reserved_by_gifts

    for slot in bag_plan:
        if not isinstance(slot, dict):
            continue
        item_id = str(slot.get("item_id", "")).strip().lower()
        if not item_id:
            continue
        try:
            qty = max(1, int(slot.get("quantity_to_pack", 1)))
        except (ValueError, TypeError):
            qty = 1

        status = str(slot.get("status", "")).strip().upper()
        if status == "HAVE":
            avail = updated_inv.get(item_id, 0)
            take = min(avail, qty)
            if take > 0:
                updated_inv[item_id] -= take
                reserved_by_gifts[item_id] = reserved_by_gifts.get(item_id, 0) + take
        elif status == "CRAFT":
            raw_needed = slot.get("raw_materials_needed")
            if isinstance(raw_needed, dict) and raw_needed:
                for mat_id, mat_cnt in raw_needed.items():
                    m_clean = str(mat_id).strip().lower()
                    try:
                        c = int(mat_cnt)
                    except (ValueError, TypeError):
                        c = 1
                    avail = updated_inv.get(m_clean, 0)
                    take = min(avail, c)
                    if take > 0:
                        updated_inv[m_clean] -= take
                        reserved_by_gifts[m_clean] = reserved_by_gifts.get(m_clean, 0) + take
            else:
                old_copy = dict(updated_inv)
                updated_inv = deduct_crafting_materials(item_id, updated_inv, recipes, count=qty)
                for k, v_old in old_copy.items():
                    v_new = updated_inv.get(k, 0)
                    delta = v_old - v_new
                    if delta > 0:
                        reserved_by_gifts[k] = reserved_by_gifts.get(k, 0) + delta

    # Clean zero or negative values
    cleaned_inv = {k: v for k, v in updated_inv.items() if v > 0}
    return cleaned_inv, reserved_by_gifts


def get_dag_unobtained_items(
    item_id: str,
    recipes: Dict[str, Any],
    acquired_items: Set[str],
    call_stack: Optional[Set[str]] = None,
) -> Set[str]:
    """
    Returns the set of all unobtained item IDs across this recipe's recursive DAG.
    """
    if call_stack is None:
        call_stack = set()
    if item_id in call_stack or item_id not in recipes:
        return set()
    call_stack.add(item_id)

    unobtained = {item_id} if item_id not in acquired_items else set()
    recipe = recipes[item_id]
    for ing in recipe.get("ingredients", []):
        if not isinstance(ing, dict):
            continue
        ing_id = str(ing.get("item_id", "")).strip().lower()
        if ing_id in recipes:
            unobtained.update(get_dag_unobtained_items(ing_id, recipes, acquired_items, call_stack))

    call_stack.remove(item_id)
    return unobtained


def compute_batch_crafting_queue(
    acquired_items: Set[str],
    unlocked_recipes: Optional[Set[str]],
    available_inventory: Dict[str, int],
    almanac_items: Dict[str, Any],
    furniture_mode: str = "one_per_recipe",
    remaining_items_map: Optional[Dict[str, Any]] = None,
    quest_data: Optional[Dict[str, Any]] = None,
    completed_quests: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Greedily schedules unlocked unobtained craftable items against available inventory.
    Chains intermediate unobtained recipes forward so one craft satisfies both
    intermediate and downstream Almanac slots without double-counting ingredients.
    """
    if remaining_items_map is None:
        remaining_items_map = {}
    if completed_quests is None:
        completed_quests = set()

    # Build recipe dictionary for crafting evaluator
    recipes_for_crafting: Dict[str, Any] = {}
    for iid, it in almanac_items.items():
        r = it.get("recipe")
        if r and isinstance(r, dict):
            r_copy = dict(r)
            r_copy["item_id"] = iid
            r_copy["display_name"] = it.get("name", iid.replace("_", " ").title())
            recipes_for_crafting[iid] = r_copy

    # Fallback to load_recipes() to enrich any missing intermediate recipes
    loaded_craft_recipes = load_recipes()
    if loaded_craft_recipes:
        for rid, rdata in loaded_craft_recipes.items():
            if rid not in recipes_for_crafting and isinstance(rdata, dict):
                recipes_for_crafting[rid] = rdata

    # Filter to unlocked recipes
    unlocked_recipes_dict: Dict[str, Any] = {}
    for rid, rdata in recipes_for_crafting.items():
        it_info = almanac_items.get(rid, {})
        r_key = it_info.get("recipe_key")
        if is_recipe_unlocked(rid, r_key, rdata, unlocked_recipes):
            unlocked_recipes_dict[rid] = rdata

    # Filter candidate craftables: items in almanac_items with recipes that are not acquired
    candidates: List[str] = []
    furniture_group_seen: Set[str] = set()

    for iid, it in almanac_items.items():
        if iid in acquired_items:
            continue
        if iid not in unlocked_recipes_dict:
            continue

        cat = it.get("category", "")
        if cat == "furniture" and furniture_mode == "one_per_recipe":
            group_key = it.get("recipe_key") or iid
            # If any swatch of this group was already acquired, exclude the entire group
            group_swatches = [
                s_id
                for s_id, s_it in almanac_items.items()
                if (s_it.get("recipe_key") or s_id) == group_key
            ]
            if any(s in acquired_items for s in group_swatches):
                continue
            if group_key in furniture_group_seen:
                continue
            furniture_group_seen.add(group_key)

        candidates.append(iid)

    # Priority ranking function
    def candidate_sort_key(cid: str) -> Tuple[int, int, int, str]:
        u_c = len(get_dag_unobtained_items(cid, unlocked_recipes_dict, acquired_items))
        # Synergy score
        s_c = 0
        rem_entry = remaining_items_map.get(cid, {})
        s_c += 10 * len(rem_entry.get("loved", []))
        s_c += 5 * len(rem_entry.get("liked", []))
        if quest_data and cid in quest_data:
            active_q = [
                q
                for q in quest_data[cid].get("quests", [])
                if _normalize_quest_key(q.get("quest_name", "")) not in completed_quests
            ]
            s_c += 15 * len(active_q)

        # Raw material cost
        raw_mats = resolve_root_raw_materials(cid, unlocked_recipes_dict)
        m_c = sum(raw_mats.values()) if raw_mats else 1

        return (-u_c, -s_c, m_c, cid)

    candidates.sort(key=candidate_sort_key)

    working_inventory = dict(available_inventory)
    batch_unlocked: Set[str] = set()
    queue_steps: List[Dict[str, Any]] = []

    for cid in candidates:
        if cid in acquired_items or cid in batch_unlocked:
            continue

        it_info = almanac_items.get(cid, {})
        if it_info.get("category") == "furniture" and furniture_mode == "one_per_recipe":
            group_key = it_info.get("recipe_key") or cid
            group_swatches = [
                s_id
                for s_id, s_it in almanac_items.items()
                if (s_it.get("recipe_key") or s_id) == group_key
            ]
            if any(s in batch_unlocked for s in group_swatches):
                continue

        plan = evaluate_craftability(cid, working_inventory, unlocked_recipes_dict)
        if plan.status in (AvailabilityTier.CRAFT, AvailabilityTier.HAVE) and plan.steps:
            for idx, step in enumerate(plan.steps):
                p_id = step.product_id
                is_almanac_unlock = (p_id not in acquired_items and p_id not in batch_unlocked)
                if is_almanac_unlock:
                    batch_unlocked.add(p_id)

                is_intermediate = (idx < len(plan.steps) - 1)
                consumed_by = None
                if is_intermediate:
                    for sub_step in plan.steps[idx + 1:]:
                        if any(str(ing.get("item_id", "")).strip().lower() == p_id for ing in sub_step.ingredients):
                            consumed_by = sub_step.product_id
                            break
                    if not consumed_by:
                        consumed_by = plan.steps[-1].product_id

                p_info = almanac_items.get(p_id, {})
                p_name = p_info.get("name", step.product_name)
                p_cat = p_info.get("category", "materials")
                p_station = p_info.get("recipe", {}).get("station", "cooking") if p_info.get("recipe") else "cooking"

                queue_steps.append({
                    "step_number": len(queue_steps) + 1,
                    "item_id": p_id,
                    "item_name": p_name,
                    "category": p_cat,
                    "station": p_station,
                    "quantity": step.count,
                    "ingredients": step.ingredients,
                    "unlocks_almanac": is_almanac_unlock,
                    "is_intermediate": is_intermediate,
                    "consumed_by": consumed_by,
                    "gift_synergy": get_gift_synergy_tags(p_id, remaining_items_map),
                    "quest_synergy": get_quest_synergy_tags(p_id, quest_data or {}, completed_quests),
                })

            working_inventory = deduct_crafting_materials(cid, working_inventory, unlocked_recipes_dict, count=1)

    return queue_steps


def build_downstream_tree(
    root_id: str,
    combined_deficit: int,
    unblocked_for_root: Set[str],
    ingredient_to_products: Dict[str, Set[str]],
    items_dict: Dict[str, Any],
    acquired_items: Set[str],
    remaining_items_map: Dict[str, Any],
    alt_sources_map: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Constructs an interactive hierarchical D3 crafting tree node for a raw material blocker,
    matching the frontend #treeModal contract.
    """
    visited: Set[str] = set()

    def _build_node(item_id: str, branch_visited: Set[str]) -> Optional[Dict[str, Any]]:
        if item_id in branch_visited:
            return None
        branch_visited = branch_visited | {item_id}

        children: List[Dict[str, Any]] = []
        downstream = ingredient_to_products.get(item_id, set())
        for prod_id in sorted(downstream):
            child_node = _build_node(prod_id, branch_visited)
            if child_node:
                children.append(child_node)

        is_target = (item_id in unblocked_for_root)
        if not is_target and not children:
            return None

        item_info = items_dict.get(item_id, {})
        display_name = item_info.get("name", item_id.replace("_", " ").title())
        category = item_info.get("category", "")
        sprite_url = f"/assets/sprites/items/{item_id}"

        rem_entry = remaining_items_map.get(item_id, {})
        gift_npcs = [str(npc).capitalize() for npc in rem_entry.get("loved", [])] + [
            str(npc).capitalize() for npc in rem_entry.get("liked", [])
        ]
        alt_sources = alt_sources_map.get(item_id, [])

        return {
            "item_id": item_id,
            "item_name": display_name,
            "category": category,
            "sprite_url": sprite_url,
            "is_almanac_missing": (item_id not in acquired_items),
            "alt_sources": alt_sources,
            "gift_npcs": gift_npcs,
            "children": children,
        }

    root_info = items_dict.get(root_id, {})
    root_name = root_info.get("name", root_id.replace("_", " ").title())
    root_cat = root_info.get("category", "")
    rem_entry = remaining_items_map.get(root_id, {})
    gift_npcs = [str(npc).capitalize() for npc in rem_entry.get("loved", [])] + [
        str(npc).capitalize() for npc in rem_entry.get("liked", [])
    ]
    alt_sources = alt_sources_map.get(root_id, [])

    visited.add(root_id)
    root_children: List[Dict[str, Any]] = []
    for prod_id in sorted(ingredient_to_products.get(root_id, set())):
        child = _build_node(prod_id, visited)
        if child:
            root_children.append(child)

    return {
        "item_id": root_id,
        "item_name": root_name,
        "category": root_cat,
        "sprite_url": f"/assets/sprites/items/{root_id}",
        "deficit": combined_deficit,
        "alt_sources": alt_sources,
        "gift_npcs": gift_npcs,
        "children": root_children,
    }


def compute_raw_material_blockers_and_trees(
    unobtained_craftable_ids: List[str],
    available_inventory: Dict[str, int],
    almanac_items: Dict[str, Any],
    all_recipes: Dict[str, Any],
    focus_suggestions: Optional[List[Dict[str, Any]]] = None,
    remaining_items_map: Optional[Dict[str, Any]] = None,
    quest_data: Optional[Dict[str, Any]] = None,
    completed_quests: Optional[Set[str]] = None,
    alt_sources_map: Optional[Dict[str, Any]] = None,
    acquired_items: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Decomposes missing craftables to root raw materials via recursive DAG resolution,
    merges Almanac deficit with Gift/Quest deficits, and generates D3 trees compatible
    with #treeModal.
    """
    if focus_suggestions is None:
        focus_suggestions = []
    if remaining_items_map is None:
        remaining_items_map = {}
    if completed_quests is None:
        completed_quests = set()
    if alt_sources_map is None:
        alt_sources_map = {}
    if acquired_items is None:
        acquired_items = set()

    # Build reverse recipe index: ingredient -> set of products
    ingredient_to_products: Dict[str, Set[str]] = {}
    for prod_id, rdata in all_recipes.items():
        if not isinstance(rdata, dict):
            continue
        for ing in rdata.get("ingredients", []):
            if isinstance(ing, dict):
                ing_id = str(ing.get("item_id", "")).strip().lower()
                if ing_id:
                    ingredient_to_products.setdefault(ing_id, set()).add(prod_id)

    # Accumulate demand and inverse unblocked mappings
    almanac_demand: Dict[str, int] = {}
    unblocked_almanac_items: Dict[str, Set[str]] = {}

    for cid in unobtained_craftable_ids:
        root_mats = resolve_root_raw_materials(cid, all_recipes)
        for raw_id, count in root_mats.items():
            almanac_demand[raw_id] = almanac_demand.get(raw_id, 0) + count
            unblocked_almanac_items.setdefault(raw_id, set()).add(cid)

    # Build index of focus suggestions
    focus_by_item: Dict[str, Dict[str, Any]] = {}
    for sug in focus_suggestions:
        if isinstance(sug, dict):
            sid = str(sug.get("item_id", "")).strip().lower()
            if sid:
                focus_by_item[sid] = sug

    blocker_cards: List[Dict[str, Any]] = []

    for raw_id, demand in almanac_demand.items():
        owned = available_inventory.get(raw_id, 0)
        almanac_deficit = max(0, demand - owned)

        sug = focus_by_item.get(raw_id, {})
        gift_deficit = int(sug.get("gift_deficit", 0))
        quest_demand = int(sug.get("quest_demand", 0))

        if quest_demand == 0 and quest_data and raw_id in quest_data:
            active_q = [
                q
                for q in quest_data[raw_id].get("quests", [])
                if _normalize_quest_key(q.get("quest_name", "")) not in completed_quests
            ]
            quest_demand = sum(int(q.get("amount", 1)) for q in active_q)

        combined_deficit = almanac_deficit + gift_deficit + quest_demand
        if combined_deficit <= 0:
            continue

        raw_info = almanac_items.get(raw_id, {})
        raw_name = raw_info.get("name", raw_id.replace("_", " ").title())
        raw_cat = raw_info.get("category", "materials")

        unblocked_for_root = unblocked_almanac_items.get(raw_id, set())
        unblocked_list = [
            {
                "item_id": it_id,
                "name": almanac_items.get(it_id, {}).get("name", it_id.replace("_", " ").title()),
                "category": almanac_items.get(it_id, {}).get("category", "materials"),
            }
            for it_id in sorted(unblocked_for_root)
        ]

        tree = build_downstream_tree(
            root_id=raw_id,
            combined_deficit=combined_deficit,
            unblocked_for_root=unblocked_for_root,
            ingredient_to_products=ingredient_to_products,
            items_dict=almanac_items,
            acquired_items=acquired_items,
            remaining_items_map=remaining_items_map,
            alt_sources_map=alt_sources_map,
        )

        blocker_cards.append({
            "item_id": raw_id,
            "item_name": raw_name,
            "category": raw_cat,
            "almanac_demand": demand,
            "inventory": owned,
            "almanac_deficit": almanac_deficit,
            "gift_deficit": gift_deficit,
            "quest_demand": quest_demand,
            "combined_deficit": combined_deficit,
            "unblocked_almanac_items": unblocked_list,
            "tree": tree,
        })

    # Sort blockers by combined_deficit descending, then len(unblocked) descending
    blocker_cards.sort(key=lambda b: (-b["combined_deficit"], -len(b["unblocked_almanac_items"]), b["item_id"]))
    return blocker_cards


def plan_almanac(
    save: Optional[SaveData] = None,
    almanac_data: Optional[Dict[str, Any]] = None,
    gift_plan_result: Optional[Dict[str, Any]] = None,
    reserve_gifts: bool = True,
    include_locked_recipes: bool = True,
    furniture_mode: str = "one_per_recipe",
    season_filter: str = "current",
    category_filter: str = "all",
) -> Dict[str, Any]:
    """
    Primary Almanac Planner Engine.
    Executes the 5-step Almanac planning pipeline:
      1. 12-category completion tracking, furniture grouping under recipe_key, gift & quest synergy tagging.
      2. Available inventory pool with Gift Bag reservation deduction.
      3. "Ready to Craft Now" greedy batch queue with forward-passing intermediate recipe chaining.
      4. Recursive raw material DAG breakdown with combined deficits and D3 trees.
      5. Unified Acquisition Source Priority (Quick / Grind / Farm) scored by Total Almanac Impact.
    """
    if almanac_data is None:
        almanac_data = load_almanac_data()

    categories_dict = almanac_data.get("categories", {})
    items_dict = almanac_data.get("items", {})

    # 1. Acquired items and recipe unlocks
    if save is not None:
        if hasattr(save, "get_acquired_items"):
            acquired_items = {str(x).strip().lower() for x in save.get_acquired_items() if x}
        else:
            raw_acq = save.player.get("items_acquired", []) if hasattr(save, "player") and isinstance(save.player, dict) else []
            acquired_items = {str(x).strip().lower() for x in raw_acq if x}
            if hasattr(save, "get_all_available_items"):
                acquired_items.update(k.strip().lower() for k in save.get_all_available_items().keys())
            if hasattr(save, "player") and isinstance(save.player, dict):
                created = save.player.get("recipes_created", {})
                if isinstance(created, (dict, list)):
                    acquired_items.update(str(k).strip().lower() for k in created)
        unlocked_recipe_ids = save.get_unlocked_recipe_ids() if hasattr(save, "get_unlocked_recipe_ids") else None
        completed_quests = save.get_completed_quest_keys() if hasattr(save, "get_completed_quest_keys") else set()
        base_inventory = save.get_all_available_items() if hasattr(save, "get_all_available_items") else {}
    else:
        acquired_items = set()
        unlocked_recipe_ids = None
        completed_quests = set()
        base_inventory = {}

    effective_season = normalize_season(season_filter, save)
    effective_category = str(category_filter).strip().lower()
    if effective_category in ("", "all", "all categories"):
        effective_category = "all"

    # Contextual data loaders
    item_locations = load_item_locations()
    alt_sources_map = load_alt_sources()
    quest_data = load_quest_data()

    remaining_items_map = {}
    focus_suggestions = []
    if gift_plan_result and isinstance(gift_plan_result, dict):
        remaining_items_map = (
            gift_plan_result.get("remaining_items_map")
            or gift_plan_result.get("all_remaining_items_map")
            or {}
        )
        focus_suggestions = gift_plan_result.get("focus_suggestions", [])

    # 2. Available inventory pooling & gift reservation
    all_recipes_dict: Dict[str, Any] = {}
    for iid, it in items_dict.items():
        r = it.get("recipe")
        if r and isinstance(r, dict):
            r_copy = dict(r)
            r_copy["item_id"] = iid
            r_copy["display_name"] = it.get("name", iid.replace("_", " ").title())
            all_recipes_dict[iid] = r_copy

    loaded_craft_recipes = load_recipes()
    if loaded_craft_recipes:
        for rid, rdata in loaded_craft_recipes.items():
            if rid not in all_recipes_dict and isinstance(rdata, dict):
                all_recipes_dict[rid] = rdata

    if reserve_gifts and gift_plan_result:
        available_inventory, reserved_by_gifts = deduct_gift_bag_reservations(
            base_inventory, gift_plan_result, all_recipes_dict
        )
    else:
        available_inventory = {k.strip().lower(): int(v) for k, v in base_inventory.items() if v > 0}
        reserved_by_gifts = {}

    # 3. 12-Category Progress & Furniture Swatch Grouping
    categories_output: Dict[str, Any] = {}

    for cat_id in CANONICAL_ALMANAC_CATEGORIES:
        cat_info = categories_dict.get(cat_id, {})
        cat_name = cat_info.get("name", cat_id.replace("_", " ").title())
        cat_icon = cat_info.get("icon", f"spr_ui_journal_almanac_icon_{cat_id}.png")

        # Gather items belonging to this category
        cat_item_ids = cat_info.get("item_ids")
        if cat_item_ids is None:
            cat_item_ids = [
                iid for iid, it in items_dict.items()
                if it.get("category") == cat_id or cat_id in it.get("categories", [])
            ]

        decorated_items: List[Dict[str, Any]] = []
        entries_total = 0
        entries_obtained = 0

        for iid in cat_item_ids:
            it = items_dict.get(iid)
            if not it:
                continue
            is_obt = (iid in acquired_items)
            entries_total += 1
            if is_obt:
                entries_obtained += 1

            it_copy = dict(it)
            it_copy["is_obtained"] = is_obt
            it_copy["gift_synergy"] = get_gift_synergy_tags(iid, remaining_items_map)
            it_copy["quest_synergy"] = get_quest_synergy_tags(iid, quest_data, completed_quests)
            decorated_items.append(it_copy)

        groups_list: List[Dict[str, Any]] = []
        if cat_id == "furniture":
            groups_map: Dict[str, List[Dict[str, Any]]] = {}
            for it in decorated_items:
                g_key = it.get("recipe_key") or it["item_id"]
                groups_map.setdefault(g_key, []).append(it)

            for g_key, swatches in groups_map.items():
                base_name = swatches[0].get("name", g_key.replace("_", " ").title())
                # Clean variant suffix if present
                base_name = re.sub(r"\s*\((Pastel|Walnut|Pink|Blue|Red|Yellow|Green|Purple|White|Black|Brown)\)$", "", base_name, flags=re.I)
                sw_total = len(swatches)
                sw_obtained = sum(1 for s in swatches if s["is_obtained"])
                is_grp_obtained = (sw_obtained >= 1) if furniture_mode == "one_per_recipe" else (sw_obtained == sw_total)

                groups_list.append({
                    "group_key": g_key,
                    "name": base_name,
                    "swatches_total": sw_total,
                    "swatches_obtained": sw_obtained,
                    "is_obtained": is_grp_obtained,
                    "swatches": swatches,
                })

            groups_total = len(groups_list)
            groups_obtained = sum(1 for g in groups_list if g["is_obtained"])
        else:
            groups_total = entries_total
            groups_obtained = entries_obtained

        if furniture_mode == "one_per_recipe" and cat_id == "furniture":
            effective_obtained = groups_obtained
            effective_total = groups_total
        else:
            effective_obtained = entries_obtained
            effective_total = entries_total

        pct = round(effective_obtained / effective_total * 100, 1) if effective_total > 0 else 100.0

        categories_output[cat_id] = {
            "name": cat_name,
            "icon": cat_icon,
            "obtained": effective_obtained,
            "total": effective_total,
            "percentage": pct,
            "entries_obtained": entries_obtained,
            "entries_total": entries_total,
            "groups_obtained": groups_obtained,
            "groups_total": groups_total,
            "items": decorated_items,
            "groups": groups_list,
        }

    total_obtained = sum(c["obtained"] for c in categories_output.values())
    total_items = sum(c["total"] for c in categories_output.values())
    total_pct = round(total_obtained / total_items * 100, 1) if total_items > 0 else 100.0

    summary = {
        "obtained": total_obtained,
        "total": total_items,
        "percentage": total_pct,
    }

    # 4. Ready to Craft Now (Greedy Batch Queue)
    ready_to_craft = compute_batch_crafting_queue(
        acquired_items=acquired_items,
        unlocked_recipes=unlocked_recipe_ids,
        available_inventory=available_inventory,
        almanac_items=items_dict,
        furniture_mode=furniture_mode,
        remaining_items_map=remaining_items_map,
        quest_data=quest_data,
        completed_quests=completed_quests,
    )

    # 5. Missing craftable items for DAG decomposition
    unobtained_craftables: List[str] = []
    seen_furniture_groups_for_dag: Set[str] = set()

    for iid, it in items_dict.items():
        if iid in acquired_items:
            continue
        r = it.get("recipe")
        if not r or not isinstance(r, dict):
            continue

        if effective_category != "all" and it.get("category") != effective_category:
            continue

        r_key = it.get("recipe_key")
        if not include_locked_recipes:
            if not is_recipe_unlocked(iid, r_key, r, unlocked_recipe_ids):
                continue

        cat = it.get("category", "")
        if cat == "furniture" and furniture_mode == "one_per_recipe":
            group_key = r_key or iid
            group_swatches = [
                s_id
                for s_id, s_it in items_dict.items()
                if (s_it.get("recipe_key") or s_id) == group_key
            ]
            if any(s in acquired_items for s in group_swatches):
                continue
            if group_key in seen_furniture_groups_for_dag:
                continue
            seen_furniture_groups_for_dag.add(group_key)

        unobtained_craftables.append(iid)

    # Recursive raw material DAG breakdown and D3 trees
    raw_material_blockers = compute_raw_material_blockers_and_trees(
        unobtained_craftable_ids=unobtained_craftables,
        available_inventory=available_inventory,
        almanac_items=items_dict,
        all_recipes=all_recipes_dict,
        focus_suggestions=focus_suggestions,
        remaining_items_map=remaining_items_map,
        quest_data=quest_data,
        completed_quests=completed_quests,
        alt_sources_map=alt_sources_map,
        acquired_items=acquired_items,
    )

    # 6. Unified Acquisition Source Priority (Quick / Grind / Farm)
    # Gatherables: missing items without recipes matching season and category filter
    gatherables_by_source: Dict[str, List[Dict[str, Any]]] = {}
    source_tier_map: Dict[str, str] = {}

    for iid, it in items_dict.items():
        if iid in acquired_items:
            continue
        if it.get("recipe"):
            continue
        if not is_item_in_season(it, effective_season):
            continue
        if effective_category != "all" and it.get("category") != effective_category:
            continue

        sources = get_item_physical_sources(iid, it, item_locations, alt_sources_map)
        item_entry = {
            "item_id": iid,
            "name": it.get("name", iid.replace("_", " ").title()),
            "category": it.get("category", "materials"),
        }
        for src_name, tier in sources:
            source_tier_map[src_name] = tier
            gatherables_by_source.setdefault(src_name, []).append(item_entry)

    # Map raw material blockers to sources
    blockers_by_source: Dict[str, List[Dict[str, Any]]] = {}
    unblocked_by_source: Dict[str, Set[str]] = {}

    for blocker in raw_material_blockers:
        raw_id = blocker["item_id"]
        raw_info = items_dict.get(raw_id, {})
        if not is_item_in_season(raw_info, effective_season):
            continue

        raw_sources = get_item_physical_sources(raw_id, raw_info, item_locations, alt_sources_map)
        blocker_entry = {
            "item_id": raw_id,
            "name": blocker["item_name"],
            "deficit": blocker["combined_deficit"],
        }
        matching_unblocked = [
            u for u in blocker["unblocked_almanac_items"]
            if effective_category == "all"
            or u.get("category") == effective_category
            or items_dict.get(u.get("item_id"), {}).get("category") == effective_category
        ]

        if matching_unblocked or (effective_category != "all" and raw_info.get("category") == effective_category) or effective_category == "all":
            for src_name, tier in raw_sources:
                source_tier_map[src_name] = tier
                blockers_by_source.setdefault(src_name, []).append(blocker_entry)
                for u in matching_unblocked:
                    unblocked_by_source.setdefault(src_name, set()).add(u["item_id"])

    # Build sources by tier
    all_sources = set(gatherables_by_source.keys()) | set(blockers_by_source.keys())
    sources_by_tier: Dict[str, List[Dict[str, Any]]] = {
        "quick": [],
        "grind": [],
        "farm": [],
    }

    for src_name in sorted(all_sources):
        tier = source_tier_map.get(src_name, "grind")
        if tier not in ("quick", "grind", "farm"):
            tier = "grind"

        # Unique direct collectibles
        direct_seen = set()
        direct_list = []
        for d in gatherables_by_source.get(src_name, []):
            if d["item_id"] not in direct_seen:
                direct_seen.add(d["item_id"])
                direct_list.append(d)

        # Unique raw materials
        raw_seen = set()
        raw_list = []
        for r in blockers_by_source.get(src_name, []):
            if r["item_id"] not in raw_seen:
                raw_seen.add(r["item_id"])
                raw_list.append(r)

        # Unique unblocked craftables
        unblocked_set = unblocked_by_source.get(src_name, set())
        unblocked_list = [
            {
                "item_id": it_id,
                "name": items_dict.get(it_id, {}).get("name", it_id.replace("_", " ").title()),
                "category": items_dict.get(it_id, {}).get("category", "materials"),
            }
            for it_id in sorted(unblocked_set)
        ]

        total_impact = len(direct_list) + len(unblocked_list)

        if effective_category != "all" and total_impact == 0:
            continue

        sources_by_tier[tier].append({
            "source": src_name,
            "tier": tier,
            "total_impact": total_impact,
            "direct_collectibles": direct_list,
            "raw_materials": raw_list,
            "unblocked_craftables": unblocked_list,
        })

    # Sort each tier descending by total_impact
    for tier in ("quick", "grind", "farm"):
        sources_by_tier[tier].sort(key=lambda s: (-s["total_impact"], s["source"]))

    # Flat source priority: Quick -> Grind -> Farm
    source_priority = (
        sources_by_tier["quick"]
        + sources_by_tier["grind"]
        + sources_by_tier["farm"]
    )

    return {
        "summary": summary,
        "categories": categories_output,
        "ready_to_craft": ready_to_craft,
        "raw_material_blockers": raw_material_blockers,
        "sources_by_tier": sources_by_tier,
        "source_priority": source_priority,
        "reserved_by_gifts": reserved_by_gifts,
    }


__all__ = [
    "CANONICAL_ALMANAC_CATEGORIES",
    "normalize_season",
    "is_item_in_season",
    "is_recipe_unlocked",
    "deduct_gift_bag_reservations",
    "compute_batch_crafting_queue",
    "compute_raw_material_blockers_and_trees",
    "plan_almanac",
]
