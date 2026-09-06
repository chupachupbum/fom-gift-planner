#!/usr/bin/env python3
"""
main.py

Primary entry point for Fields of Mistria gift planner and optimization tools.

Usage:
    python main.py                           # Run daily gift planner (auto-detects save)
    python main.py --mode saturday --slots 15 # Plan Saturday Market day
    python main.py --format terminal          # Display plan in terminal
    python main.py rankings --sort-by total   # Export gift ranking matrices
    python main.py --help                     # Show options
"""

from fom_planner.cli import main

if __name__ == "__main__":
    main()
