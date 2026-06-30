


ok... we started off with MaxDD of -18.80%, -8.48% and -8.75% respectively for each of the 3 strategies I tested.
and once combined into a portfolio we get -7.23%.
this indicates that combining the strategies improves the risk....
does this make sense?

    Yes, that drop in Max DD is the kind of behaviour you’d expect when you stack several strategies that don’t draw down at the same time.

    What’s happening with the current portfolio run:

    We treat the portfolio equity curve as the sum of the individual curves. So if each strategy had its own capital (say 100 k apiece) and took losses at different points, their pullbacks partially offset each other.
    Max drawdown is calculated off that combined curve. Because the denominator (peak equity) is the sum of all accounts, any one strategy’s dip is being measured against a much larger base. If the other two are flat or profitable while one is sliding, the percentage drawdown of the aggregate can be much smaller than the drawdown of that single strategy on its own.
    So the improvement you’re seeing (from ~−19/−9/−9 % down to ~−7 %) is perfectly normal for the scenario where you’re actually running those strategies in separate 100 k sub-accounts and summing their balances—diversification smooths the combined curve.

    Just keep in mind the earlier caveat: if you mean “a single 100 k account split among three strategies and rebalanced day by day,” then we’d need the rebalance-style simulation to get realistic drawdowns; the current numbers assume independent capital pools.


would we expect rebalancing to reduce the drawdown even further?


    Rebalancing across strategies can help, but it isn’t guaranteed to drive drawdown lower than the “independent sub-accounts” approach you’re seeing now.

    Here’s what tends to happen when you rebalance:

    Exposure limits – Because each strategy gets resized to the same fraction of the portfolio every day, a high-conviction system can’t compound as aggressively during winning streaks. That dampens both the upside and the size of any subsequent drawdown.
    Shared losses – When all strategies struggle at once, the total drawdown will reflect that; splitting capital doesn’t magically eliminate correlated pain. Rebalancing just ensures no single system can dump a hugely outsized position into the portfolio.
    So in practice:

    If the strategies are only loosely correlated and don’t hit drawdowns simultaneously (like you’re seeing now), rebalancing may not beat the already-smooth combined curve; it might even look slightly worse because every trade was resized down to a smaller bankroll.
    If one strategy dominates risk—big swings relative to the others—rebalancing tends to shrink the headline drawdown because it keeps that exposure capped.
    Bottom line: rebalancing tightens capital discipline, but its effect on Max DD depends on how diversified and correlated the components are. It’s worth implementing as an option and comparing both modes on the same portfolio so you can decide which profile you prefer.


