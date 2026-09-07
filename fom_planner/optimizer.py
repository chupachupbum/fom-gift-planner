"""
optimizer.py

Greedy weighted set-cover optimizer and focus suggestions calculator for Fields of Mistria:
- resolve_root_raw_materials
- compute_focus_suggestions
- plan_daily_gift_bag
"""

from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    SATURDAY_MARKET_VENDORS,
    AvailabilityTier,
)
from fom_planner.crafting import (
    _calculate_max_craftable,
    deduct_crafting_materials,
    evaluate_craftability,
    load_recipes,
)
from fom_planner.data_loader import load_item_locations
from fom_planner.models import SaveData

ITEM_LOCATIONS: Dict[str, str] = load_item_locations()


def resolve_root_raw_materials(
    item_id: str,
    recipes: Dict[str, Any],
    call_stack: Optional[Set[str]] = None,
) -> Dict[str, int]:
    """
    Recursively resolves item_id down its recipe tree to identify all root raw materials
    (items that do not have a recipe). Returns a dict of {raw_item_id: count_needed_per_item}.
    """
    if not item_id:
        return {}
    item_id = str(item_id).strip().lower()
    if not item_id:
        return {}

    if call_stack is None:
        call_stack = set()

    if not recipes or not isinstance(recipes, dict) or item_id in call_stack or item_id not in recipes:
        return {item_id: 1}

    recipe = recipes.get(item_id)
    if not isinstance(recipe, dict):
        return {item_id: 1}

    ingredients = recipe.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        return {item_id: 1}

    call_stack.add(item_id)
    try:
        raw_mats: Dict[str, int] = {}
        for ing in ingredients:
            if not isinstance(ing, dict):
                continue
            ing_id = str(ing.get("item_id", "")).strip().lower()
            if not ing_id:
                continue
            try:
                ing_count = max(1, int(round(float(ing.get("count", 1)))))
            except (ValueError, TypeError):
                ing_count = 1
            sub_raw = resolve_root_raw_materials(ing_id, recipes, call_stack)
            for raw_id, count in sub_raw.items():
                raw_mats[raw_id] = raw_mats.get(raw_id, 0) + count * ing_count
        return raw_mats
    finally:
        call_stack.remove(item_id)


