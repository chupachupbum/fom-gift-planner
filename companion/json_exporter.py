"""
companion/json_exporter.py

Converts fom_planner models, date structures, and optimizer output into
a JSON-serializable dictionary for consumption by the companion frontend.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from companion.config import CompanionConfig
from fom_planner.models import InGameDate, SaveData


def _to_serializable(val: Any) -> Any:
    """Recursively converts sets, tuples, Paths, and enums to JSON-safe structures."""
    if isinstance(val, (set, frozenset)):
        return sorted([_to_serializable(x) for x in val], key=lambda x: str(x))
    if isinstance(val, (list, tuple)):
        return [_to_serializable(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _to_serializable(v) for k, v in val.items()}
    if isinstance(val, Path):
        return str(val)
    if hasattr(val, "value"):  # Enum support
        return val.value
    return val


def plan_to_json(
    save: Optional[SaveData],
    plan_results: Dict[str, Any],
    metadata: Dict[str, Any],
    save_path: Optional[Path],
    config: CompanionConfig,
) -> Dict[str, Any]:
    """
    Transforms the planner output into a clean, comprehensive JSON document.
    """
    stats = plan_results.get("overall_stats", {})
    bag_plan_raw = plan_results.get("bag_plan", [])
    focus_raw = plan_results.get("focus_suggestions", [])
    npc_progress_raw = plan_results.get("npc_progress", {})

    # Extract date & player info
    date_info: Optional[InGameDate] = None
    if save and hasattr(save, "in_game_date") and save.in_game_date:
        date_info = save.in_game_date
    else:
        date_info = InGameDate(year=1, season="spring", day=1)

    player_name = save.player_name if (save and hasattr(save, "player_name")) else "Player"
    farm_name = save.farm_name if (save and hasattr(save, "farm_name")) else "Farm"

    # Save metadata
    save_info = {
        "found": save is not None,
        "path": str(save_path) if save_path else None,
        "filename": save_path.name if save_path else None,
        "modified_at": datetime.fromtimestamp(save_path.stat().st_mtime).isoformat() if (save_path and save_path.exists()) else None,
        "player_name": player_name,
        "farm_name": farm_name,
    }

    # Date info
    in_game_date = {
        "year": getattr(date_info, "year", 1),
        "season": getattr(date_info, "season", "spring").capitalize(),
        "day": getattr(date_info, "day", 1),
        "day_of_week": getattr(date_info, "day_of_week", "Sunday"),
        "is_saturday": getattr(date_info, "is_saturday", False),
        "is_animal_festival": getattr(date_info, "is_animal_festival", False),
        "festival_name": getattr(date_info, "festival_name", None),
        "days_until_saturday": getattr(date_info, "days_until_saturday", 0),
        "formatted": str(date_info),
    }

    # Bag plan items
    bag_plan: List[Dict[str, Any]] = []
    for item in bag_plan_raw:
        item_id = str(item.get("item_id", "")).strip().lower()
        recipients = []
        for r in item.get("all_recipients_today", []):
            recipients.append({
                "npc_id": r.get("npc_id", ""),
                "name": r.get("name") or r.get("npc_id", "").capitalize(),
                "preference": str(r.get("pref") or r.get("pref_tier") or "like").upper(),
                "points": r.get("points", 10),
                "is_vendor": bool(r.get("is_vendor", False)),
            })

        # Extract crafting information defensively
        plan = item.get("crafting_plan")
        raw_chain = item.get("crafting_chain")
        crafting_summary = str(raw_chain).strip() if isinstance(raw_chain, str) else ""

        crafting_steps = []
        if plan is not None and hasattr(plan, "steps") and plan.steps:
            for step in plan.steps:
                ing_list = []
                for ing in getattr(step, "ingredients", []):
                    ing_list.append({
                        "item_id": ing.get("item_id", ""),
                        "name": ing.get("display_name") or ing.get("item_id", "").replace("_", " ").title(),
                        "count": ing.get("count", 1),
                    })
                crafting_steps.append({
                    "product_id": getattr(step, "product_id", ""),
                    "product_name": getattr(step, "product_name", "") or getattr(step, "product_id", "").replace("_", " ").title(),
                    "count": getattr(step, "count", 1),
                    "ingredients": ing_list,
                })

        quantity = item.get("quantity_to_pack") or item.get("quantity") or len(recipients) or 1

        bag_plan.append({
            "slot": item.get("slot", len(bag_plan) + 1),
            "item_id": item_id,
            "item_name": item.get("item_name") or item_id.replace("_", " ").title(),
            "quantity": quantity,
            "quantity_to_pack": quantity,
            "status": str(item.get("status", "HAVE")).upper(),
            "status_badge": item.get("status_badge", "📦 HAVE"),
            "availability_tier": _to_serializable(item.get("availability_tier", 2)),
            "is_infused": bool(item.get("is_infused", False)),
            "infusion": item.get("infusion"),
            "crafting_summary": crafting_summary,
            "crafting_steps": crafting_steps,
            "max_craftable": item.get("max_craftable", 0),
            "recipients": recipients,
            "sprite_url": f"/assets/sprites/items/{item_id}",
        })

    # Focus suggestions
    rem_map = plan_results.get("remaining_items_map", {})
    all_recipes = plan_results.get("all_recipes") or plan_results.get("recipes")
    if not all_recipes:
        try:
            from fom_planner.crafting import load_recipes
            all_recipes = load_recipes()
        except Exception:
            all_recipes = {}

    focus_suggestions: List[Dict[str, Any]] = []
    for f in focus_raw:
        f_id = str(f.get("item_id", "")).strip().lower()
        impact_score = f.get("weighted_impact") if f.get("weighted_impact") is not None else f.get("impact_score", 0)
        location = f.get("location_hint") or f.get("location") or "Gather / Farm"

        blocked_raw = f.get("blocked_npcs")
        if blocked_raw:
            if isinstance(blocked_raw, (set, list)):
                blocked_list = [str(x).capitalize() for x in sorted(blocked_raw)]
            else:
                blocked_list = [str(blocked_raw)]
        else:
            blocked_set = set()
            for gift_id, targets in rem_map.items():
                if not gift_id or not isinstance(targets, dict):
                    continue
                pending = targets.get("loved", set()) | targets.get("liked", set())
                if not pending:
                    continue
                if gift_id == f_id:
                    blocked_set.update(pending)
                elif all_recipes and gift_id in all_recipes:
                    try:
                        from fom_planner.optimizer import resolve_root_raw_materials
                        raws = resolve_root_raw_materials(gift_id, all_recipes)
                        if f_id in raws:
                            blocked_set.update(pending)
                    except Exception:
                        pass
            blocked_list = sorted([str(x).capitalize() for x in blocked_set])

        focus_suggestions.append({
            "item_id": f_id,
            "item_name": f.get("item_name") or f_id.replace("_", " ").title(),
            "impact_score": impact_score,
            "deficit": f.get("deficit", 0),
            "count_needed": f.get("count_needed") or f.get("count", 0),
            "location": location,
            "seasons": _to_serializable(f.get("seasons", [])),
            "is_seasonal": bool(f.get("is_seasonal", False)),
            "blocked_npcs": blocked_list,
            "sprite_url": f"/assets/sprites/items/{f_id}",
        })

    # NPC Overview
    npc_progress: Dict[str, Any] = {}
    for nid, p in npc_progress_raw.items():
        nid_clean = str(nid).strip().lower()
        npc_progress[nid_clean] = {
            "npc_id": nid_clean,
            "name": p.get("name") or nid_clean.capitalize(),
            "is_vendor": bool(p.get("is_vendor", False)),
            "is_unlocked": bool(p.get("is_unlocked", True)),
            "gifted_today": bool(p.get("gifted_today", False)),
            "hearts": p.get("hearts", 0),
            "relationship_points": p.get("relationship_points", 0),
            "max_relationship": bool(p.get("is_max_relationship", False)),
            "gifts_given_count": p.get("gifts_given_count", 0),
            "total_remaining": p.get("total_remaining", 0),
            "pct_total_done": p.get("pct_total_done", 0.0),
            "portrait_url": f"/assets/sprites/npcs/{nid_clean}",
        }

    # Infused items summary
    infused_items = plan_results.get("infused_items")
    if infused_items is None and save is not None and hasattr(save, "get_infused_items"):
        try:
            infused_items = save.get_infused_items()
        except Exception:
            infused_items = None

    return {
        "generated_at": datetime.now().isoformat(),
        "save_info": save_info,
        "in_game_date": in_game_date,
        "config": config.to_dict(),
        "stats": {
            "strategy": config.strategy,
            "mode": stats.get("mode", config.mode),
            "max_slots": config.slots,
            "slots_used": len(bag_plan),
            "covered_npcs_count": stats.get("covered_npcs_count", len(plan_results.get("covered_npcs", []))),
            "target_npcs_count": stats.get("target_npcs_count", len(plan_results.get("target_npcs", []))),
            "total_relationship_points": stats.get("total_relationship_points", 0),
            "game_total_preferences": stats.get("game_total_preferences", 0),
            "game_given_total": stats.get("game_given_total", 0),
            "game_given_loved": stats.get("game_given_loved", 0),
            "game_given_liked": stats.get("game_given_liked", 0),
            "locked_npcs": _to_serializable(stats.get("locked_npcs", [])),
            "completed_npcs": _to_serializable(stats.get("completed_npcs", [])),
            "ungiftable_npcs": _to_serializable(stats.get("ungiftable_npcs", [])),
            "max_relationship_npcs": _to_serializable(stats.get("max_relationship_npcs", [])),
        },
        "infused_items": _to_serializable(infused_items),
        "bag_plan": bag_plan,
        "focus_suggestions": focus_suggestions,
        "npc_progress": npc_progress,
        "error": None,
    }
