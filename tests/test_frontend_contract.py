"""
tests/test_frontend_contract.py

Contract verification tests for the 100% client-side Pyodide web application.
Validates:
- web/index.html, web/style.css, web/app.js exist and meet size & content contracts.
- Complete absence of server /api/ endpoints and EventSource in web/app.js.
- Dual-state landing vs active layout with drop zone, demo button, OS paths, privacy notice.
- Client-side sprite alias dictionary containing key remaps (chocolate, baked_potato, cat_treat, miners_mushroom_stew).
- LocalStorage schema matching companion/config.py across all 15 settings.
- Web Worker postMessage protocol and error handling.
"""

from pathlib import Path
import re
import json
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
INDEX_HTML = WEB_DIR / "index.html"
STYLE_CSS = WEB_DIR / "style.css"
APP_JS = WEB_DIR / "app.js"
WORKER_JS = WEB_DIR / "planner.worker.js"


def test_frontend_files_exist_and_populated():
    """Verify all 3 core frontend files exist and are substantial in size."""
    assert INDEX_HTML.is_file(), "web/index.html does not exist"
    assert STYLE_CSS.is_file(), "web/style.css does not exist"
    assert APP_JS.is_file(), "web/app.js does not exist"

    assert INDEX_HTML.stat().st_size > 5000, f"web/index.html is unexpectedly small: {INDEX_HTML.stat().st_size} bytes"
    assert STYLE_CSS.stat().st_size > 20000, f"web/style.css is unexpectedly small: {STYLE_CSS.stat().st_size} bytes"
    assert APP_JS.stat().st_size > 50000, f"web/app.js is unexpectedly small: {APP_JS.stat().st_size} bytes"


def test_zero_api_endpoints_and_eventsource_in_app_js():
    """Verify absolute absence of /api/ server endpoints and EventSource in web/app.js."""
    content = APP_JS.read_text(encoding="utf-8")

    api_matches = re.findall(r"/api/[a-zA-Z0-9_/]+", content)
    assert len(api_matches) == 0, f"Found server /api/ endpoints in web/app.js: {api_matches}"

    es_matches = re.findall(r"\bEventSource\b", content)
    assert len(es_matches) == 0, f"Found EventSource occurrences in web/app.js: {es_matches}"

    # Also verify no residual /static/ or /assets/sprites/ paths
    static_matches = re.findall(r"/static/icons/[a-zA-Z0-9_/.-]+", content)
    assert len(static_matches) == 0, f"Found absolute /static/icons/ paths: {static_matches}"

    sprite_matches = re.findall(r"/assets/sprites/[a-zA-Z0-9_/.-]+", content)
    assert len(sprite_matches) == 0, f"Found absolute /assets/sprites/ paths: {sprite_matches}"


