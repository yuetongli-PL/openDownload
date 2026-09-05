import { get } from "../core/api.js";
import { PAGE_SIZE, playKey, state, ui } from "./state.js";
import { hydrateItem, parseActors, rememberWork, rememberModelName } from "./cards.js";

export function listCacheKey(jmode, slug, sort, year, month) {
  const mode = jmode == null ? state.jmode : jmode;
  const s = (slug == null ? state.listSlug : slug) || "";
  const so = (sort == null ? state.listSort : sort) || "";
  const y = (year == null ? state.listYear : year) || "";
  const m = (month == null ? state.listMonth : month) || "";
  return `od-jable-list-${mode}-${s}-${so}-${y}-${m}`;
}

export function listTerm(kind, sort) {
  const so = sort == null ? state.listSort : sort;
  return kind === "latest"
    ? "post_date"
    : kind === "hot"
      ? "video_viewed_today"
      : kind === "week"
        ? "video_viewed_week"
        : kind === "month"
          ? "video_viewed_month"
          : kind === "all"
            ? "video_viewed"
            : kind === "type"
              ? "video_viewed"
              : ["likes", "duration"].includes(so)
                ? ""
                : so;
}

function kindOf(jmode) {
  const mode = jmode == null ? state.jmode : jmode;
  return mode === "pick" ? "latest" : mode === "home" ? "hot" : mode;
}

function qsOf(opts) {
  const o = opts || {};
  const jmode = o.jmode == null ? state.jmode : o.jmode;
  const kind = kindOf(jmode);
  const sort = o.sort == null ? state.listSort : o.sort;
  return {
    kind,
    slug: (o.slug == null ? state.listSlug : o.slug) || "",
    term: listTerm(kind, sort) || "",
    year: (o.year == null ? state.listYear : o.year) || "",
    month: (o.month == null ? state.listMonth : o.month) || "",
    page: String(o.page || 1),
  };
}

export function listRequestUrl(opts) {
  const q = new URLSearchParams({ ...qsOf(opts), pages: "1" });
  return "/api/jable/list?" + q.toString();
}

export function pageRequestUrl(opts) {
  return "/api/jable/page?" + new URLSearchParams(qsOf(opts)).toString();
}

export function snapshotUrl(opts) {
  const q = qsOf(opts);
  delete q.page;
  return "/api/jable/snapshot?" + new URLSearchParams(q).toString();
}

export function unpackCover(value, bases) {
  const text = String(value || "");
  if (!text) return "";
  if (text[1] === "/" && text[0] >= "0" && text[0] <= "9") {
    const i = Number(text[0]);
    return ((bases && bases[i]) || "") + text.slice(1);
  }
  return text;
}

export function normalizeSitePages(raw) {
  const pages = {};
  Object.entries(raw || {}).forEach(([key, rows]) => {
    const ids = (rows || []).map((id) => String(id || "").toLowerCase()).filter(Boolean);
    if (ids.length) pages[String(key)] = ids;
  });
  return pages;
}

export function pageCountOf(total, hasMore, page) {
  const n = Math.max(1, Math.ceil(Math.max(0, Number(total) || 0) / PAGE_SIZE));
  if (hasMore) return Math.max(n, (page || 1) + 1);
  return n;
}

export function pagerRange(page, pageCount, size) {
  const count = Math.max(1, Number(pageCount) || 1);
  const cur = Math.min(Math.max(1, Number(page) || 1), count);
  const win = Math.max(1, Number(size) || 5);
  if (count <= win) return { start: 1, end: count };
  const half = Math.floor(win / 2);
  let start = cur - half;
  let end = start + win - 1;
  if (start < 1) {
    start = 1;
    end = win;
  }
  if (end > count) {
    end = count;
    start = count - win + 1;
  }
  return { start, end };
}

export function expectedListPageSize(page) {
  const p = Math.max(1, Number(page) || 1);
  const total = Number(state.listTotal) || 0;
  if (total > 0) {
    const last = Math.ceil(total / PAGE_SIZE);
    if (p === last) return total % PAGE_SIZE || PAGE_SIZE;
  }
  return PAGE_SIZE;
}