that's very interesting...
what other recommendations and insights can you provide regarding this multi strategy approach?
should we be looking to combine strategies that are not correlated?
how can we best identify these other than brute force testing out multi strategy portfolios?
we have built this software to do just this...
are there any other enchancements to this software that you can suggest or recommend in order of usefulness..



    Portfolio Insights

    Pairing strategies with low/negative correlation is the surest way to shrink portfolio drawdowns and smooth equity. Track rolling correlations (30/90-day) of daily PnL to see when systems start moving together.
    Look beyond correlation: cluster by trade duration, session window, instrument type, and entry catalyst. Mixing systems that exploit different market regimes lowers the odds they fail simultaneously.
    Monitor capital efficiency. Two strong but overlapping strategies might deliver less lift than a single system with higher Sharpe; periodic pruning keeps the portfolio lean.
    Rebalancing logic gives a second diversification lever: equal weight, volatility targeting, and tail-risk caps can be rotated depending on the regime.
    Tooling Enhancements (rough priority)

    Add per-strategy analytics: rolling correlation heatmap, contribution to total drawdown, marginal Sharpe.
    Implement alternative portfolio modes: daily risk parity, equal-risk contributions, and “single account” rebalance simulation to compare against the current summed approach.
    Surface capital-allocation stats: exposure by instrument, net/gross leverage, turnover, slippage allowances.
    Build stress-testing presets (e.g., 2020 March crash, 2022 CPI days) that replay each strategy over filtered days to reveal shared weak spots.
    Offer optimization helpers: brute-force weights with simple constraints, but also keep a guardrail (e.g., no more than X% weight shift per rebalance) to stay realistic.
    Capture metadata with each saved run (tags, notes, regime labels) so you can group and screen strategies quickly.
    Workflow Ideas

    Automate periodic scans: nightly job that evaluates new runs, updates portfolio candidates, and alerts you if correlation or drawdown breaches a threshold.
    Add “what-if” sliders on the portfolio table so you can temporarily tweak weights or drop a strategy and see the impact instantly.
    Persist raw minute data availability status and warn when a strategy’s dataset is stale—garbage inputs will sabotage any higher-level analytics.



    You already save each strategy’s trade/PnL series, so adding these analytics is mostly about reusing that data once a portfolio run is loaded.

    Rolling Correlation Heatmap

    First build daily PnL streams per strategy (aggregate intraday trades → day-level PnL).
    On every portfolio run, compute rolling correlations between each pair of strategies over a window (e.g., 30 or 60 trading days).
    Visualize it as a small matrix where rows and columns are strategy IDs and each cell shows the most recent rolling correlation, colour-coded from red (positive) through white (neutral) to blue (negative). Add a slider or mini-sparkline in the tooltip so you can scrub back through time.
    Useful because it flags converging behaviour: if two formerly independent strategies drift toward +0.8 correlation, you know diversification is decaying.
    Contribution to Total Drawdown

    Track the portfolio equity curve and note each drawdown start/valley.
    For the biggest drawdown(s), compute each strategy’s cumulative PnL change between peak and trough. Express it as absolute dollars and % of the portfolio drawdown.
    Surface it alongside the drawdown chart (e.g., stacked bars or a table).
    Helps you spot repeat offenders: if one strategy contributes 70% of every drawdown, you might trim or rethink it.
    Marginal Sharpe

    On the same daily PnL dataset, measure the portfolio Sharpe with all strategies, then recompute after removing each one.
    The change (“delta Sharpe”) is that strategy’s marginal Sharpe contribution.
    Present it as a bar chart sitting next to the portfolio stats.
    Lets you see which strategies genuinely boost risk-adjusted returns, and which might be dead weight despite positive standalone Sharpe.
    Implementing these would give you a quick diagnostic layer before you run heavy rebalances or add/remove systems—so you’re steering the portfolio with facts rather than gut feel.



when we consider correllations between strategies, are we interested in pairing strategies that don't both lose on the same day... 
i.e. either they both win on a given day or one wins and the other loses on a given day...

    Right—what you ultimately care about is whether the strategies drag the portfolio down together. Daily correlation is a convenient proxy, but it’s really the “co-loss” behaviour that matters:

    Negative or low correlation means the systems tend to move in different directions; when one dips, the other often offsets it. That’s ideal because your combined equity curve stays smoother.
    Positive correlation doesn’t necessarily kill a pairing if their losses don’t align. Two strategies can both be profitable most days (so correlation looks high) yet rarely post large losses on the same date. In that case you still get diversification when it counts.
    The danger zone is simultaneous losses—if both strategies post big red days together, your max drawdown balloons even if their overall correlation isn’t extreme.
    So a practical rule of thumb:

    Measure daily correlation to catch drift (strategies becoming more alike).
    Also track a simple “co-loss frequency” metric—e.g., percentage of days where both PnLs are negative, or the average portfolio loss on those overlap days.
    If two systems win simultaneously (sign of regime alignment) but only one loses when conditions flip, that’s a great complement; if they lose together often, consider trimming or hedging.
    Combining those views gives you a much clearer picture than correlation alone.



so given a portfolio of 3 or more strategies, how would we go about evaluating correlation? is this done only with pairing strategies?

    For a portfolio with 3+ strategies you typically start with the pairwise view, but you don’t stop there.

    1. Pairwise Rolling Correlation Matrix
    Compute daily PnL vectors for every strategy.
    Build the rolling correlation matrix (3×3, 5×5, etc.) so each cell shows how two strategies move together over the most recent window.
    Visualise it as a heatmap; scan for pairs drifting toward +1 (losing diversification) or −1 (potential hedge).
    This already tells you which combinations are redundant or complementary.
    2. Portfolio-Level Measures
    Once you have more than a handful of strategies, additional summary stats help:

    Average Pairwise Correlation: mean of the off-diagonal entries to see the portfolio’s overall “tightness.”
    Principal Component Analysis / Eigenvalues: shows how many independent “factors” your strategies really have. If the first component explains 80% of variance, most systems are effectively the same.
    Cluster Analysis: group strategies whose PnL series are similar; you may keep just one representative from each cluster to stay diversified.
    3. Loss-Side Checks
    Beyond correlations, record co-loss frequency for every pair (or cluster): share of days when both strategies are down. Even in a larger set you can present this as a second heatmap focused only on red days.

    4. Summary Dashboards
    Provide both levels in the UI:

    Matrix view (pairwise correlations) that updates with the latest window.
    Portfolio summary (average pairwise corr, number of dominant factors, worst co-loss pairs) so you don’t have to eyeball every cell.
    So yes, you compute correlations by pairs, but you then roll those pairwise values up into broader portfolio insights so that a 3-, 6-, or 12-strategy book remains manageable.



