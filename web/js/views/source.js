import { html, qs, delegate } from "../core/dom.js";
import { get } from "../core/api.js";
import { PLACEHOLDERS, YT_TABS, DY_MODES, SITE_LABEL, relTime, fmtSize, kindLabel } from "../core/format.js";
import { Button } from "../ui/button.js";
import { SegmentedTabs, bindSegmented } from "../ui/chip.js";
import { EmptyState } from "../ui/empty.js";
import { StatusDot } from "../ui/status-dot.js";

const RECENT_MAX = 10;

function recentKey(site) {
  return `od-recent-${site}`;
}

function loadRecent(site) {
  try {
    const rows = JSON.parse(localStorage.getItem(recentKey(site)) || "[]");
    return Array.isArray(rows) ? rows.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function saveRecent(site, query, tab) {
  const text = String(query || "").trim();
  if (!text && tab !== "feed" && tab !== "follow") return;
  const rows = loadRecent(site).filter((r) => r.query !== text || r.tab !== tab);
  rows.unshift({ query: text, tab: tab || "", ts: Date.now() });
  try {
    localStorage.setItem(recentKey(site), JSON.stringify(rows.slice(0, RECENT_MAX)));
  } catch {
    /* ignore */
  }
}

function clearRecent(site) {
  try {
    localStorage.removeItem(recentKey(site));
  } catch {
    /* ignore */
  }
}

async function siteLibrary(site) {
  try {
    const data = await get(`/api/library?site=${encodeURIComponent(site)}&sort=mtime&order=desc&limit=8`);
    if (data.items) return data.items.slice(0, 8);
    const pack = (data.sites || []).find((s) => s.site === site);
    return ((pack && pack.recent) || []).map((f) => ({ ...f, site })).slice(0, 8);
  } catch {
    return [];
  }
}

let ctx = null;
let root = null;
let off = null;
let timer = 0;
let libs = [];

function siteOf(route) {
  return route.segments[0] === "douyin" ? "douyin" : "youtube";
}

function tabOf(route, site) {
  if (site === "youtube") {
    const t = route.params.tab || "all";
    return ["videos", "shorts", "streams"].includes(t) ? t : "all";
  }
  const m = route.params.mode || "link";
  return ["feed", "follow", "hashtag", "likes"].includes(m) ? m : "link";
}

function ytCaps() {
  return ["视频", "频道", "播放列表", "Shorts", "直播", "字幕", "1080p–4K"];
}

function paint() {
  const site = siteOf(ctx.route);
  const tab = tabOf(ctx.route, site);
  const dy = DY_MODES.find((m) => m.id === tab) || DY_MODES[0];
  const placeholder = site === "youtube" ? PLACEHOLDERS.youtube : dy.placeholder;
  const note = site === "youtube" ? "分栏仅在解析频道时生效。单条视频会忽略分栏；清晰度与字幕在预览里再选。" : dy.note;
  const cookie = ctx.store.get("health") || {};
  const recents = loadRecent(site);
  const prev = qs("#source-query", root);
  const kept = prev ? prev.value : "";
  root.innerHTML = html`<section class="view view-source">
    <header class="source-head">
      <div>
        <h1><i class="source-dot ${site}"></i> ${SITE_LABEL[site]}</h1>
        ${site === "youtube"
          ? html`<div class="source-caps">${ytCaps().map((c) => html`<span class="source-cap">${c}</span>`)}</div>`
          : html`<button type="button" class="btn btn-ghost" data-to-settings>${StatusDot({
              status: cookie.cookie ? "ok" : "warn",
              label: cookie.cookie ? "Cookie 就绪" : "缺少 Cookie",
            })}</button>`}
      </div>
    </header>
    <div class="source-compose">
      ${site === "youtube"
        ? SegmentedTabs({ items: YT_TABS.map((t) => ({ id: t.id, name: t.name })), value: tab, name: "yt" })
        : SegmentedTabs({ items: DY_MODES.map((m) => ({ id: m.id, name: m.name })), value: tab, name: "dy" })}
      <div class="home-row">
        <input id="source-query" type="text" spellcheck="false" placeholder="${placeholder}" value="${kept}">
        ${Button({ variant: "primary", label: site === "douyin" && (tab === "feed" || tab === "follow") ? "解析此流" : "解析", attrs: "data-source-parse" })}
      </div>
      <p id="source-detect" class="detect-badge" aria-live="polite"></p>
      <p class="source-note">${note}</p>
    </div>
    <div class="source-split">
      <section>
        <h2>最近解析 ${recents.length ? html`<button type="button" class="btn btn-ghost" data-clear-recent>清空</button>` : ""}</h2>
        ${recents.length
          ? html`<div class="recent-list">${recents.map((r, i) => html`<button type="button" class="recent-item" data-replay="${i}"><span>${r.query || (r.tab === "feed" ? "推荐流" : r.tab === "follow" ? "关注流" : "空")}</span><span>${relTime(r.ts / 1000)}</span></button>`)}</div>`
          : EmptyState({ title: "还没有解析记录", text: "在此页解析过的输入会留在本地，方便重放。" })}
      </section>
      <section>
        <h2>${SITE_LABEL[site]} 馆藏</h2>
        ${libs.length
          ? libs.map(
              (it) => html`<a class="home-lib-item" href="#/library?site=${site}">
                <span class="home-lib-thumb is-${site}">${it.cover ? html`<img alt="" src="/api/library/file?rel=${encodeURIComponent(it.cover)}" loading="lazy" decoding="async">` : ""}</span>
                <span>${it.name || "未命名"} · ${[fmtSize(it.size), relTime(it.mtime)].filter(Boolean).join(" · ")}</span>
              </a>`
            )
          : EmptyState({ title: "此来源还是空的", text: "确认保存后会出现在这里。", action: { label: "查看馆藏", id: "lib" } })}
      </section>
    </div>
  </section>`;
}

async function liveDetect() {
  const input = qs("#source-query", root);
  const badge = qs("#source-detect", root);
  const site = siteOf(ctx.route);
  const tab = tabOf(ctx.route, site);
  const text = input ? input.value.trim() : "";
  if (!badge) return;
  if (!text || (site === "douyin" && (tab === "feed" || tab === "follow"))) {
    badge.textContent = "";
    return;
  }
  try {
    if (!ctx) return;
    const det = await ctx.api.post("/api/detect", { query: text, site });
    if (!ctx || !badge) return;
    if (det.kind === "empty") {
      badge.textContent = "";
      return;
    }
    badge.textContent = kindLabel(det);
    badge.classList.toggle("is-warn", det.kind === "need-site");
  } catch {
    badge.textContent = "";
  }
}

function parseNow(query) {
  const site = siteOf(ctx.route);
  const tab = tabOf(ctx.route, site);
  const text = query != null ? query : (qs("#source-query", root)?.value || "").trim();
  if (site === "douyin" && tab === "hashtag" && !text) {
    qs("#source-query", root)?.focus();
    return;
  }
  if (site === "douyin" && tab === "likes" && !text) {
    qs("#source-query", root)?.focus();
    return;
  }
  if (site === "youtube" && !text) {
    qs("#source-query", root)?.focus();
    return;
  }
  if (site === "douyin" && (tab === "feed" || tab === "follow")) {
    saveRecent(site, text, tab);
    ctx.collect.open({ query: text, site, tab, dmode: tab });
    return;
  }
  if (!text) return;
  saveRecent(site, text, tab);
  ctx.collect.open({ query: text, site, tab, dmode: site === "douyin" ? tab : "" });
}

export default {
  async mount(el, next) {
    root = el;
    ctx = next;
    libs = await siteLibrary(siteOf(ctx.route));
    if (!ctx || !root) return;
    paint();
    bindSegmented(root);
    off = delegate(root, "click", "[data-source-parse], [data-clear-recent], [data-replay], [data-to-settings], [data-empty-action], [role=tab]", (event, node) => {
      if (node.matches("[role=tab]")) {
        const site = siteOf(ctx.route);
        const value = node.dataset.value;
        if (site === "youtube") ctx.navigate(value === "all" ? "#/youtube" : `#/youtube/${value}`);
        else ctx.navigate(value === "link" ? "#/douyin" : `#/douyin/${value}`);
        return;
      }
      if (node.matches("[data-source-parse]")) parseNow();
      else if (node.matches("[data-clear-recent]")) {
        clearRecent(siteOf(ctx.route));
        paint();
      } else if (node.hasAttribute("data-replay")) {
        const rows = loadRecent(siteOf(ctx.route));
        const row = rows[Number(node.dataset.replay)];
        if (!row) return;
        const input = qs("#source-query", root);
        if (input) input.value = row.query || "";
        parseNow(row.query);
      } else if (node.matches("[data-to-settings]") || node.dataset.emptyAction === "lib") {
        ctx.navigate(node.dataset.emptyAction === "lib" ? "#/library" : "#/settings");
      }
    });
    root.addEventListener("input", onInput);
    root.addEventListener("keydown", onKey);
  },
  async update(next) {
    ctx = next;
    libs = await siteLibrary(siteOf(ctx.route));
    if (!ctx || !root) return;
    paint();
  },
  unmount() {
    if (off) off();
    if (root) {
      root.removeEventListener("input", onInput);
      root.removeEventListener("keydown", onKey);
    }
    off = null;
    root = null;
    ctx = null;
    clearTimeout(timer);
  },
};

function onInput(event) {
  if (event.target && event.target.id === "source-query") {
    clearTimeout(timer);
    timer = setTimeout(liveDetect, 280);
  }
}

function onKey(event) {
  if (event.key === "Enter" && event.target && event.target.id === "source-query") {
    event.preventDefault();
    parseNow();
  }
}
