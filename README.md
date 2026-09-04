# Fields of Mistria — Daily Gift Bag Planner & Rankings Analyzer

A standalone, dependency-free tool that optimizes your daily gift loadout in **[Fields of Mistria](https://store.steampowered.com/app/2142790/Fields_of_Mistria/)**.

It inspects your game save file (`.sav`), tracks remaining ungifted items for each NPC, scans both your backpack and farm storage chests, and uses a greedy weighted set-cover algorithm with recursive crafting resolution to calculate the **optimal set of items to carry in your bag**—maximizing NPC coverage and affection while minimizing inventory slots used.

---

## Key Features

- **Save File Inspection**: Reads uncompressed or compressed binary `.sav` files directly. Detects in-game date, time, season, bag inventory, and all farm/world storage chests.
- **Saturday Market Awareness**:
  - Mistria's 8 visiting vendors (*Darcy, Louis, Merri, Stillwell, Taliferro, Vera, Wheedle, Zorel*) only visit town on Saturdays (days 6, 13, 20, 27).
  - On weekdays, the planner focuses on the 26 townsfolk.
  - On Saturdays (or with `--mode saturday`), it plans for all 34 NPCs and prioritizes visiting vendors so you never miss their weekly appearance.
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
python gift_planner.py --save-file samples/sample_save.sav --format terminal

# Simulate Saturday Market planning
python gift_planner.py --save-file samples/sample_save.sav --mode saturday

# Export gift rankings table to CSV
python export_gift_rankings.py --format csv
```

### 2. Run with Your Own Game Save

By default, running `python gift_planner.py` automatically detects your most recent Fields of Mistria save file on Windows or Linux/Steam Deck!

```bash
python gift_planner.py
```

Or specify your save file manually:

```bash
python gift_planner.py --save-file "path/to/your/save.sav"
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

```
python gift_planner.py [OPTIONS]
```

| Option | Choices / Default | Description |
|---|---|---|
| `--save-file` | *(auto-detect)* | Path to a specific `.sav` file. |
| `--mode` | `auto`, `saturday`, `market-only`, `townsfolk`, `all` (default: `auto`) | Planning mode: `auto` uses save day; `saturday` plans for market day; `market-only` targets the 8 vendors; `townsfolk` targets 26 residents; `all` plans all 34 NPCs. |
| `--slots` | Integer (default: `20`) | Maximum backpack slots budgeted for gift items. |
| `--format` | `terminal`, `csv`, `excel`, `all`, `both` (default: `all`) | Output destination format. |
| `--output-dir` | Path (default: `exports`) | Output directory for CSV and Excel files. |
| `--loved-weight`| Integer (default: `3`) | Score weight multiplier for loved gifts. |
| `--liked-weight`| Integer (default: `1`) | Score weight multiplier for liked gifts. |
| `--vendor-boost`| Float (default: `1.5`) | Score multiplier for Saturday Market vendors on Saturdays. |
| `--force-all-npcs`| Flag | Plan gifts for all NPCs even if already gifted today. |
| `--exclude-npcs`| Comma-separated string | Exclude specific NPCs by ID (e.g. `--exclude-npcs adeline,march`). |

### Examples

```bash
# Plan Saturday Market with 15 bag slots and output to terminal
python gift_planner.py --mode saturday --slots 15 --format terminal

# Export daily plan to CSV only
python gift_planner.py --format csv

# Plan for all NPCs regardless of whether they were gifted today
python gift_planner.py --force-all-npcs
```

---

## Item Gift Rankings Exporter

To analyze which items are most universally loved or liked across all characters in Mistria:

```bash
python export_gift_rankings.py
```

Options:
- `--sort-by [total|loved|liked]`: Primary ranking metric (default: `total`).
- `--top N`: Limit output to top N items.
- `--format [csv|excel|both]`: Export format (default: `both`).

---

## Project Structure

```
fom-gift-planner/
├── README.md                 # This documentation
├── requirements.txt          # Optional dependencies (openpyxl)
├── gift_planner.py           # Main CLI optimizer & loadout planner
├── export_gift_rankings.py   # Gift popularity ranking & matrix generator
├── save_parser.py            # FoM save (.sav) parser & chest inventory extractor
├── crafting_calculator.py    # Recursive DAG crafting evaluator & pool deduction
├── data/
│   ├── item_data.json        # Database of 34 NPCs, 556 items, affinities, and tags
│   └── recipes.json          # Complete cooking, crafting, and milling recipes
├── samples/
│   └── sample_save.sav       # Sample save file for quick testing
├── exports/                  # Directory where CSV/Excel exports are saved
└── tests/                    # Unit & regression test suite (110 tests)
    ├── test_gift_planner.py
    ├── test_crafting_calculator.py
    └── test_save_parser.py
```

---

## Running the Test Suite

Run the full automated test suite (110 tests):

```bash
python -m unittest discover -s tests
```
