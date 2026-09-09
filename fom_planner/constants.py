"""
constants.py

Shared constants, enumerations, and configurations for Fields of Mistria planner.
"""

import os
from enum import IntEnum
from typing import Dict, List, Set, Tuple

# Default save folder locations on Windows and Linux/Steam Deck
DEFAULT_SAVE_DIRS: List[str] = [
    os.path.expandvars(r"%LOCALAPPDATA%\FieldsOfMistria\saves"),
    os.path.expandvars(r"%LOCALAPPDATA%\FieldsofMistria\saves"),
    os.path.expandvars(r"%APPDATA%\FieldsOfMistria\saves"),
    os.path.expanduser("~/.steam/steam/steamapps/compatdata/2142790/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria/saves"),
    os.path.expanduser("~/.local/share/Steam/steamapps/compatdata/2142790/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria/saves"),
]

# Save file entry keys that store global game state / metadata rather than location inventories
NON_LOCATION_KEYS: Set[str] = {
    "header", "player", "npcs", "gamedata", "game_stats",
    "quests", "info", "date_photos"
}

# Known Saturday Market Visiting Vendors (only present in town on Saturdays)
SATURDAY_MARKET_VENDORS: Set[str] = {
    "darcy", "louis", "merri", "stillwell", "taliferro", "vera", "wheedle", "zorel"
}

# Saturday Market Progression Tiers
# Base market starts with 4 vendors; 2 upgrade missions each add 2 more vendors
SATURDAY_MARKET_BASE_VENDORS: Set[str] = {"darcy", "louis", "merri", "vera"}
SATURDAY_MARKET_UPGRADE_1_VENDORS: Set[str] = {"taliferro", "wheedle"}  # Quest: upgrade_the_saturday_market
SATURDAY_MARKET_UPGRADE_2_VENDORS: Set[str] = {"stillwell", "zorel"}    # Quest: upgrade_the_saturday_market_plaza

# Story-gated permanent townsfolk who unlock through mine story progression
STORY_GATED_TOWNSFOLK: Set[str] = {"caldarus", "seridia"}

# Visiting vendors who attend the Animal Festival on Winter 10
ANIMAL_FESTIVAL_ATTENDING_VENDORS: Set[str] = {"louis", "merri"}

# Calendar of annual festivals in Fields of Mistria
FESTIVAL_CALENDAR: Dict[Tuple[str, int], str] = {
    ("spring", 17): "Spring Festival",
    ("summer", 28): "Shooting Star Festival",
    ("fall", 10): "Harvest Festival",
    ("autumn", 10): "Harvest Festival",
    ("winter", 10): "Animal Festival",
}

DAYS_OF_WEEK: List[str] = [
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
]

# Default maximum relationship threshold (heart points / affection for 10 hearts in Fields of Mistria)
DEFAULT_MAX_RELATIONSHIP_POINTS: float = 1755.0


class AvailabilityTier(IntEnum):
    """
    Tiered availability scoring for gift planning and crafting evaluation:
      - HAVE (2): Item already exists in bag or chest inventory.
      - CRAFT (1): Item can be crafted from available inventory materials.
      - UNAVAILABLE (0): Item is neither owned nor craftable.
    """
    UNAVAILABLE = 0
    CRAFT = 1
    HAVE = 2
