"""
Batch folder watcher for DCS Video Manager.
Monitors the recordings folder for new .mkv files and queues them for analysis.
Requires: watchdog (pip install -r requirements-batch.txt)
"""

import threading
from pathlib import Path

_watcher_thread: threading.Thread | None = None
_stop_event = threading.Event()
_observer = None


def _make_handler(queue_callback):
    """Return a watchdog event handler that calls queue_callback(path) for new .mkv files."""
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        raise RuntimeError("watchdog not installed — run: pip install -r requirements-batch.txt")

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            """Enqueue new .mkv files that appear in the watched folder."""
            if not event.is_directory and event.src_path.lower().endswith(".mkv"):
                queue_callback(event.src_path)

    return _Handler()


def start_watcher(folder: str, queue_callback) -> None:
    """Start the folder watcher in a daemon thread. Calls queue_callback(path) for each new .mkv."""
    global _watcher_thread, _observer

    try:
        from watchdog.observers import Observer
    except ImportError:
        raise RuntimeError("watchdog not installed — run: pip install -r requirements-batch.txt")

    folder_path = Path(folder)
    if not folder_path.exists():
        raise FileNotFoundError(f"Recordings folder not found: {folder}")

    _stop_event.clear()
    handler = _make_handler(queue_callback)
    _observer = Observer()
    _observer.schedule(handler, str(folder_path), recursive=False)
    _observer.start()

    def _run():
        _stop_event.wait()
        _observer.stop()
        _observer.join()

    _watcher_thread = threading.Thread(target=_run, daemon=True)
    _watcher_thread.start()


def stop_watcher() -> None:
    """Stop the folder watcher."""
    _stop_event.set()
    if _observer:
        _observer.stop()


def is_running() -> bool:
    """Return True if the watcher is currently active."""
    return _observer is not None and _observer.is_alive()
