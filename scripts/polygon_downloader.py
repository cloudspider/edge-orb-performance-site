from pathlib import Path
import csv
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
import time as time_module

import pandas as pd
import requests

try:
    import pytz
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without pytz
    pytz = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - allow running without python-dotenv
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False

load_dotenv()

API_KEY = os.getenv("POLYGON_API_KEY")
if not API_KEY:
    raise RuntimeError("Set POLYGON_API_KEY in your environment or .env file")

# Set to True if you have a paid Polygon subscription; otherwise, set to False.
PAID_POLYGON_SUBSCRIPTION = False


FREE_TIER_REQUEST_INTERVAL = 12.0  # seconds; Polygon free tier allows up to 5 requests/minute
RATE_LIMIT_INTERVAL = 0.0 if PAID_POLYGON_SUBSCRIPTION else FREE_TIER_REQUEST_INTERVAL
_LAST_REQUEST_TS = 0.0


def respect_polygon_rate_limit() -> None:
    """Ensure we leave enough time between requests for the free tier."""

    if RATE_LIMIT_INTERVAL <= 0:
        return

    global _LAST_REQUEST_TS
    now = time_module.monotonic()
    elapsed = now - _LAST_REQUEST_TS
    wait = RATE_LIMIT_INTERVAL - elapsed
    if wait > 0:
        print(f"Sleeping {wait:.1f}s to respect Polygon rate limit...")
        time_module.sleep(wait)
        now = time_module.monotonic()
    _LAST_REQUEST_TS = now


if pytz is not None:
    utc_tz = pytz.timezone('UTC')
    nyc_tz = pytz.timezone('America/New_York')
else:
    from zoneinfo import ZoneInfo

    utc_tz = ZoneInfo('UTC')
    nyc_tz = ZoneInfo('America/New_York')

POLYGON_MARKET_TZ = nyc_tz  # Polygon US equity aggregates use the exchange's Eastern Time calendar


def is_capitalized_one_minute_file(path: Path) -> bool:
    if not path.is_file():
        return False

    name = path.name
    if not name.endswith("_1m.csv"):
        return False

    symbol = name[: -len("_1m.csv")]
    return symbol.isalpha() and symbol.isupper()



def find_existing_capitalized_files(data_dir: Path) -> list[Path]:
    return sorted(path for path in data_dir.iterdir() if is_capitalized_one_minute_file(path))


def get_last_data_date(path: Path) -> Optional[date]:
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


def get_polygon_data(
    url: Optional[str],
    ticker: str,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = False,
):
    """Retrieve intraday aggregate data from Polygon.io, handling pagination."""

    MAX_RETRIES = 5
    attempt = 0

    while attempt < MAX_RETRIES:
        attempt += 1

        respect_polygon_rate_limit()

        try:
            if url is None:
                base = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
                params = {
                    "adjusted": "true" if adjusted else "false",
                    "sort": "asc",
                    "limit": 50000,
                    "apiKey": API_KEY,
                }
                response = requests.get(base, params=params, timeout=30)
            else:
                request_url = url
                if "apiKey=" not in request_url:
                    request_url = f"{request_url}&apiKey={API_KEY}" if "?" in request_url else f"{request_url}?apiKey={API_KEY}"
                response = requests.get(request_url, timeout=30)
        except requests.RequestException as exc:
            print(f"HTTP request failed: {exc}")
            return [], None

        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            try:
                retry_after = float(retry_after_header) if retry_after_header is not None else RATE_LIMIT_INTERVAL or FREE_TIER_REQUEST_INTERVAL
            except ValueError:
                retry_after = RATE_LIMIT_INTERVAL or FREE_TIER_REQUEST_INTERVAL
            retry_after = max(retry_after, RATE_LIMIT_INTERVAL or 0, 1.0)
            print(f"Rate limited (HTTP 429). Waiting {retry_after:.1f}s before retry {attempt}/{MAX_RETRIES}...")
            time_module.sleep(retry_after)
            continue

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"HTTP request failed: {exc}")
            return [], None

        try:
            data = response.json()
        except ValueError:
            print("Error: Response is not valid JSON.")
            return [], None

        next_url = data.get("next_url")
        if next_url and "apiKey=" not in next_url:
            next_url = f"{next_url}&apiKey={API_KEY}" if "?" in next_url else f"{next_url}?apiKey={API_KEY}"

        results = data.get("results", [])
        if "resultsCount" in data:
            print(f"Fetched {data.get('resultsCount')} results in this batch.")

        return results, next_url

    print("Exceeded maximum retries due to rate limiting. Giving up on this batch.")
    return [], None


