"""
companion/server.py

FastAPI Web Server for Fields of Mistria Live Companion App.
Provides Server-Sent Events (SSE) push, REST APIs for plan/settings,
dynamic sprite discovery/fallback, and static asset serving.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from companion.config import (
    CompanionConfig,
    get_repo_root,
    get_settings_schema,
    load_companion_config,
    save_companion_config,
)
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan
from companion.watcher import SaveWatcher


class AppState:
    """Thread-safe application state container."""
    def __init__(self):
        self.repo_root: Path = get_repo_root()
        self.config: CompanionConfig = load_companion_config(self.repo_root)
        self.current_plan: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.sse_queues: Set[asyncio.Queue] = set()
        self.watcher: Optional[SaveWatcher] = None
        self._lock = asyncio.Lock()

    async def broadcast_event(self, event_type: str, data: Any = None):
        payload = json.dumps({"event": event_type, "data": data or {}})
        message = f"event: {event_type}\ndata: {payload}\n\n"
        dead_queues = set()
        for q in list(self.sse_queues):
            try:
                q.put_nowait(message)
            except Exception:
                dead_queues.add(q)
        self.sse_queues.difference_update(dead_queues)

    async def recompute_plan(self) -> Dict[str, Any]:
        async with self._lock:
            try:
                # Run the synchronous CPU/disk-bound planner in a separate thread
                save, plan_res, metadata, save_path = await asyncio.to_thread(
                    execute_plan, self.config, self.repo_root
                )
                exported = plan_to_json(save, plan_res, metadata, save_path, self.config)
                self.current_plan = exported
                self.last_error = None
            except Exception as e:
                err_msg = str(e)
                print(f"[Companion] Planner execution error: {err_msg}")
                self.last_error = err_msg
                self.current_plan = {
                    "error": err_msg,
                    "generated_at": None,
                    "bag_plan": [],
                    "focus_suggestions": [],
                    "npc_progress": {},
                    "stats": {},
                    "config": self.config.to_dict(),
                }

        await self.broadcast_event("plan_updated", self.current_plan)
        return self.current_plan


state = AppState()


async def handle_save_file_changed(changed_path: Path):
    print(f"[Companion] Triggering live re-plan for updated save: {changed_path.name}")
    await state.recompute_plan()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup:
    loop = asyncio.get_running_loop()
    state.watcher = SaveWatcher(
        loop=loop,
        on_change_coro_fn=handle_save_file_changed,
        explicit_save_path=state.config.save_file,
    )
    state.watcher.start()

    # Initial plan run
    print("[Companion] Running initial plan computation...")
    await state.recompute_plan()

    yield

    # Shutdown:
    if state.watcher:
        state.watcher.stop()


app = FastAPI(title="Fields of Mistria Live Companion", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/plan")
async def get_plan():
    """Returns the most recent calculated daily gift plan."""
    if not state.current_plan:
        await state.recompute_plan()
    return state.current_plan


@app.post("/api/plan/refresh")
async def refresh_plan():
    """Forces an immediate recalculation of the plan."""
    return await state.recompute_plan()


@app.get("/api/settings")
async def get_settings():
    """Returns current config values and UI schema."""
    return {
        "config": state.config.to_dict(),
        "schema": get_settings_schema(),
    }


@app.post("/api/settings")
async def update_settings(payload: Dict[str, Any]):
    """
    Updates one or more config parameters, persists to companion_config.json,
    and recalculates the plan with live push to connected clients.
    """
    old_save_file = state.config.save_file
    for k, v in payload.items():
        if hasattr(state.config, k):
            target_type = type(getattr(state.config, k))
            if v is None:
                setattr(state.config, k, None)
            elif target_type is bool:
                setattr(state.config, k, bool(v))
            elif target_type is int:
                try:
                    setattr(state.config, k, int(v))
                except (ValueError, TypeError):
                    pass
            elif target_type is float:
                try:
                    setattr(state.config, k, float(v))
                except (ValueError, TypeError):
                    pass
            else:
                setattr(state.config, k, str(v).strip())

    save_companion_config(state.config, state.repo_root)

    # If save_file setting changed, update the watcher
    if state.config.save_file != old_save_file and state.watcher:
        state.watcher.update_watch_target(state.config.save_file)

    # Re-run plan with new config
    updated_plan = await state.recompute_plan()
    return {"success": True, "config": state.config.to_dict(), "plan": updated_plan}


@app.get("/api/events")
async def sse_events(request: Request):
    """
    Server-Sent Events endpoint. Streams live notifications when saves update
    or settings change.
    """
    queue: asyncio.Queue = asyncio.Queue()
    state.sse_queues.add(queue)

    async def event_generator():
        try:
            # Send initial hello ping
            yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            state.sse_queues.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Sprite and Asset Delivery (with graceful SVG fallback)
# ---------------------------------------------------------------------------

_ITEM_ID_TO_ASSET_NAME: Dict[str, str] = {
    # 1. Treats & Pet Feed
    "cat_treat": "animal_treat_cat",
    "dog_treat": "animal_treat_dog",
    "deluxe_hay": "animal_feed_hay_deluxe",
    "quality_hay": "animal_feed_hay_quality",
    "ultimate_hay": "animal_feed_hay_ultimate",
    "deluxe_small_animal_feed": "animal_feed_seed_deluxe",
    "quality_small_animal_feed": "animal_feed_seed_quality",
    "ultimate_small_animal_feed": "animal_feed_seed_ultimate",

    # 2. Food & Cooking
    "miners_mushroom_stew": "miner_mushroom_stew",
    "crayfish": "dive_crayfish",
    "golden_egg": "chicken_egg_gold",
    "egg": "chicken_egg_regular",
    "duck_egg": "duck_egg_regular",
    "golden_duck_egg": "duck_egg_gold",
    "cow_milk": "cow_milk_regular",
    "golden_cow_milk": "cow_milk_gold",

    # 3. Animal Products
    "golden_feather": "chicken_feather_gold",
    "feather": "chicken_feather_regular",
    "golden_duck_feather": "duck_feather_gold",
    "duck_feather": "duck_feather_regular",
    "alpaca_wool": "alpaca_wool_regular",
    "golden_alpaca_wool": "alpaca_wool_gold",
    "bristle": "capybara_bristle_regular",
    "golden_bristle": "capybara_bristle_gold",
    "horse_hair": "horse_hair_regular",
    "golden_horse_hair": "horse_hair_gold",
    "rabbit_wool": "rabbit_hair_regular",
    "golden_rabbit_wool": "rabbit_hair_gold",
    "sheep_wool": "sheep_wool_regular",
    "golden_sheep_wool": "sheep_wool_gold",
    "bull_horn": "cow_horn_regular",
    "golden_bull_horn": "cow_horn_gold",

    # 4. Plants, Trees, Forage, Farming
    "sapling_oak": "oak_sapling",
    "sapling_pine": "pine_sapling",
    "sapling_cherry": "cherry_sapling",
    "sapling_lemon": "lemon_sapling",
    "wood": "regularwood",
    "basic_wood": "regularwood",
    "wild_grapes": "bush_grape",
    "bell_berry": "bush_bell_berry",
    "blackberry": "bush_blackberry",
    "blueberry": "bush_blueberry",
    "glowberry": "bush_glowberry",
    "hydrangea": "bush_hydrangea",
    "rose_hip": "bush_rosehip",
    "wild_berries": "bush_wildberry",
    "wintergreen_berry": "bush_wintergreen",
    "breath_of_fire": "breath_of_flame",
    "dandelion": "dandelionflower",
    "middlemist": "middlemistred",
    "wild_leek": "springonion",
    "grass_seed": "small_grass_starter",
    "hay": "hayball",
    "haydens_weathervane": "weathervane",
    "lava_chestnuts": "lava_chestnut",
    "seed_mystery_bag": "bagseed_mystery_bag_icon",

    # 5. Ores, Stones & Minerals
    "ore_stone": "rock",
    "ore_copper": "copper_ore",
    "ore_iron": "iron_ore",
    "ore_gold": "gold_ore",
    "ore_silver": "silver_ore",
    "ore_mistril": "mistril_ore",
    "ore_ruby": "ruby",
    "ore_sapphire": "sapphire",
    "ore_emerald": "emerald",
    "ore_diamond": "diamond",
    "ore_pink_diamond": "pinkdiamond",

    # 6. Diving & Shells
    "blue_conch_shell": "shell_small_blue_conch",
    "pink_scallop_shell": "shell_pink_scallop",
    "sand_dollar": "shell_sand_dollar",
    "spirula_shell": "shell_common_spirula",
    "clam": "dive_clam",
    "freshwater_oyster": "dive_freshwater_oyster",
    "newt": "dive_newt",
    "river_snail": "dive_pond_snail",
    "seaweed": "dive_seaweed",

    # 7. Fish
    "sardine": "fish_small_sardine",
    "salmon": "fish_large_salmon",
    "trout": "fish_medium_trout",
    "tuna": "fish_large_tuna",
    "bonito": "fish_medium_bonito",
    "bream": "fish_large_bream",
    "catfish": "fish_medium_catfish",
    "cod": "fish_large_cod",
    "goby": "fish_medium_goby",
    "perch": "fish_large_perch",
    "pike": "fish_large_pike",
    "squid": "fish_medium_squid",
    "tilapia": "fish_small_tilapia",
    "turtle": "fish_large_turtle",
    "red_snapper": "fish_large_red_snapper",
    "sea_bream": "fish_medium_sea_bream",
    "shrimp": "fish_small_shrimp",
    "archerfish": "fish_small_archerfish",
    "coelacanth": "fish_large_coelacanth",
    "herring": "fish_small_herring",
    "mackerel": "fish_large_mackerel",
    "mullet": "fish_medium_mullet",
    "tetra": "fish_small_tetra",
    "armored_bass": "fish_medium_armored_bass",
    "bullfrog": "fish_small_bullfrog",
    "cave_shrimp": "fish_small_cave_shrimp",
    "crab": "fish_small_crab",
    "firesail_fish": "fish_large_firesail_fish",
    "freshwater_eel": "fish_medium_freshwater_eel",
    "frog": "fish_small_frog",
    "king_crab": "fish_large_king_crab",
    "lake_trout": "fish_large_lake_trout",
    "lobster": "fish_medium_lobster",
    "luminescent_crab": "fish_medium_luminescent_crab",
    "sapphire_betta": "fish_small_sapphire_betta",
    "smallmouth_bass": "fish_small_smallmouth_bass",
    "stone_loach": "fish_medium_stone_loach",
    "striped_bass": "fish_large_striped_bass",

    # 8. Bugs & Critters
    "lightning_dragonfly": "insect_lightningdragonfly",
    "hummingbird_hawk_moth": "insect_hummingbirdhawkmoth",
    "rhinoceros_beetle": "insect_rhinocerosbeetle",
    "crystalline_cricket": "insect_crystalline_cricket",
    "ant": "insect_ant",
    "ancient_firefly": "insect_ancient_firefly",
    "bumblebee": "insect_bumblebee",
    "butterfly": "insect_butterfly",
    "caterpillar": "insect_caterpillar",
    "cicada": "insect_cicada",
    "copper_beetle": "insect_copper_beetle",
    "coral_mantis": "insect_coral_mantis",
    "cricket": "insect_cricket",
    "crystal_caterpillar": "insect_crystalcaterpillar",
    "crystal_wing_moth": "insect_crystal_wing_moth",
    "deep_earthworm": "insect_deep_earthworm",
    "dragon_horn_beetle": "insect_dragon_horn_beetle",
    "fairy_bee": "insect_fairybee",
    "fire_wasp": "insect_fire_wasp",
    "firefly": "insect_firefly",
    "fuzzy_moth": "insect_fuzzymoth",
    "grasshopper": "insect_grasshopper",
    "hermit_crab": "insect_hermitcrab",
    "inchworm": "insect_inchworm",
    "jewel_beetle": "insect_jewelbeetle",
    "ladybug": "insect_ladybug",
    "lantern_moth": "insect_lantern_moth",
    "mistmoth": "insect_mistmoth",
    "monarch_butterfly": "insect_monarchbutterfly",
    "orchid_mantis": "insect_orchidmantis",
    "pond_skater": "insect_pondskater",
    "praying_mantis": "insect_prayingmantis",
    "puddle_spider": "insect_puddle_spider",
    "question_mark_butterfly": "insect_questionmarkbutterfly",
    "roly_poly": "insect_pillbug",
    "sea_scarab": "insect_sea_scarab",
    "singing_katydid": "insect_singing_katydid",
    "smoke_moth": "insect_smoke_moth",
    "snail": "insect_snail",
    "snowball_beetle": "insect_snowballbeetle",
    "strobe_firefly": "insect_strobefirefly",
    "void_snail": "insect_void_snail",
    "worm": "insect_worm",

    # 9. Tools & Wearables
    "axe_silver": "tool_silver_axe",
    "net_copper": "tool_copper_net",
    "shovel_copper": "tool_copper_shovel",
    "shovel_iron": "tool_iron_shovel",
    "sword_corrupted_mistril": "tool_corrupted_mistril_sword",
    "sword_silver": "tool_silver_sword",
    "watering_can_iron": "tool_iron_watering_can",
    "iron_armor": "wearable_top_iron_armor",

    # 10. Placeables & Misc
    "animal_currency": "currency",
    "shiny_bead": "shiny_bead",
    "spooky_haybale": "decor_spooky_haybale",
    "starter_bird_house_red": "decor_starter_bird_house_red",
    "starter_potted_plant": "decor_starter_potted_plant",
    "starter_scarecrow": "decor_starter_scarecrow",
    "starter_shipping_box": "basic_misc_shipping_bin",
    "starter_wood_fence": "decor_starter_wood_fence",

    # 11. Additional location/season item aliases
    "stone": "rock",
    "milk": "cow_milk_regular",
    "golden_milk": "cow_milk_gold",
    "cattail_fluff": "cattail",
    "alligator_gar": "fish_giant_alligator_gar",
    "anchovy": "fish_small_anchovy",
    "angel_fish": "fish_small_angel_fish",
    "barb": "fish_small_barb",
    "bluefish": "fish_large_bluefish",
    "bluegill": "fish_small_blue_gill",
    "bowfish": "fish_large_bowfish",
    "brown_bullhead": "fish_medium_brown_bullhead",
    "brown_trout": "fish_large_brown_trout",
    "burbot": "fish_large_burbot",
    "carp": "fish_medium_carp",
    "cave_eel": "fish_medium_cave_eel",
    "chum": "fish_large_chum",
    "chum_salmon": "fish_large_chum",
    "diamond_beetle": "insect_diamond_beetle",
    "dragonfly": "insect_lightningdragonfly",
    "earth_eel": "fish_medium_earth_eel",
    "flathead_catfish": "fish_medium_flathead_catfish",
    "forest_perch": "fish_medium_forest_perch",
    "gar": "fish_large_gar",
    "gazer": "fish_small_gazer",
    "giant_jellyfish": "fish_large_giant_jellyfish",
    "giant_worm": "insect_giant_worm",
    "grayling": "fish_small_grayling",
    "horse_mackerel": "fish_small_horse_mackerel",
    "koi": "fish_medium_koi",
    "minnow": "fish_small_minnow",
    "muskie": "fish_large_muskie",
    "paper_pond_shell": "dive_paper_pondshell",
    "paper_pond_snail": "dive_pond_snail",
    "parchment_moth": "insect_parchment_moth",
    "pea": "peas",
    "snow_pea": "snow_peas",
    "pearl_clam": "dive_pearl_clam",
    "pollock": "fish_large_pollock",
    "pond_snail": "dive_pond_snail",
    "puffer_fish": "fish_medium_puffer_fish",
    "radish": "daikon_radish",
    "rainbow_trout": "fish_medium_rainbow_trout",
    "roach": "fish_medium_roach",
    "rock_bass": "fish_medium_rock_bass",
    "sea_bass": "fish_medium_sea_bass",
    "sea_urchin": "fish_small_sea_urchin",
    "shadow_bass": "fish_medium_shadow_bass",
    "silver_redhorse": "fish_medium_silver_redhorse",
    "snakehead": "fish_large_snakehead",
    "snapping_turtle": "fish_large_snapping_turtle",
    "sturgeon": "fish_large_sturgeon",
    "sulfur_crab": "fish_medium_sulfur_crab",
    "sunny": "fish_small_sunny",
    "swallowtail_butterfly": "insect_tigerswallowtailbutterfly",
    "swordfish": "fish_large_swordfish",
    "walleye": "fish_large_walleye",
    "white_perch": "fish_medium_white_perch",
    "winged_shrimp": "fish_small_winged_shrimp",
    "octopus": "fish_large_octopus",
    "lava_piranha": "fish_small_lava_piranha",
    "mantis": "insect_prayingmantis",
    "yellow_perch": "fish_large_perch",
}


def _find_local_icon(kind: str, item_id: str) -> Optional[Path]:
    """
    Locates a project-local icon in companion/static/icons/{kind}/.
    Applies the resolution strategies:
      1. Exact match (spr_ui_item_{id}.png, spr_ui_generic_icon_npc_{id}.png, spr_ui_item_sub_npc_{id}.png)
      2. No-underscore match
      3. Manual remap (for items)
    """
    clean_kind = kind.strip().lower()
    clean_id = item_id.strip().lower()
    icons_root = Path(__file__).resolve().parent / "static" / "icons"

    if clean_kind in ("items", "item"):
        items_dir = icons_root / "items"
        if not items_dir.exists():
            return None

        candidates = [
            items_dir / f"spr_ui_item_{clean_id}.png",
            items_dir / f"spr_ui_item_{clean_id.replace('_', '')}.png",
        ]
        if clean_id in _ITEM_ID_TO_ASSET_NAME:
            remapped = _ITEM_ID_TO_ASSET_NAME[clean_id]
            candidates.append(items_dir / f"spr_ui_item_{remapped}.png")
            candidates.append(items_dir / f"spr_ui_item_{remapped.replace('_', '')}.png")

        for c in candidates:
            if c.is_file():
                return c

    elif clean_kind in ("npcs", "npc"):
        npcs_dir = icons_root / "npcs"
        if not npcs_dir.exists():
            return None

        candidates = [
            npcs_dir / f"spr_ui_generic_icon_npc_{clean_id}.png",
            npcs_dir / f"spr_ui_generic_icon_npc_{clean_id.replace('_', '')}.png",
            npcs_dir / f"spr_ui_item_sub_npc_{clean_id}.png",
            npcs_dir / f"spr_ui_item_sub_npc_{clean_id.replace('_', '')}.png",
            npcs_dir / f"{clean_id}.png",
        ]
        for c in candidates:
            if c.is_file():
                return c

    return None


def generate_placeholder_svg(label: str, kind: str = "item") -> str:
    """Generates an attractive SVG placeholder for items or NPCs."""
    initials = "".join([w[0] for w in label.replace("_", " ").split()[:2]]).upper() or "?"
    bg_color = "#8b6055" if kind == "npc" else "#5a7a5e"
    accent = "#f5ead8"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <rect width="48" height="48" rx="8" fill="{bg_color}" />
  <rect x="2" y="2" width="44" height="44" rx="6" fill="none" stroke="{accent}" stroke-width="2" stroke-opacity="0.4" />
  <text x="24" y="28" font-family="'Segoe UI', -apple-system, sans-serif" font-weight="bold" font-size="16" fill="{accent}" text-anchor="middle" dominant-baseline="central">{initials}</text>
</svg>"""


