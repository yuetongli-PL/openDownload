export const PAGE_SIZE = 12;
export const PAGER_WINDOW = 5;
export const PLAY_TTL_MS = 4 * 60 * 1000;
export const HOVER_DWELL_MS = 250;
export const PREFETCH_MAX = 3;
export const PREFETCH_CAP = 12;
export const PENDING_TRIES = 15;
export const PENDING_GAP_MS = 1500;
export const ORDER_GAP_MS = 8000;

export const FAST_HLS_CONFIG = {
  enableWorker: true,
  lowLatencyMode: false,
  testBandwidth: false,
  startLevel: 0,
  startFragPrefetch: true,
  progressive: false,
  autoStartLoad: true,
  maxBufferLength: 36,
  maxMaxBufferLength: 90,
  maxBufferSize: 80 * 1000 * 1000,
  maxBufferHole: 0.5,
  backBufferLength: 24,
  nudgeMaxRetry: 8,
  fragLoadingTimeOut: 20000,
  fragLoadingMaxRetry: 6,
  fragLoadingRetryDelay: 400,
  fragLoadingMaxRetryTimeout: 8000,
  manifestLoadingTimeOut: 20000,
  levelLoadingTimeOut: 20000,
};

export const ui = {
  paintList() {},
  paintJump() {},
  paintHome() {},
  fillGrid() {},
  renderFilters() {},
  setListStatus() {},
  toast() {},
  live() {},
};

export function setUI(partial) {
  Object.assign(ui, partial);
}

export const state = {
  alive: false,
  ctx: null,
  root: null,
  catalog: null,
  jableHome: null,
  jableHomeLoading: false,
  jmode: "home",
  listSlug: "",
  listYear: "",
  listMonth: "",
  listGroup: "",
  listSort: "",
  listItems: [],
  listPage: 1,
  listPageMap: {},
  listHasMore: true,
  listTotal: 0,
  listPageCount: 0,
  listReq: 0,
  listCodes: [],
  listSnapKey: "",
  listSitePages: {},
  listJumpSeq: 0,
  homeHotPage: 1,
  homeLatestPage: 1,
  workMap: {},
  snapCache: {},
  worksKnown: 0,
  worksPrefetch: false,
  modelNames: {},
  inspectCode: "",
  inspectSource: "",
  inspectPlay: "preview",
  inspectHls: null,
  inspectHlsSrc: "",
  watchCode: "",
  watchFrom: "#/jable",
  hls: null,
  hlsSrc: "",
  playCache: new Map(),
  playInflight: new Map(),
  hlsWarm: new Set(),
  dmmHit: new Map(),
  dmmWarm: new Set(),
  dmmSeq: 0,
  batch: false,
  selected: new Set(),
  lastRouteKey: "",
  lastListKey: "",
  lastInspect: "",
  lastWatch: "",
  lastCardFocus: "",
  pending: false,
  listError: "",
  homeError: "",
  timers: new Set(),
  intervals: new Set(),
  idleIds: new Set(),
  observers: new Set(),
  unbind: [],
  prefetchQueue: [],
  prefetchBusy: 0,
  prefetchDead: false,
  orderTimer: 0,
  hoverTimer: 0,
  hoverInflight: new Set(),
  hoverDone: new Set(),
};

export function playKey(code) {
  return String(code || "").trim().toLowerCase();
}

export function addTimer(id) {
  state.timers.add(id);
  return id;
}

export function addInterval(id) {
  state.intervals.add(id);
  return id;
}

export function clearTimer(id) {
  clearTimeout(id);
  state.timers.delete(id);
}

export function later(fn, ms) {
  const id = setTimeout(() => {
    state.timers.delete(id);
    if (state.alive) fn();
  }, ms);
  return addTimer(id);
}

export function every(fn, ms) {
  const id = setInterval(() => {
    if (state.alive) fn();
  }, ms);
  return addInterval(id);
}

export function onIdle(fn) {
  const ric = window.requestIdleCallback;
  if (typeof ric === "function") {
    const id = ric(() => {
      state.idleIds.delete(id);
      if (state.alive) fn();
    }, { timeout: 1200 });
    state.idleIds.add(id);
    return id;
  }
  return later(fn, 300);
}

export function loadModels() {
  try {
    const saved = JSON.parse(localStorage.getItem("od-jable-models") || "{}");
    if (saved && typeof saved === "object") state.modelNames = saved;
  } catch {
    /* ignore */
  }
}

export function stopOrders() {
  if (state.orderTimer) {
    clearInterval(state.orderTimer);
    state.intervals.delete(state.orderTimer);
    state.orderTimer = 0;
  }
}

export function resetViewFlags() {
  state.inspectCode = "";
  state.inspectSource = "";
  state.inspectPlay = "preview";
  state.watchCode = "";
  state.batch = false;
  state.selected = new Set();
  state.pending = false;
  state.listError = "";
  state.lastRouteKey = "";
  state.lastListKey = "";
  state.lastInspect = "";
  state.lastWatch = "";
  state.prefetchDead = true;
  state.prefetchQueue = [];
  state.prefetchBusy = 0;
  clearTimeout(state.hoverTimer);
  state.hoverTimer = 0;
  stopOrders();
}

export function wipeSideEffects() {
  state.timers.forEach((id) => clearTimeout(id));
  state.intervals.forEach((id) => clearInterval(id));
  state.idleIds.forEach((id) => {
    if (typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(id);
  });
  state.timers.clear();
  state.intervals.clear();
  state.idleIds.clear();
  state.observers.forEach((ob) => {
    try {
      ob.disconnect();
    } catch {
      /* ignore */
    }
  });
  state.observers.clear();
  state.unbind.forEach((fn) => {
    try {
      fn();
    } catch {
      /* ignore */
    }
  });
  state.unbind = [];
  resetViewFlags();
}
