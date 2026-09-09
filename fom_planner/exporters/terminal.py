"""
terminal.py

Terminal presentation and formatted CLI report generator for Fields of Mistria gift planner.
"""

from typing import Any, Dict, Optional, Tuple

from fom_planner.constants import ANIMAL_FESTIVAL_ATTENDING_VENDORS
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import compute_focus_suggestions


def _format_infused_summary(items: Any) -> Tuple[int, str]:
    """
    Defensively aggregates and formats arbitrary infused item structures into (total_count, summary_string).
    Supports:
      - List of dicts: [{'item_id': 'apple_pie', 'count': 2, ...}]
      - Dict mapping: {'apple_pie': 2}
      - Iterable of item IDs: ['apple_pie', 'berry_tart']
    """
    if not items:
        return 0, ""
    aggregated: Dict[str, int] = {}
    if isinstance(items, dict):
        for k, v in items.items():
            if not k:
                continue
            if isinstance(v, (int, float)):
                cnt = int(round(float(v)))
            elif isinstance(v, dict):
                cnt = int(v.get("count", 1))
            else:
                cnt = 1
            if cnt > 0:
                k_clean = str(k).strip()
                aggregated[k_clean] = aggregated.get(k_clean, 0) + cnt
    elif isinstance(items, (list, tuple, set)):
        for x in items:
            if not x:
                continue
            if isinstance(x, dict):
                iid = str(x.get("item_id", "")).strip()
                try:
                    cnt = int(round(float(x.get("count", 1))))
                except (ValueError, TypeError):
                    cnt = 1
            else:
                iid = str(x).strip()
                cnt = 1
            if iid and cnt > 0:
                aggregated[iid] = aggregated.get(iid, 0) + cnt
    total_count = sum(aggregated.values())
    if total_count == 0:
        return 0, ""
    parts = [f"{iid} (x{cnt})" for iid, cnt in sorted(aggregated.items())]
    return total_count, ", ".join(parts)


