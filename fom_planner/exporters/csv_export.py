"""
csv_export.py

CSV export routines for daily bag plans and ranked gift lists.
"""

import csv
from pathlib import Path
from typing import Any, Dict, List

def export_plan_to_csv(plan_results: dict, output_dir: Path, csv_name: str = "daily_gift_bag_plan.csv"):
    """Exports the daily bag plan and NPC progress to CSV files with availability columns."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_csv_path = output_dir / csv_name

    bag_plan = plan_results["bag_plan"]
    headers = [
        ("slot", "Slot #"),
        ("quantity_to_pack", "Pack Qty"),
        ("status", "Availability"),
        ("item_name", "Item Name"),
        ("item_id", "Item ID"),
        ("crafting_chain", "Crafting Chain"),
        ("market_vendors_covered", "Market Vendors Covered"),
        ("loved_recipients_today", "Loved Targets (Today)"),
        ("liked_recipients_today", "Liked Targets (Today)"),
        ("bin_price", "Bin Price"),
        ("store_price", "Store Price"),
        ("tags", "Tags"),
        ("description", "Description")
    ]

    with open(plan_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([h[1] for h in headers])
        for b in bag_plan:
            writer.writerow([
                b["slot"],
                b["quantity_to_pack"],
                b.get("status", ""),
                b["item_name"],
                b["item_id"],
                b.get("crafting_chain", ""),
                ", ".join(b["market_vendors_covered"]),
                ", ".join(b["loved_recipients_today"]),
                ", ".join(b["liked_recipients_today"]),
                b["bin_price"],
                b["store_price"],
                b["tags"],
                b["description"],
            ])

    print(f"[CSV] Successfully exported Daily Bag Plan to: {plan_csv_path}")




def export_to_csv(rows: list, output_path: Path):
    """Exports ranked rows to a standard CSV file with UTF-8 BOM."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    headers = [
        ("rank", "Rank"),
        ("item_name", "Item Name"),
        ("item_id", "Item ID"),
        ("total_count", "Total NPCs"),
        ("loved_count", "Loved Count"),
        ("liked_count", "Liked Count"),
        ("loved_by", "Loved By (NPCs)"),
        ("liked_by", "Liked By (NPCs)"),
        ("bin_price", "Shipping Bin Price"),
        ("store_price", "Store Price"),
        ("tags", "Tags"),
        ("quest_usage", "Quest Usages"),
        ("cooking_usage", "Cooking Usages"),
        ("crafting_usage", "Crafting Usages"),
        ("loved_by_ids", "Loved By (IDs)"),
        ("liked_by_ids", "Liked By (IDs)"),
        ("description", "Description"),
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([h[1] for h in headers])
        for r in rows:
            writer.writerow([r.get(h[0], "") for h in headers])

    print(f"[CSV] Successfully exported {len(rows)} items to: {output_path}")


