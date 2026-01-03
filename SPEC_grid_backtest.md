SPEC.md - Buy the Dip Backtest Web App

Overview
- Single-page HTML + JavaScript app that runs a Buy the Dip backtest in-browser.
- Loads intraday OHLC data from local CSV files in data/ (symbol_1m.csv).
- Optional ad hoc symbol download via /api/polygon-download.
- Results include summary metrics, trade table, and charts.

Core Parameters
Parameter              Default          Description
grid_type              buy_the_dip      Single fixed grid mode (no alternates).
grid_spacing           percent_fixed    Spacing model: fixed price or percent fixed anchor.
grid_size              5                Spacing size (dollars for fixed, percent for percent fixed).
base_price             100              Anchor price for the ladder.
trade_value            1000             Dollar value per buy leg.
fractional_shares      true             Allow fractional share quantities.
retention_mode         profit           Sell retention: none, profit, profit_plus_5, profit_plus_10.
entry_filter           none             SMA filter: none, sma10, sma20, sma50, sma100.
tick_size              0.01             Price increment used for snapping.
downsample_minutes     10               Optional resample interval (1m or 10m).

Grid Spacing
- fixed: Rungs are base_price + n * grid_size (snapped to tick_size).
- percent_fixed: Rungs are base_price * (1 + grid_size/100)^n using a fixed anchor.
  A ladder is precomputed between the min and max price of the run to snap levels.
- No ratcheting anchor. The anchor stays fixed to the base_price.

Backtest Mechanics (Buy the Dip)
1) Build ladder
   - Seed buy orders at every rung below the base price down to the min price.
   - Track the highest seeded buy level.

2) Run-up coverage
   - If price rises 2 or more rungs above the highest seeded buy, add new buy rungs
     upward one at a time until the topmost buy is within 1 rung of the high.
   - This keeps dip orders staged under rising prices without changing the anchor.

3) Buy fills
   - When price trades down through a buy level, a buy fills if the entry filter passes.
   - Quantity = trade_value / price (rounded if fractional_shares is false).
   - Autofund deposits trade_value when a new open level is created:
     capital_contributed += trade_value.
   - After a buy, place a sell one rung above.

4) Sell fills
   - When price trades up through a sell level, a sell fills based on retention_mode.
   - Retention controls how much of the bought quantity remains after the sell.
   - After a sell, place a buy one rung below.
   - A delayed buy is also queued at the sell level and activates only after price
     trades one rung higher, preventing immediate re-buys on the same rung.

5) Price path
   - Each bar is simulated as a path through open/high/low/close to capture
     intra-bar fills.

Entry Filter
- SMA filters are computed on daily closes from intraday data.
- Buys only occur when price is at or above the selected SMA.
- Backtest aborts if the dataset is too short for the selected SMA window.

Summary Metrics
- cash: cash balance after trades and autofund deposits.
- shares: final share count.
- last_price: last bar price used for holdings valuation.
- open_levels_final: open positions at the end of the run.
- capital_contributed: sum of autofund deposits (trade_value per new open level).
- net_trade_cashflow: sum(sells) - sum(buys), commissions included.
- harvested_profit: realized profit from completed trades only.
- holdings_value: shares * last_price.
- net_pl_final: net_trade_cashflow + holdings_value.
- account_equity: cash + holdings_value (also = capital_contributed + net_pl_final).
- max_open_levels: peak number of concurrent open levels.
- max_deployed_capital: peak funded levels * trade_value.
- required_capital: max(-net_trade_cashflow); minimum bankroll needed without deposits.
- max_drawdown: worst peak-to-trough drop in account equity.
- max_drawdown_pct: max_drawdown divided by peak equity.
- cagr: computed using max_deployed_capital as the base.

Trade Log Fields
- buy_time, buy_price, buy_qty
- sell_time, sell_price, sell_qty
- qty_retained, cum_qty_retained
- profit, roi_pct
- running_pnl, drawdown, open_levels

Console Output
- After each run, GRID_BACKTEST_OUTPUT is logged as JSON containing params, meta,
  and the summary results.

Files
- grid.html: UI + simulation + charts
- SPEC_grid_backtest.md: this document
