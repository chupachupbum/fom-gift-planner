"""
terminal.py

Terminal presentation and formatted CLI report generator for Fields of Mistria gift planner.
"""

from typing import Optional

from fom_planner.constants import ANIMAL_FESTIVAL_ATTENDING_VENDORS
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import compute_focus_suggestions

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

    # Market & Festival context banner
    if getattr(date_info, "is_saturday", False) or stats["mode"] in ("saturday", "market"):
        if getattr(date_info, "is_saturday", False):
            print(f"\n🎉 TODAY IS SATURDAY MARKET DAY! All 34 NPCs (26 townsfolk + 8 visiting vendors) are in town!")
        else:
            days_until = getattr(date_info, "days_until_saturday", 0)
            next_sat = getattr(date_info, "next_saturday_day", 6)
            print(f"\n🎪 PLANNING FOR SATURDAY MARKET (Simulated Day {next_sat}, in {days_until} days):")
            print(f"  • Includes all 34 NPCs with priority boost on the 8 weekly visiting vendors.")
    elif stats["mode"] == "market-only":
        print(f"\n🎪 PLANNING FOR SATURDAY MARKET VENDORS ONLY:")
        print(f"  • Focuses exclusively on the 8 weekly visiting vendors (Darcy, Louis, Merri, Stillwell, Taliferro, Vera, Wheedle, Zorel).")
    elif getattr(date_info, "is_animal_festival", False) or stats.get("is_animal_festival", False):
        days_until = getattr(date_info, "days_until_saturday", 0)
        next_sat = getattr(date_info, "next_saturday_day", 6)
        print(f"\n🎉 TODAY IS ANIMAL FESTIVAL DAY! (Winter 10)")
        print(f"  • 28 NPCs present in town (26 permanent townsfolk + visiting contestants Merri & Louis)!")
        print(f"  • Merri & Louis receive priority boost for this special non-Saturday festival appearance.")
        aldaria_vendors = sorted([npc_progress[x]["name"] for x in npc_progress if npc_progress[x]["is_vendor"] and x.lower() not in ANIMAL_FESTIVAL_ATTENDING_VENDORS])
        print(f"  ℹ️  6 Saturday Market vendors remain in Aldaria and return this Saturday (Day {next_sat}, in {days_until} days):")
        print(f"     {', '.join(aldaria_vendors)}")
    else:
        day_of_week = getattr(date_info, "day_of_week", "Weekday")
        days_until = getattr(date_info, "days_until_saturday", 0)
        next_sat = getattr(date_info, "next_saturday_day", 6)
        print(f"\n📅 TODAY'S VISITORS ({day_of_week}): 26 Townsfolk in town.")
        vendor_names = sorted([npc_progress[x]["name"] for x in npc_progress if npc_progress[x]["is_vendor"]])
        print(f"  ℹ️  8 Saturday Market vendors are visiting Aldaria and return this Saturday (Day {next_sat}, in {days_until} days):")
        print(f"     {', '.join(vendor_names)}")
        print(f"  💡 Tip: Run with '--mode saturday' to plan your upcoming Saturday Market shopping list!")

    print(f"\n📊 OVERALL COMPLETION PROGRESS:")
    p_loved = (stats["game_given_loved"] / stats["game_total_loved"] * 100) if stats["game_total_loved"] else 0
    p_liked = (stats["game_given_liked"] / stats["game_total_liked"] * 100) if stats["game_total_liked"] else 0
    p_total = (stats["game_given_total"] / stats["game_total_preferences"] * 100) if stats["game_total_preferences"] else 0
    print(f"  • Loved Gifts: {stats['game_given_loved']}/{stats['game_total_loved']} ({p_loved:.1f}%)")
    print(f"  • Liked Gifts: {stats['game_given_liked']}/{stats['game_total_liked']} ({p_liked:.1f}%)")
    print(f"  • Total Preferences: {stats['game_given_total']}/{stats['game_total_preferences']} ({p_total:.1f}%)")
    print(f"  • Unique Ungifted Items Remaining in Game: {stats['remaining_unique_items']}")

    if stats["ungiftable_npcs"]:
        print(f"\n⚠️  ALREADY GIFTED TODAY ({len(stats['ungiftable_npcs'])} NPCs): {', '.join(stats['ungiftable_npcs'])}")

    print(f"\n🎒 OPTIMAL BAG LOADOUT ({len(bag_plan)}/{stats['max_slots']} slots → covers {stats['covered_npcs_count']}/{stats['target_npcs_count']} NPCs):")
    print("━" * 86)
    print(f" {'Slot':<5} │ {'Qty':<4} │ {'Status':<9} │ {'Item Name':<24} │ {'Today Target Recipients (NPCs)'}")
    print("━" * 86)

    for b in bag_plan:
        recipients_display = []
        for r in b["all_recipients_today"]:
            badge = "♥" if r["pref"] == "LOVE" else "♡"
            vendor_tag = " [Market]" if r["is_vendor"] else ""
            recipients_display.append(f"{badge}{r['name']}{vendor_tag}")
        recip_str = ", ".join(recipients_display)

        status_badge = b.get("status_badge", "❌ NEED")
        print(f"  {b['slot']:<4} │ {b['quantity_to_pack']:<4} │ {status_badge:<9} │ {b['item_name']:<24} │ {recip_str}")
        if b.get("crafting_chain"):
            print(f"       │      │           └─ {b['crafting_chain']}")

    print("━" * 86)
    vendor_msg = f" (including {stats['vendors_covered_today']} Saturday Market vendors)" if stats['vendors_covered_today'] else ""
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


