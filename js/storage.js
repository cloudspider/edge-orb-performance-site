// Persistence layer for localStorage and IndexedDB interactions.

const STORAGE_EXPORT_VERSION = 1;
const LOCAL_STORAGE_KEYS = [
  'orbPortfolioList_v1',
  'orbPortfolioActive_v1',
  'orbAutoBacktestState_v1'
];

const INDEXED_DB_EXPORTS = [
  {
    name: 'orbBacktestDB',
    version: 2,
    stores: ['runs', 'autoResults']
  },
  {
    name: 'orb_portfolio',
    version: 1,
    stores: ['entries']
  }
];

function safeParse(value) {
  if (typeof value !== 'string') return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function collectLocalStorage(keys = LOCAL_STORAGE_KEYS) {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return {};
  }
  const result = {};
  for (const key of keys) {
    try {
      const value = window.localStorage.getItem(key);
      if (value !== null) {
        result[key] = value;
      }
    } catch {
      // Fall back to null marker so we know key existed but failed.
      result[key] = null;
    }
  }
  return result;
}

function getDbConfig(name) {
  return INDEXED_DB_EXPORTS.find(cfg => cfg && cfg.name === name) || null;
}

function openDatabase(name, version) {
  return new Promise((resolve, reject) => {
    const request = version ? window.indexedDB.open(name, version) : window.indexedDB.open(name);
    request.onerror = () => reject(request.error || new Error(`Failed to open ${name}`));
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = () => {
      // Abort unintended upgrades; we only read existing data.
      request.transaction.abort();
      reject(new Error(`Database ${name} needs upgrade before export`));
    };
  });
}

function readStore(db, storeName) {
  return new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains(storeName)) {
      resolve([]);
      return;
    }
    const tx = db.transaction(storeName, 'readonly');
    const store = tx.objectStore(storeName);
    const req = store.getAll();
    req.onsuccess = () => resolve(Array.isArray(req.result) ? req.result : []);
    req.onerror = () => reject(req.error || new Error(`Failed to read store ${storeName}`));
    tx.onerror = () => reject(tx.error || new Error(`Transaction error on store ${storeName}`));
    tx.onabort = () => reject(tx.error || new Error(`Transaction aborted on store ${storeName}`));
  });
}

async function collectIndexedDb(configs = INDEXED_DB_EXPORTS) {
  if (typeof window === 'undefined' || typeof window.indexedDB === 'undefined') {
    return {};
  }
  const result = {};
  for (const config of configs) {
    const { name, stores = [] } = config || {};
    if (!name) continue;
    try {
      const dbConfig = getDbConfig(name);
      const db = await openDatabase(name, dbConfig && dbConfig.version);
      const storeData = {};
      for (const storeName of stores) {
        try {
          storeData[storeName] = await readStore(db, storeName);
        } catch (err) {
          storeData[storeName] = { __error: err ? String(err.message || err) : 'Unknown error' };
        }
      }
      result[name] = storeData;
      db.close();
    } catch (err) {
      result[name] = { __error: err ? String(err.message || err) : 'Unknown error' };
    }
  }
  return result;
}

export async function buildExportPayload() {
  const localStorageData = collectLocalStorage();
  const indexedDbData = await collectIndexedDb();

  return {
    version: STORAGE_EXPORT_VERSION,
    exportedAt: new Date().toISOString(),
    environment: {
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
      platform: typeof navigator !== 'undefined' ? navigator.platform : null
    },
    localStorage: localStorageData,
    indexedDB: indexedDbData
  };
}

function makeDefaultFilename(timestamp = new Date()) {
  const pad = (num) => String(num).padStart(2, '0');
  const year = timestamp.getFullYear();
  const month = pad(timestamp.getMonth() + 1);
  const day = pad(timestamp.getDate());
  const hours = pad(timestamp.getHours());
  const minutes = pad(timestamp.getMinutes());
  return `orb-backup-${year}${month}${day}-${hours}${minutes}.json`;
}

export async function downloadExport(filename) {
  if (typeof window === 'undefined') {
    throw new Error('Download is only available in the browser.');
  }
  const payload = await buildExportPayload();
  const json = JSON.stringify(payload, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || makeDefaultFilename();
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  setTimeout(() => {
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }, 0);
  return payload;
}

export function parseExportFileContents(text) {
  const parsed = safeParse(text);
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Invalid export file contents.');
  }
  return parsed;
}