export function cardForCode(id) {
  const code = playKey(id);
  if (!code) return null;
  let fromPage = null;
  const pages = state.listPageMap || {};
  const keys = Object.keys(pages);
  for (let i = 0; i < keys.length; i += 1) {
    const rows = pages[keys[i]] || [];
    for (let j = 0; j < rows.length; j += 1) {
      if (rows[j] && playKey(rows[j].id) === code) {
        fromPage = rows[j];
        break;
      }
    }
    if (fromPage) break;
  }
  return hydrateItem(fromPage || state.workMap[code] || { id: code, title: code, cover: "", duration: "", views: 0 });
}

export function itemsFromSitePages(page, need) {
  const hit = state.snapCache[listCacheKey()] || {};
  const pages = hit.pages || state.listSitePages || {};
  const sitePage = Math.floor(((Math.max(1, page) - 1) * PAGE_SIZE) / 24) + 1;
  const offset = ((Math.max(1, page) - 1) * PAGE_SIZE) % 24;
  const rows = pages[String(sitePage)] || pages[sitePage] || [];
  if (!rows.length || rows.length < offset + need) return [];
  return rows.slice(offset, offset + PAGE_SIZE).map((id) => cardForCode(id)).filter(Boolean);
}

export function itemsForListPage(page) {
  const p = Math.max(1, Number(page) || 1);
  const start = (p - 1) * PAGE_SIZE;
  const need = expectedListPageSize(p);
  if (state.listSnapKey === listCacheKey() && state.listCodes.length > start) {
    const ids = state.listCodes.slice(start, start + PAGE_SIZE);
    if (ids.length >= need && ids.every(Boolean)) return ids.map((id) => cardForCode(id)).filter(Boolean);
  }
  const siteItems = itemsFromSitePages(p, need);
  if (siteItems.length >= need) return siteItems;
  if (state.listPageMap && state.listPageMap[p] && state.listPageMap[p].length) return state.listPageMap[p].map(hydrateItem);
  return [];
}

export function listPageReady(page) {
  return itemsForListPage(page).length >= expectedListPageSize(page);
}

export function listPageCount() {
  if (state.listPageCount) return state.listPageCount;
  return pageCountOf(state.listTotal || 0, state.listHasMore, state.listPage);
}

export function applyCachedSnap(key) {
  const hit = state.snapCache[key];
  const hasCodes = !!(hit && hit.codes && hit.codes.length);
  const hasPages = !!(hit && hit.pages && Object.keys(hit.pages).length);
  if (!hasCodes && !hasPages) return false;
  if (hasCodes) state.listCodes = hit.codes;
  state.listSitePages = (hit && hit.pages) || {};
  state.listSnapKey = key;
  state.listTotal = Math.max(hit.total || 0, (hit.codes || []).length, state.listTotal || 0);
  state.listPageCount = Math.max(hit.pageCount || 0, Math.ceil((state.listTotal || (hit.codes || []).length) / PAGE_SIZE), 1);
  state.listHasMore = ((hit.codes || []).length || 0) < (state.listTotal || 0);
  return true;
}

export function ingestSnapshot(data, key, keepCurrent) {
  const cards = (data && data.cards) || [];
  const bases = (data && data.cover_bases) || ["https://assets-cdn.jable.tv", "https://static-assets-cdn.jable.tv"];
  const codes = [];
  const seen = new Set();
  const pushCode = (raw) => {
    const id = String(raw || "").toLowerCase();
    if (!id || seen.has(id)) return;
    seen.add(id);
    codes.push(id);
  };
  for (let i = 0; i < cards.length; i += 1) {
    const row = cards[i];
    const id = String((row && row[0]) || "").toLowerCase();
    if (!id) continue;
    pushCode(id);
    rememberWork({
      id,
      title: row[1] || id,
      cover: unpackCover(row[2] || "", bases),
      duration: row[3] || "",
      views: row[4] || 0,
      date: row[5] || "",
      actors: parseActors(row[6] || "", row[1] || id),
    });
  }
  const rawCodes = (data && data.codes) || [];
  for (let i = 0; i < rawCodes.length; i += 1) pushCode(rawCodes[i]);
  const pages = normalizeSitePages(data && data.pages);
  const prev = state.snapCache[key];
  if (prev && prev.pages) {
    Object.keys(prev.pages).forEach((k) => {
      if (!pages[k]) pages[k] = prev.pages[k];
    });
  }
  if (!codes.length && !Object.keys(pages).length) return false;
  if (state.jmode === "model" && data && data.title) rememberModelName(state.listSlug, data.title);
  if (prev && prev.codes && prev.codes.length > codes.length && !(state.jmode === "model" && codes.length)) {
    prev.pages = Object.assign({}, pages, prev.pages);
    prev.total = Math.max(prev.total || 0, Number((data && data.total) || 0) || 0, prev.codes.length);
    prev.pageCount = Math.max(prev.pageCount || 0, Math.ceil((prev.total || prev.codes.length) / PAGE_SIZE), 1);
    if (keepCurrent && key !== listCacheKey()) return true;
    return applyCachedSnap(key);
  }
  const total = Math.max(Number((data && data.total) || 0) || 0, codes.length);
  const pageCount = Math.max(Number((data && data.page_count) || 0) || 0, Math.ceil(total / PAGE_SIZE), 1);
  state.snapCache[key] = { codes, pages, total, pageCount };
  if (keepCurrent && key !== listCacheKey()) return true;
  state.listCodes = codes;
  state.listSitePages = pages;
  state.listSnapKey = key;
  state.listTotal = Math.max(total, state.listTotal || 0);
  state.listPageCount = Math.max(pageCount, state.listPageCount || 0);
  state.listHasMore = codes.length < total;
  return true;
}

