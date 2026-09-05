import { get } from "../core/api.js";
import {
  PAGE_SIZE,
  PENDING_GAP_MS,
  PENDING_TRIES,
  PREFETCH_CAP,
  PREFETCH_MAX,
  later,
  onIdle,
  playKey,
  state,
  stopOrders,
  ui,
  every,
  ORDER_GAP_MS,
} from "./state.js";
import {
  applyCachedSnap,
  applyOrdersPayload,
  homeFallbackItems,
  ingestSnapshot,
  ingestWorksPayload,
  itemsForListPage,
  listCacheKey,
  listPageCount,
  listPageReady,
  listRequestUrl,
  loadListSnapshot,
  pageRequestUrl,
  readListCache,
  rememberListItems,
  snapshotUrl,
  stashListPage,
} from "./data.js";
import { rememberModelName } from "./cards.js";
import { listTitle } from "./route.js";

function current(req, jump) {
  return state.alive && req === state.listReq && (jump == null || jump === state.listJumpSeq);
}

export function applyListPage(data, page) {
  stashListPage(data, page);
  if (state.jmode === "model" && data && data.title) rememberModelName(state.listSlug, data.title);
  ui.paintJump(page);
}

export async function fetchJumpPage(page) {
  try {
    const data = await get(pageRequestUrl({ page }));
    if (data && data.items && data.items.length) return data;
    if (data && !data.pending) return data;
  } catch {
    /* fall through */
  }
  return get(listRequestUrl({ page }));
}

async function pollPending(page, req, jump) {
  for (let attempt = 0; attempt < PENDING_TRIES && current(req, jump); attempt += 1) {
    try {
      const data = await fetchJumpPage(page);
      if (!current(req, jump)) return;
      if (data && data.items && data.items.length) {
        applyListPage(data, page);
        return true;
      }
      if (data && !data.pending) {
        stashListPage(data, page);
        ui.paintJump(page);
        return true;
      }
    } catch {
      if (!current(req, jump)) return false;
    }
    if (itemsForListPage(page).length) return true;
    if (attempt < PENDING_TRIES - 1) await new Promise((resolve) => setTimeout(resolve, PENDING_GAP_MS));
  }
  return false;
}

export async function loadModelPage(page, req, jump = state.listJumpSeq) {
  const url = pageRequestUrl({ page });
  for (let attempt = 0; attempt < PENDING_TRIES && current(req, jump) && state.jmode === "model"; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!current(req, jump) || state.jmode !== "model") return;
      if (data.items && data.items.length) {
        applyListPage(data, page);
        return;
      }
      if (!data.pending) {
        stashListPage(data, page);
        ui.setListStatus("暂无作品");
        ui.paintJump(page);
        return;
      }
    } catch {
      if (!current(req, jump)) return;
    } finally {
      clearTimeout(timer);
    }
    if (itemsForListPage(page).length) return;
    ui.setListStatus("正在获取演员作品…");
    if (attempt < PENDING_TRIES - 1) await new Promise((resolve) => setTimeout(resolve, PENDING_GAP_MS));
  }
  if (!current(req, jump)) return;
  state.listError = "暂时无法获取演员作品，请稍后重试。";
  ui.paintJump(page);
}

export function prefetchListPages(fromPage) {
  const max = listPageCount();
  const ahead = state.jmode === "model" ? [1, 2, 3, 4] : [1, 2];
  ahead.forEach((d) => {
    const p = fromPage + d;
    if (p < 1) return;
    if (!state.listHasMore && p > max) return;
    if (listPageReady(p)) return;
    get(pageRequestUrl({ page: p }))
      .then((data) => {
        if (!state.alive) return;
        if (data && data.items && data.items.length) stashListPage(data, p);
        else if (data && data.pending) {
          get(listRequestUrl({ page: p }))
            .then((row) => {
              if (row && row.items && row.items.length) stashListPage(row, p);
            })
            .catch(() => {});
        }
      })
      .catch(() => {});
  });
}

