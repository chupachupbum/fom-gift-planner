"""
fom_planner

Fields of Mistria Daily Gift Planner & Progression Optimization Toolkit.
"""

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    SATURDAY_MARKET_VENDORS,
    SATURDAY_MARKET_BASE_VENDORS,
    SATURDAY_MARKET_UPGRADE_1_VENDORS,
    SATURDAY_MARKET_UPGRADE_2_VENDORS,
    STORY_GATED_TOWNSFOLK,
    AvailabilityTier,
)
from fom_planner.crafting import (
    deduct_crafting_materials,
    evaluate_craftability,
    format_crafting_chain,
    load_recipes,
)
from fom_planner.data_loader import (
    load_item_locations,
    load_item_metadata,
    load_npc_preferences_from_fiddle,
    load_npc_preferences_from_json,
)
from fom_planner.exporters import (
    OPENPYXL_AVAILABLE,
    export_plan_to_csv,
    export_plan_to_excel,
    export_to_csv,
    export_to_excel,
    get_excel_styles,
    print_terminal_plan,
    style_sheet_table,
)
from fom_planner.models import (
    CraftingPlan,
    CraftingStep,
    InGameDate,
    SaveData,
)
from fom_planner.optimizer import (
    ITEM_LOCATIONS,
    compute_focus_suggestions,
    plan_daily_gift_bag,
    resolve_root_raw_materials,
)
from fom_planner.parser import (
    find_latest_save,
    find_save_files,
    parse_save_file,
)
from fom_planner.rankings import build_ranked_rows

__version__ = "1.2.0"

__all__ = [
    "ANIMAL_FESTIVAL_ATTENDING_VENDORS",
    "SATURDAY_MARKET_VENDORS",
    "SATURDAY_MARKET_BASE_VENDORS",
    "SATURDAY_MARKET_UPGRADE_1_VENDORS",
    "SATURDAY_MARKET_UPGRADE_2_VENDORS",
    "STORY_GATED_TOWNSFOLK",
    "AvailabilityTier",
    "CraftingPlan",
    "CraftingStep",
    "InGameDate",
    "SaveData",
    "parse_save_file",
    "find_save_files",
    "find_latest_save",
    "load_recipes",
    "evaluate_craftability",
    "deduct_crafting_materials",
    "format_crafting_chain",
    "load_item_locations",
    "load_item_metadata",
    "load_npc_preferences_from_fiddle",
    "load_npc_preferences_from_json",
    "build_ranked_rows",
    "ITEM_LOCATIONS",
    "resolve_root_raw_materials",
    "compute_focus_suggestions",
    "plan_daily_gift_bag",
    "print_terminal_plan",
    "export_plan_to_csv",
    "export_to_csv",
    "export_plan_to_excel",
    "export_to_excel",
    "get_excel_styles",
    "style_sheet_table",
    "OPENPYXL_AVAILABLE",
]
