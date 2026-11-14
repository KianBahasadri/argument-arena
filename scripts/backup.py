#!/usr/bin/env python3
"""Consistent SQLite backup; destination must be outside a public repository."""

import argparse
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("Source database does not exist.")
    if args.destination.exists():
        parser.error("Destination already exists; choose a new backup name.")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(args.destination) as destination:
            source.backup(destination)
    args.destination.chmod(0o600)
    print(f"Backup created: {args.destination}")


if __name__ == "__main__":
    main()
