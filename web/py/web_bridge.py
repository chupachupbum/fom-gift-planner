"""
web/py/web_bridge.py

Pure-Python web bridge module for Fields of Mistria Gift Planner.
Runs inside Pyodide WASM in browser Web Workers with ZERO external or companion.* dependencies.
Accepts save bytes/paths, runs optimizer, and returns plan data matching companion JSON schema.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fom_planner.crafting import filter_recipes_by_unlocks, load_recipes
from fom_planner.data_loader import (
    load_alt_sources,
    load_item_locations,
    load_item_metadata,
    load_item_seasons,
    load_npc_preferences_from_json,
    load_recipe_sources,
)
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import (
    plan_daily_gift_bag,
    plan_max_relationship,
    resolve_root_raw_materials,
)
from fom_planner.parser import parse_save_file


class WebPlannerConfig:
    """Lightweight configuration model matching CompanionConfig with zero external dependencies."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, **kwargs):
        d = dict(data or {})
        d.update(kwargs)

        self.strategy: str = str(d.get("strategy", "journal"))
        self.mode: str = str(d.get("mode", "auto"))
        self.date_override: Optional[str] = d.get("date_override")
        self.slots: int = int(d.get("slots", 20))
        self.focus_sort: str = str(d.get("focus_sort", "impact"))
        self.all_seasons: bool = bool(d.get("all_seasons", False))

        self.loved_weight: int = int(d.get("loved_weight", 3))
        self.liked_weight: int = int(d.get("liked_weight", 1))
        self.vendor_boost: float = float(d.get("vendor_boost", 1.5))
        self.seasonal_boost: float = float(d.get("seasonal_boost", 2.0))

        self.focus_mode_enabled: bool = bool(d.get("focus_mode_enabled", False))

        raw_focus = d.get("focus_npcs", "")
        if isinstance(raw_focus, (list, set, tuple)):
            self.focus_npcs: str = ",".join(str(x).strip() for x in raw_focus if str(x).strip())
        else:
            self.focus_npcs = str(raw_focus or "")

        raw_exclude = d.get("exclude_npcs", "")
        if isinstance(raw_exclude, (list, set, tuple)):
            self.exclude_npcs: str = ",".join(str(x).strip() for x in raw_exclude if str(x).strip())
        else:
            self.exclude_npcs = str(raw_exclude or "")

        self.force_all_npcs: bool = bool(d.get("force_all_npcs", False))
        self.max_relationship_points: Optional[float] = (
            float(d["max_relationship_points"]) if d.get("max_relationship_points") is not None else None
        )
        self.no_exclude_max_relationship: bool = bool(d.get("no_exclude_max_relationship", False))

        self.save_file: Optional[str] = d.get("save_file")
        self.recipes: str = str(d.get("recipes", "data/recipes.json"))
        self.fiddle: str = str(d.get("fiddle", "assets/fiddle"))
        self.item_data: str = str(d.get("item_data", "data/item_data.json"))
        self.item_locations: str = str(d.get("item_locations", "data/item_locations.json"))
        self.recipe_sources: str = str(d.get("recipe_sources", "data/recipe_sources.json"))
        self.item_seasons: str = str(d.get("item_seasons", "data/item_seasons.json"))

        self.game_assets_dir: Optional[str] = d.get("game_assets_dir")
        self.server_host: str = str(d.get("server_host", "127.0.0.1"))
        self.server_port: int = int(d.get("server_port", 8000))
        self._raw = d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "mode": self.mode,
            "date_override": self.date_override,
            "slots": self.slots,
            "focus_sort": self.focus_sort,
            "all_seasons": self.all_seasons,
            "loved_weight": self.loved_weight,
            "liked_weight": self.liked_weight,
            "vendor_boost": self.vendor_boost,
            "seasonal_boost": self.seasonal_boost,
            "focus_mode_enabled": self.focus_mode_enabled,
            "focus_npcs": self.focus_npcs,
            "exclude_npcs": self.exclude_npcs,
            "force_all_npcs": self.force_all_npcs,
            "max_relationship_points": self.max_relationship_points,
            "no_exclude_max_relationship": self.no_exclude_max_relationship,
            "save_file": self.save_file,
            "recipes": self.recipes,
            "fiddle": self.fiddle,
            "item_data": self.item_data,
            "item_locations": self.item_locations,
            "recipe_sources": self.recipe_sources,
            "item_seasons": self.item_seasons,
            "game_assets_dir": self.game_assets_dir,
            "server_host": self.server_host,
            "server_port": self.server_port,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebPlannerConfig":
        return cls(data)


