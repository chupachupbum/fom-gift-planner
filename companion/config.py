"""
companion/config.py

Configuration model, serialization, and grouped metadata for the
Mistria Gift Planner App.
Designed for seamless cross-platform usage (Windows & Linux).
"""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_repo_root() -> Path:
    """Finds repository root containing the data/ folder."""
    curr = Path.cwd().resolve()
    if (curr / "data").exists():
        return curr
    parent = Path(__file__).resolve().parent.parent
    if (parent / "data").exists():
        return parent
    return curr


@dataclass
class CompanionConfig:
    # 1. Planning Core
    strategy: str = "journal"  # "journal" or "max-relationship"
    mode: str = "auto"         # "auto", "today", "saturday", "market-only", "townsfolk", "weekday", "all"
    date_override: Optional[str] = None  # e.g. "saturday", "winter 10", "6"
    slots: int = 20
    focus_sort: str = "impact"  # "impact", "deficit", "quick-wins"
    all_seasons: bool = False

    # 2. Scoring & Weights
    loved_weight: int = 3
    liked_weight: int = 1
    vendor_boost: float = 1.5
    seasonal_boost: float = 2.0

    # 3. NPC Filters
    focus_mode_enabled: bool = False
    focus_npcs: str = ""        # Comma-separated list of NPC IDs
    exclude_npcs: str = ""      # Comma-separated list of NPC IDs
    force_all_npcs: bool = False
    max_relationship_points: Optional[float] = None  # None uses default (1755.0)
    no_exclude_max_relationship: bool = False

    # 4. Data & Save Paths (stored as strings; can be relative to repo or absolute Windows/Linux paths)
    save_file: Optional[str] = None
    recipes: str = "data/recipes.json"
    fiddle: str = "assets/fiddle"
    item_data: str = "data/item_data.json"
    item_locations: str = "data/item_locations.json"
    recipe_sources: str = "data/recipe_sources.json"
    item_seasons: str = "data/item_seasons.json"

    # 5. Game Assets & Server Settings
    game_assets_dir: Optional[str] = None
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanionConfig":
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        if "focus_npcs" in filtered and isinstance(filtered["focus_npcs"], (list, set, tuple)):
            filtered["focus_npcs"] = ",".join(str(x).strip() for x in filtered["focus_npcs"] if str(x).strip())
        if "exclude_npcs" in filtered and isinstance(filtered["exclude_npcs"], (list, set, tuple)):
            filtered["exclude_npcs"] = ",".join(str(x).strip() for x in filtered["exclude_npcs"] if str(x).strip())
        if "focus_mode_enabled" in filtered and not isinstance(filtered["focus_mode_enabled"], bool):
            filtered["focus_mode_enabled"] = bool(filtered["focus_mode_enabled"])
        return cls(**filtered)


def get_config_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or get_repo_root()
    return root / "companion_config.json"


def load_companion_config(repo_root: Optional[Path] = None) -> CompanionConfig:
    path = get_config_path(repo_root)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CompanionConfig.from_dict(data)
        except Exception:
            pass
    config = CompanionConfig()
    save_companion_config(config, repo_root)
    return config


def save_companion_config(config: CompanionConfig, repo_root: Optional[Path] = None) -> None:
    path = get_config_path(repo_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)
    except Exception as e:
        print(f"Warning: could not write {path}: {e}")