def process_data(results: List[Dict[str, Any]]) -> pd.DataFrame:
    """Process Polygon aggregate data into a clean DataFrame."""

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).copy()
    df["datetime_utc"] = pd.to_datetime(df["t"], unit="ms", errors="coerce")
    df["datetime_et"] = df["datetime_utc"].dt.tz_localize(utc_tz, nonexistent="shift_forward", ambiguous="NaT").dt.tz_convert(nyc_tz)
    df["caldt"] = df["datetime_et"].dt.tz_localize(None)

    df = df.set_index("datetime_et").sort_index()
    try:
        market_data = df.between_time("04:00", "19:59", inclusive="both").reset_index()
    except TypeError:
        market_data = df.between_time("04:00", "19:59").reset_index()

    market_data["date"] = market_data["datetime_et"].dt.date
    market_data = market_data.rename(
        columns={
            "v": "volume",
            "vw": "vwap",
            "o": "open",
            "c": "close",
            "h": "high",
            "l": "low",
            "t": "timestamp_ms",
            "n": "transactions",
        },
        errors="ignore",
    )

    market_data["day"] = market_data["date"].astype(str)
    return market_data


def append_to_csv(final_df: pd.DataFrame, output_file: Path) -> None:
    cols = ["caldt", "open", "high", "low", "close", "volume", "vwap", "transactions", "day"]
    available_cols = [col for col in cols if col in final_df.columns]
    new_rows = final_df[available_cols].copy()

    if output_file.exists():
        try:
            existing_df = pd.read_csv(output_file)
            combined = pd.concat([existing_df, new_rows], ignore_index=True)
        except Exception as exc:
            print(f"Failed to read existing CSV {output_file}: {exc}. Overwriting with new data.")
            combined = new_rows
    else:
        combined = new_rows

    if "caldt" in combined.columns:
        combined["caldt"] = pd.to_datetime(combined["caldt"], errors="coerce")
        combined = combined.sort_values("caldt").drop_duplicates(subset=["caldt"], keep="last")
        combined["caldt"] = combined["caldt"].dt.strftime("%Y-%m-%d %H:%M:%S")

    combined.to_csv(output_file, index=False)
    print(f"Data saved to {output_file}")


def download_and_merge_data(
    ticker: str,
    start_date: str,
    end_date: str,
    output_file: Path,
) -> Optional[pd.DataFrame]:
    """Download intraday data, process it, and append to the CSV file."""

    now_market = datetime.now(POLYGON_MARKET_TZ)
    today_market = now_market.date()

    if not PAID_POLYGON_SUBSCRIPTION:
        two_years_ago = today_market - timedelta(days=730)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        if start_dt < two_years_ago:
            print("ERROR: For free Polygon subscriptions, start_date must be within the past 2 years.")
            return None

    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_dt > today_market:
            print("WARNING: end_date is in the future. You may get empty/partial data.")
    except Exception:
        pass

    all_raw_data: List[Dict[str, Any]] = []
    next_url: Optional[str] = None
    batch_count = 0
    print(f"Downloading intraday data for {ticker} from {start_date} to {end_date}")

    MAX_BATCHES = 500

    while True:
        batch_count += 1
        if batch_count > MAX_BATCHES:
            print("Stopping: reached MAX_BATCHES safety cap.")
            break

        print(f"Batch {batch_count}...")
        results, next_url = get_polygon_data(
            url=next_url,
            ticker=ticker,
            adjusted=False,
            from_date=start_date,
            to_date=end_date,
        )

        if not results:
            print("No more data or empty batch.")
            break

        all_raw_data.extend(results)
        print(f"Batch {batch_count}: Retrieved {len(results)} records. Total so far: {len(all_raw_data)}")

        if not next_url:
            print("Download complete (no next_url).")
            break

    if not all_raw_data:
        print("No data collected.")
        return None

    print(f"Processing {len(all_raw_data)} total records...")
    final_df = process_data(all_raw_data)

    if final_df.empty:
        print("No data after processing.")
        return None

    append_to_csv(final_df, output_file)
    print(f"Total records after processing: {len(final_df)}")
    return final_df


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    if not data_dir.exists():
        raise RuntimeError(f"Expected data directory at {data_dir}")

    existing_files = find_existing_capitalized_files(data_dir)
    today = datetime.now(POLYGON_MARKET_TZ).date()
    yesterday = today - timedelta(days=1)

    for file_path in existing_files:
        last_date = get_last_data_date(file_path)

        # Skip retrieval if last_date is yesterday or later
        if last_date is not None and last_date >= yesterday:
            print(f"{file_path}: last_date={last_date} >= yesterday={yesterday}; up to date, skipping.")
            continue

        if last_date is None:
            start_date = today - timedelta(days=730)
            last_date_display = "None (empty file)"
        else:
            start_date = last_date + timedelta(days=1)
            last_date_display = str(last_date)
        end_date = today
        print(f"{file_path}: last_date={last_date_display}, start_date={start_date}, end_date={end_date}")

        if start_date > end_date:
            print("No new data to download (start_date is after end_date).")
            continue

        symbol = file_path.stem[:-len("_1m")]
        if not symbol:
            print(f"Unable to extract symbol from {file_path.name}; skipping.")
            continue

        download_and_merge_data(
            ticker=symbol,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            output_file=file_path,
        )


if __name__ == "__main__":
    main()
