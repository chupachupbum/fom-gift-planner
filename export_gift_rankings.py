#!/usr/bin/env python3
"""
export_gift_rankings.py

Backward-compatible shim delegating to fom_planner.rankings, data_loader, exporters, and cli.
"""

from fom_planner.cli import run_rankings as main
from fom_planner.data_loader import (
    load_item_metadata,
    load_npc_preferences_from_fiddle,
    load_npc_preferences_from_json,
)
from fom_planner.exporters.csv_export import export_to_csv
from fom_planner.exporters.excel_export import (
    OPENPYXL_AVAILABLE,
    export_to_excel,
    get_excel_styles,
    style_sheet_table,
)
from fom_planner.rankings import build_ranked_rows

__all__ = [
    "load_npc_preferences_from_fiddle",
    "load_npc_preferences_from_json",
    "load_item_metadata",
    "build_ranked_rows",
    "export_to_csv",
    "OPENPYXL_AVAILABLE",
    "get_excel_styles",
    "style_sheet_table",
    "export_to_excel",
    "main",
]

if __name__ == "__main__":
    main()