export async function loadListSnapshot(req) {
  const key = listCacheKey();
  try {
    const data = await get(snapshotUrl());
    if (req != null && req !== state.listReq) return false;
    if (!ingestSnapshot(data, key)) return false;
    if (req != null && req !== state.listReq) return false;
    ui.paintList();
    return true;
  } catch {
    return false;
  }
}

export function rememberOrderSnap(jmode, slug, row) {
  const sort = jmode === "tag" || jmode === "cat" ? "post_date_and_popularity" : "";
  const key = listCacheKey(jmode, slug, sort, "", "");
  const codes = [];
  const seen = new Set();
  ((row && row.codes) || []).forEach((raw) => {
    const id = String(raw || "").toLowerCase();
    if (!id || seen.has(id)) return;
    seen.add(id);
    codes.push(id);
    if (!state.workMap[id]) state.workMap[id] = { id, title: id, cover: "", duration: "", views: 0 };
  });
  const pages = normalizeSitePages(row && row.pages);
  Object.values(pages).forEach((rows) => {
    rows.forEach((id) => {
      if (!state.workMap[id]) state.workMap[id] = { id, title: id, cover: "", duration: "", views: 0 };
    });
  });
  if (!codes.length && !Object.keys(pages).length) return;
  const total = Math.max(Number((row && row.total) || 0) || 0, codes.length);
  const prev = state.snapCache[key];
  const prevPages = (prev && prev.pages) || {};
  if (prev && prev.codes && prev.codes.length >= codes.length && (prev.total || 0) >= total && Object.keys(prevPages).length >= Object.keys(pages).length) {
    return;
  }
  state.snapCache[key] = {
    codes: codes.length >= ((prev && prev.codes) || []).length ? codes : prev.codes,
    pages: Object.assign({}, prevPages, pages),
    total: Math.max(total, (prev && prev.total) || 0),
    pageCount: Math.max(1, Math.ceil(Math.max(total, (prev && prev.total) || 0) / PAGE_SIZE)),
  };
  if (key === listCacheKey()) applyCachedSnap(key);
}

export function applyOrdersPayload(data) {
  Object.entries((data && data.tags) || {}).forEach(([slug, row]) => rememberOrderSnap("tag", slug, row));
  Object.entries((data && data.cats) || {}).forEach(([slug, row]) => rememberOrderSnap("cat", slug, row));
  if (state.jmode === "tag" || state.jmode === "cat") {
    const key = listCacheKey();
    if (applyCachedSnap(key) && listPageReady(state.listPage || 1)) ui.paintJump(state.listPage || 1);
  }
  return Number(data && data.complete) >= Number(data && data.lists);
}

export function ingestWorksPayload(data) {
  ingestSnapshot(data, "od-jable-works", true);
  state.worksKnown = Math.max(state.worksKnown || 0, ((data && data.cards) || []).length, Number((data && data.total) || 0) || 0);
  try {
    localStorage.setItem("od-jable-works", JSON.stringify({ total: data.total, cards: (data.cards || []).slice(0, 400), cover_bases: data.cover_bases }));
  } catch {
    /* quota */
  }
  if (state.listCodes.length && listPageReady(state.listPage || 1)) ui.paintJump(state.listPage || 1);
}