def _to_serializable(val: Any) -> Any:
    """Recursively converts sets, tuples, Paths, and enums to JSON-safe structures."""
    if isinstance(val, (set, frozenset)):
        return sorted([_to_serializable(x) for x in val], key=lambda x: str(x))
    if isinstance(val, (list, tuple)):
        return [_to_serializable(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _to_serializable(v) for k, v in val.items()}
    if isinstance(val, Path):
        return val.as_posix()
    if hasattr(val, "value"):  # Enum support (e.g. AvailabilityTier)
        return val.value
    return val


def parse_date_override(
    date_override: Optional[str],
    default_date: Optional[InGameDate] = None,
) -> Optional[InGameDate]:
    """
    Parses a user-defined date override string into an InGameDate object.
    Supports festivals, Saturday keyword, seasonal date strings, and JSON formats.
    """
    if not date_override:
        return None
    raw = str(date_override).strip()
    if not raw or raw.lower() in ("none", "auto", "save", "default", "null", "false", "0"):
        return None

    # JSON format
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            season = str(data.get("season", "spring")).strip().lower()
            if season == "autumn":
                season = "fall"
            day = int(data.get("day", 1))
            day = max(1, min(28, day))
            yr = int(data.get("year", default_date.year if default_date else 1))
            yr = max(1, yr)
            return InGameDate(year=yr, season=season, day=day, time_str="10:00")
        except Exception:
            pass

    text = raw.lower()

    # 1. Festival keywords
    if "animal" in text or text in ("winter 10", "winter_10", "10 winter"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="winter", day=10, time_str="10:00")
    if "shooting" in text or text in ("summer 28", "summer_28", "28 summer"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="summer", day=28, time_str="10:00")
    if "harvest" in text:
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="fall", day=10, time_str="10:00")
    if "spring fest" in text or text in ("spring 17", "spring_17", "17 spring"):
        yr = default_date.year if default_date else 1
        return InGameDate(year=yr, season="spring", day=17, time_str="10:00")

    # 2. "saturday" or "sat" keyword
    if text.startswith("sat"):
        if default_date is not None:
            yr = default_date.year
            season = default_date.season.lower()
            if season == "autumn":
                season = "fall"
            next_day = default_date.next_saturday_day
            if next_day <= 28:
                return InGameDate(year=yr, season=season, day=next_day, time_str="10:00")
            else:
                seasons_cycle = ["spring", "summer", "fall", "winter"]
                curr_idx = seasons_cycle.index(season) if season in seasons_cycle else 0
                next_idx = (curr_idx + 1) % 4
                next_season = seasons_cycle[next_idx]
                next_yr = yr + 1 if next_idx == 0 else yr
                return InGameDate(year=next_yr, season=next_season, day=6, time_str="10:00")
        else:
            return InGameDate(year=1, season="spring", day=6, time_str="10:00")

    # 3. Year, season, and day extraction
    yr = default_date.year if default_date else 1
    yr_match = re.search(r"(?:year|y)\s*[:=]?\s*(\d+)", text)
    if yr_match:
        try:
            yr = int(yr_match.group(1))
            text = text[: yr_match.start()] + " " + text[yr_match.end() :]
        except Exception:
            pass

    season = default_date.season.lower() if default_date else "spring"
    if season == "autumn":
        season = "fall"
    if "spring" in text:
        season = "spring"
    elif "summer" in text:
        season = "summer"
    elif "fall" in text or "autumn" in text:
        season = "fall"
    elif "winter" in text:
        season = "winter"

    # Search for day number (1..28)
    day_match = re.search(r"\b([1-9]|[12][0-9])\b", text)
    if day_match:
        day = int(day_match.group(1))
        if 1 <= day <= 28:
            return InGameDate(year=max(1, yr), season=season, day=day, time_str="10:00")

    digits = re.findall(r"\d+", text)
    if digits:
        val = int(digits[0])
        day = max(1, min(28, val))
        return InGameDate(year=max(1, yr), season=season, day=day, time_str="10:00")

    return None


