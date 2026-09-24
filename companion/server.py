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
    Attempts to locate real game sprite in configured game_assets_dir.
    Falls back to inline generated SVG if not found or dir not configured.
    """
    item_clean = item_id.strip().lower()

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
