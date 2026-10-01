# Fields of Mistria — Daily Gift Bag Planner & Rankings Analyzer

A standalone, dependency-free tool that optimizes your daily gift loadout in **[Fields of Mistria](https://store.steampowered.com/app/2142790/Fields_of_Mistria/)**.

It inspects your game save file (`.sav`), tracks remaining ungifted items for each NPC, scans both your backpack and farm storage chests, and uses a greedy weighted set-cover algorithm with recursive crafting resolution to calculate the **optimal set of items to carry in your bag**—maximizing NPC coverage and affection while minimizing inventory slots used.

---

## Key Features

- **Dual Planning Strategies (`--strategy`)**:
  - **Journal Completion (`journal`, default)**: Prioritizes discovering and checking off remaining unrecorded gift preferences in your journal.
  - **Max Relationship (`max-relationship`)**: Maximizes daily relationship points (+20 for Loved, +10 for Liked) across all available characters using a strict 5-tier priority hierarchy and Most-Constrained Variable (MRV) greedy allocation to prevent item starvation.
- **Cooking Perk Infused Items Detection**:
  - Scans both player backpack and all farm/world storage chests for cooking perk infused dishes (`lovable` and `likable`).
  - Lovable dishes act as universal loves (+20 pts) and likable dishes act as universal likes (+10 pts) for any eligible character.
- **Max Relationship Cap & Auto-Exclusion**:
  - Detects characters who have reached maximum affection (default: 1,755 heart points / 10 hearts).
  - Automatically excludes maxed NPCs from the daily gift loadout to conserve items and inventory slots, with configurable thresholds (`--max-relationship-points`) and optional override (`--no-exclude-max-relationship`).
- **Save File Inspection**: Reads uncompressed or compressed binary `.sav` files directly. Detects in-game date, time, season, bag inventory, and all farm/world storage chests.
- **Saturday Market & Progression Awareness**:
  - Mistria's Saturday Market features up to 8 visiting vendors, unlocked as the town progresses:
    - **Base Market (4 vendors)**: *Darcy, Louis, Merri, Vera*
    - **Upgrade 1 (`upgrade_the_saturday_market`, +2 vendors)**: *Taliferro, Wheedle*
    - **Upgrade 2 (`upgrade_the_saturday_market_plaza`, +2 vendors)**: *Stillwell, Zorel*
  - Story-gated permanent townsfolk (*Caldarus, Seridia*) unlock through mine progression.
  - When inspecting your save file, the planner detects which vendors and townsfolk you have unlocked, dynamically calculates counts (e.g. 24 townsfolk + 4 vendors), excludes locked characters from today's bag plan, and alerts you to locked NPCs.
  - Forward-looking **Focus Suggestions** still include pending gifts for locked NPCs so you can prepare rare materials in advance.
- **Recursive DAG Crafting & Material Deduction**:
  - Evaluates whether unowned items can be crafted or cooked from materials in your chests or bag.
  - Status badges: `📦 HAVE` (in bag/chests) > `✅ CRAFT` (craftable) > `❌ NEED` (need to gather/buy).
  - Dynamically deducts shared ingredients (e.g. flour, milk, sugar) so recipes never double-count materials.
- **Configurable Focus Suggestions (`--focus-sort`)**:
  - Pinpoints top blocker raw materials (crops, animal products, forageables) to guide your daily farming and gathering tasks.
  - Supports 3 ranking criteria:
    - `impact` (default): Prioritizes items gating the highest number of NPC gifts across town.
    - `deficit`: Prioritizes items with the largest overall deficit/shortage in your storage.
    - `quick-wins`: Prioritizes items closest to completion (smallest deficit first) for immediate gift unlocks.
- **Focus Crafting Trees & Downstream Dependency Breakdown**:
  - Automatically calculates downstream crafting dependencies for top blocker items (e.g. `milk` → `cheese`, `wood` → `wooden_chest`).
  - Displays recipient NPCs unlocked by each downstream craft and indicates required crafting stations (Kitchen, Mill, Crafting Bench, Smelter).
  - Visualized as interactive tree nodes in the Web Companion UI.
- **Alternate Acquisition Sources (`data/alt_sources.json`)**:
  - Maps items and ingredients to alternate acquisition paths: shops (Balor's Wagon, General Store, Hayden's Ranch, Tack Shop, Sleeping Dragon Inn), Saturday Market stalls, Chicken Statue offerings, Wishing Well wishes, Mining chests & Mimics, Mill processing, Fishing, Quests, Museum rewards, Festivals, and Living off the Land Farming perk bonus drops.
  - Badges indicate vendor/source, buy cost, currency (`tesserae` vs `shiny_beads`), and special availability notes.
- **Zero External Core Dependencies**: The core optimization engine runs entirely on standard Python 3.10+.

---

## Requirements

- **Python 3.10 or newer**
- Recommended: **[uv](https://docs.astral.sh/uv/)** for fast, reproducible dependency and environment management:
  ```bash
  # Install dependencies and sync environment
  uv sync
  ```

---

## Quick Start

### 1. Launch Live Companion Web App (Auto-Updates When You Save!)

Run the companion on your second monitor or in the background while playing Fields of Mistria on Windows or Linux:

```bash
# Start companion server
uv run fom-companion
# or: python main.py
```

Then open **[http://localhost:8000](http://localhost:8000)** in any browser.

- 📡 **Instant Live Sync**: Uses Server-Sent Events (SSE) and watchdog to automatically update the gift plan the moment you save or sleep in-game.
- 📂 **Save File Picker & Direct Upload**: Browse and select from auto-detected saves or upload any `.sav` file directly through the web UI without manual file paths.
- 🎒 **Optimal Daily Bag Cards**: Shows item status (`📦 HAVE`, `✅ CRAFT`, `❌ NEED`), quantities, pixel-art item sprites, and recipient NPC avatar chips.
- 🌾 **Focus Suggestions & Interactive Crafting Trees**: Pinpoints top blocker raw materials to gather or plant today, with expandable downstream crafting trees and vendor/alternate-source badges.
- ⚙️ **All Parameters Configurable**: Change strategy (`journal` vs `max-relationship`), bag slot budget, date overrides, scoring multipliers, or NPC exclusions directly from the sidebar.
- 🪟 **Cross-Platform & Windows Optimized**: Supports Windows filesystem semantics, atomic save rename handling, and Proton/Steam Deck/Linux save detection.

### 2. Client-Side Static Web App

A 100% client-side web version runs directly in the browser via Pyodide WebAssembly in `web/index.html` (deployable to GitHub Pages).

---

## Save File Locations

Fields of Mistria save files (`.sav`) are located at:

- **Windows**:
  ```
  %LOCALAPPDATA%\FieldsOfMistria\saves\
  ```
  *(Press `Win + R`, paste the path above, and press Enter)*

- **Linux / Steam Deck (Proton)**:
  ```
  ~/.steam/steam/steamapps/compatdata/2142790/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria/saves/
  ~/.local/share/Steam/steamapps/compatdata/2142790/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria/saves/
  ```

- **Linux (Native, Snap, & Flatpak Steam)**:
  ```
  ~/.local/share/FieldsOfMistria/saves/
  ~/snap/steam/common/.local/share/FieldsOfMistria/saves/
  ~/.var/app/com.valvesoftware.Steam/.local/share/FieldsOfMistria/saves/
  ```

---

## Companion Configuration & Features

All planner features are dynamically controlled through the companion web interface:

| Setting | Choices / Default | Description |
|---|---|---|
| **Save File** | Auto-detect or file upload | Select an existing save or drop in a new `.sav` file. |
| **Strategy** | `journal` / `max-relationship` | Optimization strategy: `journal` targets unrecorded preferences; `max-relationship` maximizes daily friendship points gained across all characters. |
| **Mode** | `auto`, `saturday`, `market-only`, `townsfolk`, `all` | Planning mode: `auto` uses save day; `saturday` plans for market day; `market-only` targets visiting vendors; `townsfolk` targets permanent residents; `all` plans all eligible NPCs. |
| **Bag Slots Budget** | Integer (default: `20`) | Maximum backpack slots budgeted for gift items. |
| **Max Relationship Cap** | 1,755 points / 10 hearts | Characters at max relationship are automatically excluded unless disabled in settings. |
| **Date Override** | Day number, season name, or festival | Simulate future dates (e.g. `saturday`, `winter 10` for Animal Festival) without advancing your game save. |
| **Focus Sort** | `impact`, `deficit`, `quick-wins` | Ranking criteria for focus suggestions: `impact` (most blocked gifts first), `deficit` (largest missing count first), or `quick-wins` (closest to completion first). |
| **NPC Exclusions** | Selection list | Exclude specific NPCs from planning. |

---

## Project Structure

```
fom-gift-planner/
├── README.md                 # Project documentation
├── pyproject.toml            # Project metadata and dependencies
├── uv.lock                   # Deterministic lockfile for uv
├── main.py                   # Primary entry point (launches companion server)
│
├── fom_planner/              # Core optimization and domain package
│   ├── __init__.py           # Public API exports
│   ├── constants.py          # Vendors, festivals, and availability tiers
│   ├── models.py             # Domain models (InGameDate, SaveData, CraftingPlan)
│   ├── parser.py             # Binary save decompressor & parser
│   ├── crafting.py           # Recursive DAG recipe calculator & material deduction
│   ├── data_loader.py        # Database loaders (locations, recipes, metadata, alt sources)
│   ├── optimizer.py          # Greedy set-cover, max-relationship, focus suggestions & trees
│   └── rankings.py           # Gift popularity ranking builder
│
├── companion/                # Live companion web server & backend
│   ├── server.py             # FastAPI backend & SSE event stream
│   ├── config.py             # Companion configuration model
│   ├── json_exporter.py      # Companion JSON payload formatter
│   ├── planner_bridge.py     # Execution bridge to fom_planner
│   ├── watcher.py            # File watcher for auto-syncing saves
│   └── static/               # Web client assets (HTML, CSS, JS, pixel-art sprites)
│
├── web/                      # Client-side static Pyodide web application
│   ├── index.html            # Static single-page application
│   ├── app.js                # Web application logic & UI
│   ├── style.css             # Theme & UI styling
│   ├── planner.worker.js     # Web Worker hosting Pyodide runtime
│   └── py/web_bridge.py      # In-browser Python bridge
│
├── data/
│   ├── item_data.json        # Database of 34 NPCs, 556 items, affinities, and tags
│   ├── item_locations.json   # Database of 452 item spawn and acquisition locations
│   ├── alt_sources.json      # Database of alternate acquisition paths (shops, wells, etc.)
│   ├── recipe_sources.json   # Cooking recipe unlock sources
│   ├── item_seasons.json     # Seasonal availability metadata
│   └── recipes.json          # Complete cooking, crafting, and milling recipes
├── samples/
│   └── sample_save.sav       # Sample save file for testing
└── tests/                    # Automated test suite
    ├── fixtures.py           # Reusable synthetic save and item fixture generators
    ├── conftest.py           # Pytest root configuration and shared fixtures
    ├── core/                 # Core engine tests (planner, crafting, parser, focus)
    ├── companion/            # Companion FastAPI backend & calendar tests
    ├── web/                  # Pyodide web worker, bridge, sprites & UI contract tests
    └── ci/                   # GitHub Actions CI/CD contracts & security audits
```

---

## Running the Test Suite

Run the full automated test suite (976 tests):

```bash
# Run all tests with uv (recommended)
uv run pytest

# Run tests by functional subsystem
uv run pytest tests/core/         # Core engine & domain tests
uv run pytest tests/companion/    # Companion API & server tests
uv run pytest tests/web/          # Pyodide web application & worker tests
uv run pytest tests/ci/           # CI/CD contract & security audit tests
```
