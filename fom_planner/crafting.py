"""
crafting.py

Recursive DAG crafting calculator and inventory deduction engine:
- load_recipes
- evaluate_craftability
- deduct_crafting_materials
- format_crafting_chain
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from fom_planner.constants import AvailabilityTier
from fom_planner.models import CraftingPlan, CraftingStep


def load_recipes(recipes_path: Optional[Union[Path, str]] = None) -> Dict[str, Any]:
    """
    Loads the recipe database from JSON file.
    If recipes_path is not specified, defaults to 'data/recipes.json' relative
    to the repository root.
    """
    if recipes_path is None:
        root_path = Path(__file__).resolve().parent.parent / "data" / "recipes.json"
        script_path = Path(__file__).resolve().parent / "data" / "recipes.json"
        if root_path.exists():
            target = root_path
        elif script_path.exists():
            target = script_path
        else:
            target = Path("data/recipes.json")
    else:
        target = Path(recipes_path)

    if not target.exists() or not target.is_file():
        return {}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _craft_item(
    target_id: str,
    target_count: int,
    inv_pool: Dict[str, int],
    recipes: Dict[str, Any],
    call_stack: Set[str],
    steps: List[CraftingStep],
) -> bool:
    """
    Internal recursive helper to satisfy target_count of target_id from inv_pool or sub-recipes.
    Mutates inv_pool in-place and appends to steps.
    Returns True if successfully fulfilled, False otherwise.
    """
    target_id = target_id.strip().lower()
    if target_count <= 0:
        return True

    # 1. Consume available target_id directly from inv_pool if present
    have_count = inv_pool.get(target_id, 0)
    take = min(have_count, target_count)
    if take > 0:
        inv_pool[target_id] -= take
        target_count -= take

    if target_count == 0:
        return True

    # 2. Prevent circular dependency cycles
    if target_id in call_stack:
        return False

    # 3. Check if recipe exists
    if target_id not in recipes:
        return False

    recipe = recipes[target_id]
    output_count = max(1, int(recipe.get("output_count", 1)))
    batches = math.ceil(target_count / output_count)
    total_produced = batches * output_count

    call_stack.add(target_id)

    # 4. Resolve ingredients
    step_ingredients: List[Dict[str, Any]] = []
    recipe_ingredients = recipe.get("ingredients", [])

    for ing in recipe_ingredients:
        ing_id = str(ing.get("item_id", "")).strip().lower()
        ing_name = ing.get("display_name", ing_id)
        ing_unit = int(ing.get("count", 1))
        total_ing_needed = ing_unit * batches

        if not _craft_item(ing_id, total_ing_needed, inv_pool, recipes, call_stack, steps):
            call_stack.remove(target_id)
            return False

        step_ingredients.append({
            "item_id": ing_id,
            "display_name": ing_name,
            "count": total_ing_needed,
        })

    call_stack.remove(target_id)

    # 5. Record the completed crafting step
    steps.append(CraftingStep(
        product_id=target_id,
        product_name=recipe.get("display_name", target_id),
        count=total_produced,
        ingredients=step_ingredients,
    ))

    # 6. Put surplus back into inv_pool
    surplus = total_produced - target_count
    if surplus > 0:
        inv_pool[target_id] = inv_pool.get(target_id, 0) + surplus

    return True


def _calculate_max_craftable(
    item_id: str,
    inventory: Dict[str, int],
    recipes: Dict[str, Any],
) -> int:
    """
    Determines the maximum craftable quantity of item_id given inventory and recipes.
    Uses exponential doubling followed by binary search.
    """
    item_id = item_id.strip().lower()

    def can_craft(qty: int) -> bool:
        if qty <= 0:
            return True
        sim_inv = dict(inventory)
        steps: List[CraftingStep] = []
        call_stack: Set[str] = set()
        return _craft_item(item_id, qty, sim_inv, recipes, call_stack, steps)

    if not can_craft(1):
        return 0

    # Exponential doubling to find upper bound
    low = 1
    high = 2
    while can_craft(high):
        low = high
        high *= 2
        if high > 100_000_000:
            break

    # Binary search within [low, high]
    best = low
    left = low
    right = high
    while left <= right:
        mid = (left + right) // 2
        if can_craft(mid):
            best = mid
            left = mid + 1
        else:
            right = mid - 1

    return best


def format_crafting_chain(plan: CraftingPlan) -> str:
    """
    Produces a concise human-readable summary of the intermediate crafting steps.
    E.g.: 'Golden Cheese [← 2× Golden Milk], Golden Butter [← 2× Golden Milk]'
    """
    if not plan.steps:
        return ""

    # If there are intermediate sub-recipes, list the intermediate steps
    if len(plan.steps) > 1:
        intermediate_steps = plan.steps[:-1]
    else:
        intermediate_steps = plan.steps

    step_strs: List[str] = []
    for step in intermediate_steps:
        ing_parts = [
            f"{ing.get('count', 1)}× {ing.get('display_name', ing.get('item_id', ''))}"
            for ing in step.ingredients
        ]
        step_strs.append(f"{step.product_name} [← {', '.join(ing_parts)}]")

    return ", ".join(step_strs)


def evaluate_craftability(
    item_id: str,
    inventory: Dict[str, int],
    recipes: Dict[str, Any],
    count_needed: int = 1,
) -> CraftingPlan:
    """
    Evaluates whether an item is owned (HAVE), craftable (CRAFT), or UNAVAILABLE.

    Rules:
    - If inventory has >= count_needed of item_id: returns HAVE (tier 2), max_craftable = inventory[item_id] // count_needed.
    - Otherwise, performs recursive DAG resolution on recipes:
      - Consumes owned intermediate products first.
      - Resolves missing intermediates recursively against a shared inventory pool.
      - Accurately solves the Golden Milk Problem.
      - Guarded against circular dependencies.
      - If satisfiable: returns CRAFT (tier 1), max_craftable, raw_materials_needed, steps, chain_summary.
      - If unsatisfiable: returns UNAVAILABLE (tier 0), max_craftable = 0.
    """
    item_id = item_id.strip().lower()
    clean_inv = {k.strip().lower(): int(v) for k, v in inventory.items() if v > 0}

    # Edge case: count_needed <= 0
    effective_needed = max(1, count_needed)

    # 1. Direct HAVE check (no recipe lookup needed)
    owned_count = clean_inv.get(item_id, 0)
    if count_needed <= 0 and owned_count > 0:
        return CraftingPlan(
            status=AvailabilityTier.HAVE,
            max_craftable=owned_count,
            raw_materials_needed={},
            steps=[],
            chain_summary="",
        )

    if count_needed > 0 and owned_count >= count_needed:
        return CraftingPlan(
            status=AvailabilityTier.HAVE,
            max_craftable=owned_count // count_needed,
            raw_materials_needed={},
            steps=[],
            chain_summary="",
        )

    # 2. Craftability resolution
    sim_inv = dict(clean_inv)
    steps: List[CraftingStep] = []
    call_stack: Set[str] = set()

    success = _craft_item(item_id, effective_needed, sim_inv, recipes, call_stack, steps)

    if not success:
        return CraftingPlan(
            status=AvailabilityTier.UNAVAILABLE,
            max_craftable=0,
            raw_materials_needed={},
            steps=[],
            chain_summary="",
        )

    # Calculate raw materials consumed from the initial inventory pool
    raw_materials_needed: Dict[str, int] = {}
    for k, initial_qty in clean_inv.items():
        consumed = initial_qty - sim_inv.get(k, 0)
        if consumed > 0:
            raw_materials_needed[k] = consumed

    # Calculate max craftable quantity from initial inventory
    max_craftable = _calculate_max_craftable(item_id, clean_inv, recipes)

    plan = CraftingPlan(
        status=AvailabilityTier.CRAFT,
        max_craftable=max_craftable,
        raw_materials_needed=raw_materials_needed,
        steps=steps,
    )
    plan.chain_summary = format_crafting_chain(plan)
    return plan


def deduct_crafting_materials(
    item_id: str,
    inventory: Dict[str, int],
    recipes: Dict[str, Any],
    count: int = 1,
) -> Dict[str, int]:
    """
    Deducts required materials (either directly from owned inventory if HAVE,
    or from intermediate/raw materials if CRAFT) from a copy of inventory
    and returns the updated inventory dict.
    """
    item_id = item_id.strip().lower()
    updated_inv = {k: int(v) for k, v in inventory.items()}
    if count <= 0:
        return updated_inv

    # 1. If item is owned in inventory, deduct directly
    owned = updated_inv.get(item_id, 0)
    take = min(owned, count)
    if take > 0:
        updated_inv[item_id] -= take
        count -= take

    if count == 0:
        return updated_inv

    # 2. Deduct remaining count by recursive crafting resolution
    call_stack: Set[str] = set()
    steps: List[CraftingStep] = []
    _craft_item(item_id, count, updated_inv, recipes, call_stack, steps)

    # Clean up negative or float values
    for k in list(updated_inv.keys()):
        if updated_inv[k] < 0:
            updated_inv[k] = 0

    return updated_inv
