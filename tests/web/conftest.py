"""
tests/e2e/conftest.py

Shared pytest fixtures, synthetic save data builders, path resolvers,
and decoupled test adapters for the 4-Tier E2E test suite.
"""

import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
import zlib

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"
SAMPLES_DIR = REPO_ROOT / "samples"
SAMPLE_SAVE_PATH = SAMPLES_DIR / "sample_save.sav"
WEB_SAMPLE_SAVE_PATH = REPO_ROOT / "web" / "sample_save.sav"
WEB_BRIDGE_PATH = REPO_ROOT / "web" / "py" / "web_bridge.py"


def get_web_bridge():
    """
    Dynamically loads web/py/web_bridge.py if present.
    Returns module or None if not yet created.
    """
    if WEB_BRIDGE_PATH.exists():
        try:
            spec = importlib.util.spec_from_file_location("web_bridge", WEB_BRIDGE_PATH)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except Exception:
            pass
    return None


def make_synthetic_save_bytes(
    player_name: str = "TestHero",
    farm_name: str = "SunnyFarm",
    year: int = 1,
    season: str = "spring",  # spring, summer, autumn, winter
    day: int = 1,
    clock_time_str: str = "06:00",
    inventory_items: Optional[List[Dict[str, Any]]] = None,
    npc_affection: Optional[Dict[str, float]] = None,
    unlocked_recipes: Optional[List[str]] = None,
    infused_items: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Constructs binary FoM .sav bytes with zlib compression and little-endian
    length-prefixed entry blocks.
    """
    season_indices = {"spring": 0, "summer": 1, "autumn": 2, "fall": 2, "winter": 3}
    s_idx = season_indices.get(season.lower(), 0)

    # FoM calendar_time: 86400 seconds per day, 28 days per season, 112 days per year
    total_days = ((year - 1) * 112) + (s_idx * 28) + (day - 1)
    calendar_time = total_days * 86400

    parts = clock_time_str.split(":")
    hours = int(parts[0]) if len(parts) > 0 else 6
    minutes = int(parts[1]) if len(parts) > 1 else 0
    clock_time = hours * 3600 + minutes * 60

    header_dict = {
        "name": player_name,
        "farm_name": farm_name,
        "calendar_time": calendar_time,
        "clock_time": clock_time,
        "playtime": 3600.0 * 5,
    }

    inv_list = []
    if inventory_items:
        for it in inventory_items:
            item_id = it.get("item_id", "turnip")
            count = it.get("count", 1)
            infusion = it.get("infusion")
            inv_list.append({
                "count": count,
                "item": {
                    "item_id": item_id,
                    "cosmetic": None,
                    "infusion": infusion,
                },
                "required_tags": [],
            })

    player_dict = {
        "name": player_name,
        "farm_name": farm_name,
        "inventory": inv_list,
    }

    npcs_dict = {}
    default_town_npcs = [
        "adeline", "balor", "caldarus", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis", "luc",
        "maple", "march", "merri", "nora", "olric", "priestess", "reina", "ryis", "seridia", "stillwell",
        "taliferro", "terithia", "valen", "vera", "wheedle", "zorel",
    ]
    for nid in default_town_npcs:
        npcs_dict[nid] = {
            "heart_points": 0.0,
            "affection": 0.0,
            "gift_flag": True,
        }

    if npc_affection:
        for npc_id, aff in npc_affection.items():
            if isinstance(aff, dict):
                npcs_dict[npc_id] = aff
            else:
                try:
                    num_aff = float(aff)
                except (ValueError, TypeError):
                    num_aff = aff
                entry = npcs_dict.get(npc_id, {})
                entry["heart_points"] = num_aff
                entry["affection"] = num_aff
                entry.setdefault("gift_flag", True)
                npcs_dict[npc_id] = entry

    gamedata_dict: Dict[str, Any] = {"date": calendar_time}
    if unlocked_recipes is not None:
        gamedata_dict["unlocked_recipes"] = unlocked_recipes

    raw_blocks: Dict[str, str] = {
        "header": json.dumps(header_dict),
        "player": json.dumps(player_dict),
        "npcs": json.dumps(npcs_dict),
        "gamedata": json.dumps(gamedata_dict),
        "game_stats": json.dumps({}),
        "quests": json.dumps({}),
        "info": json.dumps({}),
    }

    body = bytearray()
    body.extend(struct.pack("<Q", len(raw_blocks)))
    for key, val_str in raw_blocks.items():
        kb = key.encode("utf-8")
        vb = val_str.encode("utf-8")
        body.extend(struct.pack("<Q", len(kb)))
        body.extend(kb)
        body.extend(struct.pack("<Q", len(vb)))
        body.extend(vb)

    return zlib.compress(bytes(body))


def execute_plan_e2e(
    save_data: Union[bytes, str, Path],
    config: Optional[Dict[str, Any]] = None,
    filename: str = "upload.sav",
) -> Tuple[str, Dict[str, Any]]:
    """
    Executes a plan via web_bridge if available, or reference companion bridge as oracle.
    Returns (raw_json_string, parsed_plan_dict).
    """
    bridge = get_web_bridge()
    if bridge and hasattr(bridge, "generate_plan"):
        raw_json = bridge.generate_plan(save_data, config, filename)
        parsed = json.loads(raw_json)
        return raw_json, parsed

    # Fallback to reference engine oracle
    from companion.planner_bridge import execute_plan
    from companion.json_exporter import plan_to_json
    from companion.config import CompanionConfig

    tmp_file = None
    if isinstance(save_data, bytes):
        tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
        tmp.write(save_data)
        tmp.flush()
        tmp.close()
        save_path = Path(tmp.name)
        tmp_file = save_path
    elif isinstance(save_data, (str, Path)):
        save_path = Path(save_data).resolve()
    else:
        raise ValueError(f"Unsupported save_data type: {type(save_data)}")

    try:
        conf_obj = CompanionConfig()
        conf_obj.save_file = str(save_path)
        if config:
            for k, v in config.items():
                if hasattr(conf_obj, k):
                    setattr(conf_obj, k, v)

        save, results, meta, _ = execute_plan(conf_obj, repo_root=REPO_ROOT)
        plan_dict = plan_to_json(save, results, meta, save_path, conf_obj)
        raw_json = json.dumps(plan_dict, default=str)
        return raw_json, plan_dict
    finally:
        if tmp_file and tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def sample_save_path() -> Path:
    assert SAMPLE_SAVE_PATH.exists(), f"Missing sample save at {SAMPLE_SAVE_PATH}"
    return SAMPLE_SAVE_PATH


@pytest.fixture(scope="session")
def sample_save_bytes(sample_save_path) -> bytes:
    with open(sample_save_path, "rb") as f:
        return f.read()


@pytest.fixture
def default_config() -> Dict[str, Any]:
    return {
        "strategy": "journal",
        "mode": "auto",
        "slots": 20,
        "focus_sort": "impact",
        "all_seasons": False,
        "loved_weight": 3,
        "liked_weight": 1,
        "vendor_boost": 1.5,
        "seasonal_boost": 2.0,
        "focus_mode_enabled": False,
        "focus_npcs": "",
        "exclude_npcs": "",
        "force_all_npcs": False,
        "max_relationship_points": None,
        "no_exclude_max_relationship": False,
    }


@pytest.fixture
def synthetic_save_builder():
    return make_synthetic_save_bytes


@pytest.fixture
def plan_executor():
    return execute_plan_e2e