export async function gotoListPage(page) {
  const raw = Math.max(1, Number(page) || 1);
  const max = listPageCount();
  page = state.listHasMore && raw > max ? raw : Math.min(raw, Math.max(max, 1));
  const jump = ++state.listJumpSeq;
  const req = state.listReq;
  if (state.jmode === "model") {
    ui.paintJump(page, { skeleton: !itemsForListPage(page).length });
    await loadModelPage(page, req, jump);
    return;
  }
  if (listPageReady(page)) {
    ui.paintJump(page);
    fetchJumpPage(page)
      .then((data) => {
        if (jump !== state.listJumpSeq || req !== state.listReq) return;
        if (data && data.items && data.items.length) applyListPage(data, page);
      })
      .catch(() => {});
    prefetchListPages(page);
    return;
  }
  state.pending = true;
  ui.paintJump(page, { skeleton: true });
  const ok = await pollPending(page, req, jump);
  state.pending = false;
  if (current(req, jump)) ui.paintJump(page);
  if (!ok && current(req, jump) && !itemsForListPage(page).length) {
    state.listError = "这一页还没准备好，请稍后重试。";
    ui.paintJump(page);
  } else if (current(req, jump)) {
    prefetchListPages(page);
  }
}

export async function pullJableList(req, title, retryPending) {
  try {
    const p1 = await get(listRequestUrl({ page: 1 }));
    if (req !== state.listReq) return;
    stashListPage(p1, 1);
    if (state.listPage === 1) ui.paintList(title || (p1 && p1.title));
    else ui.paintJump(state.listPage);
    get(listRequestUrl({ page: 2 }))
      .then((p2) => {
        if (req !== state.listReq) return;
        stashListPage(p2, 2);
        ui.paintJump(state.listPage);
      })
      .catch(() => {});
    get(listRequestUrl({ page: 3 }))
      .then((p3) => {
        if (req !== state.listReq) return;
        stashListPage(p3, 3);
      })
      .catch(() => {});
    scheduleSiblingPrefetch();
    if (p1 && p1.pending && retryPending) {
      [400, 900].forEach((ms) => later(() => pullJableList(req, title, false), ms));
    }
  } catch (err) {
    if (req !== state.listReq) return;
    if (!retryPending) return;
    if (!(state.listItems && state.listItems.length)) {
      state.listError = (err && err.message) || "加载未完成";
      ui.paintList();
    }
  }
}

export function scheduleModelSnapRefresh(req) {
  if (state.jmode !== "model") return;
  [1200, 3200, 7000, 14000].forEach((ms) => {
    later(() => {
      if (req !== state.listReq || state.jmode !== "model") return;
      const total = Number(state.listTotal) || 0;
      if (total && (state.listCodes || []).length >= total) return;
      loadListSnapshot(req).then(() => {
        if (req !== state.listReq) return;
        if (listPageReady(state.listPage || 1)) ui.paintJump(state.listPage || 1);
      });
    }, ms);
  });
}

