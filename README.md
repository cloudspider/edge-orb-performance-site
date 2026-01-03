# edge-orb-performance-site

This site uses Apache ECharts for interactive charts on both pages (`index.html` and `backtest.html`). ECharts provides smooth pinch-zoom and scroll on mobile via `dataZoom` (inside + slider), so you can zoom and pan charts with touch gestures.

Files of interest:
- `index.html` — Monthly performance UI with combined equity and streak charts rendered using ECharts.
- `backtest.html` — ORB backtest UI with equity and win/loss streak charts rendered using ECharts.

Static data lives under `data/`.

## Databento downloader

`scripts/databento_download.py` pulls a small slice of 1-minute OHLCV data for the continuous Micro Nasdaq future (`MNQ.C.0`) from Databento and writes two CSV files:
- `data/mnq_1m_raw.csv` — the unmodified Databento response (including index metadata).
- `data/mnq_1m.csv` — trimmed columns matching `caldt,open,high,low,close,volume,vwap,transactions,day`.

### Prerequisites
- Databento account with access to the `glbx.mdp3` dataset.
- A Python environment with `databento`, `pandas`, and `python-dotenv` installed. (The repo’s virtual environment already includes these.)

### Configure
1. Copy `.env.example` to `.env` if you haven’t already.
2. Add your Databento key:
   ```
   DATABENTO_API_KEY="<your_api_key>"
   ```

The script loads `.env` automatically; no other environment variables are required. If you prefer, you can export the variable in your shell instead of using `.env`.

### Run the downloader
```zsh
/Users/guy/repos/edge-orb-performance-site/.venv/bin/python scripts/databento_download.py
```

By default the script requests 2023‑09‑18 to 2023‑09‑19. You can tweak the `START`, `END`, or other constants near the top of the script if you need a different range, dataset, or symbol.

Console output will show:
- The request parameters.
- Raw frame shape/columns for debugging.
- Paths to the raw and formatted CSV exports.

If you encounter import errors for `databento`, ensure there is no local folder named `databento/` shadowing the installed package; rename or remove it.


# Documentation



# Run the Backtester
```
   /Users/guy/repos/edge-orb-performance-site/.venv/bin/python scripts/polygon_service.py
```




| `HitType`        | Meaning/Reason                                     |
| ---------------- | -------------------------------------------------- |
| `NotEnoughBars`  | Not enough valid data bars to process the day      |
| `NoBreak`        | Price never broke ORH/ORL; no trade taken          |
| `NoSize`         | Trade signal exists, but position size is 0        |
| `Indeterminate`  | Both stop and target hit in same bar (ambiguous)   |
| `TP`             | Target profit hit before stop                      |
| `Stop`           | Stop loss hit before target                        |
| `EOD`            | Neither hit; exit at end of day                    |
| `ORTooSmall`     | Opening Range % below minimum threshold (no trade) |
