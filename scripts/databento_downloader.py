from __future__ import annotations

import csv
import os
from datetime import date, datetime, timedelta, time, timezone
from pathlib import Path
from typing import Dict, Optional
import re

import pandas as pd
from databento import Historical

try:
    import pytz
except ModuleNotFoundError:  # pragma: no cover - fallback when pytz is unavailable
    pytz = None

try:
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:  # pragma: no cover - Python <3.9 requires pytz
    ZoneInfo = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - allow running without python-dotenv
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False

load_dotenv()

API_KEY = os.getenv("DATABENTO_API_KEY")
if not API_KEY:
    raise RuntimeError("Set DATABENTO_API_KEY in your environment or .env file")

if pytz is not None:
    NY_TZ = pytz.timezone("America/New_York")
elif ZoneInfo is not None:
    NY_TZ = ZoneInfo("America/New_York")
else:  # pragma: no cover - defensive fallback
    raise RuntimeError("Neither pytz nor zoneinfo is available for timezone handling")

DEFAULT_SCHEMA = "ohlcv-1m"
DEFAULT_DATASET = "glbx.mdp3"
DEFAULT_START_DATE = date(2024, 1, 1)

# Mapping of CSV filenames in data/ to the Databento instrument configuration.
DATABENTO_TARGETS: Dict[str, Dict[str, str]] = {
    "es_1m.csv": {"symbol": "ES.v.0"},
    "mes_1m.csv": {"symbol": "MES.v.0"},
    "nq_1m.csv": {"symbol": "NQ.v.0"},
    "mnq_1m.csv": {"symbol": "MNQ.v.0"},
    "ym_1m.csv": {"symbol": "YM.v.0"},
    "mym_1m.csv": {"symbol": "MYM.v.0"},
    "gc_1m.csv": {"symbol": "GC.v.0"},
    "mgc_1m.csv": {"symbol": "MGC.v.0"},
    "hg_1m.csv": {"symbol": "HG.v.0"},
}