def test_welcome_landing_dom_contract():
    """Verify web/index.html contains all welcome landing and privacy elements."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    # Dual-state body class and container visibility
    assert 'class="mode-welcome"' in html or "mode-welcome" in html
    assert 'id="welcomeLanding"' in html
    assert 'class="layout-container"' in html

    # Pyodide WASM loading meter & progress bar
    assert 'id="pyodideStatusCard"' in html
    assert 'id="pyodideStatusDot"' in html
    assert 'id="pyodideStatusLabel"' in html
    assert 'id="pyodideStatusPct"' in html
    assert 'id="pyodideProgressBar"' in html

    # Drag & drop zone with browse fallback
    assert 'id="welcomeDropZone"' in html
    assert 'id="welcomeBrowseBtn"' in html
    assert 'id="welcomeFileInput"' in html

    # Try demo button
    assert 'id="welcomeDemoBtn"' in html

    # OS Save path instructions & copy buttons
    assert "%LOCALAPPDATA%Low/NPC Studio/FieldsOfMistria/saves/" in html
    assert "~/.local/share/Steam/steamapps/compatdata/2142790/pfx/drive_c/users/steamuser/AppData/LocalLow/NPC Studio/FieldsOfMistria/saves/" in html
    assert 'class="btn-copy-path"' in html

    # 100% Client-side privacy notices in landing and footer
    assert "100% Client-Side Privacy" in html or "100% local" in html.lower() or "never uploaded" in html.lower()
    assert "Save files are parsed locally in your browser" in html or "processed entirely inside your browser" in html


def test_active_planner_dom_elements():
    """Verify web/index.html retains all core active planner components and modals."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    # Header elements
    assert 'id="liveIndicator"' in html
    assert 'id="dateBadge"' in html
    assert 'id="playerFarmBadge"' in html
    assert 'id="errorBanner"' in html

    # 4-card statistics dashboard
    assert 'id="section-stats"' in html
    assert 'id="cardGiftProgress"' in html
    assert 'id="cardCompletedNpcs"' in html
    assert 'id="cardIncompleteNpcs"' in html
    assert 'id="cardRecipes"' in html

    # 3 Drawers
    assert 'id="drawerCompleted"' in html
    assert 'id="drawerIncomplete"' in html
    assert 'id="drawerRecipes"' in html

    # Main grids
    assert 'id="section-bag"' in html
    assert 'id="bagGrid"' in html
    assert 'id="section-focus"' in html
    assert 'id="focusGrid"' in html

    # Modals
    assert 'id="treeModal"' in html
    assert 'id="calendarModal"' in html
    assert 'id="recipeModal"' in html or 'id="drawerRecipes"' in html

    # Sidebar
    assert 'id="settingsAccordion"' in html
    assert 'id="refreshBtn"' in html
    assert 'id="saveStatusBox"' in html


def test_sprite_alias_dictionary_and_resolvers():
    """Verify sprite alias mapping contains key remaps and resolver functions."""
    js = APP_JS.read_text(encoding="utf-8")

    # Required remaps from dispatch & survey
    assert '"chocolate": "chocolate"' in js
    assert '"baked_potato": "bakedpotato"' in js
    assert '"cat_treat": "animal_treat_cat"' in js
    assert '"miners_mushroom_stew": "miner_mushroom_stew"' in js

    # Resolver functions
    assert "function resolveItemSprite(" in js
    assert "function resolveNpcPortrait(" in js
    assert "function resolveLocationIcon(" in js
    assert "function generatePlaceholderSvg(" in js

    # Extract ITEM_ID_TO_ASSET_NAME dictionary and verify substantial entry count
    dict_match = re.search(r"const ITEM_ID_TO_ASSET_NAME\s*=\s*(\{.*?\});", js, re.DOTALL)
    assert dict_match is not None, "Could not find ITEM_ID_TO_ASSET_NAME in web/app.js"
    dict_json_str = dict_match.group(1)
    # Parse as JSON or eval-safe dict
    remap_dict = json.loads(dict_json_str)
    assert len(remap_dict) >= 200, f"Expected >= 200 items in alias map, got {len(remap_dict)}"

    # Specific tests on item resolutions
    assert remap_dict["baked_potato"] == "bakedpotato"
    assert remap_dict["cat_treat"] == "animal_treat_cat"
    assert remap_dict["miners_mushroom_stew"] == "miner_mushroom_stew"
    assert remap_dict["deluxe_hay"] == "animal_feed_hay_deluxe"
    assert remap_dict["dog_treat"] == "animal_treat_dog"


