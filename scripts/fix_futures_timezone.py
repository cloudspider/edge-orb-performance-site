"""Utility to convert Databento-derived futures CSVs from UTC to New York time.

The Databento downloader originally wrote `caldt`/`day` columns in UTC. This
script reinterprets those timestamps as UTC, converts them to
`America/New_York`, drops the timezone, and overwrites the CSV.

Usage:
    python scripts/fix_futures_timezone.py data/nq_1m.csv data/mnq_1m.csv
    python scripts/fix_futures_timezone.py --backup data/nq_1m.csv data/mnq_1m.csv data/es_1m.csv data/mes_1m.csv
    
For safety you can pass `--backup` to emit `<filename>.bak` files before
rewriting.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

NY_TZ = "America/New_York"


def convert_file(path: Path, backup: bool = False) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    if "caldt" not in df.columns:
        raise ValueError(f"{path}: missing required 'caldt' column")

    timestamps = pd.to_datetime(df["caldt"], utc=True, errors="raise")
    timestamps_ny = timestamps.dt.tz_convert(NY_TZ)

    df["caldt"] = timestamps_ny.dt.strftime("%Y-%m-%d %H:%M:%S")
    if "day" in df.columns:
        df["day"] = timestamps_ny.dt.strftime("%Y-%m-%d")

    out_path = path
    backup_path = None
    if backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if backup_path.exists():
            raise FileExistsError(f"Backup already exists: {backup_path}")
        path.rename(backup_path)

    df.to_csv(out_path, index=False)

    if backup_path is not None:
        print(f"Backup saved to {backup_path}")


def iter_paths(values: Iterable[str]) -> Iterable[Path]:
    for value in values:
        p = Path(value)
        if p.is_dir():
            yield from sorted(p.glob("*_1m.csv"))
        else:
            yield p


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Convert Databento futures CSVs to New York timestamps")
    parser.add_argument("paths", nargs="+", help="CSV files or directories to process")
    parser.add_argument("--backup", action="store_true", help="Keep a .bak copy before overwriting")
    args = parser.parse_args(argv)

    errors: list[str] = []
    for path in iter_paths(args.paths):
        try:
            convert_file(path, backup=args.backup)
            print(f"Converted {path}")
        except Exception as exc:  # noqa: BLE001 - bubble up after loop
            errors.append(f"{path}: {exc}")

    if errors:
        joined = "\n".join(errors)
        raise SystemExit(f"Errors encountered:\n{joined}")


if __name__ == "__main__":
    main()