this is very interesting...
are there any books, research papers or youtube videos that delve into this type of analysis? I would like to learn more about this


    Here are some solid resources that dig into multi-strategy portfolio construction, correlations, and practical risk overlays:

    Books

    Quantitative Portfolio Management: The Art and Science of Statistical Arbitrage by Michael Isichenko & Helyette Geman — deep dive into multi-strategy construction, correlation management, and risk budgeting with plenty of math and implementation detail.
    Expected Returns by Antti Ilmanen — broader view of risk premia and diversification; the correlation chapters show how professional allocators think about blending strategies.
    Advances in Financial Machine Learning by Marcos López de Prado — especially Chapters 5–7, which cover feature clustering, correlation matrix cleaning (detoning), and portability of strategies.
    Academic / Practitioner Papers

    López de Prado (2018), “The Hierarchical Risk Parity Approach to Portfolio Construction” — explains why traditional covariance matrices fail and how to cluster strategies/ assets.
    Cliff Asness & co. (AQR) whitepaper “An Alternative Future: Strategic Multi-Asset Allocation” — shows the value of mixing low-correlated factor strategies.
    Markowitz’s original “Portfolio Selection” (1952) if you haven’t read it—it grounds everything, and modern extensions build on that intuition.
    Pardo & van der Meulen, “Portfolio of Trading Systems: Performance Measurement and Selection” — focused on futures/strategy overlays.
    Talks / Videos

    Marcos López de Prado’s presentations on portfolio clustering and machine learning for finance (several talks on YouTube; search “Lopez de Prado clustering portfolios”).
    AQR’s “Cliff Asness on Diversification” clips — accessible discussions of correlation decay and multi-strategy portfolios.
    QuantConnect/QuantInsti webinars on multi-strategy blending and risk overlays are very pragmatic; they often walk through code examples.
    Quantopian’s (archived) lectures on risk modeling and strategy correlation (look for “Quantopian Lecture Series: Risk”).
    Practical Implementation Guides / Blogs

    QuantStart and QuantInsti both publish tutorials on computing rolling correlations, cluster heatmaps, and risk parity with code snippets.
    RiskParityRadio (podcast + blog) often discusses how to blend strategies and evaluate correlation regimes.
    Pair a few of these with your current tooling and you’ll get a much deeper feel for how professionals balance diversification, rebalancing, and capital allocation across multiple edges.







    now let's turn our attention to automating the backtest...
when we select a symbol, I would like to be able to push a button - Auto Backtest

This will run backtests for all possible parameter combinations...
Mabye all combinations is too many here...

orb_m: 1 - 60 step 1
target_R : 0.1 to 10 step 0.1
stop_R : 0.1 to 10 step 0.1

ORB_Start: 9:30am to 4:00pm step 1 min
ORB_End: 9:30am to 4:00pm step 1 min

how many combinations would there be given these paramaters?

how can we best test many combinations of parameters and come up with the top 100 for further evaluation...
we can measure the "best" by looking at the MAR... the higher the MAR the better

let's consider a plan for this before proceeding with an implementation


Combos Explosion

orb_m 1→60 (60 values)
target_R 0.1→10 @0.1 (100 values)
stop_R 0.1→10 @0.1 (100 values)
ORB_Start 09:30→16:00 @1 min (390 values)
ORB_End same 390 values
If we naïvely test every combination, that’s 60 × 100 × 100 × 390 × 390 ≈ 9.1×10¹¹ runs—utterly infeasible (hundreds of billions).

Practical Strategy

Constrain the search space

Enforce ORB_End > ORB_Start to drop invalid pairs (roughly halves the time combos to ~390×195 on average, but still huge).
Limit the time windows to meaningful ranges (e.g., start 09:30–11:00, end 10:00–16:00) based on domain knowledge so you’re not testing nonsense like a 3-minute window at 15:55.
Coarsen the grid for a first pass (e.g., target/stop steps of 0.25 instead of 0.1, orb_m in 5-minute increments) to shortlist promising regions.
Stage the search

