SPEC.md — Pullback Grid Backtest Web App
🧩 Overview

A single-page HTML + JavaScript web app that:

Lets the user upload a CSV containing 1-minute OHLC data (e.g. TQQQ_1m.csv).

Runs a continuous pullback grid backtest (limit-order-only) entirely in the browser.

Displays an aggregated trade table and an equity-curve chart.

No external servers or Python required.

⚙️ Core Logic
Grid Parameters
Parameter	Default	Description
grid_size	5	Dollar spacing between grid levels.
trade_value	1000	Dollar amount per trade leg.
initial_cash	10000	Starting cash balance.
fractional_shares	true	Allow fractional quantities.
Strategy Definition

Continuous Pullback Grid (Limit-Only)

Compute price grid levels: all $5 multiples covering the dataset range.

Start with active buy limits at every level below the first price, and sell limits above.

When price ≤ buy level → fill $1000 at that level, remove that buy, and create a new sell $5 higher.

When price ≥ sell level → fill $1000 at that level, remove that sell, and create a new buy $5 lower.

Each completed buy/sell cycle is logged with:

buy_datetime, buy_price, buy_qty

sell_datetime, sell_price, sell_qty

qty_retained = buy_qty – sell_qty

cum_qty_retained (running total)

profit_$ and ROI_%

Equity = cash + shares × current price, tracked each minute.

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