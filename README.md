# edge-orb-performance-site

This site uses Apache ECharts for interactive charts on both pages (`index.html` and `backtest.html`). ECharts provides smooth pinch-zoom and scroll on mobile via `dataZoom` (inside + slider), so you can zoom and pan charts with touch gestures.

Files of interest:
- `index.html` — Monthly performance UI with combined equity and streak charts rendered using ECharts.
- `backtest.html` — ORB backtest UI with equity and win/loss streak charts rendered using ECharts.

Static data lives under `data/`.