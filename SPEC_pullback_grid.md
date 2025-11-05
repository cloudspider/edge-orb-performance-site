SPEC.md — Buy-the-Dip Grid Backtest Web App
🧩 Overview

A single-page HTML + JavaScript web app that:

Lets the user upload a CSV containing 1-minute OHLC data (e.g. TQQQ_1m.csv).

Runs a continuous buy-the-dip grid backtest (limit-order-only) entirely in the browser.

Displays an aggregated trade table and an equity-curve chart.

No external servers or Python required.

⚙️ Core Logic
Grid Parameters
Parameter	Default	Description
grid_type	pullback	Buy-the-dip grid (classic) or progressive ratchet.
grid_size	5	Dollar spacing between grid levels.
grid_offset	0	Shift applied to every rung (e.g. offset 2.5 → 47.5, 52.5, … when size is 5).
trade_value	1000	Dollar amount per trade leg.
initial_cash	10000	Starting cash balance.
fractional_shares	true	Allow fractional quantities.
retention_mode	profit	Controls post-sell leftovers: none, profit-only, profit+5 %, profit+10 %.
allow_margin	true	Permit buys to borrow cash (run negative balance) instead of being capped by cash on hand.

Grid Types

Buy-the-Dip Grid (default)
- Seed buy limits at every snapped ladder level below the first bar; sell limits above.
- When price trades down to a buy rung: fill `trade_value`, remove that buy, and spawn a sell exactly one grid step higher.
- When price trades up to a sell rung: fill `trade_value`, remove that sell, and spawn a buy one grid step lower (allowing continuous dip buying).
- All levels are snapped to `grid_offset + n * grid_size`.

Progressive Grid (ratcheting)
- Always keeps at most one active sell and a set of buy resting orders.
- Initial action: buy at the closest snapped level to the first price, then queue a sell one grid step higher.
- When the sell fills, immediately queue **two** buys in a group: one grid step above (to keep chasing the trend) and one grid step below (to catch the dip). Both orders are snapped to the offset ladder.
- Whichever buy fills first keeps the dip ladder alive: an upper-fill immediately ensures a buy one step below stays queued (and respects the retention setting), while a lower-fill automatically seeds the next rung down. In both cases a new sell is placed one grid step above the fill.
- Results include full trade logs, equity series, drawdown, retained-share tracking, and realized PnL as with the buy-the-dip mode.

Shared Outputs
- Each completed buy/sell cycle logs:
  • buy_datetime, buy_price, buy_qty  
  • sell_datetime, sell_price, sell_qty  
  • qty_retained = buy_qty – sell_qty  
  • cum_qty_retained  
  • profit_$ and ROI_%  
- Equity curve computed each minute: equity = cash + shares × last price.

📊 Outputs
1. Trade Table

Columns:

Column	Type	Description
buy_datetime	string	Timestamp of buy fill
buy_price	number	Executed buy price
buy_qty	number	Quantity bought
sell_datetime	string	Timestamp of sell fill
sell_price	number	Executed sell price
sell_qty	number	Quantity sold
qty_retained	number	Shares retained
cum_qty_retained	number	Running retained total
profit_$	number	Realized profit for trade
ROI_%	number	Return on investment per trade

Displayed with a sortable, paginated HTML table (e.g. using DataTables or vanilla JS).

2. Summary Stats

Total completed trades

Net profit

Final equity

Total retained shares

Average ROI %

Max drawdown (currency and %)

3. Charts

Equity Curve — cumulative equity vs. time (Plotly / Chart.js).

Price + Trades Overlay — plot price with buy/sell markers.

🧠 UI / UX Requirements

Minimal single-page layout (HTML + Tailwind or simple CSS).

File input → parses CSV via Papaparse
 or native FileReader.

“Run Backtest” button triggers simulation and populates table + chart.

Optional numeric inputs for grid size, trade value, and initial cash.

Loading spinner and progress indicator for large files.

📁 File Structure
index.html      # Main UI & layout
app.js          # Core simulation + DOM update
style.css       # Optional styling
SPEC.md         # (this document)

🔬 Technical Notes

Handle date parsing as D/M/YYYY H:M (Australian format).

Use Number(price.toFixed(2)) to align trades to nearest $5 grid.

Use efficient loops — 500k+ rows possible; avoid O(n²).

Computation should be synchronous for simplicity but not block UI excessively (use requestIdleCallback or chunked processing if needed).

✅ Deliverables

index.html — lightweight UI (CSV upload, parameter inputs, Run button, results section).

app.js — grid-based backtest implementation and chart rendering.

style.css — optional basic styling.

Working demo that runs fully offline in browser.