def plan_to_json(
    save: Optional[SaveData],
    plan_results: Dict[str, Any],
    metadata: Dict[str, Any],
    save_path: Optional[Path],
    config: Union[WebPlannerConfig, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Transforms planner output into canonical JSON schema matching companion/json_exporter.py.
    """
    if isinstance(config, dict):
        config = WebPlannerConfig(config)

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

    save_date_info: Optional[InGameDate] = None
    if save and hasattr(save, "original_in_game_date"):
        try:
            save_date_info = save.original_in_game_date
        except Exception:
            pass

    is_overridden = bool(config.date_override and str(config.date_override).strip())

    player_name = save.player_name if (save and hasattr(save, "player_name")) else "Player"
    farm_name = save.farm_name if (save and hasattr(save, "farm_name")) else "Farm"

    # Save metadata
    save_info = {
        "found": save is not None,
        "path": str(save_path) if save_path else None,
        "filename": save_path.name if save_path else None,
        "modified_at": (
            datetime.fromtimestamp(save_path.stat().st_mtime).isoformat()
            if (save_path and save_path.exists())
            else None
        ),
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
        "is_overridden": is_overridden,
        "date_override": config.date_override or "",
        "save_date": (
            {
                "year": getattr(save_date_info, "year", 1),
                "season": getattr(save_date_info, "season", "spring").capitalize(),
                "day": getattr(save_date_info, "day", 1),
                "day_of_week": getattr(save_date_info, "day_of_week", "Sunday"),
                "is_saturday": getattr(save_date_info, "is_saturday", False),
                "festival_name": getattr(save_date_info, "festival_name", None),
                "formatted": str(save_date_info),
            }
            if save_date_info
            else None
        ),
    }

    # Bag plan items
    bag_plan: List[Dict[str, Any]] = []
    for item in bag_plan_raw:
        item_id = str(item.get("item_id", "")).strip().lower()
        recipients = []
        for r in item.get("all_recipients_today", []):
            recipients.append(
                {
                    "npc_id": r.get("npc_id", ""),
                    "name": r.get("name") or r.get("npc_id", "").capitalize(),
                    "preference": str(r.get("pref") or r.get("pref_tier") or "like").upper(),
                    "points": r.get("points", 10),
                    "is_vendor": bool(r.get("is_vendor", False)),
                }
            )

        # Extract crafting information defensively
        plan = item.get("crafting_plan")
        raw_chain = item.get("crafting_chain")
        crafting_summary = str(raw_chain).strip() if isinstance(raw_chain, str) else ""

        crafting_steps = []
        if plan is not None and hasattr(plan, "steps") and plan.steps:
            for step in plan.steps:
                ing_list = []
                for ing in getattr(step, "ingredients", []):
                    ing_list.append(
                        {
                            "item_id": ing.get("item_id", ""),
                            "name": ing.get("display_name") or ing.get("item_id", "").replace("_", " ").title(),
                            "count": ing.get("count", 1),
                        }
                    )
                crafting_steps.append(
                    {
                        "product_id": getattr(step, "product_id", ""),
                        "product_name": getattr(step, "product_name", "")
                        or getattr(step, "product_id", "").replace("_", " ").title(),
                        "count": getattr(step, "count", 1),
                        "ingredients": ing_list,
                    }
                )

        quantity = item.get("quantity_to_pack") or item.get("quantity") or len(recipients) or 1

        bag_plan.append(
            {
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
            }
        )

    # Focus suggestions
    rem_map = plan_results.get("remaining_items_map", {})
    all_recipes = plan_results.get("all_recipes") or plan_results.get("recipes")
    if not all_recipes:
        try:
            all_recipes = load_recipes()
        except Exception:
            all_recipes = {}

    alt_sources_data = plan_results.get("alt_sources")
    if alt_sources_data is None:
        try:
            alt_sources_data = load_alt_sources()
        except Exception:
            alt_sources_data = {}

    item_aliases = {
        "milk": "cow_milk",
        "cow_milk": "milk",
        "golden_milk": "golden_cow_milk",
        "golden_cow_milk": "golden_milk",
        "wood": "basic_wood",
        "basic_wood": "wood",
        "stone": "ore_stone",
        "ore_stone": "stone",
        "rice_ball": "riceball",
        "riceball": "rice_ball",
        "tea": "cup_of_tea",
        "cup_of_tea": "tea",
    }

    focus_suggestions: List[Dict[str, Any]] = []
    for f in focus_raw:
        f_id = str(f.get("item_id", "")).strip().lower()
        impact_score = f.get("weighted_impact") if f.get("weighted_impact") is not None else f.get("impact_score", 0)
        location = f.get("location_hint") or f.get("location") or "Gather / Farm"

        # Resolve alt sources for item
        alt_sources_list = []
        if isinstance(alt_sources_data, dict):
            alt_sources_list = alt_sources_data.get(f_id, [])
            if not alt_sources_list and f_id in item_aliases:
                alt_sources_list = alt_sources_data.get(item_aliases[f_id], [])
        if not alt_sources_list and f.get("alt_sources"):
            alt_sources_list = f.get("alt_sources", [])

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
                        raws = resolve_root_raw_materials(gift_id, all_recipes)
                        if f_id in raws:
                            blocked_set.update(pending)
                    except Exception:
                        pass
            blocked_list = sorted([str(x).capitalize() for x in blocked_set])

        focus_suggestions.append(
            {
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
                "alt_sources": _to_serializable(alt_sources_list),
            }
        )

    # NPC Overview & Completed / Incomplete Breakdown
    npc_progress: Dict[str, Any] = {}
    completed_npcs_details: List[Dict[str, Any]] = []
    incomplete_npcs_details: List[Dict[str, Any]] = []

    for nid, p in npc_progress_raw.items():
        nid_clean = str(nid).strip().lower()
        rem_loved_raw = p.get("remaining_loved", [])
        rem_liked_raw = p.get("remaining_liked", [])

        rem_loved = []
        for item_id in sorted(rem_loved_raw):
            item_clean = str(item_id).strip().lower()
            item_meta = metadata.get(item_clean, {}) if metadata else {}
            rem_loved.append(
                {
                    "item_id": item_clean,
                    "name": item_meta.get("display_name") or item_clean.replace("_", " ").title(),
                    "sprite_url": f"/assets/sprites/items/{item_clean}",
                }
            )

        rem_liked = []
        for item_id in sorted(rem_liked_raw):
            item_clean = str(item_id).strip().lower()
            item_meta = metadata.get(item_clean, {}) if metadata else {}
            rem_liked.append(
                {
                    "item_id": item_clean,
                    "name": item_meta.get("display_name") or item_clean.replace("_", " ").title(),
                    "sprite_url": f"/assets/sprites/items/{item_clean}",
                }
            )

        is_completed = bool(
            p.get("is_completed", False)
            or (len(rem_loved) == 0 and len(rem_liked) == 0 and p.get("gifts_given_count", 0) > 0)
        )
        pct_done = round(float(p.get("pct_total_done", 100.0 if is_completed else 0.0)), 1)
        hearts_val = p.get("hp", 0) if "hp" in p else p.get("hearts", 0)

        npc_info = {
            "npc_id": nid_clean,
            "name": p.get("name") or nid_clean.capitalize(),
            "is_vendor": bool(p.get("is_vendor", False)),
            "is_unlocked": bool(p.get("is_unlocked", True)),
            "is_completed": is_completed,
            "gifted_today": bool(p.get("gifted_today", False)),
            "hearts": hearts_val,
            "relationship_points": p.get("relationship_points", 0),
            "max_relationship": bool(p.get("is_max_relationship", False)),
            "gifts_given_count": p.get("gifts_given_count", 0),
            "total_remaining": p.get("total_remaining", len(rem_loved) + len(rem_liked)),
            "remaining_loved_count": len(rem_loved),
            "remaining_liked_count": len(rem_liked),
            "pct_total_done": pct_done,
            "portrait_url": f"/assets/sprites/npcs/{nid_clean}",
            "remaining_loved": rem_loved,
            "remaining_liked": rem_liked,
        }

        npc_progress[nid_clean] = npc_info
        if is_completed:
            completed_npcs_details.append(npc_info)
        else:
            incomplete_npcs_details.append(npc_info)

    completed_npcs_details.sort(key=lambda x: str(x["name"]).lower())
    incomplete_npcs_details.sort(key=lambda x: (-x["pct_total_done"], str(x["name"]).lower()))

    # Un-obtained recipes & unlock stats
    raw_unobtained = plan_results.get("all_unobtained_recipes") or plan_results.get("focus_recipes") or []
    unobtained_recipes: List[Dict[str, Any]] = []
    for r in raw_unobtained:
        rid = str(r.get("recipe_id", "")).strip().lower()
        unobtained_recipes.append(
            {
                "rank": r.get("rank", len(unobtained_recipes) + 1),
                "recipe_id": rid,
                "display_name": r.get("display_name") or rid.replace("_", " ").title(),
                "impact": r.get("impact", 0),
                "unlock_source": r.get("unlock_source", "Unknown"),
                "sprite_url": f"/assets/sprites/items/{rid}",
            }
        )

    raw_recipe_stats = plan_results.get("recipe_unlock_stats") or {}
    recipe_stats = {
        "total_cooking": raw_recipe_stats.get("total_cooking_recipes", len(unobtained_recipes)),
        "unlocked_count": raw_recipe_stats.get("unlocked_recipes_count", 0),
        "locked_count": len(unobtained_recipes),
        "unlocked_percentage": round(float(raw_recipe_stats.get("unlocked_percentage", 0.0)), 1),
        "has_unlock_data": bool(raw_recipe_stats.get("has_unlock_data", False)),
    }

    # Overall Gift Progress percentage
    total_preferences = stats.get("game_total_preferences", 0)
    given_total = stats.get("game_given_total", 0)
    overall_progress_pct = round((given_total / total_preferences * 100.0), 1) if total_preferences > 0 else 0.0

    # Infused items summary
    infused_items = plan_results.get("infused_items")
    if infused_items is None and save is not None and hasattr(save, "get_infused_items"):
        try:
            infused_items = save.get_infused_items()
        except Exception:
            infused_items = None

    # Source Priority Summary
    source_priority_raw = plan_results.get("source_priority", [])
    source_priority: List[Dict[str, Any]] = []
    if isinstance(source_priority_raw, list):
        for entry in source_priority_raw:
            if not isinstance(entry, dict):
                continue
            entry_dict = dict(entry)
            items_raw = entry.get("items", [])
            if isinstance(items_raw, dict):
                items_raw = list(items_raw.values())
            items_clean = []
            if isinstance(items_raw, list):
                for it in items_raw:
                    if isinstance(it, dict):
                        it_dict = dict(it)
                        i_id = str(it_dict.get("item_id", "")).strip().lower()
                        if i_id:
                            it_dict["sprite_url"] = f"/assets/sprites/items/{i_id}"
                        items_clean.append(_to_serializable(it_dict))
                    else:
                        items_clean.append(_to_serializable(it))
            entry_dict["items"] = items_clean
            entry_dict["benefited_npcs"] = _to_serializable(entry.get("benefited_npcs", []))
            source_priority.append(_to_serializable(entry_dict))
    else:
        source_priority = _to_serializable(source_priority_raw)

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
            "game_total_preferences": total_preferences,
            "game_given_total": given_total,
            "game_given_loved": stats.get("game_given_loved", 0),
            "game_given_liked": stats.get("game_given_liked", 0),
            "overall_gift_progress_pct": overall_progress_pct,
            "completed_npcs_count": len(completed_npcs_details),
            "incomplete_npcs_count": len(incomplete_npcs_details),
            "total_npcs_count": len(npc_progress_raw),
            "completed_npcs": _to_serializable(stats.get("completed_npcs", [])),
            "completed_npcs_details": completed_npcs_details,
            "incomplete_npcs_details": incomplete_npcs_details,
            "locked_npcs": _to_serializable(stats.get("locked_npcs", [])),
            "ungiftable_npcs": _to_serializable(stats.get("ungiftable_npcs", [])),
            "max_relationship_npcs": _to_serializable(stats.get("max_relationship_npcs", [])),
        },
        "completed_npcs_details": completed_npcs_details,
        "incomplete_npcs_details": incomplete_npcs_details,
        "unobtained_recipes": unobtained_recipes,
        "recipe_stats": recipe_stats,
        "infused_items": _to_serializable(infused_items),
        "bag_plan": bag_plan,
        "focus_suggestions": focus_suggestions,
        "focus_trees": _to_serializable(plan_results.get("focus_trees", [])),
        "source_priority": source_priority,
        "npc_progress": npc_progress,
        "error": None,
    }


# Static database pre-cache container
_CACHED_DATA: Dict[str, Any] = {}


def _resolve_data_dir(data_dir: str = "web/data") -> Path:
    """Finds directory containing game data JSON files."""
    candidates = [
        Path(data_dir),
        Path.cwd() / data_dir,
        Path(__file__).resolve().parent.parent / "data",
        Path(__file__).resolve().parent.parent.parent / "data",
        Path("/data"),
        Path("web/data"),
        Path("data"),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "item_data.json").exists():
            return candidate.resolve()
    return Path(data_dir).resolve()


def init_bridge(data_dir: str = "web/data") -> None:
    """
    Preloads all 6 static JSON databases into memory to accelerate subsequent computations.
    """
    resolved = _resolve_data_dir(data_dir)
    recipes_path = resolved / "recipes.json"
    item_locations_path = resolved / "item_locations.json"
    recipe_sources_path = resolved / "recipe_sources.json"
    item_seasons_path = resolved / "item_seasons.json"
    alt_sources_path = resolved / "alt_sources.json"
    item_data_path = resolved / "item_data.json"

    _CACHED_DATA["data_dir"] = resolved
    _CACHED_DATA["all_recipes"] = load_recipes(str(recipes_path)) if recipes_path.exists() else {}
    _CACHED_DATA["item_locations"] = load_item_locations(str(item_locations_path)) if item_locations_path.exists() else {}
    _CACHED_DATA["recipe_sources"] = load_recipe_sources(str(recipe_sources_path)) if recipe_sources_path.exists() else {}
    _CACHED_DATA["item_seasons"] = load_item_seasons(str(item_seasons_path)) if item_seasons_path.exists() else {}
    _CACHED_DATA["alt_sources"] = load_alt_sources(str(alt_sources_path)) if alt_sources_path.exists() else {}

    if item_data_path.exists():
        npc_defs, _ = load_npc_preferences_from_json(item_data_path)
        _CACHED_DATA["npc_definitions"] = npc_defs
        _CACHED_DATA["metadata"] = load_item_metadata(None, item_data_path, None)
    else:
        _CACHED_DATA["npc_definitions"] = {}
        _CACHED_DATA["metadata"] = {}


# Alias for compatibility with survey design
init_engine = init_bridge


def generate_plan(
    save_data: Union[bytes, bytearray, memoryview, str, Path, None],
    config_dict: Optional[Union[Dict[str, Any], str, WebPlannerConfig]] = None,
    filename: str = "upload.sav",
    data_dir: Optional[str] = None,
) -> str:
    """
    Main entry point for Pyodide worker and static web planner.
    Accepts raw save bytes or file path, executes the gift planner,
    and returns a serialized JSON string containing all 16 canonical keys.
    """
    save_path: Optional[Path] = None
    config: WebPlannerConfig = WebPlannerConfig()

    try:
        # Pre-cache databases if not yet initialized
        if not _CACHED_DATA or data_dir:
            init_bridge(data_dir or "web/data")

        # Parse configuration
        if config_dict is not None:
            if isinstance(config_dict, WebPlannerConfig):
                config = config_dict
            elif isinstance(config_dict, str):
                try:
                    config = WebPlannerConfig(json.loads(config_dict))
                except Exception:
                    config = WebPlannerConfig()
            elif isinstance(config_dict, dict):
                config = WebPlannerConfig(config_dict)

        # Handle save data
        save: Optional[SaveData] = None
        if isinstance(save_data, (bytes, bytearray, memoryview)):
            # Write to /tmp or system temp directory
            tmp_dir = Path("/tmp")
            if not tmp_dir.exists() or not os.access(tmp_dir, os.W_OK):
                tmp_dir = Path(tempfile.gettempdir())
            save_path = tmp_dir / filename
            save_path.write_bytes(bytes(save_data))
        elif isinstance(save_data, (str, Path)) and str(save_data).strip():
            save_path = Path(save_data).resolve()

        if save_path and save_path.exists():
            save = parse_save_file(save_path)

        # Handle date override
        effective_mode = config.mode
        current_ingame_date = save.in_game_date if (save and hasattr(save, "in_game_date")) else None
        override_date = parse_date_override(config.date_override, current_ingame_date)

        if override_date is not None:
            yr = override_date.year
            s_name = override_date.season.lower()
            if s_name == "autumn":
                s_name = "fall"
            d_num = override_date.day

            if save is None:
                seasons_order = ["spring", "summer", "fall", "winter"]
                s_idx = seasons_order.index(s_name) if s_name in seasons_order else 0
                cal_days = (yr - 1) * 112 + s_idx * 28 + (d_num - 1)
                dummy_entries = {
                    "header": json.dumps({"name": "Player", "calendar_time": cal_days * 86400, "clock_time": 36000}),
                    "player": json.dumps({"name": "Player", "inventory": []}),
                    "npcs": json.dumps({}),
                }
                dummy_path = save_path or Path(filename or "simulated.sav")
                save = SaveData(dummy_path, dummy_entries)

            save.in_game_date = InGameDate(year=yr, season=s_name, day=d_num, time_str="10:00")

            if effective_mode == "auto" and save.in_game_date.is_saturday:
                effective_mode = "saturday"

        # NPC filters
        excluded: Set[str] = set()
        if config.exclude_npcs:
            if isinstance(config.exclude_npcs, (list, set, tuple)):
                excluded = {str(x).strip().lower() for x in config.exclude_npcs if str(x).strip()}
            else:
                excluded = {x.strip().lower() for x in str(config.exclude_npcs).split(",") if x.strip()}

        focus_mode_enabled = bool(config.focus_mode_enabled)
        focus_npcs: Set[str] = set()
        if config.focus_npcs:
            if isinstance(config.focus_npcs, (list, set, tuple)):
                focus_npcs = {str(x).strip().lower() for x in config.focus_npcs if str(x).strip()}
            else:
                focus_npcs = {x.strip().lower() for x in str(config.focus_npcs).split(",") if x.strip()}

        # Load databases from cache
        all_recipes = _CACHED_DATA.get("all_recipes", {})
        recipes = all_recipes
        if save is not None and hasattr(save, "get_unlocked_recipe_ids"):
            unlocked = save.get_unlocked_recipe_ids()
            if unlocked is not None:
                recipes = filter_recipes_by_unlocks(all_recipes, unlocked)

        item_locations = _CACHED_DATA.get("item_locations", {})
        recipe_sources = _CACHED_DATA.get("recipe_sources", {})
        item_seasons = _CACHED_DATA.get("item_seasons", {})
        alt_sources = _CACHED_DATA.get("alt_sources", {})
        npcs_def = _CACHED_DATA.get("npc_definitions", {})
        metadata = _CACHED_DATA.get("metadata", {})

        focus_sort = config.focus_sort or "impact"
        all_seasons_flag = bool(config.all_seasons)
        seasonal_boost_val = float(config.seasonal_boost)

        # Execute optimization strategy
        if config.strategy == "max-relationship":
            infused_items = save.get_infused_items() if (save is not None and hasattr(save, "get_infused_items")) else None
            plan_results = plan_max_relationship(
                save=save,
                npc_gift_definitions=npcs_def,
                item_metadata=metadata,
                mode=effective_mode,
                max_slots=config.slots,
                exclude_npcs=excluded,
                force_all_npcs=config.force_all_npcs,
                infused_items=infused_items,
                recipes=recipes,
                all_recipes=all_recipes,
                item_locations=item_locations,
                max_relationship_points=config.max_relationship_points,
                exclude_max_relationship=not config.no_exclude_max_relationship,
                focus_sort=focus_sort,
                recipe_sources=recipe_sources,
                item_seasons=item_seasons,
                all_seasons=all_seasons_flag,
                seasonal_boost=seasonal_boost_val,
                focus_mode_enabled=focus_mode_enabled,
                focus_npcs=focus_npcs,
                alt_sources=alt_sources,
            )
        else:
            plan_results = plan_daily_gift_bag(
                save=save,
                npc_gift_definitions=npcs_def,
                item_metadata=metadata,
                mode=effective_mode,
                max_slots=config.slots,
                loved_weight=config.loved_weight,
                liked_weight=config.liked_weight,
                vendor_boost=config.vendor_boost,
                exclude_npcs=excluded,
                force_all_npcs=config.force_all_npcs,
                recipes=recipes,
                all_recipes=all_recipes,
                item_locations=item_locations,
                focus_sort=focus_sort,
                recipe_sources=recipe_sources,
                item_seasons=item_seasons,
                all_seasons=all_seasons_flag,
                seasonal_boost=seasonal_boost_val,
                focus_mode_enabled=focus_mode_enabled,
                focus_npcs=focus_npcs,
                alt_sources=alt_sources,
            )

        # Ensure loaded assets are accessible to plan_to_json
        plan_results["all_recipes"] = all_recipes
        plan_results["alt_sources"] = alt_sources

        # Serialize into canonical JSON schema
        plan_dict = plan_to_json(save, plan_results, metadata, save_path, config)
        if filename and isinstance(save_data, (bytes, bytearray, memoryview)):
            plan_dict["save_info"]["filename"] = filename

        return json.dumps(plan_dict)

    except Exception as e:
        traceback.print_exc()
        error_payload = {
            "generated_at": datetime.now().isoformat(),
            "save_info": {
                "found": False,
                "path": str(save_path) if save_path else None,
                "filename": filename,
                "modified_at": None,
                "player_name": "Player",
                "farm_name": "Farm",
                "error": str(e),
            },
            "in_game_date": {
                "year": 1,
                "season": "Spring",
                "day": 1,
                "day_of_week": "Sunday",
                "is_saturday": False,
                "is_animal_festival": False,
                "festival_name": None,
                "days_until_saturday": 0,
                "formatted": "Year 1, Spring 1",
                "is_overridden": False,
                "date_override": "",
                "save_date": None,
            },
            "config": config.to_dict() if hasattr(config, "to_dict") else {},
            "stats": {},
            "completed_npcs_details": [],
            "incomplete_npcs_details": [],
            "unobtained_recipes": [],
            "recipe_stats": {
                "total_cooking": 0,
                "unlocked_count": 0,
                "locked_count": 0,
                "unlocked_percentage": 0.0,
                "has_unlock_data": False,
            },
            "infused_items": [],
            "bag_plan": [],
            "focus_suggestions": [],
            "focus_trees": [],
            "source_priority": [],
            "npc_progress": {},
            "error": str(e),
        }
        return json.dumps(error_payload)


def run_plan_from_vfs(
    save_path: Optional[str],
    config_dict: Optional[Union[Dict[str, Any], str, WebPlannerConfig]] = None,
    filename: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> str:
    """Executes the gift planner on a save file existing in Pyodide VFS."""
    name = filename or (Path(save_path).name if save_path else "upload.sav")
    return generate_plan(save_path, config_dict=config_dict, filename=name, data_dir=data_dir)
