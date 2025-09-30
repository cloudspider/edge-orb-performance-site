// optimizer.js
// Placeholder module for automated parameter search logic.
// Exports parameter space definitions and helper utilities; wiring happens later.

const TIME_HELPERS = (() => {
  const toMinutes = (timeStr) => {
    if (!timeStr) return 0;
    const [hh, mm] = timeStr.split(':').map(Number);
    return (Number.isFinite(hh) ? hh : 0) * 60 + (Number.isFinite(mm) ? mm : 0);
  };
  const toTimeString = (minutes) => {
    const clampVal = Math.max(0, Math.floor(minutes));
    const hh = Math.floor(clampVal / 60);
    const mm = clampVal % 60;
    return `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}`;
  };
  return { toMinutes, toTimeString };
})();

export const PARAMETER_SPACE = {
  orb_m: { type: 'int', min: 1, max: 60 },
  tp_R: { type: 'float', min: 0.1, max: 8.0, step: 0.1 },
  sl_R: { type: 'float', min: 0.1, max: 8.0, step: 0.1 },
  start_ny: { type: 'time', min: '09:30', max: '15:59' },
  end_ny: { type: 'time', min: '12:00', max: '15:59' },
  direction: { type: 'cat', values: ['LONG', 'SHORT', 'BOTH'] }
};

export const INITIAL_GRID = {
  orb_m: [5, 10, 15, 20, 25, 30],
  tp_R: Array.from({ length: 18 }, (_, i) => Number((0.3 + 0.1 * i).toFixed(1))),
  sl_R: Array.from({ length: 18 }, (_, i) => Number((0.3 + 0.1 * i).toFixed(1))),
  start_ny: ['09:30'],
  end_ny: ['13:30'],
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
            if (TIME_HELPERS.toMinutes(end) <= TIME_HELPERS.toMinutes(start)) continue;
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

const PARAM_ORDER = ['orb_m','tp_R','sl_R','start_ny','end_ny','direction'];

const SOBOL_DIRECTION_DATA = [
  { degree: 1, a: 0, m: [1] },
  { degree: 2, a: 1, m: [1,3] },
  { degree: 3, a: 1, m: [1,3,5] },
  { degree: 3, a: 2, m: [1,3,1] },
  { degree: 4, a: 1, m: [1,1,5,5] },
  { degree: 4, a: 4, m: [1,3,5,15] }
];

class SobolSampler {
  constructor(dimensions, startIndex = 0, maxBits = 30) {
    if (dimensions > SOBOL_DIRECTION_DATA.length) {
      throw new Error(`SobolSampler supports up to ${SOBOL_DIRECTION_DATA.length} dimensions.`);
    }
    this.dimensions = dimensions;
    this.maxBits = maxBits;
    this.index = 0;
    this.X = new Array(dimensions).fill(0);
    this.direction = SOBOL_DIRECTION_DATA.slice(0, dimensions).map(info => this.#buildDirectionNumbers(info));
    // Advance to startIndex
    for (let i = 0; i < startIndex; i++) {
      this.next();
    }
  }

  #buildDirectionNumbers(info) {
    const { degree, a, m } = info;
    const V = new Array(this.maxBits + 1).fill(0);
    for (let i = 1; i <= degree; i++) {
      V[i] = m[i - 1] << (32 - i);
    }
    for (let i = degree + 1; i <= this.maxBits; i++) {
      let value = V[i - degree] ^ (V[i - degree] >> degree);
      for (let k = 1; k <= degree - 1; k++) {
        if ((a >> (degree - 1 - k)) & 1) {
          value ^= V[i - k];
        }
      }
      V[i] = value;
    }
    return V;
  }

  next() {
    const result = new Array(this.dimensions);
    if (this.index === 0) {
      this.index = 1;
      return result.fill(0);
    }
    let value = this.index;
    let c = 1;
    while (value & 1) {
      value >>= 1;
      c += 1;
    }
    for (let dim = 0; dim < this.dimensions; dim++) {
      this.X[dim] ^= this.direction[dim][c];
      result[dim] = this.X[dim] / Math.pow(2, this.maxBits);
    }
    this.index += 1;
    return result;
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function mapUnitToParams(unitVector) {
  const { toMinutes, toTimeString } = TIME_HELPERS;
  const [uOrb, uTp, uSl, uStart, uEnd, uDir] = unitVector;
  const orb = Math.round(PARAMETER_SPACE.orb_m.min + uOrb * (PARAMETER_SPACE.orb_m.max - PARAMETER_SPACE.orb_m.min));
  const tpRange = PARAMETER_SPACE.tp_R;
  const slRange = PARAMETER_SPACE.sl_R;
  const tpStep = tpRange.step || 0.1;
  const slStep = slRange.step || 0.1;
  const tpRaw = tpRange.min + uTp * (tpRange.max - tpRange.min);
  const slRaw = slRange.min + uSl * (slRange.max - slRange.min);
  const tp = clamp(tpRange.min + Math.round((tpRaw - tpRange.min) / tpStep) * tpStep, tpRange.min, tpRange.max);
  const sl = clamp(slRange.min + Math.round((slRaw - slRange.min) / slStep) * slStep, slRange.min, slRange.max);
  const minStart = toMinutes(PARAMETER_SPACE.start_ny.min);
  const maxStartRaw = toMinutes(PARAMETER_SPACE.start_ny.max);
  const minEnd = toMinutes(PARAMETER_SPACE.end_ny.min);
  const maxEnd = toMinutes(PARAMETER_SPACE.end_ny.max);
  const maxStart = Math.min(maxStartRaw, maxEnd - 1);
  let startMinutes = clamp(Math.round(minStart + uStart * (maxStart - minStart)), minStart, maxStart);
  let endMinutes = clamp(Math.round(minEnd + uEnd * (maxEnd - minEnd)), minEnd, maxEnd);
  if (endMinutes <= startMinutes) {
    const proposed = startMinutes + 1;
    endMinutes = clamp(proposed, Math.max(minEnd, startMinutes + 1), maxEnd);
    if (endMinutes <= startMinutes) {
      startMinutes = clamp(startMinutes, minStart, Math.max(minStart, maxEnd - 1));
      endMinutes = clamp(startMinutes + 1, minEnd, maxEnd);
    }
  }
  const dirValues = PARAMETER_SPACE.direction.values;
  const dirIndex = clamp(Math.floor(uDir * dirValues.length), 0, dirValues.length - 1);
  return {
    orb_m: orb,
    tp_R: Number(tp.toFixed(3)),
    sl_R: Number(sl.toFixed(3)),
    start_ny: toTimeString(startMinutes),
    end_ny: toTimeString(endMinutes),
    direction: dirValues[dirIndex]
  };
}

export const SOBOL_DEFAULT_BATCH = 500;

export function getSobolBatch(batchSize = SOBOL_DEFAULT_BATCH, startIndex = 0) {
  const sampler = new SobolSampler(PARAM_ORDER.length, startIndex);
  const combos = [];
  for (let i = 0; i < batchSize; i++) {
    const vec = sampler.next();
    combos.push(mapUnitToParams(vec));
  }
  return { combos, nextIndex: startIndex + combos.length };
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
    getInitialGridCombos,
    getSobolBatch,
    SOBOL_DEFAULT_BATCH,
    mapUnitToParams
  };
}