def test_localstorage_schema_and_all_15_settings():
    """Verify localStorage key and all 15 settings keys are mapped with defaults matching companion/config.py."""
    js = APP_JS.read_text(encoding="utf-8")

    # LocalStorage key
    assert '"fom_companion_settings_v1"' in js

    # Extract DEFAULT_SETTINGS
    defaults_match = re.search(r"const DEFAULT_SETTINGS\s*=\s*(\{.*?\});", js, re.DOTALL)
    assert defaults_match is not None, "Could not find DEFAULT_SETTINGS in web/app.js"
    defaults = json.loads(defaults_match.group(1))

    expected_15_keys = {
        # Planning Core (10)
        "strategy",
        "mode",
        "slots",
        "date_override",
        "exclude_npcs",
        "force_all_npcs",
        "no_exclude_max_relationship",
        "loved_weight",
        "liked_weight",
        "vendor_boost",
        # Focus Suggestions (5)
        "focus_mode_enabled",
        "focus_npcs",
        "focus_sort",
        "all_seasons",
        "seasonal_boost",
    }

    assert set(defaults.keys()) == expected_15_keys, (
        f"Mismatch in 15 settings keys! Found: {set(defaults.keys())}, Missing: {expected_15_keys - set(defaults.keys())}"
    )

    # Check key default values
    assert defaults["strategy"] == "journal"
    assert defaults["mode"] == "auto"
    assert defaults["slots"] == 20
    assert defaults["focus_sort"] == "impact"
    assert defaults["loved_weight"] == 3
    assert defaults["liked_weight"] == 1
    assert defaults["vendor_boost"] == 1.5
    assert defaults["seasonal_boost"] == 2.0
    assert defaults["focus_mode_enabled"] is False
    assert defaults["force_all_npcs"] is False
    assert defaults["no_exclude_max_relationship"] is False


def test_worker_integration_in_app_js():
    """Verify Web Worker instantiation and message handling protocol in web/app.js."""
    js = APP_JS.read_text(encoding="utf-8")

    # Worker instantiation
    assert "new Worker('planner.worker.js')" in js or 'new Worker("planner.worker.js")' in js

    # Outgoing actions
    assert "'init'" in js or '"init"' in js
    assert "'plan'" in js or '"plan"' in js
    assert "'recompute'" in js or '"recompute"' in js

    # Incoming message actions
    assert '"progress"' in js
    assert '"ready"' in js
    assert '"result"' in js
    assert '"error"' in js


def test_style_css_rules():
    """Verify style.css includes dual-state view toggling and component styles."""
    css = STYLE_CSS.read_text(encoding="utf-8")

    # Dual-state display toggling
    assert "body.mode-welcome .layout-container" in css
    assert "body.mode-welcome #welcomeLanding" in css
    assert "body.mode-active #welcomeLanding" in css
    assert "body.mode-active .layout-container" in css

    # Welcome landing components
    assert ".welcome-dropzone" in css
    assert ".welcome-dropzone:hover" in css or ".welcome-dropzone.drag-over" in css
    assert ".pyodide-status-card" in css
    assert ".btn-keycap" in css
    assert ".btn-copy-path" in css
    assert ".paths-columns" in css

    # Game design tokens
    assert "--surface-plaque" in css
    assert "--border-outline" in css
    assert "--radius-plaque" in css
    assert "fnt_nosutaru.ttf" in css


def test_indexeddb_save_persistence_contract():
    """Verify IndexedDB client-side save persistence functions, DOM elements, and auto-restore wiring."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    # DOM elements for clearing / unloading save
    assert 'id="quickClearBtn"' in html

    # IndexedDB DB identifiers and keys
    assert "fom_gift_planner_db" in js
    assert "active_save" in js

    # IndexedDB storage functions
    assert "function openSaveDB(" in js
    assert "async function persistActiveSave(" in js
    assert "async function loadPersistedSave(" in js
    assert "async function clearPersistedSave(" in js
    assert "async function restorePersistedSave(" in js
    assert "async function unloadActiveSave(" in js

    # Reachability: Auto-restore called on DOMContentLoaded
    assert "restorePersistedSave();" in js

    # Reachability: Persist called in file handler and demo loader
    assert "await persistActiveSave(file.name, currentSaveBytes);" in js
    assert 'await persistActiveSave("sample_save.sav (Demo)", buf);' in js

    # Reachability: quickClearBtn wired to unloadActiveSave
    assert "unloadActiveSave();" in js