function neighborTargets() {
  const mode = state.jmode;
  const targets = [];
  const currentKey = listCacheKey();
  const push = (t) => {
    if (listCacheKey(t.jmode, t.slug, t.sort, t.year, t.month) === currentKey) return;
    targets.push(t);
  };
  if (["hot", "week", "month", "all"].includes(mode)) {
    const order = ["hot", "week", "month", "all"];
    const sorts = { hot: "video_viewed_today", week: "video_viewed_week", month: "video_viewed_month", all: "video_viewed" };
    const i = order.indexOf(mode);
    [i - 1, i + 1, i - 2, i + 2].forEach((j) => {
      if (j >= 0 && j < order.length) push({ jmode: order[j], slug: "", sort: sorts[order[j]], year: "", month: "" });
    });
  } else if (mode === "latest") {
    const years = ((state.catalog && state.catalog.years) || [2026, 2025, 2024]).map(String);
    const yi = state.listYear ? years.indexOf(state.listYear) : 0;
    const nearby = yi < 0 ? years.slice(0, 3) : years.slice(Math.max(0, yi - 1), yi + 3);
    nearby.forEach((y) => push({ jmode: "latest", slug: "", sort: "post_date", year: y, month: "" }));
    if (state.listYear) {
      const m = Number(state.listMonth) || new Date().getMonth() + 1;
      [m - 1, m, m + 1]
        .filter((x) => x >= 1 && x <= 12)
        .forEach((mm) => push({ jmode: "latest", slug: "", sort: "post_date", year: state.listYear, month: String(mm) }));
    }
  } else if (["type", "cat", "tag"].includes(mode)) {
    const cats = (state.catalog && state.catalog.categories) || [];
    let start = 0;
    if (mode === "cat" && state.listSlug) {
      const i = cats.findIndex((c) => c.slug === state.listSlug);
      start = Math.max(0, i - 2);
    }
    cats.slice(start, start + 6).forEach((c) => {
      if (c && c.slug) push({ jmode: "cat", slug: c.slug, sort: "post_date_and_popularity", year: "", month: "" });
    });
    const groups = (state.catalog && state.catalog.groups) || [];
    const g = groups.find((x) => x.name === state.listGroup) || groups[0];
    ((g && g.tags) || []).slice(0, 6).forEach((t) => {
      if (t && t.slug) push({ jmode: "tag", slug: t.slug, sort: "post_date_and_popularity", year: "", month: "" });
    });
  }
  return targets.slice(0, PREFETCH_CAP);
}

async function prefetchJableList(target) {
  const key = listCacheKey(target.jmode, target.slug, target.sort, target.year, target.month);
  try {
    let existing = null;
    try {
      existing = JSON.parse(localStorage.getItem(key) || "null");
    } catch {
      existing = null;
    }
    if (existing && existing.pages && Number(existing.pageCount) > 1) return;
    const data = await get(listRequestUrl(target));
    const items = (data && data.items) || [];
    if (!items.length || data.pending) return;
    localStorage.setItem(key, JSON.stringify({ total: data.total || items.length, hasMore: !!data.has_more, pageCount: data.page_count || 0, pages: { 1: items } }));
  } catch {
    /* ignore */
  }
}

function pumpListPrefetch() {
  while (state.prefetchBusy < PREFETCH_MAX && state.prefetchQueue.length && !state.prefetchDead) {
    const target = state.prefetchQueue.shift();
    state.prefetchBusy += 1;
    prefetchJableList(target).finally(() => {
      state.prefetchBusy -= 1;
      if (!state.prefetchDead) pumpListPrefetch();
    });
  }
}

export function scheduleSiblingPrefetch() {
  onIdle(() => {
    if (!state.alive || state.prefetchDead) return;
    neighborTargets().forEach((t) => {
      const key = listCacheKey(t.jmode, t.slug, t.sort, t.year, t.month);
      if (state.prefetchQueue.some((x) => listCacheKey(x.jmode, x.slug, x.sort, x.year, x.month) === key)) return;
      if (state.prefetchQueue.length + state.prefetchBusy >= PREFETCH_CAP) return;
      state.prefetchQueue.push(t);
    });
    pumpListPrefetch();
  });
}

export function prefetchWorksOnce() {
  if (state.worksPrefetch) return;
  state.worksPrefetch = true;
  get("/api/jable/works")
    .then(ingestWorksPayload)
    .catch(() => {
      state.worksPrefetch = false;
    });
}

export function syncOrdersPoll() {
  const need = (state.jmode === "cat" || state.jmode === "tag") && state.alive;
  if (!need) {
    stopOrders();
    return;
  }
  const pull = () => {
    if (!state.alive || (state.jmode !== "cat" && state.jmode !== "tag")) {
      stopOrders();
      return;
    }
    get("/api/jable/orders")
      .then((data) => {
        const done = applyOrdersPayload(data);
        const n = Number((data && data.cache && data.cache.works) || 0);
        if (n > (state.worksKnown || 0)) get("/api/jable/works").then(ingestWorksPayload).catch(() => {});
        if (done) stopOrders();
      })
      .catch(() => {});
  };
  pull();
  if (!state.orderTimer) state.orderTimer = every(pull, ORDER_GAP_MS);
}

