from pathlib import Path
import csv
import os
from datetime import date, datetime, timedelta
from typing import Optional

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


if pytz is not None:
    utc_tz = pytz.timezone('UTC')
    nyc_tz = pytz.timezone('America/New_York')
else:
    from zoneinfo import ZoneInfo

    utc_tz = ZoneInfo('UTC')
    nyc_tz = ZoneInfo('America/New_York')


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


def get_last_data_date(path: Path) -> date:
    last_row: Optional[dict[str, str]] = None
    with path.open("r", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            last_row = row

    if not last_row:
        raise RuntimeError(f"No data rows found in {path}")

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


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    if not data_dir.exists():
        raise RuntimeError(f"Expected data directory at {data_dir}")

    existing_files = find_existing_capitalized_files(data_dir)
    today = datetime.now(nyc_tz).date()

    for file_path in existing_files:
        last_date = get_last_data_date(file_path)
        start_date = last_date + timedelta(days=1)
        end_date = today
        print(f"{file_path}: last_date={last_date}, start_date={start_date}, end_date={end_date}")


if __name__ == "__main__":
    main()