def get_last_data_date(path: Path) -> Optional[date]:
    """Read the final row's date from an existing CSV file."""

    if not path.exists():
        return None

    last_row: Optional[dict[str, str]] = None
    with path.open("r", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            last_row = row

    if not last_row:
        return None

    day_value = last_row.get("day")
    if day_value:
        try:
            return datetime.strptime(day_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise RuntimeError(f"Unexpected day format in {path}: {day_value}") from exc

    caldt_value = last_row.get("caldt")
    if not caldt_value:
        raise RuntimeError(f"Could not find day or caldt columns in {path}")

    date_part = caldt_value.split(" ", 1)[0]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(f"Unexpected caldt format in {path}: {caldt_value}") from exc


def append_to_csv(final_df: pd.DataFrame, output_file: Path) -> None:
    """Merge freshly downloaded data into the target CSV, preserving sort order."""

    columns = [
        "caldt",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "transactions",
        "day",
    ]

    available_cols = [col for col in columns if col in final_df.columns]
    fresh_rows = final_df[available_cols].copy()

    if output_file.exists():
        try:
            existing_df = pd.read_csv(output_file)
            combined = pd.concat([existing_df, fresh_rows], ignore_index=True)
        except Exception as exc:
            print(f"{output_file}: failed reading existing CSV ({exc}); overwriting with new data.")
            combined = fresh_rows
    else:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        combined = fresh_rows

    if "caldt" in combined.columns:
        combined["caldt"] = pd.to_datetime(combined["caldt"], errors="coerce")
        combined = combined.sort_values("caldt").drop_duplicates(subset=["caldt"], keep="last")
        combined["caldt"] = combined["caldt"].dt.strftime("%Y-%m-%d %H:%M:%S")

    combined.to_csv(output_file, index=False)
    print(f"Data saved to {output_file}")


def process_databento_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a Databento OHLCV frame into our standardized schema."""

    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    timestamp_column = next(
        (col for col in ("ts_event", "ts", "ts_start", "ts_end") if col in df.columns),
        None,
    )
    if timestamp_column is None:
        raise RuntimeError("Could not find a timestamp column in the Databento response")

    timestamps = pd.to_datetime(df[timestamp_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise RuntimeError("Encountered unparseable timestamps in Databento response")

    timestamps_ny = timestamps.dt.tz_convert(NY_TZ)
    caldt = timestamps_ny.dt.tz_localize(None)

    vwap_series = df["vwap"] if "vwap" in df.columns else pd.Series([""] * len(df))
    transactions_series: pd.Series
    if "count" in df.columns:
        transactions_series = df["count"]
    elif "n" in df.columns:
        transactions_series = df["n"]
    elif "transactions" in df.columns:
        transactions_series = df["transactions"]
    else:
        transactions_series = pd.Series([""] * len(df))

    result = pd.DataFrame(
        {
            "caldt": caldt,
            "open": df["open"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
            "volume": df["volume"],
            "vwap": vwap_series,
            "transactions": transactions_series,
        }
    )
    result["day"] = result["caldt"].dt.strftime("%Y-%m-%d")
    return result


def download_and_process_range(
    client: Historical,
    dataset: str,
    schema: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Request the missing range from Databento and normalize it."""

    start_str = start_date.strftime("%Y-%m-%d")
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min).replace(tzinfo=timezone.utc)

    adjusted = False
    while True:
        end_arg = end_dt.isoformat()
        print(f"Downloading {schema} data for {symbol} from {start_str} to {end_arg} (exclusive)...")
        try:
            store = client.timeseries.get_range(
                dataset=dataset,
                schema=schema,
                symbols=symbol,
                start=start_str,
                end=end_arg,
                stype_in="continuous",
            )
            break
        except Exception as exc:  # pragma: no cover - relies on external service
            message = str(exc)
            if "data_end_after_available_end" in message:
                match = re.search(r"available up to '([^']+)'", message)
                if match:
                    available_end_raw = match.group(1)
                    try:
                        available_end_dt = datetime.fromisoformat(available_end_raw.replace(" ", "T"))
                    except ValueError:
                        available_end_dt = datetime.fromisoformat(available_end_raw)

                    available_end_dt = available_end_dt.astimezone(timezone.utc)
                    if available_end_dt.date() < start_date:
                        print(
                            f"{symbol}: available data ends on {available_end_dt.date()}, "
                            f"before requested start {start_date}; skipping."
                        )
                        return pd.DataFrame()

                    if adjusted and available_end_dt >= end_dt:
                        print(f"Databento request failed for {symbol}: {exc}")
                        return pd.DataFrame()

                    print(
                        f"{symbol}: adjusting end parameter to {available_end_dt.isoformat()} "
                        "based on Databento availability."
                    )
                    end_dt = available_end_dt
                    adjusted = True
                    continue

            print(f"Databento request failed for {symbol}: {exc}")
            return pd.DataFrame()

    raw_df = store.to_df()
    print(f"Received {len(raw_df)} raw rows for {symbol}")
    processed = process_databento_frame(raw_df.reset_index())
    if processed.empty:
        return processed

    mask = processed["caldt"].dt.date.between(start_date, end_date)
    filtered = processed.loc[mask]
    print(f"Retained {len(filtered)} rows within target range.")
    return filtered


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    if not data_dir.exists():
        raise RuntimeError(f"Expected data directory at {data_dir}")

    client = Historical(key=API_KEY)
    today = datetime.now(NY_TZ).date()
    yesterday = today - timedelta(days=1)

    for filename, config in DATABENTO_TARGETS.items():
        output_file = data_dir / filename

        if not output_file.exists():
            print(f"{output_file}: file does not exist; skipping.")
            continue

        last_date = get_last_data_date(output_file)
        if last_date is not None and last_date >= yesterday:
            print(f"{output_file}: last_date={last_date} >= yesterday={yesterday}; up to date, skipping.")
            continue

        base_start = config.get("start_date", DEFAULT_START_DATE)
        if isinstance(base_start, str):
            base_start = datetime.strptime(base_start, "%Y-%m-%d").date()
        assert isinstance(base_start, date)

        if last_date is None:
            start_date = max(base_start, DEFAULT_START_DATE)
            last_date_display = "None (empty file)"
        else:
            start_date = max(last_date + timedelta(days=1), base_start)
            last_date_display = str(last_date)

        end_date = today
        print(f"{output_file}: last_date={last_date_display}, start_date={start_date}, end_date={end_date}")

        if start_date > end_date:
            print(f"{output_file}: no new data to download (start_date after end_date).")
            continue

        dataset = config.get("dataset", DEFAULT_DATASET)
        schema = config.get("schema", DEFAULT_SCHEMA)
        symbol = config["symbol"]

        new_rows = download_and_process_range(
            client=client,
            dataset=dataset,
            schema=schema,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )

        if new_rows.empty:
            print(f"{output_file}: no new rows returned; nothing to append.")
            continue

        append_to_csv(new_rows, output_file)


if __name__ == "__main__":
    main()