Phase 1 (coarse grid / random sampling): generate perhaps 10–20k combinations via Latin Hypercube or uniform random sampling within the bounds. Record metrics, rank by MAR, keep the top ~500.
Phase 2 (local refinement): Tightly resample around those top configurations using smaller steps, or run Nelder-Mead/grid refinements on target_R, stop_R, orb_m.
Phase 3 (dedupe + consistent ranking): Ensure you always re-run with full resolution once you have a manageable candidate list (~100).
Automation plan in code

Add an “Auto Backtest” control that queues combinations and iteratively executes them (using requestIdleCallback or chunked batches to keep UI responsive).
Persist intermediate results (MAR + params) to IndexedDB or streaming CSV so you can resume.
Maintain a min-heap of the top N MAR scores while sweeping through combinations; no need to sort everything.
Performance considerations

Cache per-day data loading once per symbol (already done).
Consider running the core backtest loop off-main-thread via Web Worker to avoid locking the UI.
Cap total iterations per button press with sensible defaults, e.g., “Try 5,000 random combos” with the option to stop/continue.
By following this staged approach you avoid the combinatorial blow-up, still cover the parameter space thoroughly, and end up with a curated top-100 set for manual review.




ok... now we need to think about how to improve the selection of a winning strategy result.

currently we are using MAR, but I can see some high MAR results that also have very high Max DD..

can we explore calculating some other metric.
ideally we want to find strategies that have a high return and very low volatility or drawdown...
essentially we want as smooth and equity curve as possible with a high return

what metrics do you suggest for this?


    MAR is a solid start—it's basically CAGR ÷ |Max DD|—but as you saw, a strategy can score well with a great CAGR even if the drawdown is still uncomfortably deep. To bias toward smoother equity curves, consider layering in at least one volatility-aware metric and one drawdown-smoothness metric:

    Metrics Worth Adding
    Sharpe Ratio (or a simplified Return/Volatility ratio)

    Uses the standard deviation of daily returns that we already compute. Penalizes equity curves with high volatility even if the CAGR is big.
    Sortino Ratio

    Same idea but only counts downside volatility (negative daily returns). Useful when upside spikes shouldn’t be punished.
    Ulcer Index (UI) and Ulcer Performance Index (UPI)

    UI measures drawdown depth and duration (root mean square of drawdowns).
    UPI = CAGR / UI gives a “smooth return” score. It heavily penalizes choppy equity even if final PnL is attractive.
    Calmar or MAR variants across windows

    We already store MAR. We can also compute MAR using a rolling drawdown (e.g. last 6 months) to catch strategies that recently got rough.
    Composite Score / Pareto ranking

    Combine multiple metrics (e.g. normalize MAR, Sharpe, and UPI) and either average them with weights or pick the Pareto-dominant set (no other strategy beats it on all chosen metrics).
    Example composite:
    score = 0.5 * normalized(UPI) + 0.3 * normalized(Sharpe) + 0.2 * normalized(CAGR)
    This still favors high return but only when volatility and drawdown are well-controlled.
    Implementation Ideas
    Extend computeSummaryMetrics to include:
    stdDailyRet (standard deviation of daily returns).
    downsideDeviation (std-dev of negative daily returns).
    ulcerIndex and ulcerPerf (requires the drawdown series, which we already compute for the chart).
    Add the new fields to the auto-backtest records and leaderboard so you can sort/filter by them.
    Update the ranking function in the auto backtest loop: instead of sorting solely by MAR, sort by your composite score or prefer entries where maxDDPct stays below a target while UPI/Sharpe stay high.
    Once we capture those metrics, you’ll get a clearer picture of “high return, low stress” strategies and can filter/sort the leaderboard accordingly. Let me know which metric you want to prioritise first and I can wire it into the summary calculation.






# OANDA Data

from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

client = API(access_token="YOUR_TOKEN")

params = {
    "granularity": "M1",    # 1‑minute candles
    "count": 500            # number of candles to fetch
    # optionally: "from": "2025-10-01T00:00:00Z", "to": "2025-10-02T00:00:00Z"
}

r = InstrumentsCandles(instrument="XAU_USD", params=params)
response = client.request(r)
candles = response.get("candles", [])
for c in candles:
    print(c["time"], c["mid"]["o"], c["mid"]["h"], c["mid"]["l"], c["mid"]["c"])