def get_settings_schema() -> List[Dict[str, Any]]:
    """
    Returns UI schema and descriptors for settings controls in the companion sidebar.
    """
    return [
        {
            "group": "Planning Core",
            "id": "planning",
            "fields": [
                {
                    "key": "strategy",
                    "label": "Strategy",
                    "type": "select",
                    "options": [
                        {"value": "journal", "label": "Journal Completion (Discover unrecorded gifts)"},
                        {"value": "max-relationship", "label": "Max Relationship (Daily points + Infused dishes)"},
                    ],
                    "help": "Choose Journal Completion (discovering unrecorded preferences) or Max Relationship (maximizing friendship points).",
                },
                {
                    "key": "mode",
                    "label": "Mode",
                    "type": "select",
                    "options": [
                        {"value": "auto", "label": "Auto (Follow save calendar day)"},
                        {"value": "saturday", "label": "Saturday Market (All 34 Villagers + Vendor Boost)"},
                        {"value": "weekday", "label": "Weekday (26 Townsfolk only)"},
                        {"value": "market-only", "label": "Market Vendors Only (8 Villagers)"},
                        {"value": "all", "label": "All Villagers (Ignore calendar)"},
                    ],
                    "help": "Filter villagers by schedule (Auto from save date, Saturday Market, Weekday townsfolk, or Market Vendors).",
                },
                {
                    "key": "slots",
                    "label": "Bag Slots Budget",
                    "type": "number",
                    "min": 1,
                    "max": 30,
                    "step": 1,
                    "help": "Maximum daily inventory bag slots allocated for gift items (1–30).",
                },
                {
                    "key": "date_override",
                    "label": "Date Override",
                    "type": "date_override",
                    "placeholder": "Leave empty for save date",
                    "help": "Simulate an upcoming day, season, or festival instead of your current save file's date.",
                },
                {
                    "key": "exclude_npcs",
                    "label": "Exclude Villagers",
                    "type": "exclude_npc_picker",
                    "placeholder": "Select villagers to exclude",
                    "help": "Choose specific villagers to omit from all gift planning.",
                },
                {
                    "key": "force_all_npcs",
                    "label": "Include Already-Gifted Villagers",
                    "type": "checkbox",
                    "help": "Plan gifts even for villagers already gifted on the current in-game day.",
                },
                {
                    "key": "no_exclude_max_relationship",
                    "label": "Include Villagers at Max Hearts (10 Hearts)",
                    "type": "checkbox",
                    "help": "Continue planning gifts for villagers who have already reached 10 hearts.",
                },
                {
                    "key": "loved_weight",
                    "label": "Loved Gift Weight",
                    "type": "range",
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "help": "Scoring multiplier for loved gift recommendations (higher means prioritize more).",
                },
                {
                    "key": "liked_weight",
                    "label": "Liked Gift Weight",
                    "type": "range",
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "help": "Scoring multiplier for liked gift recommendations (higher means prioritize more).",
                },
                {
                    "key": "vendor_boost",
                    "label": "Saturday Vendor Boost Multiplier",
                    "type": "range",
                    "min": 1.0,
                    "max": 5.0,
                    "step": 0.1,
                    "help": "Extra score priority for market vendors who only visit town on Saturdays (higher means prioritize more).",
                },
            ],
        },
        {
            "group": "Focus Suggestions",
            "id": "focus_suggestions",
            "fields": [
                {
                    "key": "focus_mode_enabled",
                    "label": "Focus Mode",
                    "type": "checkbox",
                    "help": "Restrict gift recommendations and focus suggestions solely to selected villagers.",
                },
                {
                    "key": "focus_npcs",
                    "label": "Focus Villagers",
                    "type": "focus_npc_picker",
                    "placeholder": "e.g. adeline, balor",
                    "help": "Choose which specific villagers to prioritize when Focus Mode is active.",
                },
                {
                    "key": "focus_sort",
                    "label": "Focus Suggestions Sort",
                    "type": "select",
                    "options": [
                        {"value": "impact", "label": "Impact (Most blocked villager gifts first)"},
                        {"value": "deficit", "label": "Deficit (Largest shortage first)"},
                        {"value": "quick-wins", "label": "Quick Wins (Closest to completion)"},
                    ],
                    "help": "Order blockers by Impact (unblocks most gifts), Deficit (largest quantity needed), or Quick Wins.",
                },
                {
                    "key": "all_seasons",
                    "label": "Show All Seasons for Focus Items",
                    "type": "checkbox",
                    "help": "Include out-of-season material blockers alongside current season items.",
                },
                {
                    "key": "seasonal_boost",
                    "label": "Current Season Focus Boost",
                    "type": "range",
                    "min": 1.0,
                    "max": 5.0,
                    "step": 0.5,
                    "help": "Priority multiplier for raw materials available in the current season (higher means prioritize more).",
                },
            ],
        },
    ]
