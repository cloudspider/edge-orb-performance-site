// optimizer.js
// Placeholder module for automated parameter search logic.
// Exports parameter space definitions and helper utilities; wiring happens later.

export const PARAMETER_SPACE = {
  orb_m: { type: 'int', min: 1, max: 60 },
  tp_R: { type: 'float', min: 0.1, max: 8.0 },
  sl_R: { type: 'float', min: 0.1, max: 8.0 },
  start_ny: { type: 'time', min: '09:30', max: '15:59' },
  end_ny: { type: 'time', min: '12:00', max: '15:59' },
  direction: { type: 'cat', values: ['LONG', 'SHORT', 'BOTH'] }
};

export const INITIAL_GRID = {
  orb_m: [5, 10, 15, 20, 25, 30],
  tp_R: Array.from({ length: 18 }, (_, i) => Number((0.3 + 0.1 * i).toFixed(1))),
  sl_R: Array.from({ length: 18 }, (_, i) => Number((0.3 + 0.1 * i).toFixed(1))),
  start_ny: ['09:30'],
  end_ny: ['15:30'],
  direction: ['BOTH']
};

export function describeInitialGrid() {
  const counts = Object.values(INITIAL_GRID).map(arr => arr.length);
  return counts.reduce((acc, val) => acc * val, 1);
}

export function* initialGridIterator(grid = INITIAL_GRID) {
  const {
    orb_m = [],
    tp_R = [],
    sl_R = [],
    start_ny = [],
    end_ny = [],
    direction = []
  } = grid || {};
  for (const m of orb_m) {
    for (const tp of tp_R) {
      for (const sl of sl_R) {
        for (const start of start_ny) {
          for (const end of end_ny) {
            for (const dir of direction) {
              yield {
                orb_m: m,
                tp_R: tp,
                sl_R: sl,
                start_ny: start,
                end_ny: end,
                direction: dir
              };
            }
          }
        }
      }
    }
  }
}

export function getInitialGridCombos(grid = INITIAL_GRID) {
  return Array.from(initialGridIterator(grid));
}

export class OptimizerCoordinator {
  constructor(options = {}) {
    this.options = options;
  }

  // Placeholder for future orchestration logic.
  async runBatch() {
    throw new Error('Auto backtest not implemented yet.');
  }
}

if (typeof window !== 'undefined') {
  window.ORBOptimizer = {
    PARAMETER_SPACE,
    INITIAL_GRID,
    describeInitialGrid,
    initialGridIterator,
    getInitialGridCombos
  };
}
