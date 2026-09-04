#!/usr/bin/env python3
"""
save_parser.py

Module to parse and inspect Fields of Mistria (.sav) save files.
Handles zlib decompression, binary header/entry extraction, JSON deserialization,
and provides structured access to player state, NPC relationship data, in-game calendar,
and current inventory.
"""

import glob
import json
import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# Default save folder locations on Windows
DEFAULT_SAVE_DIRS = [
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


def _extract_slot_item_and_count(slot: Any) -> Tuple[Optional[str], int]:
    """
    Safely extracts item_id and positive integer count from an inventory slot dict.
    Returns (None, 0) for empty/null slots, missing item_ids, or invalid counts.
    """
    if not isinstance(slot, dict):
        return None, 0
    item = slot.get("item")
    if not isinstance(item, dict):
        return None, 0
    item_id = item.get("item_id")
    if not item_id or not isinstance(item_id, str):
        return None, 0
    count_val = slot.get("count", 0)
    try:
        count = int(round(float(count_val)))
    except (ValueError, TypeError):
        count = 0
    if count <= 0:
        return None, 0
    return item_id, count


# Known Saturday Market Visiting Vendors (only present in town on Saturdays)
SATURDAY_MARKET_VENDORS = {
    "darcy", "louis", "merri", "stillwell", "taliferro", "vera", "wheedle", "zorel"
}

# Visiting vendors who attend the Animal Festival on Winter 10
ANIMAL_FESTIVAL_ATTENDING_VENDORS = {"louis", "merri"}

# Calendar of annual festivals in Fields of Mistria
FESTIVAL_CALENDAR = {
    ("spring", 17): "Spring Festival",
    ("summer", 28): "Shooting Star Festival",
    ("fall", 10): "Harvest Festival",
    ("autumn", 10): "Harvest Festival",
    ("winter", 10): "Animal Festival",
}

DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@dataclass
class InGameDate:
    year: int
    season: str
    day: int
    time_str: str = "06:00"

    @property
    def day_of_week(self) -> str:
        """FoM uses a 7-day week starting with Monday (Day 1). Day 6 is Saturday."""
        return DAYS_OF_WEEK[self.day % 7]

    @property
    def is_saturday(self) -> bool:
        """Returns True if today is Saturday (Saturday Market day)."""
        return (self.day % 7) == 6

    @property
    def days_until_saturday(self) -> int:
        """Returns number of days until the next Saturday Market."""
        return (6 - (self.day % 7)) % 7

    @property
    def next_saturday_day(self) -> int:
        """Returns the in-season day number of the next Saturday Market."""
        return self.day + self.days_until_saturday

    @property
    def is_animal_festival(self) -> bool:
        """Returns True if today is the Animal Festival (Winter 10)."""
        return self.season.lower() == "winter" and self.day == 10

    @property
    def festival_name(self) -> Optional[str]:
        """Returns the festival name if today is an annual festival, else None."""
        return FESTIVAL_CALENDAR.get((self.season.lower(), self.day))

    def __str__(self) -> str:
        if self.is_saturday:
            event_badge = " [SATURDAY MARKET DAY]"
        elif self.festival_name:
            event_badge = f" [{self.festival_name.upper()} DAY]"
        else:
            event_badge = ""
        return f"Year {self.year}, {self.season.capitalize()} Day {self.day} ({self.day_of_week}, {self.time_str}){event_badge}"


class SaveData:
    """Represents a parsed Fields of Mistria save game."""

    def __init__(self, file_path: Path, entries: Dict[str, str]):
        self.file_path = Path(file_path)
        self.raw_entries = entries
        self._override_date: Optional[InGameDate] = None

        # Primary JSON blocks
        self.header: dict = self._safe_json("header")
        self.player: dict = self._safe_json("player")
        self.npcs: dict = self._safe_json("npcs")
        self.gamedata: dict = self._safe_json("gamedata")
        self.game_stats: dict = self._safe_json("game_stats")
        self.quests: dict = self._safe_json("quests")
        self.info: dict = self._safe_json("info")

    def _safe_json(self, key: str) -> dict:
        val = self.raw_entries.get(key, "{}")
        try:
            return json.loads(val)
        except Exception:
            return {}

    @property
    def player_name(self) -> str:
        return self.header.get("name") or self.player.get("name") or "Player"

    @property
    def farm_name(self) -> str:
        return self.header.get("farm_name") or self.player.get("farm_name") or "Farm"

    @property
    def playtime_hours(self) -> float:
        seconds = self.header.get("playtime", 0.0)
        return seconds / 3600.0

    @property
    def in_game_date(self) -> InGameDate:
        """
        Calculates the in-game year, season, and day from calendar_time (in seconds).
        FoM uses 28 days per season, 4 seasons per year (112 days / year).
        1 game day = 86,400 calendar_time units.
        """
        if self._override_date is not None:
            return self._override_date

        cal_time = self.header.get("calendar_time")
        if cal_time is None:
            cal_time = self.gamedata.get("date", 0)

        day_seconds = 86400
        total_days = int(cal_time) // day_seconds
        days_per_year = 112
        year = (total_days // days_per_year) + 1
        day_in_year = total_days % days_per_year
        seasons = ["spring", "summer", "autumn", "winter"]
        season_idx = min(day_in_year // 28, 3)
        day_in_season = (day_in_year % 28) + 1

        # Clock
        clock_time = self.header.get("clock_time", 21600)
        hours = int(clock_time) // 3600
        minutes = (int(clock_time) % 3600) // 60
        time_str = f"{hours:02d}:{minutes:02d}"

        return InGameDate(
            year=year,
            season=seasons[season_idx],
            day=day_in_season,
            time_str=time_str
        )

    @in_game_date.setter
    def in_game_date(self, val: InGameDate):
        self._override_date = val

    @property
    def inventory(self) -> List[dict]:
        return self.player.get("inventory", [])

    @property
    def total_inventory_slots(self) -> int:
        return len(self.inventory) or 30

    @property
    def empty_inventory_slots(self) -> int:
        empty = 0
        for slot in self.inventory:
            if not slot or slot.get("item") is None or slot.get("count", 0) == 0:
                empty += 1
        return empty

    def get_npc_heart_points(self, npc_id: str) -> float:
        npc = self.npcs.get(npc_id, {})
        return float(npc.get("heart_points", 0.0))

    def get_npc_gifts_given(self, npc_id: str) -> Set[str]:
        """Returns the set of item IDs that have already been given to this NPC."""
        npc = self.npcs.get(npc_id, {})
        return set(npc.get("gifts_given", []))

    def get_npc_known_preferences(self, npc_id: str) -> Set[str]:
        """Returns the set of item IDs whose gift preferences are recorded in the player's journal."""
        npc = self.npcs.get(npc_id, {})
        return set(npc.get("known_gift_preferences", []))

    def can_gift_npc_today(self, npc_id: str) -> bool:
        """
        Returns True if this NPC is eligible to receive a gift today.
        In FoM save files, gift_flag is True if the NPC can still be gifted today.
        """
        npc = self.npcs.get(npc_id)
        if not npc:
            return False
        return bool(npc.get("gift_flag", True))

    def is_saturday_market_vendor(self, npc_id: str) -> bool:
        """Returns True if this NPC is a visiting Saturday Market vendor."""
        return npc_id.lower() in SATURDAY_MARKET_VENDORS

    def is_npc_present_in_town_today(self, npc_id: str) -> bool:
        """
        Returns True if the NPC is present in Mistria today.
        On Saturdays, all 34 NPCs (26 townsfolk + 8 vendors) are in town.
        On Winter 10 (Animal Festival), 28 NPCs are in town (26 townsfolk + Louis & Merri).
        On standard weekdays/Sundays, the 8 Saturday Market vendors are off-map in Aldaria.
        """
        if self.in_game_date.is_saturday:
            return True

        # Animal Festival exception: Louis and Merri attend as animal contestants
        if self.in_game_date.is_animal_festival and npc_id.lower() in ANIMAL_FESTIVAL_ATTENDING_VENDORS:
            return True

        if self.is_saturday_market_vendor(npc_id):
            return False

        # Extra check: check location_id
        npc_data = self.npcs.get(npc_id, {})
        loc = npc_data.get("location_position", {}).get("location_id", "")
        if loc == "aldaria":
            return False

        return True

    def get_present_npcs_today(self) -> List[str]:
        """Returns a list of NPC IDs who are physically in town on the current in-game day."""
        return [
            nid for nid in self.npcs.keys()
            if self.is_npc_present_in_town_today(nid)
        ]

    def get_giftable_npcs_today(self, only_present: bool = True) -> List[str]:
        """
        Returns a list of NPC IDs who are eligible to receive a gift today.
        If only_present is True, restricts to NPCs actually in town today.
        """
        return [
            nid for nid, data in self.npcs.items()
            if self.can_gift_npc_today(nid) and (not only_present or self.is_npc_present_in_town_today(nid))
        ]

    def get_bag_items(self) -> Dict[str, int]:
        """
        Returns a dictionary mapping {item_id: total_count} for all valid items
        currently held in the player's bag inventory.
        """
        items: Dict[str, int] = {}
        for slot in self.inventory:
            item_id, count = _extract_slot_item_and_count(slot)
            if item_id:
                items[item_id] = items.get(item_id, 0) + count
        return items

    def get_chest_items(self) -> Dict[str, int]:
        """
        Scans all location keys in raw_entries (ignoring non-location metadata keys),
        extracts items from all chests in each location's 'inventories' array, and
        returns a dictionary mapping {item_id: total_count}.
        """
        items: Dict[str, int] = {}
        for key, val_str in self.raw_entries.items():
            if key in NON_LOCATION_KEYS:
                continue
            try:
                loc_data = json.loads(val_str)
            except Exception:
                continue
            if not isinstance(loc_data, dict):
                continue
            inventories = loc_data.get("inventories")
            if not isinstance(inventories, list):
                continue
            for chest in inventories:
                if not isinstance(chest, list):
                    continue
                for slot in chest:
                    item_id, count = _extract_slot_item_and_count(slot)
                    if item_id:
                        items[item_id] = items.get(item_id, 0) + count
        return items

    def get_all_available_items(self, include_bag: bool = True, include_chests: bool = True) -> Dict[str, int]:
        """
        Merges player bag inventory and/or chest inventories across all locations
        into a single {item_id: total_count} dictionary.
        """
        combined: Dict[str, int] = {}
        if include_chests:
            for k, v in self.get_chest_items().items():
                combined[k] = combined.get(k, 0) + v
        if include_bag:
            for k, v in self.get_bag_items().items():
                combined[k] = combined.get(k, 0) + v
        return combined

    def get_chests_by_location(self) -> Dict[str, List[List[Dict[str, Any]]]]:
        """
        Returns a mapping of location_key -> list of chests (each chest being a list of slot dicts)
        for all locations that contain at least one chest inventory.
        """
        loc_map: Dict[str, List[List[Dict[str, Any]]]] = {}
        for key, val_str in self.raw_entries.items():
            if key in NON_LOCATION_KEYS:
                continue
            try:
                loc_data = json.loads(val_str)
            except Exception:
                continue
            if isinstance(loc_data, dict):
                invs = loc_data.get("inventories")
                if isinstance(invs, list) and invs:
                    loc_map[key] = invs
        return loc_map

    def summary(self) -> str:
        date = self.in_game_date
        present_count = len(self.get_present_npcs_today())
        giftable_count = len(self.get_giftable_npcs_today(only_present=True))
        bag_items = len(self.get_bag_items())
        chest_items = len(self.get_chest_items())
        total_items = len(self.get_all_available_items())
        return (
            f"Save: {self.file_path.name}\n"
            f"Player: {self.player_name} @ {self.farm_name}\n"
            f"Date: {date}\n"
            f"Playtime: {self.playtime_hours:.1f} hours\n"
            f"Inventory: {self.empty_inventory_slots}/{self.total_inventory_slots} slots empty ({bag_items} unique items in bag)\n"
            f"Storage: {chest_items} unique items in chests across {len(self.get_chests_by_location())} locations (Total available: {total_items} unique)\n"
            f"NPCs Present Today: {present_count}/34 ({giftable_count} giftable today)"
        )


def parse_save_file(file_path: Path | str) -> SaveData:
    """
    Parses a Fields of Mistria .sav file.
    Structure:
      - Zlib decompression
      - 8-byte little-endian unsigned integer (entry count)
      - Repeated entries of:
          * 8-byte key length (u64 LE)
          * UTF-8 key bytes
          * 8-byte value length (u64 LE)
          * UTF-8 JSON value bytes
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Save file not found at: '{path}'")

    with open(path, "rb") as f:
        compressed_bytes = f.read()

    try:
        data = zlib.decompress(compressed_bytes)
    except Exception as e:
        raise ValueError(f"Failed to zlib-decompress save file '{path}': {e}")

    if len(data) < 8:
        raise ValueError(f"Corrupted or empty save data in '{path}'")

    num_entries = struct.unpack_from("<Q", data, 0)[0]
    pos = 8
    entries: Dict[str, str] = {}

    for _ in range(num_entries):
        if pos + 8 > len(data):
            break
        key_len = struct.unpack_from("<Q", data, pos)[0]
        pos += 8
        if pos + key_len > len(data):
            break
        key = data[pos : pos + key_len].decode("utf-8", errors="replace")
        pos += key_len

        if pos + 8 > len(data):
            break
        val_len = struct.unpack_from("<Q", data, pos)[0]
        pos += 8
        if pos + val_len > len(data):
            break
        val = data[pos : pos + val_len].decode("utf-8", errors="replace")
        pos += val_len

        entries[key] = val

    return SaveData(path, entries)


def find_save_files(save_dir: Optional[Path | str] = None) -> List[Path]:
    """
    Finds all .sav files in the specified directory or standard FoM directories.
    Sorted by modification time (most recent first). Deduplicates identical files.
    """
    search_dirs: List[Path] = []
    if save_dir:
        p = Path(save_dir)
        if p.exists():
            search_dirs.append(p)
    else:
        seen_dirs: Set[Path] = set()
        for d in DEFAULT_SAVE_DIRS:
            p = Path(d)
            if p.exists():
                try:
                    resolved_d = p.resolve()
                except Exception:
                    resolved_d = p
                if resolved_d not in seen_dirs:
                    seen_dirs.add(resolved_d)
                    search_dirs.append(p)

    save_files: List[Path] = []
    seen_files: Set[Path] = set()
    for d in search_dirs:
        for f in d.glob("*.sav"):
            try:
                resolved_f = f.resolve()
            except Exception:
                resolved_f = f
            if resolved_f not in seen_files:
                seen_files.add(resolved_f)
                save_files.append(f)

    # Sort by modification time, newest first
    save_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return save_files


def find_latest_save(save_dir: Optional[Path | str] = None) -> Optional[Path]:
    """Returns the path to the most recent .sav file found."""
    saves = find_save_files(save_dir)
    return saves[0] if saves else None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse and inspect Fields of Mistria save files.")
    parser.add_argument("save_file", nargs="?", help="Path to .sav file (optional; defaults to latest)")
    args = parser.parse_args()

    target_path = Path(args.save_file) if args.save_file else find_latest_save()
    if not target_path or not target_path.exists():
        print("No save file found. Please provide a path to a .sav file.")
        sys.exit(1)

    print(f"Parsing: {target_path}")
    save = parse_save_file(target_path)
    print("\n" + save.summary())
