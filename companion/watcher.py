"""
companion/watcher.py

Filesystem watcher for Fields of Mistria save files using watchdog.
Designed specifically with Windows filesystem semantics in mind:
- Handles FileCreatedEvent, FileModifiedEvent, and FileMovedEvent (atomic temp->save renames).
- Debounces rapid consecutive filesystem events.
- Safely bridges background watchdog thread to asyncio event loop.
- Case-insensitive .sav extension matching.
"""

import asyncio
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, List, Optional, Set

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from fom_planner.constants import DEFAULT_SAVE_DIRS
from fom_planner.parser import find_save_files


class SaveFileEventHandler(FileSystemEventHandler):
    """
    Watches a save directory for .sav file creation, modification, or move/rename.
    """
    def __init__(self, on_save_changed: Callable[[Path], None], debounce_seconds: float = 0.5):
        super().__init__()
        self.on_save_changed = on_save_changed
        self.debounce_seconds = debounce_seconds
        self._last_event_time: float = 0.0
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _is_sav_file(self, path_str: str) -> bool:
        if not path_str:
            return False
        return path_str.lower().endswith(".sav")

    def _schedule_trigger(self, target_path: Path):
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self.debounce_seconds,
                self._dispatch,
                args=[target_path],
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _dispatch(self, target_path: Path):
        try:
            self.on_save_changed(target_path)
        except Exception as e:
            print(f"[Watcher] Error in change callback: {e}")

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self._is_sav_file(event.src_path):
            self._schedule_trigger(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and self._is_sav_file(event.src_path):
            self._schedule_trigger(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent):
        dest = getattr(event, "dest_path", None)
        if dest and not event.is_directory and self._is_sav_file(dest):
            self._schedule_trigger(Path(dest))


def resolve_watch_directories(explicit_save_path: Optional[str] = None) -> List[Path]:
    """
    Identifies valid directories to watch.
    """
    watch_dirs: List[Path] = []
    seen: Set[Path] = set()

    # 1. Explicit save file parent
    if explicit_save_path:
        p = Path(explicit_save_path).expanduser()
        parent = p.parent if p.is_file() else p
        if parent.exists():
            resolved = parent.resolve()
            watch_dirs.append(resolved)
            seen.add(resolved)

    # 2. Existing save files from discovery
    found_saves = find_save_files()
    for s in found_saves:
        parent = s.parent.resolve()
        if parent not in seen and parent.exists():
            watch_dirs.append(parent)
            seen.add(parent)

    # 3. Standard default directories on system
    for raw_dir in DEFAULT_SAVE_DIRS:
        p = Path(raw_dir)
        if p.exists():
            try:
                resolved = p.resolve()
                if resolved not in seen:
                    watch_dirs.append(resolved)
                    seen.add(resolved)
            except Exception:
                pass

    return watch_dirs


class SaveWatcher:
    """
    Manages the watchdog Observer lifecycle and notifies the async server on save updates.
    """
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_change_coro_fn: Callable[[Path], Any],
        explicit_save_path: Optional[str] = None,
    ):
        self.loop = loop
        self.on_change_coro_fn = on_change_coro_fn
        self.explicit_save_path = explicit_save_path
        self.observer: Optional[Observer] = None
        self.watched_paths: List[Path] = []

    def _sync_callback(self, changed_path: Path):
        print(f"[Watcher] Detected save change at: {changed_path}")
        # Dispatch async coroutine onto main event loop in a thread-safe manner
        asyncio.run_coroutine_threadsafe(self.on_change_coro_fn(changed_path), self.loop)

    def start(self):
        self.stop()
        self.watched_paths = resolve_watch_directories(self.explicit_save_path)
        if not self.watched_paths:
            print("[Watcher] No active save directories found to watch. Watching will start when a save is provided.")
            return

        self.observer = Observer()
        handler = SaveFileEventHandler(self._sync_callback)

        for p in self.watched_paths:
            print(f"[Watcher] Watching save directory: {p}")
            self.observer.schedule(handler, str(p), recursive=False)

        self.observer.daemon = True
        self.observer.start()

    def update_watch_target(self, explicit_save_path: Optional[str]):
        """Re-evaluates watched directories when settings change."""
        self.explicit_save_path = explicit_save_path
        self.start()

    def stop(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2.0)
            except Exception:
                pass
            self.observer = None
