"""
rankings.py

Calculates and ranks items by popularity, loved counts, and liked counts across all NPCs.
"""

from typing import Any, Dict, List


def build_ranked_rows(
    items: Dict[str, Any],
    metadata: Dict[str, Any],
    sort_by: str = "total",
    min_npcs: int = 1,
) -> List[Dict[str, Any]]:
    """
    Builds and sorts the list of item dictionary rows.
    """
    rows = []
    for item_id, gift_info in items.items():
        loved_names = sorted(list(gift_info["loved_by"]))
        liked_names = sorted(list(gift_info["liked_by"]))
        loved_count = len(loved_names)
        liked_count = len(liked_names)
        total_count = loved_count + liked_count

        if total_count < min_npcs:
            continue

        meta = metadata.get(item_id, {})
        disp_name = meta.get("display_name") or item_id.replace("_", " ").title()

        tag_list = meta.get("tags", [])
        tags_str = ", ".join(tag_list) if isinstance(tag_list, list) else str(tag_list)

        rows.append({
            "item_id": item_id,
            "item_name": disp_name,
            "total_count": total_count,
            "loved_count": loved_count,
            "liked_count": liked_count,
            "loved_by": ", ".join(loved_names),
            "liked_by": ", ".join(liked_names),
            "loved_by_ids": ", ".join(sorted(list(gift_info["loved_by_ids"]))),
            "liked_by_ids": ", ".join(sorted(list(gift_info["liked_by_ids"]))),
            "bin_price": meta.get("bin_price", ""),
            "store_price": meta.get("store_price", ""),
            "tags": tags_str,
            "cooking_usage": meta.get("cooking_recipes_count", 0),
            "crafting_usage": meta.get("crafting_recipes_count", 0),
            "quest_usage": meta.get("quests_count", 0),
            "description": meta.get("description", "")
        })

    # Sorting
    if sort_by == "loved":
        rows.sort(key=lambda r: (-r["loved_count"], -r["total_count"], -r["liked_count"], r["item_name"].lower()))
    elif sort_by == "liked":
        rows.sort(key=lambda r: (-r["liked_count"], -r["total_count"], -r["loved_count"], r["item_name"].lower()))
    else:  # "total"
        rows.sort(key=lambda r: (-r["total_count"], -r["loved_count"], -r["liked_count"], r["item_name"].lower()))

    # Assign 1-indexed ranks
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    return rows
