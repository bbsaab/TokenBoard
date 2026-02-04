"""
File watcher module for monitoring Claude usage JSONL files.

Watches ~/.claude/projects/ for new/modified .jsonl files and parses
new lines to insert usage records into the database.
"""

import json
import os
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


# Type alias for the callback function
UsageCallback = Callable[[Dict[str, Any]], None]


class JSONLFileTracker:
    """Tracks file positions to only read new lines."""

    def __init__(self) -> None:
        self._positions: Dict[str, int] = {}
        self._lock = threading.Lock()

    def get_position(self, file_path: str) -> int:
        """Get the last read position for a file."""
        with self._lock:
            return self._positions.get(file_path, 0)

    def set_position(self, file_path: str, position: int) -> None:
        """Set the last read position for a file."""
        with self._lock:
            self._positions[file_path] = position

    def remove_file(self, file_path: str) -> None:
        """Remove tracking for a file."""
        with self._lock:
            self._positions.pop(file_path, None)


class ClaudeUsageHandler(FileSystemEventHandler):
    """Handles file system events for Claude usage JSONL files."""

    def __init__(
        self,
        tracker: JSONLFileTracker,
        callback: UsageCallback,
    ) -> None:
        super().__init__()
        self.tracker = tracker
        self.callback = callback

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return
        if event.src_path.endswith('.jsonl'):
            self._process_new_lines(event.src_path)

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle file creation events."""
        if event.is_directory:
            return
        if event.src_path.endswith('.jsonl'):
            self._process_new_lines(event.src_path)

    def _process_new_lines(self, file_path: str) -> None:
        """Read and process only new lines from a JSONL file."""
        try:
            position = self.tracker.get_position(file_path)

            with open(file_path, 'r', encoding='utf-8') as f:
                # Seek to last known position
                f.seek(position)

                # Read new lines
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            self.callback(record)
                        except json.JSONDecodeError:
                            # Skip malformed lines
                            continue

                # Update position to current end of file
                self.tracker.set_position(file_path, f.tell())

        except (OSError, IOError) as e:
            # File may have been deleted or is inaccessible
            print(f"Error reading {file_path}: {e}")


class ClaudeUsageWatcher:
    """
    Watches Claude projects directory for usage data changes.

    Usage:
        def handle_usage(record):
            print(f"New usage: {record}")

        watcher = ClaudeUsageWatcher(callback=handle_usage)
        watcher.start()
        # ... later ...
        watcher.stop()
    """

    def __init__(
        self,
        callback: UsageCallback,
        watch_path: Optional[str] = None,
    ) -> None:
        """
        Initialize the watcher.

        Args:
            callback: Function to call when new usage records are found.
            watch_path: Path to watch. Defaults to ~/.claude/projects/
        """
        if watch_path is None:
            watch_path = os.path.join(
                os.path.expanduser('~'),
                '.claude',
                'projects'
            )

        self.watch_path = Path(watch_path)
        self.callback = callback
        self.tracker = JSONLFileTracker()
        self.observer: Optional[Observer] = None
        self._running = False

    def start(self) -> bool:
        """
        Start watching for file changes.

        Returns:
            True if started successfully, False if path doesn't exist.
        """
        if self._running:
            return True

        if not self.watch_path.exists():
            print(f"Watch path does not exist: {self.watch_path}")
            return False

        handler = ClaudeUsageHandler(self.tracker, self.callback)

        self.observer = Observer()
        self.observer.schedule(
            handler,
            str(self.watch_path),
            recursive=True
        )
        self.observer.start()
        self._running = True

        # Process existing files on startup
        self._scan_existing_files()

        return True

    def stop(self) -> None:
        """Stop watching and clean up resources."""
        if self.observer is not None:
            self.observer.stop()
            self.observer.join(timeout=5.0)
            self.observer = None
        self._running = False

    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._running

    def _scan_existing_files(self) -> None:
        """Scan and process any existing JSONL files."""
        try:
            for jsonl_file in self.watch_path.rglob('*.jsonl'):
                handler = ClaudeUsageHandler(self.tracker, self.callback)
                handler._process_new_lines(str(jsonl_file))
        except Exception as e:
            print(f"Error scanning existing files: {e}")


def create_watcher(
    callback: UsageCallback,
    watch_path: Optional[str] = None,
) -> ClaudeUsageWatcher:
    """
    Factory function to create a configured watcher.

    Args:
        callback: Function to call with new usage records.
        watch_path: Optional custom path to watch.

    Returns:
        Configured ClaudeUsageWatcher instance.
    """
    return ClaudeUsageWatcher(callback=callback, watch_path=watch_path)


# Example usage and testing
if __name__ == '__main__':
    import signal
    import sys

    def print_usage(record: Dict[str, Any]) -> None:
        """Simple callback that prints usage records."""
        print(f"Usage record: {json.dumps(record, indent=2)}")

    watcher = create_watcher(callback=print_usage)

    def signal_handler(signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        print("\nShutting down watcher...")
        watcher.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"Starting watcher on {watcher.watch_path}")
    if watcher.start():
        print("Watching for changes. Press Ctrl+C to stop.")
        # Keep main thread alive
        while watcher.is_running():
            try:
                threading.Event().wait(1.0)
            except KeyboardInterrupt:
                break
        watcher.stop()
    else:
        print("Failed to start watcher.")
        sys.exit(1)