export function bootWorksCache() {
  try {
    const raw = JSON.parse(localStorage.getItem("od-jable-works") || "null");
    if (raw && raw.cards) ingestWorksPayload(raw);
  } catch {
    /* ignore */
  }
}

export function mergeListItems(base, extra) {
  const seen = new Set((base || []).map((it) => it && it.id).filter(Boolean));
  const out = (base || []).slice();
  for (const it of extra || []) {
    const id = it && it.id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(it);
  }
  return out;
}

export function rememberListItems() {
  try {
    localStorage.setItem(
      listCacheKey(),
      JSON.stringify({
        total: state.listTotal,
        hasMore: state.listHasMore,
        pageCount: state.listPageCount,
        pages: state.listPageMap || {},
      })
    );
  } catch {
    /* ignore */
  }
}

export function stashListPage(data, page) {
  const chunk = ((data && data.items) || []).map(hydrateItem);
  if (!state.listPageMap) state.listPageMap = {};
  state.listPageMap[page] = chunk.slice(0, PAGE_SIZE);
  const flat = [];
  Object.keys(state.listPageMap)
    .map(Number)
    .sort((a, b) => a - b)
    .forEach((p) => {
      (state.listPageMap[p] || []).forEach((it) => flat.push(it));
    });
  state.listItems = mergeListItems([], flat);
  if (data && data.total != null) state.listTotal = Math.max(state.listTotal || 0, Number(data.total) || 0, (data.items || []).length);
  else state.listTotal = Math.max(state.listTotal || 0, state.listItems.length);
  if (data && data.page_count != null) {
    state.listPageCount = Math.max(state.listPageCount || 0, Number(data.page_count) || 0, Math.ceil((state.listTotal || 0) / PAGE_SIZE), 1);
  } else {
    state.listPageCount = Math.max(1, Math.ceil((state.listTotal || 0) / PAGE_SIZE));
  }
  if (data && data.has_more != null) state.listHasMore = !!data.has_more;
  rememberListItems();
}

export function readListCache() {
  let raw = null;
  try {
    raw = JSON.parse(localStorage.getItem(listCacheKey()) || "null");
  } catch {
    raw = null;
  }
  if (Array.isArray(raw) && raw.length) {
    const pages = {};
    for (let i = 0; i < raw.length; i += PAGE_SIZE) pages[Math.floor(i / PAGE_SIZE) + 1] = raw.slice(i, i + PAGE_SIZE);
    return { total: raw.length, hasMore: true, pageCount: 0, pages };
  }
  if (raw && raw.pages) return raw;
  return null;
}

export function readLocalHome() {
  try {
    const raw = localStorage.getItem("od-jable-home-v1");
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data && (data.latest || data.hot)) return data;
  } catch {
    /* ignore */
  }
  return null;
}

export function homeFallbackItems(kind) {
  const home = state.jableHome || readLocalHome() || {};
  const hot = (home.hot && home.hot.items) || [];
  const latest = (home.latest && home.latest.items) || [];
  if (["hot", "week", "month", "all", "type"].includes(kind)) return hot.length ? hot : latest;
  return latest.length ? latest : hot;
}

export function knownItem(code) {
  const key = playKey(code);
  if (state.workMap[key]) return hydrateItem(state.workMap[key]);
  const pools = [state.listItems || [], (((state.jableHome || {}).hot || {}).items) || [], (((state.jableHome || {}).latest || {}).items) || []];
  for (const pool of pools) {
    const hit = pool.find((it) => playKey(it && it.id) === key);
    if (hit) return hydrateItem(hit);
  }
  return null;
}

export function sortListItems(items, sort) {
  const arr = (items || []).slice();
  const dur = (s) => {
    const parts = String(s || "").split(":").map((n) => Number(n) || 0);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return 0;
  };
  if (sort === "likes") arr.sort((a, b) => (b.likes || 0) - (a.likes || 0));
  else if (sort === "duration") arr.sort((a, b) => dur(b.duration) - dur(a.duration));
  return arr;
}
