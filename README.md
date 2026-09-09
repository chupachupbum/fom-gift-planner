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
- **Focus Suggestions**: Pinpoints top blocker raw materials (crops, animal products, forageables) to help guide your daily farming and gathering tasks.
- **Zero Mandatory Dependencies**: Runs entirely on Python's standard library. Optional Excel export via `openpyxl`.
- **Gift Rankings Exporter**: Includes `export_gift_rankings.py` to rank all 438+ giftable items by popularity across the 34 NPCs.

---

## Requirements

- **Python 3.10 or newer** (built-in standard library is all that's required).
- *(Optional)* `openpyxl` if you want to export `.xlsx` Excel spreadsheets:
  ```bash
  pip install -r requirements.txt
  ```

---

## Quick Start

### 1. Test Immediately (Using Included Sample Save)

You don't even need the game installed to try it out! A realistic sample save file is included in `samples/`:

```bash
# Run daily planner on sample save
python main.py --save-file samples/sample_save.sav --format terminal

# Simulate Saturday Market planning
python main.py --save-file samples/sample_save.sav --mode saturday

# Export gift rankings table to terminal or CSV
python main.py rankings --format terminal --top 10
python main.py rankings --format csv
```

### 2. Run with Your Own Game Save

By default, running `python main.py` automatically detects your most recent Fields of Mistria save file on Windows or Linux/Steam Deck!

```bash
python main.py
```

Or specify your save file manually:

```bash
python main.py --save-file "path/to/your/save.sav"
```

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
  ```

---

## CLI Options & Usage

Run the daily planner directly:

```bash
python main.py [OPTIONS]
```
*(Note: `python gift_planner.py` remains supported as a backward-compatible alias).*

| Option | Choices / Default | Description |
|---|---|---|
| `--save-file` | *(auto-detect)* | Path to a specific `.sav` file. |
| `--strategy` | `journal`, `max-relationship` (default: `journal`) | Optimization strategy: `journal` targets unrecorded preferences; `max-relationship` maximizes daily friendship points gained across all characters. |
| `--mode` | `auto`, `saturday`, `market-only`, `townsfolk`, `all` (default: `auto`) | Planning mode: `auto` uses save day; `saturday` plans for market day; `market-only` targets visiting vendors; `townsfolk` targets permanent residents; `all` plans all eligible NPCs. Respects player unlock progression when save is provided. |
| `--slots` | Integer (default: `20`) | Maximum backpack slots budgeted for gift items. |
| `--max-relationship-points` | Float (default: `1755.0`) | Affection/heart points threshold to consider an NPC maxed out. |
| `--no-exclude-max-relationship` | Flag | Include characters in the gift plan even if they have reached max relationship. |
| `--item-locations` | Path (default: `data/item_locations.json`) | Path to item locations database. |
| `--format` | `terminal`, `csv`, `excel`, `all`, `both` (default: `all`) | Output destination format. |
| `--output-dir` | Path (default: `exports`) | Output directory for CSV and Excel files. |
| `--loved-weight`| Integer (default: `3`) | Score weight multiplier for loved gifts. |
| `--liked-weight`| Integer (default: `1`) | Score weight multiplier for liked gifts. |
| `--vendor-boost`| Float (default: `1.5`) | Score multiplier for Saturday Market vendors on Saturdays. |
| `--force-all-npcs`| Flag | Plan gifts for all NPCs even if already gifted today. |
| `--exclude-npcs`| Comma-separated string | Exclude specific NPCs by ID (e.g. `--exclude-npcs adeline,march`). |

### Examples

```bash
# Maximize daily friendship points across all available NPCs
python main.py --strategy max-relationship --format terminal

# Plan Saturday Market with 22 bag slots under max-relationship strategy
python main.py --strategy max-relationship --mode saturday --slots 22

# Plan Saturday Market with 15 bag slots and output to terminal
python main.py --mode saturday --slots 15 --format terminal

# Export daily plan to CSV only
python main.py --format csv

# Plan for all NPCs regardless of whether they were gifted today
python main.py --force-all-npcs
```

---

## Item Gift Rankings Exporter

To analyze which items are most universally loved or liked across all characters in Mistria:

```bash
python main.py rankings [OPTIONS]
# or: python export_gift_rankings.py [OPTIONS]
```

Options:
- `--sort-by [total|loved|liked]`: Primary ranking metric (default: `total`).
- `--top N`: Limit output to top N items.
- `--format [csv|excel|both|terminal]`: Export format (default: `both`).

---

## Project Structure

```
fom-gift-planner/
├── README.md                 # Project documentation
├── requirements.txt          # Optional dependencies (openpyxl)
├── main.py                   # Primary unified CLI entry point
│
├── fom_planner/              # Modular package
│   ├── __init__.py           # Public API re-exports
│   ├── constants.py          # Vendors, festivals, and availability tiers
│   ├── models.py             # Domain models (InGameDate, SaveData, CraftingPlan)
│   ├── parser.py             # Binary save decompressor & parser
│   ├── crafting.py           # Recursive DAG recipe calculator & material deduction
│   ├── data_loader.py        # Database loaders (locations, recipes, metadata, prefs)
│   ├── optimizer.py          # Greedy set-cover & max-relationship solvers, focus suggestions
│   ├── rankings.py           # Gift popularity ranking builder
│   ├── cli.py                # Unified CLI parser & execution dispatch
│   └── exporters/
│       ├── __init__.py       # Exporters package
│       ├── terminal.py       # Terminal UI formatting (banners, badges, impact summary)
│       ├── csv_export.py     # CSV exporters
│       └── excel_export.py   # Multi-sheet openpyxl Excel exporter
│
├── gift_planner.py           # Backward-compatible shim
├── export_gift_rankings.py   # Backward-compatible shim
├── save_parser.py            # Backward-compatible shim
├── crafting_calculator.py    # Backward-compatible shim
│
├── data/
│   ├── item_data.json        # Database of 34 NPCs, 556 items, affinities, and tags
│   ├── item_locations.json   # Database of 452 item spawn and acquisition locations
│   └── recipes.json          # Complete cooking, crafting, and milling recipes
├── samples/
│   └── sample_save.sav       # Sample save file for quick testing
├── exports/                  # Directory where CSV/Excel exports are saved
└── tests/                    # Unit & regression test suite (327 tests)
    ├── test_cli.py
    ├── test_crafting_calculator.py
    ├── test_exporters.py
    ├── test_gift_planner.py
    ├── test_infused_items.py
    ├── test_max_relationship.py
    └── test_save_parser.py
```

---

## Running the Test Suite

Run the full automated test suite (327 tests):

```bash
python -m unittest discover -s tests
```
