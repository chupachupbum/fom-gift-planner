#!/usr/bin/env python3
"""
export_gift_rankings.py

Analyzes NPC gift preferences in Fields of Mistria and exports ranked item tables
to CSV and Excel (.xlsx) formats, ordered by the number of NPCs who love/like each item.

Features:
- Primary ranking by total NPC interest (Loved + Liked), Loved count, Liked count.
- Includes comprehensive metadata: Bin Sell Price, Store Price, Item Tags, Quests & Recipe usages.
- Generates detailed CSV files (UTF-8 with BOM for native Excel compatibility).
- Generates multi-sheet Excel workbooks with:
    1. 'All Items Ranked' (Full ranked table with filters and auto-fitted columns)
    2. 'Loved Gifts Ranked' (Items sorted by most loved)
    3. 'Liked Gifts Ranked' (Items sorted by most liked)
    4. 'NPC Gift Matrix' (Items x 34 NPCs matrix with colored LOVE/LIKE badges)
    5. 'NPC Summary' (Per-NPC preferences breakdown)
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


def load_npc_preferences_from_fiddle(fiddle_dir: Path):
    """
    Parses NPC TOML files from assets/fiddle/npcs/*.toml.
    Returns:
        npcs: dict of npc_id -> {"name": display_name, "loved": set(), "liked": set()}
        items: dict of item_id -> {"loved_by": set(npc_names), "liked_by": set(npc_names),
                                   "loved_by_ids": set(npc_ids), "liked_by_ids": set(npc_ids)}
    """
    npcs_dir = fiddle_dir / "npcs"
    if not npcs_dir.exists() or tomllib is None:
        return {}, {}

    npcs = {}
    items = {}

    for file_path in sorted(npcs_dir.glob("*.toml")):
        npc_id = file_path.stem
        try:
            with open(file_path, "rb") as fp:
                data = tomllib.load(fp)

            npc_name = data.get("name", npc_id.capitalize())
            loved_gifts = data.get("loved_gifts", [])
            liked_gifts = data.get("liked_gifts", [])

            npcs[npc_id] = {
                "name": npc_name,
                "loved": set(loved_gifts),
                "liked": set(liked_gifts)
            }

            for item_id in loved_gifts:
                if item_id not in items:
                    items[item_id] = {
                        "loved_by": set(), "liked_by": set(),
                        "loved_by_ids": set(), "liked_by_ids": set()
                    }
                items[item_id]["loved_by"].add(npc_name)
                items[item_id]["loved_by_ids"].add(npc_id)

            for item_id in liked_gifts:
                if item_id not in items:
                    items[item_id] = {
                        "loved_by": set(), "liked_by": set(),
                        "loved_by_ids": set(), "liked_by_ids": set()
                    }
                items[item_id]["liked_by"].add(npc_name)
                items[item_id]["liked_by_ids"].add(npc_id)

        except Exception as e:
            print(f"Warning: Failed to parse NPC TOML '{file_path}': {e}", file=sys.stderr)

    return npcs, items


def load_npc_preferences_from_json(json_path: Path):
    """Fallback loader from gift_indicator/data/item_data.json."""
    if not json_path.exists():
        return {}, {}

    with open(json_path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    npc_names_map = data.get("npcs", {})
    npcs = {}
    items = {}

    for npc_id, npc_name in npc_names_map.items():
        npcs[npc_id] = {"name": npc_name, "loved": set(), "liked": set()}

    for item_id, item_info in data.get("items", {}).items():
        loved_ids = set(item_info.get("loved_by", []))
        liked_ids = set(item_info.get("liked_by", []))

        if not loved_ids and not liked_ids:
            continue

        loved_names = {npc_names_map.get(nid, nid.capitalize()) for nid in loved_ids}
        liked_names = {npc_names_map.get(nid, nid.capitalize()) for nid in liked_ids}

        for nid in loved_ids:
            if nid in npcs:
                npcs[nid]["loved"].add(item_id)
        for nid in liked_ids:
            if nid in npcs:
                npcs[nid]["liked"].add(item_id)

        items[item_id] = {
            "loved_by": loved_names,
            "liked_by": liked_names,
            "loved_by_ids": loved_ids,
            "liked_by_ids": liked_ids,
        }

    return npcs, items


def load_item_metadata(fiddle_dir: Path, item_data_json_path: Path = None, tracker_files_dir: Path = None):
    """
    Loads comprehensive item metadata: display name, description, sell price (bin & store),
    tags, and recipe/quest usage counts.
    """
    metadata = {}

    # 1. Load from fiddle TOML files if available
    items_dir = fiddle_dir / "items"
    if items_dir.exists() and tomllib is not None:
        for toml_path in items_dir.glob("**/*.toml"):
            try:
                with open(toml_path, "rb") as fp:
                    data = tomllib.load(fp)
                for item_id, item_info in data.items():
                    if not isinstance(item_info, dict):
                        continue
                    bin_price = None
                    store_price = None
                    if "value" in item_info and isinstance(item_info["value"], dict):
                        bin_price = item_info["value"].get("bin")
                        store_price = item_info["value"].get("store")

                    metadata[item_id] = {
                        "display_name": item_info.get("name", item_id.replace("_", " ").title()),
                        "description": item_info.get("description", ""),
                        "bin_price": bin_price if bin_price is not None else "",
                        "store_price": store_price if store_price is not None else "",
                        "tags": item_info.get("tags", []),
                        "cooking_recipes_count": 0,
                        "crafting_recipes_count": 0,
                        "quests_count": 0,
                    }
            except Exception as e:
                print(f"Warning: Failed to parse item TOML '{toml_path}': {e}", file=sys.stderr)

    # 2. Enrich from tracker items.json.js if available
    if tracker_files_dir and tracker_files_dir.exists():
        tracker_json_path = tracker_files_dir / "items.json.js.download"
        if not tracker_json_path.exists():
            tracker_json_path = tracker_files_dir / "items.json.js"
        if tracker_json_path.exists():
            try:
                with open(tracker_json_path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                json_str = re.sub(r'^\s*var\s+objItems\s*=\s*', '', content).rstrip(';\n ')
                t_items = json.loads(json_str)
                for iid, info in t_items.items():
                    if not isinstance(info, dict):
                        continue
                    if iid not in metadata:
                        metadata[iid] = {
                            "display_name": info.get("name", iid.replace("_", " ").title()),
                            "description": "",
                            "bin_price": "",
                            "store_price": "",
                            "tags": info.get("tags", []),
                            "cooking_recipes_count": 0,
                            "crafting_recipes_count": 0,
                            "quests_count": 0,
                        }
                    else:
                        if not metadata[iid]["tags"] and info.get("tags"):
                            metadata[iid]["tags"] = info.get("tags")
                        if not metadata[iid]["display_name"] and info.get("name"):
                            metadata[iid]["display_name"] = info.get("name")
            except Exception as e:
                print(f"Warning: Failed to parse tracker items JS: {e}", file=sys.stderr)

    # 3. Enrich from item_data.json if available
    if item_data_json_path and item_data_json_path.exists():
        try:
            with open(item_data_json_path, "r", encoding="utf-8") as fp:
                json_data = json.load(fp)
            for item_id, item_info in json_data.get("items", {}).items():
                if item_id not in metadata:
                    metadata[item_id] = {
                        "display_name": item_info.get("display_name", item_id.replace("_", " ").title()),
                        "description": "",
                        "bin_price": "",
                        "store_price": "",
                        "tags": item_info.get("tags", []),
                        "cooking_recipes_count": 0,
                        "crafting_recipes_count": 0,
                        "quests_count": 0,
                    }
                else:
                    if item_info.get("display_name"):
                        metadata[item_id]["display_name"] = item_info["display_name"]
                    if not metadata[item_id]["tags"] and item_info.get("tags"):
                        metadata[item_id]["tags"] = item_info["tags"]

                metadata[item_id]["cooking_recipes_count"] = len(item_info.get("cooking_recipes", []))
                metadata[item_id]["crafting_recipes_count"] = len(item_info.get("crafting_recipes", []))
                metadata[item_id]["quests_count"] = len(item_info.get("quests", []))
        except Exception as e:
            print(f"Warning: Failed to read item_data.json: {e}", file=sys.stderr)

    return metadata


def build_ranked_rows(items: dict, metadata: dict, sort_by: str = "total", min_npcs: int = 1):
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


def get_excel_styles():
    """Returns standard openpyxl style objects for workbook formatting."""
    if not OPENPYXL_AVAILABLE:
        return {}
    return {
        "header_fill": PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid"),
        "header_font": Font(name="Segoe UI", size=11, bold=True, color="FFFFFF"),
        "sub_header_fill": PatternFill(start_color="34495E", end_color="34495E", fill_type="solid"),
        "love_fill": PatternFill(start_color="FFD1DC", end_color="FFD1DC", fill_type="solid"),  # Soft pink
        "love_font": Font(name="Segoe UI", size=10, bold=True, color="900C3F"),
        "like_fill": PatternFill(start_color="D4EFDF", end_color="D4EFDF", fill_type="solid"),  # Soft green
        "like_font": Font(name="Segoe UI", size=10, bold=True, color="1E8449"),
        "done_fill": PatternFill(start_color="EAECEE", end_color="EAECEE", fill_type="solid"),  # Soft gray
        "done_font": Font(name="Segoe UI", size=10, italic=True, color="7F8C8D"),
        "accent_fill": PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid"),  # Soft blue
        "accent_font": Font(name="Segoe UI", size=10, bold=True, color="1B4F72"),
        "data_font": Font(name="Segoe UI", size=10),
        "bold_font": Font(name="Segoe UI", size=10, bold=True),
        "center_align": Alignment(horizontal="center", vertical="center"),
        "left_align": Alignment(horizontal="left", vertical="center"),
        "right_align": Alignment(horizontal="right", vertical="center"),
        "thin_border": Border(
            left=Side(style="thin", color="E0E0E0"),
            right=Side(style="thin", color="E0E0E0"),
            top=Side(style="thin", color="E0E0E0"),
            bottom=Side(style="thin", color="E0E0E0")
        )
    }


def style_sheet_table(ws, headers, data_rows, numeric_cols=None, center_cols=None, styles=None):
    """Applies clean, standard styling to an openpyxl worksheet table."""
    if styles is None:
        styles = get_excel_styles()

    ws.append(headers)
    ws.row_dimensions[1].height = 26

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = styles["header_fill"]
        cell.font = styles["header_font"]
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_idx, r_data in enumerate(data_rows, start=2):
        ws.append(r_data)
        ws.row_dimensions[row_idx].height = 20
        for col_idx in range(1, len(r_data) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = styles["data_font"]
            cell.border = styles["thin_border"]
            if center_cols and col_idx in center_cols:
                cell.alignment = styles["center_align"]
            elif numeric_cols and col_idx in numeric_cols:
                cell.alignment = styles["right_align"]
            else:
                cell.alignment = styles["left_align"]

    # Auto column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 60)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def export_to_excel(all_rows: list, npcs: dict, output_path: Path):
    """
    Exports a styled multi-sheet Excel workbook with openpyxl.
    """
    if not OPENPYXL_AVAILABLE:
        print("[Excel] openpyxl is not installed. Skipping Excel export.", file=sys.stderr)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet
    styles = get_excel_styles()

    # ----------------------------------------------------
    # Sheet 1: All Items Ranked
    # ----------------------------------------------------
    ws1 = wb.create_sheet(title="All Items Ranked")
    headers1 = [
        "Rank", "Item Name", "Item ID", "Total NPCs", "Loved Count", "Liked Count",
        "Loved By (NPCs)", "Liked By (NPCs)", "Bin Price", "Store Price", "Tags",
        "Quest Usages", "Cooking Usages", "Crafting Usages"
    ]
    rows1 = [
        [
            r["rank"], r["item_name"], r["item_id"], r["total_count"],
            r["loved_count"], r["liked_count"], r["loved_by"], r["liked_by"],
            r["bin_price"], r["store_price"], r["tags"], r["quest_usage"],
            r["cooking_usage"], r["crafting_usage"]
        ]
        for r in all_rows
    ]
    style_sheet_table(ws1, headers1, rows1, numeric_cols=[1, 4, 5, 6, 9, 10, 12, 13, 14], center_cols=[1, 4, 5, 6])

    # ----------------------------------------------------
    # Sheet 2: Loved Gifts Ranked
    # ----------------------------------------------------
    loved_rows = [r for r in all_rows if r["loved_count"] > 0]
    loved_rows_sorted = sorted(loved_rows, key=lambda x: (-x["loved_count"], -x["total_count"], x["item_name"].lower()))
    ws2 = wb.create_sheet(title="Loved Gifts Ranked")
    headers2 = ["Loved Rank", "Item Name", "Loved Count", "Total NPCs", "Loved By (NPCs)", "Bin Price", "Store Price", "Tags"]
    rows2 = [
        [idx, r["item_name"], r["loved_count"], r["total_count"], r["loved_by"], r["bin_price"], r["store_price"], r["tags"]]
        for idx, r in enumerate(loved_rows_sorted, start=1)
    ]
    style_sheet_table(ws2, headers2, rows2, numeric_cols=[1, 3, 4, 6, 7], center_cols=[1, 3, 4])

    # ----------------------------------------------------
    # Sheet 3: Liked Gifts Ranked
    # ----------------------------------------------------
    liked_rows = [r for r in all_rows if r["liked_count"] > 0]
    liked_rows_sorted = sorted(liked_rows, key=lambda x: (-x["liked_count"], -x["total_count"], x["item_name"].lower()))
    ws3 = wb.create_sheet(title="Liked Gifts Ranked")
    headers3 = ["Liked Rank", "Item Name", "Liked Count", "Total NPCs", "Liked By (NPCs)", "Bin Price", "Store Price", "Tags"]
    rows3 = [
        [idx, r["item_name"], r["liked_count"], r["total_count"], r["liked_by"], r["bin_price"], r["store_price"], r["tags"]]
        for idx, r in enumerate(liked_rows_sorted, start=1)
    ]
    style_sheet_table(ws3, headers3, rows3, numeric_cols=[1, 3, 4, 6, 7], center_cols=[1, 3, 4])

    # ----------------------------------------------------
    # Sheet 4: NPC Gift Matrix (Items x NPCs)
    # ----------------------------------------------------
    ws4 = wb.create_sheet(title="NPC Gift Matrix")
    sorted_npc_ids = sorted(npcs.keys(), key=lambda nid: npcs[nid]["name"])
    matrix_headers = ["Rank", "Item Name", "Total", "Loved", "Liked"] + [npcs[nid]["name"] for nid in sorted_npc_ids]
    
    ws4.append(matrix_headers)
    ws4.row_dimensions[1].height = 28

    for col_idx in range(1, len(matrix_headers) + 1):
        cell = ws4.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    for row_idx, r in enumerate(all_rows, start=2):
        row_cells = [r["rank"], r["item_name"], r["total_count"], r["loved_count"], r["liked_count"]]
        loved_ids_set = set(r["loved_by_ids"].split(", ")) if r["loved_by_ids"] else set()
        liked_ids_set = set(r["liked_by_ids"].split(", ")) if r["liked_by_ids"] else set()

        for nid in sorted_npc_ids:
            if nid in loved_ids_set:
                row_cells.append("LOVE")
            elif nid in liked_ids_set:
                row_cells.append("LIKE")
            else:
                row_cells.append("")

        ws4.append(row_cells)
        ws4.row_dimensions[row_idx].height = 19

        # Style row cells
        for col_idx in range(1, len(row_cells) + 1):
            cell = ws4.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            val = cell.value

            if col_idx == 2:
                cell.font = bold_font
                cell.alignment = left_align
            elif col_idx in (1, 3, 4, 5):
                cell.font = data_font
                cell.alignment = center_align
            else:
                cell.alignment = center_align
                if val == "LOVE":
                    cell.fill = love_fill
                    cell.font = love_font
                elif val == "LIKE":
                    cell.fill = like_fill
                    cell.font = like_font
                else:
                    cell.font = data_font

    # Set matrix column widths
    ws4.column_dimensions["A"].width = 7
    ws4.column_dimensions["B"].width = 28
    ws4.column_dimensions["C"].width = 8
    ws4.column_dimensions["D"].width = 8
    ws4.column_dimensions["E"].width = 8
    for col_idx in range(6, len(matrix_headers) + 1):
        ws4.column_dimensions[get_column_letter(col_idx)].width = 11

    ws4.freeze_panes = "C2"
    ws4.auto_filter.ref = ws4.dimensions

    # ----------------------------------------------------
    # Sheet 5: NPC Summary
    # ----------------------------------------------------
    ws5 = wb.create_sheet(title="NPC Summary")
    headers5 = ["NPC Name", "NPC ID", "Total Loved Gifts", "Total Liked Gifts", "Loved Gift Items", "Liked Gift Items"]
    npc_summary_rows = []
    
    # Map item_id to name
    item_name_lookup = {r["item_id"]: r["item_name"] for r in all_rows}

    for nid in sorted_npc_ids:
        n_info = npcs[nid]
        loved_names = sorted([item_name_lookup.get(iid, iid.replace("_", " ").title()) for iid in n_info["loved"]])
        liked_names = sorted([item_name_lookup.get(iid, iid.replace("_", " ").title()) for iid in n_info["liked"]])
        npc_summary_rows.append([
            n_info["name"],
            nid,
            len(loved_names),
            len(liked_names),
            ", ".join(loved_names),
            ", ".join(liked_names)
        ])

    style_sheet_table(ws5, headers5, npc_summary_rows, numeric_cols=[3, 4], center_cols=[2, 3, 4])

    wb.save(output_path)
    print(f"[Excel] Successfully exported multi-sheet workbook to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and export ranked love/like gift items table to CSV and Excel."
    )
    parser.add_argument(
        "--fiddle",
        default="assets/fiddle",
        help="Path to assets/fiddle directory (default: assets/fiddle)"
    )
    parser.add_argument(
        "--item-data",
        default="data/item_data.json",
        help="Path to item_data.json (default: gift_indicator/data/item_data.json)"
    )
    parser.add_argument(
        "--tracker-files",
        default=None,
        help="Path to tracker files directory (default: Fields of Mistria Progress Tracker_files)"
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory for generated CSV and Excel files (default: exports)"
    )
    parser.add_argument(
        "--csv-name",
        default="item_gift_rankings.csv",
        help="Filename for CSV export (default: item_gift_rankings.csv)"
    )
    parser.add_argument(
        "--excel-name",
        default="item_gift_rankings.xlsx",
        help="Filename for Excel export (default: item_gift_rankings.xlsx)"
    )
    parser.add_argument(
        "--format",
        choices=["both", "csv", "excel"],
        default="both",
        help="Export format: csv, excel, or both (default: both)"
    )
    parser.add_argument(
        "--sort-by",
        choices=["total", "loved", "liked"],
        default="total",
        help="Primary sorting criterion: total, loved, or liked (default: total)"
    )
    parser.add_argument(
        "--min-npcs",
        type=int,
        default=1,
        help="Minimum number of NPCs liking or loving the item (default: 1)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Limit output to top N items (default: all)"
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    if not (repo_root / "data").exists() and (repo_root.parent / "data").exists():
        repo_root = repo_root.parent
    fiddle_path = (repo_root / args.fiddle).resolve() if not Path(args.fiddle).is_absolute() else Path(args.fiddle)
    item_data_path = (repo_root / args.item_data).resolve() if not Path(args.item_data).is_absolute() else Path(args.item_data)
    if args.tracker_files:
        p = Path(args.tracker_files)
        tracker_files_path = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    else:
        tracker_files_path = None
    output_dir = (repo_root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    print(f"Loading NPC preferences from: {fiddle_path}...")
    npcs, items = load_npc_preferences_from_fiddle(fiddle_path)

    if not npcs or not items:
        print("Falling back to item_data.json...")
        npcs, items = load_npc_preferences_from_json(item_data_path)

    if not npcs or not items:
        print("Error: Could not load NPC gift preferences from fiddle or item_data.json", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(npcs)} NPCs and {len(items)} giftable items.")

    print("Loading item metadata...")
    metadata = load_item_metadata(fiddle_path, item_data_path, tracker_files_path)

    print("Building rankings...")
    ranked_rows = build_ranked_rows(items, metadata, sort_by=args.sort_by, min_npcs=args.min_npcs)

    if args.top:
        ranked_rows = ranked_rows[:args.top]

    print(f"Total ranked items: {len(ranked_rows)}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ("both", "csv"):
        csv_path = output_dir / args.csv_name
        export_to_csv(ranked_rows, csv_path)

    if args.format in ("both", "excel"):
        excel_path = output_dir / args.excel_name
        export_to_excel(ranked_rows, npcs, excel_path)

    # Print summary top 15 to stdout
    print("\n" + "=" * 80)
    print(f"TOP 15 MOST POPULAR GIFTS (by number of NPCs)")
    print("=" * 80)
    print(f"{'Rank':<5} | {'Item Name':<24} | {'Total':<5} | {'Loved':<5} | {'Liked':<5} | {'Loved By'}")
    print("-" * 80)
    for r in ranked_rows[:15]:
        loved_preview = r["loved_by"] if len(r["loved_by"]) <= 35 else r["loved_by"][:32] + "..."
        print(f"{r['rank']:<5} | {r['item_name']:<24} | {r['total_count']:<5} | {r['loved_count']:<5} | {r['liked_count']:<5} | {loved_preview}")
    print("=" * 80)


if __name__ == "__main__":
    main()