@app.get("/assets/sprites/{kind}/{item_id}")
async def get_sprite(kind: str, item_id: str):
    """
    Attempts to locate real game sprite:
    1. Project-local static icons in companion/static/icons/{kind}/
    2. Configured external game_assets_dir
    3. Inline generated SVG fallback
    """
    item_clean = item_id.strip().lower()

    # 1. First priority: Check project-local static icons
    local_icon = _find_local_icon(kind, item_clean)
    if local_icon and local_icon.is_file():
        return FileResponse(local_icon)

    # 2. Second priority: External game_assets_dir probe
    if state.config.game_assets_dir:
        assets_path = Path(state.config.game_assets_dir).expanduser()
        if assets_path.exists():
            # Potential filenames
            candidates = [
                assets_path / f"{item_clean}.png",
                assets_path / f"spr_{item_clean}.png",
                assets_path / f"spr_ui_{item_clean}.png",
                assets_path / f"spr_ui_item_{item_clean}.png",
                assets_path / "items" / f"{item_clean}.png",
                assets_path / "animations" / "items" / f"{item_clean}.png",
                assets_path / "sprites" / f"{item_clean}.png",
                assets_path / "npcs" / f"{item_clean}.png",
                assets_path / "portraits" / f"{item_clean}.png",
            ]
            for c in candidates:
                if c.exists() and c.is_file():
                    return FileResponse(c)

    # 3. Third priority: Inline SVG placeholder fallback
    svg_data = generate_placeholder_svg(item_clean, kind)
    return Response(content=svg_data, media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# Frontend Static Files & Index
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Companion UI is compiling... Please refresh shortly.</h1>")


# ---------------------------------------------------------------------------
# CLI Launcher
# ---------------------------------------------------------------------------

def launch():
    """Entry point for fom-companion script."""
    import uvicorn

    repo_root = get_repo_root()
    config = load_companion_config(repo_root)

    host = config.server_host or "127.0.0.1"
    port = config.server_port or 8000

    print("=" * 70)
    print("🌾 FIELDS OF MISTRIA — LIVE COMPANION SERVER")
    print(f"📡 Serving at: http://{host}:{port}")
    print("👀 Live Save Watcher active (auto-refreshes on every save)")
    print("=" * 70)

    uvicorn.run("companion.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    launch()
