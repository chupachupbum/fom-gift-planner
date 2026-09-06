#!/usr/bin/env python3
"""
gift_planner.py

Backward-compatible shim delegating to fom_planner.optimizer, exporters, data_loader, and cli.
"""

from fom_planner.cli import run_planner as main
from fom_planner.data_loader import load_item_locations
from fom_planner.exporters.csv_export import export_plan_to_csv
from fom_planner.exporters.excel_export import export_plan_to_excel
from fom_planner.exporters.terminal import print_terminal_plan
from fom_planner.optimizer import (
    ITEM_LOCATIONS,
    compute_focus_suggestions,
    plan_daily_gift_bag,
    resolve_root_raw_materials,
)

__all__ = [
    "load_item_locations",
    "ITEM_LOCATIONS",
    "resolve_root_raw_materials",
    "compute_focus_suggestions",
    "plan_daily_gift_bag",
    "print_terminal_plan",
    "export_plan_to_csv",
    "export_plan_to_excel",
    "main",
]

if __name__ == "__main__":
    main()
