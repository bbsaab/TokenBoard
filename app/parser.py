"""JSONL parser for Claude conversation logs."""

import json
import os
from pathlib import Path
from typing import Generator, Optional

from . import db


def parse_jsonl_file(file_path: Path) -> Generator[dict, None, None]:
    """
    Parse a single JSONL file and extract usage data from assistant messages.

    Yields dicts with: timestamp, session_id, model, input_tokens, output_tokens,
    cache_creation_tokens, cache_read_tokens
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only process assistant messages with usage data
                if record.get("type") != "assistant":
                    continue

                usage = record.get("message", {}).get("usage")
                if not usage:
                    continue

                # Extract session_id from file name (format: session_id.jsonl)
                session_id = file_path.stem

                # Extract timestamp
                timestamp = record.get("timestamp")
                if not timestamp:
                    continue

                # Extract model
                model = record.get("message", {}).get("model", "unknown")

                yield {
                    "timestamp": timestamp,
                    "session_id": session_id,
                    "model": model,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                }
    except (OSError, IOError) as e:
        print(f"Error reading file {file_path}: {e}")


def scan_directory(directory: Path) -> Generator[dict, None, None]:
    """
    Recursively scan a directory tree for JSONL files and extract usage data.

    Yields usage dicts from all JSONL files found.
    """
    if not directory.exists():
        print(f"Directory does not exist: {directory}")
        return

    for jsonl_file in directory.rglob("*.jsonl"):
        yield from parse_jsonl_file(jsonl_file)


def import_from_directory(directory: Path) -> tuple[int, int]:
    """
    Import all usage data from JSONL files in a directory into the database.

    Returns tuple of (new_records, total_processed).
    """
    new_records = 0
    total_processed = 0
    files_processed = 0

    # Find all JSONL files first (skip symlinks to avoid hanging)
    if not directory.exists():
        print(f"Directory does not exist: {directory}", flush=True)
        return 0, 0

    # Use a custom walker that skips symlinks
    print("  Walking directory tree (skipping symlinks)...", flush=True)
    jsonl_files = []
    for root, dirs, files in os.walk(directory, followlinks=False):
        # Skip symlinked directories
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for f in files:
            if f.endswith('.jsonl'):
                file_path = Path(root) / f
                if not file_path.is_symlink():
                    jsonl_files.append(file_path)
    total_files = len(jsonl_files)
    print(f"  Found {total_files} JSONL files to process...", flush=True)

    for jsonl_file in jsonl_files:
        files_processed += 1
        file_records = 0

        try:
            for usage in parse_jsonl_file(jsonl_file):
                total_processed += 1
                file_records += 1
                inserted = db.insert_usage(
                    timestamp=usage["timestamp"],
                    session_id=usage["session_id"],
                    model=usage["model"],
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cache_creation_tokens=usage["cache_creation_tokens"],
                    cache_read_tokens=usage["cache_read_tokens"],
                )
                if inserted:
                    new_records += 1
        except Exception as e:
            print(f"Error processing {jsonl_file.name}: {e}", flush=True)
            continue

        # Progress update every 50 files
        if files_processed % 50 == 0:
            print(f"  Progress: {files_processed}/{total_files} files, {total_processed} records...", flush=True)

    return new_records, total_processed