export function prefetchCatalogSnapshots() {
  prefetchWorksOnce();
  [
    { jmode: "hot", slug: "", sort: "video_viewed_today", year: "", month: "" },
    { jmode: "latest", slug: "", sort: "post_date", year: "", month: "" },
    { jmode: "type", slug: "", sort: "video_viewed", year: "", month: "" },
  ].forEach((target) => {
    const key = listCacheKey(target.jmode, target.slug, target.sort, target.year, target.month);
    if (state.snapCache[key] && state.snapCache[key].codes && state.snapCache[key].codes.length) return;
    get(snapshotUrl(target))
      .then((data) => ingestSnapshot(data, key, true))
      .catch(() => {});
  });
}

export async function openJableList() {
  const req = ++state.listReq;
  state.prefetchDead = false;
  const kind = state.jmode === "pick" ? "latest" : state.jmode;
  const title = listTitle();
  state.listPage = 1;
  state.listHasMore = true;
  state.listPageMap = {};
  state.listItems = [];
  state.listTotal = 0;
  state.listPageCount = 0;
  state.listError = "";
  const snapKey = listCacheKey();
  if (state.listSnapKey !== snapKey) {
    state.listCodes = [];
    state.listSnapKey = "";
  }
  const cached = readListCache();
  let instant = [];
  if (cached && cached.pages) {
    state.listPageMap = cached.pages;
    state.listTotal = cached.total || 0;
    state.listPageCount = cached.pageCount || Math.ceil((cached.total || 0) / PAGE_SIZE);
    state.listHasMore = !!cached.hasMore;
    instant = cached.pages[1] || [];
    const flat = [];
    Object.keys(cached.pages)
      .map(Number)
      .sort((a, b) => a - b)
      .forEach((p) => (cached.pages[p] || []).forEach((it) => flat.push(it)));
    state.listItems = flat;
  }
  if (!instant.length && !["model", "cat", "tag"].includes(kind)) {
    instant = homeFallbackItems(kind === "type" ? "hot" : kind) || [];
    state.listItems = instant;
    state.listPageMap = { 1: instant.slice(0, PAGE_SIZE) };
  }
  ui.paintList(title);
  if (!itemsForListPage(1).length) ui.paintJump(1, { skeleton: true });
  if (kind === "model") {
    await loadModelPage(1, req, ++state.listJumpSeq);
    return;
  }
  const snapped = applyCachedSnap(listCacheKey());
  if (snapped) {
    ui.paintList(title);
    loadListSnapshot(req).then(() => scheduleModelSnapRefresh(req));
    fetchJumpPage(1)
      .then((data) => {
        if (req !== state.listReq) return;
        if (data && data.items && data.items.length) applyListPage(data, 1);
        prefetchListPages(1);
      })
      .catch(() => {});
    scheduleSiblingPrefetch();
    syncOrdersPoll();
    return;
  }
  const snap = loadListSnapshot(req);
  await pullJableList(req, title, true);
  await snap;
  scheduleModelSnapRefresh(req);
  syncOrdersPoll();
}

export function scheduleHoverWarm(code) {
  const key = playKey(code);
  if (!key || state.hoverDone.has(key) || state.hoverInflight.has(key)) return;
  clearTimeout(state.hoverTimer);
  state.hoverTimer = later(() => {
    if (!state.alive) return;
    if (state.hoverInflight.size >= 2 && !state.hoverInflight.has(key)) return;
    state.hoverInflight.add(key);
    Promise.all([
      get("/api/jable/play/warm?codes=" + encodeURIComponent(key)).catch(() => {}),
      get("/api/dmm/preview/warm?codes=" + encodeURIComponent(key)).catch(() => {}),
    ]).finally(() => {
      state.hoverInflight.delete(key);
      state.hoverDone.add(key);
    });
  }, 250);
}

export function cancelHoverWarm() {
  clearTimeout(state.hoverTimer);
  state.hoverTimer = 0;
}

export { rememberListItems };
