#!/usr/bin/env python3
"""
crafting_calculator.py

Backward-compatible shim delegating to fom_planner.crafting and fom_planner.models.
"""

from fom_planner.constants import AvailabilityTier
from fom_planner.crafting import (
    _calculate_max_craftable,
    _craft_item,
    deduct_crafting_materials,
    evaluate_craftability,
    format_crafting_chain,
    load_recipes,
)
from fom_planner.models import (
    CraftingPlan,
    CraftingStep,
)

__all__ = [
    "AvailabilityTier",
    "CraftingStep",
    "CraftingPlan",
    "load_recipes",
    "_craft_item",
    "_calculate_max_craftable",
    "format_crafting_chain",
    "evaluate_craftability",
    "deduct_crafting_materials",
]
