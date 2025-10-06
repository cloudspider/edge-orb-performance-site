from pathlib import Path
import os

import pandas as pd
from databento import Historical
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("DATABENTO_API_KEY")
if not API_KEY:
    raise RuntimeError("Set DATABENTO_API_KEY in your environment or .env file")

DATASET = "glbx.mdp3"
SCHEMA = "ohlcv-1m"
SYMBOL = "MGC.v.0"       # ES1! equivalent on TradingView
SYMBOL_SLUG = SYMBOL.lower()
START = "2024-01-01"
END = "2025-10-05"
OUTPUT_FILE = Path(f"data/{SYMBOL_SLUG}_{START}_{END}_1m.csv")
RAW_OUTPUT_FILE = OUTPUT_FILE.with_name(f"{SYMBOL_SLUG}_{START}_{END}_1m_raw.csv")
NY_TZ = "America/New_York"


def main() -> None:
    client = Historical(key=API_KEY)

    print(
        f"Downloading {SCHEMA} data for {SYMBOL} from {START} to {END} "
        f"using dataset {DATASET}..."
    )

    store = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=SYMBOL,
        start=START,
        end=END,
        stype_in="continuous",
    )

    raw_df = store.to_df()
    print(f"Received {len(raw_df)} raw rows")
    print(f"Raw columns: {list(raw_df.columns)}")
    print(f"Raw index names: {list(raw_df.index.names)}")

    RAW_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw_df.to_csv(RAW_OUTPUT_FILE, index=True)
    print(f"Saved raw data to {RAW_OUTPUT_FILE.resolve()}")

    df = raw_df.reset_index()

    timestamp_column = next(
        (col for col in ("ts_event", "ts", "ts_start", "ts_end") if col in df.columns),
        None,
    )
    if timestamp_column is None:
        raise RuntimeError("Could not find a timestamp column in the Databento response")

    required_columns = {"open", "high", "low", "close", "volume"}
    missing_prices = required_columns - set(df.columns)
    if missing_prices:
        raise RuntimeError(
            "Missing expected price/volume columns: " + ", ".join(sorted(missing_prices))
        )

    timestamps = pd.to_datetime(df[timestamp_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise RuntimeError("Encountered unparseable timestamps in Databento response")

    timestamps_ny = timestamps.dt.tz_convert(NY_TZ)
    caldt = timestamps_ny.dt.tz_localize(None)
    df["caldt"] = caldt.dt.strftime("%Y-%m-%d %H:%M:%S")
    df["day"] = caldt.dt.strftime("%Y-%m-%d")
    df["vwap"] = ""
    df["transactions"] = ""

    result = df[[
        "caldt",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "transactions",
        "day",
    ]]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)

    print(f"Saved {len(result)} rows to {OUTPUT_FILE.resolve()}")
    print(result.head())


if __name__ == "__main__":
    main()