def compute_focus_suggestions(
    remaining_items_map: Dict[str, Dict[str, Set[str]]],
    inventory: Optional[Dict[str, int]] = None,
    recipes: Optional[Dict[str, Any]] = None,
    item_metadata: Optional[Dict[str, dict]] = None,
    top_n: int = 5,
    item_locations: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Computes a ranked list of top insufficient items (raw materials and direct gifts)
    blocking pending NPC gift opportunities.

    Algorithm:
      1. For each item in remaining_items_map, recursively resolves its recipe tree
         to identify all root raw material ingredients needed.
      2. Sums total demand for each raw ingredient across ALL pending gift-NPC pairs.
      3. Accounts for player's owned inventory, including:
         - Pre-crafted/finished gifts in inventory that directly satisfy pending NPC preferences.
         - Processed/intermediate goods (e.g. Flour for Wheat, Sugar for Sugar Cane, Rice for
           Rice Stalk, Cheese/Butter for Milk) converting their surplus towards root raw material inventory.
      4. Subtracts player's effective inventory pool to find deficit = demand - inventory.
      5. Identifies items where deficit > 0.
      6. Ranks by: (1) blocked NPC-gift pairs count descending,
                   (2) deficit count descending (tiebreaker),
                   (3) display name ascending (tiebreaker).
      7. Returns top N items with 1-based rank, deficit, and location hints.
    """
    if top_n <= 0:
        return []

    if recipes is None:
        recipes = load_recipes()
    if item_metadata is None:
        item_metadata = {}

    clean_inv: Dict[str, int] = {}
    if inventory and isinstance(inventory, dict):
        for k, v in inventory.items():
            if not k:
                continue
            k_clean = str(k).strip().lower()
            if not k_clean:
                continue
            try:
                val = int(round(float(v)))
                if val > 0:
                    clean_inv[k_clean] = clean_inv.get(k_clean, 0) + val
            except (ValueError, TypeError):
                pass

    def _normalize_npc_set(val: Any) -> Set[str]:
        if val is None:
            return set()
        if isinstance(val, (str, bytes)):
            s = str(val).strip()
            return {s} if s else set()
        if hasattr(val, "__iter__"):
            res = set()
            for x in val:
                if x is not None:
                    s = str(x).strip()
                    if s:
                        res.add(s)
            return res
        return set()

    # Identify intermediate items in recipes (crafted items used as ingredients in other recipes)
    all_recipe_ingredients: Set[str] = set()
    if recipes and isinstance(recipes, dict):
        for r in recipes.values():
            if isinstance(r, dict):
                for ing in r.get("ingredients", []):
                    if isinstance(ing, dict) and ing.get("item_id"):
                        all_recipe_ingredients.add(str(ing["item_id"]).strip().lower())
    intermediate_items: Set[str] = (
        {k.strip().lower() for k in recipes.keys()} & all_recipe_ingredients
        if recipes and isinstance(recipes, dict)
        else set()
    )

    # Track direct gift demand for intermediate items to reserve them before converting surplus
    direct_gift_demand: Dict[str, int] = {}
    if remaining_items_map and isinstance(remaining_items_map, dict):
        for item_id, targets in remaining_items_map.items():
            if item_id and isinstance(targets, dict):
                item_clean = str(item_id).strip().lower()
                pending = _normalize_npc_set(targets.get("loved")) | _normalize_npc_set(targets.get("liked"))
                direct_gift_demand[item_clean] = len(pending)

    # Calculate effective inventory for root raw materials (including equivalents from surplus intermediate goods)
    effective_inv: Dict[str, int] = dict(clean_inv)
    for item_id, count in clean_inv.items():
        if item_id in intermediate_items:
            needed_direct = direct_gift_demand.get(item_id, 0)
            surplus_count = max(0, count - needed_direct)
            if surplus_count > 0:
                sub_raws = resolve_root_raw_materials(item_id, recipes)
                for raw_id, raw_cnt in sub_raws.items():
                    if raw_id != item_id:
                        effective_inv[raw_id] = effective_inv.get(raw_id, 0) + raw_cnt * surplus_count

    raw_demand: Dict[str, int] = {}
    raw_blocked_pairs: Dict[str, Set[Tuple[str, str]]] = {}

    if remaining_items_map and isinstance(remaining_items_map, dict):
        for item_id, targets in remaining_items_map.items():
            if not item_id or not isinstance(targets, dict):
                continue
            item_clean = str(item_id).strip().lower()
            if not item_clean:
                continue
            loved_set = _normalize_npc_set(targets.get("loved"))
            liked_set = _normalize_npc_set(targets.get("liked"))
            pending_npcs = loved_set | liked_set
            if not pending_npcs:
                continue

            # If player already owns finished copies of this crafted gift, they don't need raw ingredients
            have_finished = clean_inv.get(item_clean, 0) if (recipes and item_clean in recipes) else 0
            total_needed = len(pending_npcs)
            needed_to_craft = max(0, total_needed - have_finished)

            if not recipes or item_clean not in recipes:
                # Raw item (not craftable)
                raw_demand[item_clean] = raw_demand.get(item_clean, 0) + total_needed
                if item_clean not in raw_blocked_pairs:
                    raw_blocked_pairs[item_clean] = set()
                for nid in pending_npcs:
                    raw_blocked_pairs[item_clean].add((str(nid), item_clean))
            else:
                # Crafted item
                if needed_to_craft > 0:
                    raw_mats = resolve_root_raw_materials(item_clean, recipes)
                    for raw_id, count_per_gift in raw_mats.items():
                        if not raw_id:
                            continue
                        raw_demand[raw_id] = raw_demand.get(raw_id, 0) + count_per_gift * needed_to_craft
                        if raw_id not in raw_blocked_pairs:
                            raw_blocked_pairs[raw_id] = set()
                        for nid in list(pending_npcs)[:needed_to_craft]:
                            raw_blocked_pairs[raw_id].add((str(nid), item_clean))

    suggestions: List[Dict[str, Any]] = []
    for raw_id, total_dem in raw_demand.items():
        inv_count = effective_inv.get(raw_id, 0)
        deficit = total_dem - inv_count
        if deficit > 0:
            blocked_count = len(raw_blocked_pairs.get(raw_id, set()))
            meta = item_metadata.get(raw_id, {}) if isinstance(item_metadata, dict) else {}
            if isinstance(meta, dict):
                disp_name = meta.get("display_name") or raw_id.replace("_", " ").title()
            elif isinstance(meta, str) and meta.strip():
                disp_name = meta.strip()
            else:
                disp_name = raw_id.replace("_", " ").title()
            loc_map = item_locations if item_locations is not None else ITEM_LOCATIONS
            location = loc_map.get(raw_id, "")

            suggestions.append({
                "item_id": raw_id,
                "item_name": disp_name,
                "blocked_pairs": blocked_count,
                "demand": total_dem,
                "inventory": inv_count,
                "deficit": deficit,
                "location_hint": location,
            })

    # Sort by: (1) blocked NPC-gift pairs descending, (2) deficit descending, (3) name ascending
    suggestions.sort(key=lambda x: (-x["blocked_pairs"], -x["deficit"], str(x["item_name"]).lower()))

    # Assign 1-indexed ranks and trim to top_n
    result: List[Dict[str, Any]] = []
    for rank, item in enumerate(suggestions[:top_n], start=1):
        item["rank"] = rank
        result.append(item)

    return result


def plan_daily_gift_bag(
    save: Optional[SaveData] = None,
    npc_gift_definitions: Optional[Dict[str, dict]] = None,
    item_metadata: Optional[Dict[str, dict]] = None,
    mode: str = "auto",
    max_slots: int = 20,
    loved_weight: int = 3,
    liked_weight: int = 1,
    vendor_boost: float = 1.5,
    exclude_npcs: Optional[Set[str]] = None,
    force_all_npcs: bool = False,
    inventory: Optional[Dict[str, int]] = None,
    recipes: Optional[Dict[str, Any]] = None,
    item_locations: Optional[Dict[str, str]] = None,
) -> dict:
    """
    Computes the optimal bag loadout for today's gifting session with inventory awareness.

    Modes:
      - 'auto' / 'today': Use save calendar date (weekday = 26 townsfolk, Saturday = 34 NPCs)
      - 'saturday' / 'market': Simulate Saturday Market day (all 34 NPCs with vendor boost)
      - 'market-only': Plan only for the 8 visiting Saturday Market vendors
      - 'townsfolk' / 'weekday': Plan only for the 26 permanent townsfolk
      - 'all': Plan for all 34 NPCs regardless of day

    Returns a dict with:
        - bag_plan: list of bag slot dicts (including availability_tier, status, status_badge, crafting_chain)
        - npc_progress: dict of npc_id -> stats
        - covered_npcs: set of npc_ids covered today
        - target_npcs: set of npc_ids included in planning
        - remaining_items_map: dict of ungifted item_id -> {"loved": set(), "liked": set()}
        - focus_suggestions: top 5 insufficient blocker items
        - overall_stats: summary counts
    """
    if exclude_npcs is None:
        exclude_npcs = set()
    if npc_gift_definitions is None:
        npc_gift_definitions = {}
    if item_metadata is None:
        item_metadata = {}
    if recipes is None:
        recipes = load_recipes()

    # Determine current inventory pool (merging bag + chests or using explicit inventory)
    if inventory is not None:
        current_inventory = {}
        for k, v in inventory.items():
            if not k:
                continue
            try:
                cnt = int(round(float(v)))
                if cnt > 0:
                    k_clean = str(k).strip().lower()
                    current_inventory[k_clean] = current_inventory.get(k_clean, 0) + cnt
            except (ValueError, TypeError):
                pass
    elif save is not None and hasattr(save, "get_all_available_items"):
        current_inventory = {}
        for k, v in save.get_all_available_items().items():
            if not k:
                continue
            try:
                cnt = int(round(float(v)))
                if cnt > 0:
                    k_clean = str(k).strip().lower()
                    current_inventory[k_clean] = current_inventory.get(k_clean, 0) + cnt
            except (ValueError, TypeError):
                pass
    else:
        current_inventory = {}

    initial_inventory = dict(current_inventory)

    is_sat = False
    is_animal_fest = False
    if save is not None and hasattr(save, "in_game_date") and save.in_game_date is not None:
        is_sat = getattr(save.in_game_date, "is_saturday", False)
        is_animal_fest = getattr(save.in_game_date, "is_animal_festival", False)

    planning_for_saturday = (mode in ("saturday", "market")) or (mode == "auto" and is_sat)

    # 1. Determine which NPCs are eligible under current mode
    all_npcs = sorted(npc_gift_definitions.keys())
    target_npcs = set()
    ungiftable_npcs = []
    not_present_npcs = []
    locked_npcs = []

    npc_progress = {}
    total_game_loved = 0
    total_game_liked = 0
    total_given_loved = 0
    total_given_liked = 0

    for nid in all_npcs:
        if nid in exclude_npcs:
            continue

        g_def = npc_gift_definitions[nid]
        npc_name = g_def.get("name", nid.replace("_", " ").title())
        all_loved = set(g_def.get("loved", []))
        all_liked = set(g_def.get("liked", []))
        is_vendor = nid.lower() in SATURDAY_MARKET_VENDORS

        total_game_loved += len(all_loved)
        total_game_liked += len(all_liked)

        if save is not None and hasattr(save, "get_npc_gifts_given"):
            given_set = save.get_npc_gifts_given(nid)
        else:
            given_set = set()

        given_loved = all_loved & given_set
        given_liked = all_liked & given_set

        total_given_loved += len(given_loved)
        total_given_liked += len(given_liked)

        remaining_loved = all_loved - given_set
        remaining_liked = all_liked - given_set

        # Check unlocked status from save progression
        is_unlocked = True
        if save is not None and hasattr(save, "is_npc_unlocked") and hasattr(save, "npcs") and save.npcs:
            is_unlocked = save.is_npc_unlocked(nid)

        # Determine presence based on mode
        if not is_unlocked:
            is_present = False
            can_gift = False
            locked_npcs.append(nid)
        else:
            if mode in ("saturday", "market"):
                is_present = True
            elif mode == "market-only":
                is_present = is_vendor
            elif mode in ("townsfolk", "weekday"):
                is_present = not is_vendor
            elif mode == "all":
                is_present = True
            else:  # "auto" or "today"
                is_present = save.is_npc_present_in_town_today(nid) if (save and hasattr(save, "is_npc_present_in_town_today")) else True

            if force_all_npcs:
                can_gift = True
            elif mode in ("saturday", "market") and not is_sat:
                can_gift = True
            elif save is not None and hasattr(save, "can_gift_npc_today"):
                can_gift = save.can_gift_npc_today(nid)
            else:
                can_gift = True

            if not is_present:
                not_present_npcs.append(nid)
            elif not can_gift:
                ungiftable_npcs.append(nid)
            elif remaining_loved or remaining_liked:
                target_npcs.add(nid)

        hp = save.get_npc_heart_points(nid) if (save and hasattr(save, "get_npc_heart_points")) else 0.0
        npc_progress[nid] = {
            "name": npc_name,
            "hp": hp,
            "is_vendor": is_vendor,
            "is_unlocked": is_unlocked,
            "is_present_today": is_present,
            "can_gift_today": can_gift,
            "gifts_given_count": len(given_set),
            "given_loved_count": len(given_loved),
            "given_liked_count": len(given_liked),
            "remaining_loved": remaining_loved,
            "remaining_liked": remaining_liked,
            "remaining_loved_count": len(remaining_loved),
            "remaining_liked_count": len(remaining_liked),
            "total_remaining": len(remaining_loved) + len(remaining_liked),
            "pct_loved_done": (len(given_loved) / len(all_loved) * 100.0) if all_loved else 100.0,
            "pct_total_done": ((len(given_loved) + len(given_liked)) / (len(all_loved) + len(all_liked)) * 100.0) if (all_loved or all_liked) else 100.0,
            "assigned_item_id": None,
            "assigned_item_name": None,
            "assigned_pref_type": None,
        }

    # 2. Build remaining item coverage mapping
    # all_remaining_items_map: All non-excluded NPCs with pending preferences (for focus suggestions and game totals)
    all_remaining_items_map = {}
    for nid, p in npc_progress.items():
        for item_id in p["remaining_loved"]:
            if item_id not in all_remaining_items_map:
                all_remaining_items_map[item_id] = {"loved": set(), "liked": set()}
            all_remaining_items_map[item_id]["loved"].add(nid)

        for item_id in p["remaining_liked"]:
            if item_id not in all_remaining_items_map:
                all_remaining_items_map[item_id] = {"loved": set(), "liked": set()}
            all_remaining_items_map[item_id]["liked"].add(nid)

    # today_remaining_items_map: Items relevant to today's target NPCs (for greedy bag selection)
    today_remaining_items_map = {}
    for nid in target_npcs:
        p = npc_progress[nid]
        for item_id in p["remaining_loved"]:
            if item_id not in today_remaining_items_map:
                today_remaining_items_map[item_id] = {"loved": set(), "liked": set()}
            today_remaining_items_map[item_id]["loved"].add(nid)

        for item_id in p["remaining_liked"]:
            if item_id not in today_remaining_items_map:
                today_remaining_items_map[item_id] = {"loved": set(), "liked": set()}
            today_remaining_items_map[item_id]["liked"].add(nid)

    # 3. Greedy Weighted Set Cover Algorithm with Tiered Availability & Dynamic Pool Deduction
    covered_npcs = set()
    bag_plan = []

    while len(bag_plan) < max_slots and len(covered_npcs) < len(target_npcs):
        best_item_id = None
        best_tuple = None
        best_selected_recipients = []
        best_status_tier = AvailabilityTier.UNAVAILABLE
        best_qty = 0

        for item_id, targets in today_remaining_items_map.items():
            new_loved = (targets["loved"] & target_npcs) - covered_npcs
            new_liked = (targets["liked"] & target_npcs) - covered_npcs

            if not new_loved and not new_liked:
                continue

            max_avail = _calculate_max_craftable(item_id, current_inventory, recipes)
            owned_count = current_inventory.get(item_id, 0)

            # Sort candidate recipients by priority:
            # Loved vendors > Loved townsfolk > Liked vendors > Liked townsfolk
            def recip_sort_key(nid):
                is_v = npc_progress[nid]["is_vendor"]
                is_l = nid in new_loved
                is_boosted = (planning_for_saturday and is_v) or (is_animal_fest and nid.lower() in ANIMAL_FESTIVAL_ATTENDING_VENDORS)
                return (0 if is_l and is_boosted else (1 if is_l else (2 if is_boosted else 3)), npc_progress[nid]["name"])

            sorted_recips = sorted(list(new_loved | new_liked), key=recip_sort_key)

            if max_avail > 0:
                actual_cover_count = min(len(sorted_recips), max_avail)
            else:
                actual_cover_count = len(sorted_recips)

            selected_recips = sorted_recips[:actual_cover_count]
            selected_loved = [nid for nid in selected_recips if nid in new_loved]
            selected_liked = [nid for nid in selected_recips if nid in new_liked]

            # Score calculation with Saturday / Festival vendor boost
            score = 0.0
            for nid in selected_loved:
                weight = float(loved_weight)
                is_boosted = (planning_for_saturday and npc_progress[nid]["is_vendor"]) or (is_animal_fest and nid.lower() in ANIMAL_FESTIVAL_ATTENDING_VENDORS)
                if is_boosted:
                    weight *= vendor_boost
                score += weight

            for nid in selected_liked:
                weight = float(liked_weight)
                is_boosted = (planning_for_saturday and npc_progress[nid]["is_vendor"]) or (is_animal_fest and nid.lower() in ANIMAL_FESTIVAL_ATTENDING_VENDORS)
                if is_boosted:
                    weight *= vendor_boost
                score += weight

            if score <= 0:
                continue

            if max_avail <= 0:
                tier = AvailabilityTier.UNAVAILABLE
            elif owned_count >= actual_cover_count:
                tier = AvailabilityTier.HAVE
            else:
                tier = AvailabilityTier.CRAFT

            meta = item_metadata.get(item_id, {})
            try:
                bin_p = int(meta.get("bin_price")) if meta.get("bin_price") not in ("", None) else 999999
            except (ValueError, TypeError):
                bin_p = 999999

            try:
                store_p = int(meta.get("store_price")) if meta.get("store_price") not in ("", None) else 999999
            except (ValueError, TypeError):
                store_p = 999999

            item_name = str(meta.get("display_name", item_id))

            # Count how many visiting / boosted vendors are covered by this item
            vendor_hits = sum(
                1 for nid in selected_recips
                if (planning_for_saturday and npc_progress[nid]["is_vendor"])
                or (is_animal_fest and nid.lower() in ANIMAL_FESTIVAL_ATTENDING_VENDORS)
            )

            # 7-element Candidate ranking tuple:
            # (availability_tier, score, vendor_hits, len(selected_loved), -bin_p, -store_p, -len(item_name))
            candidate_tuple = (int(tier), score, vendor_hits, len(selected_loved), -bin_p, -store_p, -len(item_name))

            if best_item_id is None or candidate_tuple > best_tuple:
                best_tuple = candidate_tuple
                best_item_id = item_id
                best_selected_recipients = selected_recips
                best_status_tier = tier
                best_qty = actual_cover_count

        if best_item_id is None or best_qty <= 0:
            break

        owned = current_inventory.get(best_item_id, 0)
        best_new_loved = [nid for nid in best_selected_recipients if nid in today_remaining_items_map[best_item_id]["loved"]]
        best_new_liked = [nid for nid in best_selected_recipients if nid in today_remaining_items_map[best_item_id]["liked"]]

        meta = item_metadata.get(best_item_id, {})
        disp_name = meta.get("display_name") or best_item_id.replace("_", " ").title()

        # Build list of recipient info
        recipients = []
        for nid in sorted(best_new_loved):
            recipients.append({
                "npc_id": nid,
                "name": npc_progress[nid]["name"],
                "pref": "LOVE",
                "is_vendor": npc_progress[nid]["is_vendor"]
            })
            npc_progress[nid]["assigned_item_id"] = best_item_id
            npc_progress[nid]["assigned_item_name"] = disp_name
            npc_progress[nid]["assigned_pref_type"] = "LOVE"

        for nid in sorted(best_new_liked):
            recipients.append({
                "npc_id": nid,
                "name": npc_progress[nid]["name"],
                "pref": "LIKE",
                "is_vendor": npc_progress[nid]["is_vendor"]
            })
            npc_progress[nid]["assigned_item_id"] = best_item_id
            npc_progress[nid]["assigned_item_name"] = disp_name
            npc_progress[nid]["assigned_pref_type"] = "LIKE"

        quantity_to_pack = best_qty

        # Evaluate craftability and perform dynamic inventory deduction
        plan = evaluate_craftability(best_item_id, current_inventory, recipes, count_needed=quantity_to_pack)
        current_inventory = deduct_crafting_materials(best_item_id, current_inventory, recipes, count=quantity_to_pack)

        # Availability status string and badge
        if best_status_tier == AvailabilityTier.HAVE:
            status_str = "HAVE"
            status_badge = "📦 HAVE"
        elif best_status_tier == AvailabilityTier.CRAFT:
            status_str = "CRAFT"
            if owned > 0:
                status_badge = f"🔨 HAVE ({owned}) + CRAFT ({quantity_to_pack - owned})"
            else:
                status_badge = "✅ CRAFT"
        else:
            status_str = "UNAVAILABLE"
            status_badge = "❌ NEED"

        crafting_chain = plan.chain_summary if plan is not None else ""

        # Also get all potential NPCs who could take this item across all NPCs in the game
        all_potential_loved = sorted([npc_progress[x]["name"] for x in all_remaining_items_map.get(best_item_id, {}).get("loved", set())])
        all_potential_liked = sorted([npc_progress[x]["name"] for x in all_remaining_items_map.get(best_item_id, {}).get("liked", set())])

        tag_list = meta.get("tags", [])
        tags_str = ", ".join(tag_list) if isinstance(tag_list, list) else str(tag_list)

        bag_plan.append({
            "slot": len(bag_plan) + 1,
            "item_id": best_item_id,
            "item_name": disp_name,
            "quantity_to_pack": quantity_to_pack,
            "status": status_str,
            "availability_tier": int(best_status_tier),
            "status_badge": status_badge,
            "crafting_chain": crafting_chain,
            "crafting_plan": plan,
            "max_craftable": plan.max_craftable if plan is not None else 0,
            "raw_materials_needed": plan.raw_materials_needed if plan is not None else {},
            "loved_recipients_today": [r["name"] for r in recipients if r["pref"] == "LOVE"],
            "liked_recipients_today": [r["name"] for r in recipients if r["pref"] == "LIKE"],
            "all_recipients_today": recipients,
            "market_vendors_covered": [r["name"] for r in recipients if r["is_vendor"]],
            "all_potential_loved": all_potential_loved,
            "all_potential_liked": all_potential_liked,
            "bin_price": meta.get("bin_price", ""),
            "store_price": meta.get("store_price", ""),
            "tags": tags_str,
            "description": meta.get("description", "")
        })

        covered_npcs |= set(best_selected_recipients)

    # Overall statistics
    today_loved_count = sum(len(b["loved_recipients_today"]) for b in bag_plan)
    today_liked_count = sum(len(b["liked_recipients_today"]) for b in bag_plan)
    vendors_covered_today = sum(len(b["market_vendors_covered"]) for b in bag_plan)

    if save is not None and hasattr(save, "get_unlocked_npc_ids") and hasattr(save, "npcs") and save.npcs:
        unlocked_vendor_ids = save.get_unlocked_vendor_ids()
        unlocked_townsfolk_ids = {k for k in save.get_unlocked_npc_ids() if k not in SATURDAY_MARKET_VENDORS}
        unlocked_vendors_count = len(unlocked_vendor_ids)
        unlocked_townsfolk_count = len(unlocked_townsfolk_ids)
        unlocked_npcs_count = len(save.get_unlocked_npc_ids())
    else:
        unlocked_npcs_list = [nid for nid, p in npc_progress.items() if p.get("is_unlocked", True)]
        unlocked_vendors = [nid for nid in unlocked_npcs_list if npc_progress[nid]["is_vendor"]]
        unlocked_townsfolk = [nid for nid in unlocked_npcs_list if not npc_progress[nid]["is_vendor"]]
        unlocked_vendors_count = len(unlocked_vendors)
        unlocked_townsfolk_count = len(unlocked_townsfolk)
        unlocked_npcs_count = len(unlocked_npcs_list)

    overall_stats = {
        "mode": mode,
        "planning_for_saturday": planning_for_saturday,
        "is_animal_festival": is_animal_fest,
        "target_npcs_count": len(target_npcs),
        "covered_npcs_count": len(covered_npcs),
        "unlocked_npcs_count": unlocked_npcs_count,
        "unlocked_vendors_count": unlocked_vendors_count,
        "unlocked_townsfolk_count": unlocked_townsfolk_count,
        "slots_used": len(bag_plan),
        "max_slots": max_slots,
        "today_loved_completed": today_loved_count,
        "today_liked_completed": today_liked_count,
        "today_total_completed": today_loved_count + today_liked_count,
        "vendors_covered_today": vendors_covered_today,
        "game_total_loved": total_game_loved,
        "game_total_liked": total_game_liked,
        "game_total_preferences": total_game_loved + total_game_liked,
        "game_given_loved": total_given_loved,
        "game_given_liked": total_given_liked,
        "game_given_total": total_given_loved + total_given_liked,
        "remaining_unique_items": len(all_remaining_items_map),
        "ungiftable_npcs": [npc_gift_definitions[nid].get("name", nid) for nid in ungiftable_npcs if nid in npc_gift_definitions],
        "not_present_npcs": [npc_gift_definitions[nid].get("name", nid) for nid in not_present_npcs if nid in npc_gift_definitions],
        "locked_npcs": [npc_gift_definitions[nid].get("name", nid) for nid in locked_npcs if nid in npc_gift_definitions],
    }

    focus_suggestions = compute_focus_suggestions(
        remaining_items_map=all_remaining_items_map,
        inventory=initial_inventory,
        recipes=recipes,
        item_metadata=item_metadata,
        top_n=5,
        item_locations=item_locations,
    )

    return {
        "bag_plan": bag_plan,
        "npc_progress": npc_progress,
        "covered_npcs": covered_npcs,
        "target_npcs": target_npcs,
        "remaining_items_map": all_remaining_items_map,
        "all_remaining_items_map": all_remaining_items_map,
        "today_remaining_items_map": today_remaining_items_map,
        "focus_suggestions": focus_suggestions,
        "overall_stats": overall_stats,
    }

