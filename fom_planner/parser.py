"""
parser.py

Parsing and discovery routines for Fields of Mistria (.sav) save files:
- parse_save_file
- find_save_files
- find_latest_save
"""

import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from fom_planner.constants import DEFAULT_SAVE_DIRS
from fom_planner.models import SaveData, _extract_slot_item_and_count


def parse_save_file(file_path: Union[Path, str]) -> SaveData:
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


def find_save_files(save_dir: Optional[Union[Path, str]] = None) -> List[Path]:
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


def find_latest_save(save_dir: Optional[Union[Path, str]] = None) -> Optional[Path]:
    """Returns the path to the most recent .sav file found."""
    saves = find_save_files(save_dir)
    return saves[0] if saves else None
