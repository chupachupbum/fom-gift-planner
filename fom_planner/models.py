"""
models.py

Data structures and domain models for Fields of Mistria planner:
- InGameDate
- SaveData
- CraftingStep
- CraftingPlan
- is_quest_completed
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    DAYS_OF_WEEK,
    DEFAULT_MAX_RELATIONSHIP_POINTS,
    FEMALE_MARRIAGE_CANDIDATES,
    FESTIVAL_CALENDAR,
    MARRIAGE_EXCLUSIVE_QUEST_NAMES,
    NON_LOCATION_KEYS,
    SATURDAY_MARKET_VENDORS,
    AvailabilityTier,
)


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


def _extract_slot_item_count_and_infusion(
    slot: Any,
) -> Tuple[Optional[str], int, Optional[str]]:
    """
    Safely extracts item_id, positive integer count, and normalized infusion ('lovable' or 'likable')
    from an inventory slot dict.
    Returns (None, 0, None) for empty/null slots, missing item_ids, non-positive counts, or corrupt data.
    """
    if not isinstance(slot, dict):
        return None, 0, None

    item = slot.get("item")
    if not isinstance(item, dict):
        return None, 0, None

    item_id = item.get("item_id")
    if not item_id or not isinstance(item_id, str):
        return None, 0, None
    norm_item_id = item_id.strip().lower()
    if not norm_item_id:
        return None, 0, None

    count_val = slot.get("count", 0)
    if isinstance(count_val, bool):
        return None, 0, None

    try:
        count = int(round(float(count_val)))
    except (ValueError, TypeError, OverflowError):
        count = 0

    if count <= 0:
        return None, 0, None

    raw_infusion = item.get("infusion")
    infusion = None
    if isinstance(raw_infusion, str) and not isinstance(raw_infusion, bool):
        norm_infusion = raw_infusion.strip().lower()
        if norm_infusion == "lovable":
            infusion = "lovable"
        elif norm_infusion in ("likable", "likeable"):
            infusion = "likable"

    return norm_item_id, count, infusion


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


# Quest title alias dictionary mapping normalized Wiki titles / variants to internal game save keys
QUEST_TITLE_ALIASES: Dict[str, str] = {
    "restocking_mistrias_food_reserves": "replenishing_mistrias_food_reserves_1",
    "restocking_mistrias_food_reserves_1": "replenishing_mistrias_food_reserves_1",
    "restocking_mistrias_food_reserves_2": "replenishing_mistrias_food_reserves_2",
    "request_for_wood_fencing": "request_for_wood_fence",
    "wood_fencing_request": "request_for_wood_fence",
    "crown_request_archeology_shards": "crown_request_archaeology_shards",
    "upgrade_haydens_barn": "repair_haydens_barn",
    "request_for_a_hay_bale": "request_for_haybale",
    "request_for_hay_bale": "request_for_haybale",
    "request_for_a_really_round_rock": "request_for_round_rock",
    "request_for_really_round_rock": "request_for_round_rock",
    "request_for_capybara_bristles": "request_for_bristles",
    "fried_earthshroom_challenge": "crispy_fried_earthshroom_challenge",
    "request_for_a_daikon_radish": "request_for_daikon",
    "request_for_daikon_radish": "request_for_daikon",
    "request_for_bell_berry_bakewell_tart": "request_for_bell_berry_bakewell",
    "the_mill_restoration_project": "repair_the_mill",
    "upgrade_the_inn": "repair_the_inn",
    "expanding_the_saturday_market": "upgrade_the_saturday_market",
    "request_for_wild_berries": "request_for_wild_berry",
}

REVERSE_QUEST_TITLE_ALIASES: Dict[str, List[str]] = {}
for _wiki_k, _save_v in QUEST_TITLE_ALIASES.items():
    REVERSE_QUEST_TITLE_ALIASES.setdefault(_save_v, []).append(_wiki_k)

GERUND_NOUN_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("_fencing", "_fence"),
)


def _normalize_quest_key(raw_key: str) -> str:
    """Normalizes a quest ID or quest display title into lowercase snake_case."""
    if not raw_key:
        return ""
    s = str(raw_key).strip().lower()
    # Strip straight and curly apostrophes (e.g. "Mistria's" -> "mistrias", "Jo's" -> "jos")
    s = re.sub(r"['’]", "", s)
    # Replace non-alphanumeric characters with underscore
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _strip_articles(s: str) -> str:
    """Strips leading and internal articles from a normalized snake_case string."""
    for p in ("a_", "an_", "the_"):
        if s.startswith(p):
            s = s[len(p):]
            break
    return re.sub(r"_(a|an|the)_", "_", s)


def is_quest_completed(quest_name: str, completed_keys: Set[str]) -> bool:
    """
    Checks whether a quest (by display title or ID) is marked completed in completed_keys.
    Normalizes quest_name into snake_case, and checks:
      1. Exact match
      2. Direct alias match from QUEST_TITLE_ALIASES
      3. Article-stripped match ('a', 'an', 'the')
      4. Request pattern swap ('X_request' <-> 'request_for_X')
      5. Gerund/noun suffix variants (e.g. '_fencing' <-> '_fence')
      6. Alias checks across all generated candidates
      7. Singular / plural match (trailing 's' or 'es')
    """
    if not quest_name or not completed_keys:
        return False

    norm = _normalize_quest_key(quest_name)
    if not norm:
        return False

    if norm in completed_keys:
        return True

    candidates: Set[str] = set()

    # 1. Direct alias lookup for norm
    if norm in QUEST_TITLE_ALIASES:
        candidates.add(QUEST_TITLE_ALIASES[norm])
    for rev in REVERSE_QUEST_TITLE_ALIASES.get(norm, []):
        candidates.add(rev)

    # 2. Leading article stripping & adding
    for prefix in ("a_", "an_", "the_"):
        if norm.startswith(prefix):
            candidates.add(norm[len(prefix):])
        candidates.add(prefix + norm)

    # 3. Inner article stripping (e.g. 'request_for_a_red_toadstool' <-> 'request_for_red_toadstool')
    inner_stripped = re.sub(r"_(a|an|the)_", "_", norm)
    if inner_stripped != norm:
        candidates.add(inner_stripped)

    # 4. Request pattern swap (X_request <-> request_for_X) and article variations
    variants = {norm, inner_stripped} | set(candidates)
    for v in list(variants):
        if v.endswith("_request"):
            core = v[:-8]
            for art in ("a_", "an_", "the_"):
                if core.startswith(art):
                    core = core[len(art):]
                    break
            candidates.add(f"request_for_{core}")
            candidates.add(f"request_for_a_{core}")
            candidates.add(f"request_for_an_{core}")
            candidates.add(f"request_for_the_{core}")
            candidates.add(core)
            candidates.add(f"a_{core}")
            candidates.add(f"the_{core}")
        if v.startswith("request_for_"):
            core = v[12:]
            for art in ("a_", "an_", "the_"):
                if core.startswith(art):
                    core = core[len(art):]
                    break
            candidates.add(f"{core}_request")
            candidates.add(f"request_for_{core}")
            candidates.add(f"request_for_a_{core}")
            candidates.add(f"request_for_an_{core}")
            candidates.add(f"request_for_the_{core}")
            candidates.add(core)
            candidates.add(f"a_{core}")
            candidates.add(f"the_{core}")

    # 5. Gerund/noun suffix variants (e.g. '_fencing' <-> '_fence')
    gerund_variants: Set[str] = set()
    for item in {norm} | candidates:
        for gerund_sfx, noun_sfx in GERUND_NOUN_SUFFIXES:
            if item.endswith(gerund_sfx):
                gerund_variants.add(item[:-len(gerund_sfx)] + noun_sfx)
            elif item.endswith(noun_sfx):
                gerund_variants.add(item[:-len(noun_sfx)] + gerund_sfx)
            if f"{gerund_sfx}_" in item:
                gerund_variants.add(item.replace(f"{gerund_sfx}_", f"{noun_sfx}_"))
            elif f"{noun_sfx}_" in item:
                gerund_variants.add(item.replace(f"{noun_sfx}_", f"{gerund_sfx}_"))
    candidates |= gerund_variants

    # 6. Check QUEST_TITLE_ALIASES for all generated candidate permutations
    alias_variants: Set[str] = set()
    for item in {norm} | candidates:
        if item in QUEST_TITLE_ALIASES:
            alias_variants.add(QUEST_TITLE_ALIASES[item])
        for rev in REVERSE_QUEST_TITLE_ALIASES.get(item, []):
            alias_variants.add(rev)
    candidates |= alias_variants

    # 7. Singular / Plural match for norm and all generated candidates
    all_to_check = {norm} | candidates
    plural_variants: Set[str] = set()
    for item in all_to_check:
        if item.endswith("s"):
            plural_variants.add(item[:-1])
        else:
            plural_variants.add(item + "s")
        if item.endswith("es"):
            plural_variants.add(item[:-2])
        else:
            plural_variants.add(item + "es")

    all_to_check |= plural_variants

    for item in list(plural_variants):
        if item in QUEST_TITLE_ALIASES:
            all_to_check.add(QUEST_TITLE_ALIASES[item])
        for rev in REVERSE_QUEST_TITLE_ALIASES.get(item, []):
            all_to_check.add(rev)

    if any(c in completed_keys for c in all_to_check):
        return True

    # 8. Fallback article-stripped comparison against completed_keys
    norm_core = _strip_articles(norm)
    for k in completed_keys:
        if _strip_articles(k) == norm_core:
            return True

    return False


def normalize_future_wife(val: Any) -> str:
    """
    Normalizes the future_wife setting into 'none', 'all', or one of the 6 lowercased
    female marriage candidate IDs ('adeline', 'celine', 'juniper', 'reina', 'seridia', 'valen').
    """
    if val is None or isinstance(val, bool):
        return "none"
    s = str(val).strip().lower()
    if not s or s in ("none", "null", "undecided", "false", "0"):
        return "none"
    if s in ("all", "all_bachelorettes", "keep_all"):
        return "all"
    if s in FEMALE_MARRIAGE_CANDIDATES:
        return s
    return "none"


def is_quest_applicable_for_future_wife(
    quest: Dict[str, Any],
    future_wife: Optional[str] = "none",
) -> bool:
    """
    Returns True if the quest is applicable given the player's selected future_wife.
    Post-marriage pregnancy Heart Quest 'A Craving' only triggers for the single
    female marriage candidate the player marries. All other quests return True.
    """
    if not isinstance(quest, dict):
        return True
    q_name = quest.get("quest_name") or ""
    norm_key = _normalize_quest_key(str(q_name))
    if norm_key not in MARRIAGE_EXCLUSIVE_QUEST_NAMES:
        return True
    norm_wife = normalize_future_wife(future_wife)
    if norm_wife == "none":
        return False
    if norm_wife == "all":
        return True
    requester = str(quest.get("requester") or "").strip().lower()
    return requester == norm_wife


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
        Returns override date if set, otherwise original date.
        """
        if self._override_date is not None:
            return self._override_date

        return self.original_in_game_date

    @property
    def original_in_game_date(self) -> InGameDate:
        """Calculates original save in-game date regardless of override."""
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
        npc = self.npcs.get(npc_id)
        if not npc:
            npc = self.npcs.get(npc_id.lower(), {})
        val = npc.get("heart_points")
        if val is None:
            val = npc.get("affection", 0.0)
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def get_npc_gifts_given(self, npc_id: str) -> Set[str]:
        """Returns the set of item IDs that have already been given to this NPC."""
        npc = self.npcs.get(npc_id)
        if not npc:
            npc = self.npcs.get(npc_id.lower(), {})
        given = npc.get("gifts_given")
        if given is None:
            given = npc.get("gift_history", [])
        return set(given)

    def is_npc_max_relationship(self, npc_id: str, max_points: Optional[float] = None) -> bool:
        """
        Returns True if the NPC in this save file has reached maximum relationship.
        Checks:
          1. Explicit save flags (e.g. 'is_max_relationship', 'max_relationship',
             'is_max_hearts', 'max_hearts', 'is_capped', 'capped', 'heart_cap').
          2. Whether heart_points or affection is >= max_points (defaults to DEFAULT_MAX_RELATIONSHIP_POINTS).
        """
        if not self.npcs:
            return False
        npc = self.npcs.get(npc_id)
        if not npc:
            npc = self.npcs.get(npc_id.lower(), {})
        if not npc or not isinstance(npc, dict):
            return False

        for flag in (
            "is_max_relationship",
            "max_relationship",
            "is_max_hearts",
            "max_hearts",
            "is_capped",
            "capped",
            "heart_cap",
        ):
            if bool(npc.get(flag)):
                return True

        threshold = max_points if max_points is not None else DEFAULT_MAX_RELATIONSHIP_POINTS
        hp = self.get_npc_heart_points(npc_id)
        return hp >= threshold

    def get_max_relationship_npc_ids(self, max_points: Optional[float] = None) -> Set[str]:
        """Returns the set of lowercased NPC IDs currently at max relationship in this save."""
        return {
            nid.lower() for nid in self.npcs.keys()
            if self.is_npc_max_relationship(nid, max_points=max_points)
        }

    def get_npc_known_preferences(self, npc_id: str) -> Set[str]:
        """Returns the set of item IDs whose gift preferences are recorded in the player's journal."""
        npc = self.npcs.get(npc_id)
        if not npc:
            npc = self.npcs.get(npc_id.lower(), {})
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

    def get_unlocked_npc_ids(self) -> Set[str]:
        """
        Returns the set of lowercased NPC IDs present in the save's npcs block.
        NPCs not present in this set are locked / not yet unlocked in the player's progression.
        """
        return {k.lower() for k in self.npcs.keys()}

    def get_unlocked_vendor_ids(self) -> Set[str]:
        """Returns the set of Saturday Market vendor IDs currently unlocked in this save."""
        return self.get_unlocked_npc_ids() & SATURDAY_MARKET_VENDORS

    def is_npc_unlocked(self, npc_id: str) -> bool:
        """
        Returns True if the given NPC has been unlocked in this save.
        If self.npcs is empty (e.g. mock or stripped save), defaults to True.
        """
        if not self.npcs:
            return True
        return npc_id.lower() in self.get_unlocked_npc_ids()

    def get_unlocked_recipe_ids(self) -> Optional[Set[str]]:
        """
        Returns the set of lowercased recipe IDs the player has unlocked in this save file,
        or None if recipe unlock data is not present or empty.
        """
        if not hasattr(self, "player") or not isinstance(self.player, dict):
            return None
        unlocks = self.player.get("recipe_unlocks")
        if not unlocks or not isinstance(unlocks, list):
            return None
        result = {str(r).strip().lower() for r in unlocks if r and isinstance(r, str)}
        return result if result else None

    def get_acquired_items(self) -> Set[str]:
        """
        Returns the set of lowercased item IDs the player has acquired in this save file.
        Combines:
          1. player.get("items_acquired", []) normalized to lowercase.
          2. Any items currently present in the player bag or storage chests
             (via self.get_all_available_items()) as a defensive fallback.
          3. Any recipe/item IDs recorded in player.get("recipes_created", [])
             (or keys if dict) as a defensive fallback.
        """
        acquired: Set[str] = set()

        player = getattr(self, "player", None)
        if isinstance(player, dict):
            # 1. Primary: player["items_acquired"]
            raw_acquired = player.get("items_acquired")
            if isinstance(raw_acquired, (list, set, tuple)):
                for item in raw_acquired:
                    if item and isinstance(item, str):
                        norm = item.strip().lower()
                        if norm:
                            acquired.add(norm)
            elif isinstance(raw_acquired, dict):
                for item in raw_acquired.keys():
                    if item and isinstance(item, str):
                        norm = item.strip().lower()
                        if norm:
                            acquired.add(norm)

            # 2. Defensive fallback: player["recipes_created"]
            raw_created = player.get("recipes_created")
            if isinstance(raw_created, (list, set, tuple)):
                for item in raw_created:
                    if item and isinstance(item, str):
                        norm = item.strip().lower()
                        if norm:
                            acquired.add(norm)
            elif isinstance(raw_created, dict):
                for item in raw_created.keys():
                    if item and isinstance(item, str):
                        norm = item.strip().lower()
                        if norm:
                            acquired.add(norm)

        # 3. Defensive fallback: items currently in bag or chests
        try:
            available = self.get_all_available_items()
            if isinstance(available, dict):
                for item_id in available.keys():
                    if item_id and isinstance(item_id, str):
                        norm = item_id.strip().lower()
                        if norm:
                            acquired.add(norm)
        except Exception:
            pass

        return acquired

    def get_completed_quest_keys(self) -> Set[str]:
        """
        Returns a set of normalized lowercase snake_case quest IDs for all quests
        marked completed in this save file.
        Inspects:
          - self.quests.get("completed_quests", [])
          - self.quests.get("completion_timestamps", {}).keys()
          - self.gamedata.get("completed_quests", [])
        """
        completed: Set[str] = set()

        # 1. self.quests["completed_quests"]
        if hasattr(self, "quests") and isinstance(self.quests, dict):
            raw_cq = self.quests.get("completed_quests", [])
            if isinstance(raw_cq, (list, set, tuple)):
                for qid in raw_cq:
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)
            elif isinstance(raw_cq, dict):
                for qid in raw_cq.keys():
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)

            # 2. self.quests["completion_timestamps"]
            raw_ct = self.quests.get("completion_timestamps", {})
            if isinstance(raw_ct, dict):
                for qid in raw_ct.keys():
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)
            elif isinstance(raw_ct, (list, set, tuple)):
                for qid in raw_ct:
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)

        # 3. self.gamedata["completed_quests"]
        if hasattr(self, "gamedata") and isinstance(self.gamedata, dict):
            raw_gd = self.gamedata.get("completed_quests", [])
            if isinstance(raw_gd, (list, set, tuple)):
                for qid in raw_gd:
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)
            elif isinstance(raw_gd, dict):
                for qid in raw_gd.keys():
                    norm = _normalize_quest_key(str(qid))
                    if norm:
                        completed.add(norm)

        return completed

    def is_quest_completed(self, quest_name: str) -> bool:
        """Helper checking if a quest is marked completed in this save."""
        return is_quest_completed(quest_name, self.get_completed_quest_keys())

    def is_npc_present_in_town_today(self, npc_id: str) -> bool:
        """
        Returns True if the NPC is present in Mistria today.
        On Saturdays, unlocked NPCs (townsfolk + vendors) are in town.
        On Winter 10 (Animal Festival), unlocked townsfolk + Louis & Merri (if unlocked) are in town.
        On standard weekdays/Sundays, visiting vendors are off-map in Aldaria.
        Locked NPCs (not yet unlocked in player progression) are never present.
        """
        if self.npcs and not self.is_npc_unlocked(npc_id):
            return False

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

    def get_infused_items(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scans both player bag inventory and all chest inventories across locations
        for items with 'infusion' field set to 'lovable' or 'likable'.

        Returns:
            Dict[str, List[Dict[str, Any]]]: Guaranteed keys 'lovable' and 'likable'.
            Each value is a list of dictionaries:
                {"item_id": str, "count": int, "location": str}
            All items in a single stack share the same infusion.
            Duplicate stacks of the same item within the same location are aggregated (counts summed).
            Identical items in distinct locations remain separate entries.
            Lists are sorted deterministically by (item_id, location).
        """
        agg: Dict[Tuple[str, str, str], int] = {}

        # 1. Player bag inventory (location: "bag")
        bag_slots: List[Any] = []
        try:
            inv = self.inventory
            if isinstance(inv, list):
                bag_slots = inv
        except Exception:
            pass
        if not bag_slots and isinstance(getattr(self, "player", None), dict):
            inv = self.player.get("inventory")
            if isinstance(inv, list):
                bag_slots = inv

        for slot in bag_slots:
            item_id, count, infusion = _extract_slot_item_count_and_infusion(slot)
            if infusion in ("lovable", "likable") and item_id and count > 0:
                key = (infusion, item_id, "bag")
                agg[key] = agg.get(key, 0) + count

        # 2. Chest inventories across all world locations in raw_entries
        entries = self.raw_entries if isinstance(self.raw_entries, dict) else {}
        for loc_key, val_str in entries.items():
            if not isinstance(loc_key, str):
                continue
            loc_clean = loc_key.strip()
            if loc_clean.lower() in NON_LOCATION_KEYS:
                continue

            if isinstance(val_str, dict):
                loc_data = val_str
            elif isinstance(val_str, str):
                try:
                    loc_data = json.loads(val_str)
                except Exception:
                    continue
            else:
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
                    item_id, count, infusion = _extract_slot_item_count_and_infusion(slot)
                    if infusion in ("lovable", "likable") and item_id and count > 0:
                        key = (infusion, item_id, loc_clean)
                        agg[key] = agg.get(key, 0) + count

        # 3. Assemble structured return dictionary
        result: Dict[str, List[Dict[str, Any]]] = {
            "lovable": [],
            "likable": [],
        }

        for (infusion, item_id, location), total_count in agg.items():
            result[infusion].append({
                "item_id": item_id,
                "count": total_count,
                "location": location,
            })

        # 4. Deterministic sorting by (item_id, location)
        result["lovable"].sort(key=lambda x: (x["item_id"], x["location"]))
        result["likable"].sort(key=lambda x: (x["item_id"], x["location"]))

        return result

    def summary(self) -> str:
        date = self.in_game_date
        present_count = len(self.get_present_npcs_today())
        giftable_count = len(self.get_giftable_npcs_today(only_present=True))
        bag_items = len(self.get_bag_items())
        chest_items = len(self.get_chest_items())
        total_items = len(self.get_all_available_items())
        unlocked_count = len(self.get_unlocked_npc_ids()) or 34
        return (
            f"Save: {self.file_path.name}\n"
            f"Player: {self.player_name} @ {self.farm_name}\n"
            f"Date: {date}\n"
            f"Playtime: {self.playtime_hours:.1f} hours\n"
            f"Inventory: {self.empty_inventory_slots}/{self.total_inventory_slots} slots empty ({bag_items} unique items in bag)\n"
            f"Storage: {chest_items} unique items in chests across {len(self.get_chests_by_location())} locations (Total available: {total_items} unique)\n"
            f"NPCs Present Today: {present_count}/{unlocked_count} ({giftable_count} giftable today)"
        )


@dataclass
class CraftingStep:
    """Represents a single crafting or milling operation in a multi-step chain."""
    product_id: str
    product_name: str
    count: int
    ingredients: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CraftingPlan:
    """Result of evaluating the craftability of an item."""
    status: AvailabilityTier
    max_craftable: int
    raw_materials_needed: Dict[str, int] = field(default_factory=dict)
    steps: List[CraftingStep] = field(default_factory=list)
    chain_summary: str = ""