function applyLocalStorageImport(data = {}) {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    throw new Error('localStorage is not available.');
  }
  const applied = [];
  const removed = [];
  const skipped = [];
  for (const [key, value] of Object.entries(data)) {
    try {
      if (value === null || value === undefined) {
        window.localStorage.removeItem(key);
        removed.push(key);
      } else if (typeof value === 'string') {
        window.localStorage.setItem(key, value);
        applied.push(key);
      } else {
        skipped.push({ key, reason: 'Value must be a string or null.' });
      }
    } catch (err) {
      skipped.push({ key, reason: err ? String(err.message || err) : 'Failed to apply value.' });
    }
  }
  return { applied, removed, skipped };
}

function normalizeStoreRecords(records) {
  if (records && typeof records === 'object' && '__error' in records) {
    return { error: records.__error };
  }
  if (!Array.isArray(records)) {
    return { error: 'Store payload must be an array.' };
  }
  return { records };
}

async function applyIndexedDbImport(data = {}) {
  if (typeof window === 'undefined' || typeof window.indexedDB === 'undefined') {
    throw new Error('IndexedDB is not available.');
  }
  const dbResults = {};
  for (const [dbName, storesPayload] of Object.entries(data)) {
    if (!storesPayload || typeof storesPayload !== 'object') {
      dbResults[dbName] = { error: 'Invalid database payload.' };
      continue;
    }
    if ('__error' in storesPayload) {
      dbResults[dbName] = { error: storesPayload.__error };
      continue;
    }
    const dbConfig = getDbConfig(dbName);
    const stores = dbConfig ? dbConfig.stores : Object.keys(storesPayload);
    if (!stores || !stores.length) {
      dbResults[dbName] = { error: 'No stores defined for import.' };
      continue;
    }
    try {
      const db = await openDatabase(dbName, dbConfig && dbConfig.version);
      const storeResults = {};
      for (const storeName of stores) {
        const payload = normalizeStoreRecords(storesPayload[storeName]);
        if (payload.error) {
          storeResults[storeName] = { error: payload.error };
          continue;
        }
        const records = payload.records;
        try {
          await new Promise((resolve, reject) => {
            if (!db.objectStoreNames.contains(storeName)) {
              reject(new Error(`Store ${storeName} does not exist in ${dbName}.`));
              return;
            }
            const tx = db.transaction(storeName, 'readwrite');
            const store = tx.objectStore(storeName);
            const clearReq = store.clear();
            clearReq.onerror = () => reject(clearReq.error || new Error(`Failed to clear ${storeName}`));
            clearReq.onsuccess = () => {
              for (const record of records) {
                try {
                  store.put(record);
                } catch (err) {
                  reject(err);
                  return;
                }
              }
            };
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error || new Error(`Transaction error on ${storeName}`));
            tx.onabort = () => reject(tx.error || new Error(`Transaction aborted on ${storeName}`));
          });
          storeResults[storeName] = { inserted: records.length };
        } catch (storeErr) {
          storeResults[storeName] = { error: storeErr ? String(storeErr.message || storeErr) : 'Unknown store error' };
        }
      }
      dbResults[dbName] = storeResults;
      db.close();
    } catch (err) {
      dbResults[dbName] = { error: err ? String(err.message || err) : 'Failed to open database.' };
    }
  }
  return dbResults;
}

export async function importStoragePayload(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Import payload must be an object.');
  }
  const { version, localStorage: lsData = {}, indexedDB: idbData = {} } = payload;
  if (version && Number(version) > STORAGE_EXPORT_VERSION) {
    console.warn(`Import payload version ${version} is newer than supported version ${STORAGE_EXPORT_VERSION}. Attempting import anyway.`);
  }
  const localResult = applyLocalStorageImport(lsData);
  const indexedDbResult = await applyIndexedDbImport(idbData);
  return {
    version: version ?? null,
    localStorage: localResult,
    indexedDB: indexedDbResult
  };
}

if (typeof window !== 'undefined') {
  window.ORBStorage = window.ORBStorage || {};
  window.ORBStorage.buildExportPayload = buildExportPayload;
  window.ORBStorage.downloadExport = downloadExport;
  window.ORBStorage.parseExportFileContents = parseExportFileContents;
  window.ORBStorage.importStoragePayload = importStoragePayload;
}

export default {
  buildExportPayload,
  downloadExport,
  parseExportFileContents,
  importStoragePayload
};