def print_terminal_plan(save: Optional[SaveData], plan_results: dict):
    """Prints a beautiful, formatted CLI summary of the gift plan with inventory badges and Saturday Market context."""
    stats = plan_results["overall_stats"]
    bag_plan = plan_results["bag_plan"]
    npc_progress = plan_results["npc_progress"]

    player_name = save.player_name if (save and hasattr(save, "player_name")) else "Player"
    farm_name = save.farm_name if (save and hasattr(save, "farm_name")) else "Farm"
    date_info = save.in_game_date if (save and hasattr(save, "in_game_date")) else InGameDate(year=1, season="spring", day=1)
    save_name = save.file_path.name if (save and hasattr(save, "file_path")) else "active_session"

    print("\n" + "═" * 86)
    print(f"  🎁 FIELDS OF MISTRIA — DAILY GIFT BAG PLANNER")
    print(f"  Player: {player_name} @ {farm_name}  |  {date_info}  |  Save: {save_name}")
    print("═" * 86)

    # Storage & inventory status banner
    if save and hasattr(save, "get_all_available_items"):
        bag_items = len(save.get_bag_items()) if hasattr(save, "get_bag_items") else 0
        chest_items = len(save.get_chest_items()) if hasattr(save, "get_chest_items") else 0
        total_avail = len(save.get_all_available_items())
        print(f"\n📦 INVENTORY & STORAGE STATUS:")
        print(f"  • Player Bag: {bag_items} unique items ({save.empty_inventory_slots}/{save.total_inventory_slots} slots empty)")
        print(f"  • Chest Storage: {chest_items} unique items across all farm/world chests")
        print(f"  • Total Available for Gifting/Crafting: {total_avail} unique items")

    # Infused items detected banner (Cooking Perk)
    infused_items = plan_results.get("infused_items")
    if infused_items is None and save is not None and hasattr(save, "get_infused_items"):
        try:
            infused_items = save.get_infused_items()
        except Exception:
            infused_items = None

    is_max_rel = stats.get("strategy") == "max-relationship" or "total_relationship_points" in stats
    has_infused = bool(infused_items and any(infused_items.values() if isinstance(infused_items, dict) else infused_items))

    if is_max_rel or has_infused:
        lovable_count, lovable_str = _format_infused_summary(
            infused_items.get("lovable") if isinstance(infused_items, dict) else None
        )
        likable_count, likable_str = _format_infused_summary(
            (infused_items.get("likable") or infused_items.get("likeable")) if isinstance(infused_items, dict) else None
        )
        print(f"\n🔮 DETECTED INFUSED ITEMS (Cooking Perk):")
        if lovable_count == 0 and likable_count == 0:
            print(f"  • None detected in bag or chest storage.")
        else:
            if lovable_count > 0:
                print(f"  • Lovable Dishes (✨ Universal Love, +20 pts): {lovable_count} total — {lovable_str}")
            if likable_count > 0:
                print(f"  • Likable Dishes (🌟 Universal Like, +10 pts): {likable_count} total — {likable_str}")

    # Dynamic NPC counts based on unlocked progression
    num_vendors = stats.get("unlocked_vendors_count", len([x for x in npc_progress if npc_progress[x]["is_vendor"] and npc_progress[x].get("is_unlocked", True)]))
    num_townsfolk = stats.get("unlocked_townsfolk_count", len([x for x in npc_progress if not npc_progress[x]["is_vendor"] and npc_progress[x].get("is_unlocked", True)]))
    num_total = num_vendors + num_townsfolk

    if save is not None and hasattr(save, "get_unlocked_vendor_ids") and hasattr(save, "npcs") and save.npcs:
        unlocked_vendor_names = sorted([
            npc_progress[x]["name"] if (x in npc_progress and "name" in npc_progress[x]) else x.capitalize()
            for x in save.get_unlocked_vendor_ids()
        ])
    else:
        unlocked_vendor_names = sorted([
            npc_progress[x]["name"] for x in npc_progress
            if npc_progress[x]["is_vendor"] and npc_progress[x].get("is_unlocked", True)
        ])

    # Market & Festival context banner
    if getattr(date_info, "is_saturday", False) or stats["mode"] in ("saturday", "market"):
        if getattr(date_info, "is_saturday", False):
            print(f"\n🎉 TODAY IS SATURDAY MARKET DAY! All {num_total} NPCs ({num_townsfolk} townsfolk + {num_vendors} visiting vendors) are in town!")
        else:
            days_until = getattr(date_info, "days_until_saturday", 0)
            next_sat = getattr(date_info, "next_saturday_day", 6)
            print(f"\n🎪 PLANNING FOR SATURDAY MARKET (Simulated Day {next_sat}, in {days_until} days):")
            print(f"  • Includes all {num_total} NPCs ({num_townsfolk} townsfolk + {num_vendors} visiting vendors) with priority boost on the {num_vendors} weekly visiting vendors.")
    elif stats["mode"] == "market-only":
        print(f"\n🎪 PLANNING FOR SATURDAY MARKET VENDORS ONLY:")
        vendor_names_str = ", ".join(unlocked_vendor_names) if unlocked_vendor_names else "None"
        print(f"  • Focuses exclusively on the {num_vendors} weekly visiting vendors ({vendor_names_str}).")
    elif getattr(date_info, "is_animal_festival", False) or stats.get("is_animal_festival", False):
        days_until = getattr(date_info, "days_until_saturday", 0)
        next_sat = getattr(date_info, "next_saturday_day", 6)
        festival_vendors = [
            npc_name for npc_id in ["merri", "louis"]
            for npc_name in unlocked_vendor_names if npc_name.lower() == npc_id
        ]
        fest_names_str = " & ".join(festival_vendors) if len(festival_vendors) == 2 else (", ".join(festival_vendors) if festival_vendors else "None")
        fest_total = num_townsfolk + len(festival_vendors)
        aldaria_vendors = sorted([x for x in unlocked_vendor_names if x.lower() not in ANIMAL_FESTIVAL_ATTENDING_VENDORS])
        print(f"\n🎉 TODAY IS ANIMAL FESTIVAL DAY! (Winter 10)")
        print(f"  • {fest_total} NPCs present in town ({num_townsfolk} permanent townsfolk + visiting contestants {fest_names_str})!")
        print(f"  • {fest_names_str} receive priority boost for this special non-Saturday festival appearance.")
        print(f"  ℹ️  {len(aldaria_vendors)} Saturday Market vendors remain in Aldaria and return this Saturday (Day {next_sat}, in {days_until} days):")
        print(f"     {', '.join(aldaria_vendors)}")
    else:
        day_of_week = getattr(date_info, "day_of_week", "Weekday")
        days_until = getattr(date_info, "days_until_saturday", 0)
        next_sat = getattr(date_info, "next_saturday_day", 6)
        print(f"\n📅 TODAY'S VISITORS ({day_of_week}): {num_townsfolk} Townsfolk in town.")
        print(f"  ℹ️  {len(unlocked_vendor_names)} Saturday Market vendors are visiting Aldaria and return this Saturday (Day {next_sat}, in {days_until} days):")
        print(f"     {', '.join(unlocked_vendor_names)}")
        print(f"  💡 Tip: Run with '--mode saturday' to plan your upcoming Saturday Market shopping list!")

    print(f"\n📊 OVERALL COMPLETION PROGRESS:")
    p_loved = (stats["game_given_loved"] / stats["game_total_loved"] * 100) if stats["game_total_loved"] else 0
    p_liked = (stats["game_given_liked"] / stats["game_total_liked"] * 100) if stats["game_total_liked"] else 0
    p_total = (stats["game_given_total"] / stats["game_total_preferences"] * 100) if stats["game_total_preferences"] else 0
    print(f"  • Loved Gifts: {stats['game_given_loved']}/{stats['game_total_loved']} ({p_loved:.1f}%)")
    print(f"  • Liked Gifts: {stats['game_given_liked']}/{stats['game_total_liked']} ({p_liked:.1f}%)")
    print(f"  • Total Preferences: {stats['game_given_total']}/{stats['game_total_preferences']} ({p_total:.1f}%)")
    print(f"  • Unique Ungifted Items Remaining in Game: {stats['remaining_unique_items']}")

    if stats.get("locked_npcs"):
        print(f"\n🔒 NOT YET UNLOCKED ({len(stats['locked_npcs'])} NPCs): {', '.join(stats['locked_npcs'])}")

    if stats.get("max_relationship_npcs"):
        print(f"\n💖 MAX RELATIONSHIP REACHED ({len(stats['max_relationship_npcs'])} NPCs): {', '.join(stats['max_relationship_npcs'])}")

    if stats["ungiftable_npcs"]:
        print(f"\n⚠️  ALREADY GIFTED TODAY ({len(stats['ungiftable_npcs'])} NPCs): {', '.join(stats['ungiftable_npcs'])}")

    print(f"\n🎒 OPTIMAL BAG LOADOUT ({len(bag_plan)}/{stats['max_slots']} slots → covers {stats['covered_npcs_count']}/{stats['target_npcs_count']} NPCs):")
    print("━" * 86)
    print(f" {'Slot':<5} │ {'Qty':<4} │ {'Status':<9} │ {'Item Name':<24} │ {'Today Target Recipients (NPCs)'}")
    print("━" * 86)

    for b in bag_plan:
        recipients_display = []
        for r in b["all_recipients_today"]:
            pref = str(r.get("pref") or r.get("pref_tier") or "LIKE").upper()
            vendor_tag = " [Market]" if r.get("is_vendor") else ""
            if stats.get("strategy") == "max-relationship":
                if pref == "LOVE":
                    badge = "💖 LOVE"
                elif pref in ("UNIV_LOVE", "UNIVERSAL_LOVE"):
                    badge = "✨ UNIV. LOVE"
                elif pref == "LIKE":
                    badge = "💙 LIKE"
                elif pref in ("UNIV_LIKE", "UNIVERSAL_LIKE"):
                    badge = "🌟 UNIV. LIKE"
                else:
                    badge = pref
                recipients_display.append(f"[{badge}] {r['name']}{vendor_tag}")
            else:
                badge = "♥" if pref in ("LOVE", "UNIV_LOVE", "UNIVERSAL_LOVE") else "♡"
                recipients_display.append(f"{badge}{r['name']}{vendor_tag}")
        recip_str = ", ".join(recipients_display)

        status_badge = b.get("status_badge", "❌ NEED")
        print(f"  {b['slot']:<4} │ {b['quantity_to_pack']:<4} │ {status_badge:<9} │ {b['item_name']:<24} │ {recip_str}")
        if b.get("crafting_chain"):
            print(f"       │      │           └─ {b['crafting_chain']}")

    print("━" * 86)
    vendor_msg = f" (including {stats.get('vendors_covered_today', 0)} Saturday Market vendors)" if stats.get("vendors_covered_today") else ""
    if "total_relationship_points" in stats:
        pts = stats["total_relationship_points"]
        print(f"TOTAL RELATIONSHIP POINTS EARNED TODAY: +{pts} pts")
        print(f"💞 RELATIONSHIP IMPACT: +{pts} total points earned today across {stats['covered_npcs_count']} NPCs!{vendor_msg}")
        print(f"   • Loved: {stats.get('today_loved_completed', 0)} gifts (+20 pts each) | Liked: {stats.get('today_liked_completed', 0)} gifts (+10 pts each)")
    else:
        print(f"🎯 IMPACT: +{stats['today_loved_completed']} Loved & +{stats['today_liked_completed']} Liked preferences completed in one trip!{vendor_msg}")
    if stats['covered_npcs_count'] == stats['target_npcs_count'] and stats['target_npcs_count'] > 0:
        extra_slots = stats['max_slots'] - len(bag_plan)
        print(f"✨ 100% NPC coverage achieved! You have {extra_slots} extra bag slots free for tools/foraging.")

    # Focus Suggestions Section
    focus_suggestions = plan_results.get("focus_suggestions")
    if focus_suggestions is None:
        inv = save.get_all_available_items() if (save and hasattr(save, "get_all_available_items")) else {}
        focus_suggestions = compute_focus_suggestions(
            remaining_items_map=plan_results.get("all_remaining_items_map") or plan_results.get("remaining_items_map", {}),
            inventory=inv,
        )

    print(f"\n💡 FOCUS SUGGESTIONS (Top Blocker Items):")
    print("━" * 86)
    if not focus_suggestions:
        print("  🎉 All required materials and gifts are currently in your inventory!")
    else:
        for s in focus_suggestions:
            loc_str = f"  ({s['location_hint']})" if s.get("location_hint") else ""
            print(f"  {s['rank']}. {s['item_name']} — Need {s['deficit']} more{loc_str}")
    print("━" * 86)
    print("═" * 86 + "\n")


