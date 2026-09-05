import { html, raw } from "../core/dom.js";
import { get } from "../core/api.js";
import { coverUrl, fmtViews } from "../core/format.js";
import { playKey, state, PAGE_SIZE } from "./state.js";
import { listTitle } from "./route.js";

export function isHexSlug(text) {
  return /^[a-f0-9]{32}$/i.test(String(text || "").trim());
}

export function junkActorName(name) {
  const t = String(name || "").trim();
  if (!t) return true;
  if (["演员", "女優", "女优", "首頁", "首页"].includes(t)) return true;
  if (/[«»‹›]/.test(t) || /首[頁页]/.test(t)) return true;
  if (isHexSlug(t)) return true;
  return false;
}

export function rememberModelName(slug, name) {
  const key = String(slug || "").trim();
  const label = String(name || "").trim();
  if (!key || !label || junkActorName(label)) return;
  const prev = state.modelNames[key] || "";
  if (prev && prev !== label && !isHexSlug(prev) && prev !== "演员" && prev !== "女優") return;
  state.modelNames[key] = label;
  try {
    localStorage.setItem("od-jable-models", JSON.stringify(state.modelNames));
  } catch {
    /* ignore */
  }
}

export function slugForActorName(name) {
  const want = String(name || "").trim();
  if (!want) return "";
  for (const slug of Object.keys(state.modelNames || {})) {
    if (state.modelNames[slug] === want) return slug;
  }
  return "";
}

export function fmtWorkDate(raw) {
  const text = String(raw || "").trim();
  const full = text.match(/(20\d{2})[./-](\d{1,2})[./-](\d{1,2})/);
  if (full) return `${full[1]}-${String(full[2]).padStart(2, "0")}-${String(full[3]).padStart(2, "0")}`;
  const ym = text.match(/^(20\d{2})[./-](\d{1,2})$/);
  if (ym) return `${ym[1]}-${String(ym[2]).padStart(2, "0")}`;
  const year = text.match(/^(20\d{2})$/);
  return year ? year[1] : "";
}

export function actorsFromTitle(title) {
  let text = String(title || "").trim();
  if (!text) return [];
  text = text.replace(/^[A-Z]{2,10}-?\d+\S*\s+/i, "").trim();
  const bits = text.split(/[\s　]+/).filter(Boolean);
  const skip = { 作品: 1, 出演: 1, 女優: 1, 女优: 1, デビュー: 1, SP: 1, SEX: 1, AV: 1 };
  let names = [];
  for (let i = bits.length - 1; i >= 0; i -= 1) {
    const token = bits[i].replace(/[·・,，。.!！?？]+$/g, "");
    if (!token || skip[token] || !/^(?:[A-Za-z][A-Za-z.\-]{1,19}|[\u4e00-\u9fff\u3040-\u30ff]{2,12})$/.test(token)) break;
    names.unshift(token);
  }
  if (names.length > 2) names = names.slice(-2);
  if (!names.length) {
    const m = text.match(/([\u4e00-\u9fff\u3040-\u30ff]{2,12})$/);
    if (m) names.push(m[1]);
  }
  return names.map((name) => ({ name, slug: slugForActorName(name) }));
}

export function parseActors(raw, title) {
  let listed = [];
  if (Array.isArray(raw)) {
    listed = raw
      .map((row) => {
        if (typeof row === "string") return { name: row, slug: "" };
        return { name: (row && (row.name || row.title)) || "", slug: (row && row.slug) || "" };
      })
      .filter((a) => a.name);
  } else if (raw) {
    listed = String(raw || "")
      .split(",")
      .map((part) => {
        const bits = part.split("|");
        return { name: (bits[0] || "").trim(), slug: (bits[1] || "").trim() };
      })
      .filter((a) => a.name);
  }
  if (listed.length) {
    return listed.filter((a) => a.name && !junkActorName(a.name)).map((a) => (a.slug ? a : { name: a.name, slug: slugForActorName(a.name) }));
  }
  return actorsFromTitle(title).filter((a) => a.name && !junkActorName(a.name));
}

export function attachPageActor(actors) {
  const list = (actors || []).filter((a) => a && a.name && !junkActorName(a.name));
  if (state.jmode !== "model" || !state.listSlug) return list;
  const slug = String(state.listSlug || "").trim();
  const name = listTitle();
  if (!slug || junkActorName(name)) return list;
  const prefix = /[\u4e00-\u9fff\u3040-\u30ff]/.test(name) ? name.slice(0, 2) : "";
  const rest = list.filter((a) => {
    if (a.slug === slug || a.name === name) return false;
    if (prefix && String(a.name || "").startsWith(prefix)) return false;
    return true;
  });
  return [{ name, slug }, ...rest].slice(0, 3);
}

export function rememberWork(it) {
  if (!it || !it.id) return;
  const id = playKey(it.id);
  const cur = state.workMap[id] || { id };
  if (it.title && it.title !== id) cur.title = it.title;
  if (it.cover) cur.cover = it.cover;
  if (it.preview) cur.preview = it.preview;
  if (it.duration) cur.duration = it.duration;
  if (it.views != null && it.views !== "") cur.views = it.views;
  if (it.likes != null) cur.likes = it.likes;
  if (fmtWorkDate(it.date) && (!fmtWorkDate(cur.date) || fmtWorkDate(it.date).length >= fmtWorkDate(cur.date).length)) {
    cur.date = it.date;
  }
  const actors = parseActors(it.actors, it.title || cur.title);
  if (actors.length) cur.actors = actors;
  cur.id = id;
  state.workMap[id] = cur;
}

export function hydrateItem(it) {
  if (!it || !it.id) return it;
  const id = playKey(it.id);
  const known = state.workMap[id] || {};
  const row = Object.assign({ id, title: id, cover: "", duration: "", views: 0, date: "", actors: [] }, known, it, { id });
  if (known.title && known.title !== id && (!row.title || row.title === id)) row.title = known.title;
  if (known.cover && !row.cover) row.cover = known.cover;
  if (known.duration && !row.duration) row.duration = known.duration;
  if ((row.views == null || row.views === "") && known.views != null) row.views = known.views;
  if (fmtWorkDate(known.date) && (!fmtWorkDate(row.date) || fmtWorkDate(known.date).length > fmtWorkDate(row.date).length)) {
    row.date = known.date;
  }
  const actors = parseActors(row.actors && row.actors.length ? row.actors : known.actors, row.title || known.title);
  if (actors.length) row.actors = actors;
  rememberWork(row);
  row.actors = attachPageActor(actors.length ? actors : parseActors(row.actors, row.title));
  return row;
}

function actorBits(item) {
  const actors = attachPageActor(parseActors(item.actors, item.title)).slice(0, 2);
  if (!actors.length) return "";
  const names = actors.map((a) => {
    if (a.slug) {
      rememberModelName(a.slug, a.name);
      return html`<a class="av-card-actor" href="#/jable/model/${encodeURIComponent(a.slug)}">${a.name}</a>`;
    }
    return html`<span>${a.name}</span>`;
  });
  return html`<span class="av-card-actors">${raw(names.join('<span class="av-card-actor-sep"> · </span>'))}</span>`;
}

export function cardHtml(item, opts = {}) {
  const id = playKey(item.id);
  const title = item.title || item.id || "";
  const src = item.cover ? coverUrl(item.cover) : "";
  const dur = item.duration || "";
  const views = item.views != null && item.views !== "" ? fmtViews(item.views) : "";
  const date = fmtWorkDate(item.date);
  const on = state.inspectCode && playKey(item.id) === playKey(state.inspectCode);
  const batch = !!opts.batch;
  const checked = batch && state.selected.has(id);
  const priority = !!opts.priority;
  const img = src
    ? html`<img alt="" src="${src}" loading="lazy" decoding="async" ${priority ? raw('fetchpriority="high"') : ""}>`
    : html`<span class="ph av-skel"></span>`;
  return html`<article class="av-card media-card ${on ? "is-inspect is-active" : ""}" data-code="${id}" data-id="${id}" tabindex="0">
    <div class="media-card-cover av-thumb">
      ${img}
      ${dur ? html`<span class="media-card-dur av-dur">${dur}</span>` : ""}
      ${batch ? html`<label class="media-card-check"><input type="checkbox" data-batch-check ${checked ? "checked" : ""} aria-label="选择 ${title}"></label>` : ""}
    </div>
    <h3 class="media-card-title av-card-title">${title}</h3>
    <p class="media-card-meta av-card-meta">
      ${views ? html`<span class="av-card-views">${views}</span>` : ""}
      ${date ? html`<span class="av-card-date">${date}</span>` : ""}
      ${raw(actorBits(item))}
    </p>
  </article>`;
}

export function skeletonHtml(count = PAGE_SIZE) {
  return html`${Array.from({ length: count }, () => html`<div class="av-skel skeleton" aria-hidden="true"></div>`)}<span class="sr-only">加载中</span>`;
}

export function emptyHtml(text, actionId) {
  return html`<div class="empty av-status" role="status">
    <h3>${text || "暂无作品"}</h3>
    <p>可以调整筛选条件后再试。</p>
    ${actionId ? html`<button type="button" class="btn btn-primary" data-empty-action="${actionId}">重试</button>` : ""}
  </div>`;
}

export function errorHtml(message) {
  return html`<div class="empty" role="alert">
    <h3>加载未完成</h3>
    <p>${message || "无法读取列表。检查网络后重试。"}</p>
    <button type="button" class="btn btn-primary" data-empty-action="retry">重试</button>
  </div>`;
}

export function fillGrid(host, items, skeletons, opts = {}) {
  if (!host) return;
  host.setAttribute("aria-busy", skeletons ? "true" : "false");
  if (skeletons) {
    // innerHTML: skeleton markup is static
    host.innerHTML = skeletonHtml(PAGE_SIZE);
    return;
  }
  const page = (items || []).slice(0, PAGE_SIZE).map(hydrateItem);
  if (!page.length) {
    host.innerHTML = emptyHtml(opts.empty || "暂无作品，可以调整筛选条件后再试。", opts.retry ? "retry" : "");
    return;
  }
  // innerHTML: cards built with html``
  host.innerHTML = page.map((it, i) => cardHtml(it, { batch: opts.batch, priority: i < 8 })).join("");
  enrichCardMeta(page);
}

export function markActiveCards(root, code) {
  const key = playKey(code);
  (root || document).querySelectorAll(".av-card").forEach((el) => {
    const on = playKey(el.dataset.code) === key && !!key;
    el.classList.toggle("is-inspect", on);
    el.classList.toggle("is-active", on);
  });
}

export function applyWorkMeta(it) {
  if (!it || !it.id) return;
  const id = playKey(it.id);
  const cur = state.workMap[id] || { id };
  if (it.date) cur.date = it.date;
  if (it.actors && it.actors.length) cur.actors = it.actors;
  if (it.title) cur.title = it.title;
  if (it.views != null) cur.views = it.views;
  if (it.duration) cur.duration = it.duration;
  if (it.cover) cur.cover = it.cover;
  state.workMap[id] = cur;
  Object.keys(state.listPageMap || {}).forEach((p) => {
    const rows = state.listPageMap[p] || [];
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i] && playKey(rows[i].id) === id) rows[i] = Object.assign({}, rows[i], cur);
    }
  });
}

export function patchCardMeta(root, it) {
  if (!it || !it.id) return;
  const card = (root || document).querySelector(`.av-card[data-code="${playKey(it.id)}"]`);
  if (!card) return;
  const meta = card.querySelector(".av-card-meta");
  if (!meta) return;
  const views = it.views != null && it.views !== "" ? fmtViews(it.views) : "";
  const date = fmtWorkDate(it.date);
  // innerHTML: meta rebuilt with html``
  meta.innerHTML = html`${views ? html`<span class="av-card-views">${views}</span>` : ""}${date ? html`<span class="av-card-date">${date}</span>` : ""}${raw(actorBits(it))}`;
}

export function enrichCardMeta(items) {
  const rows = (items || []).filter((it) => it && it.id);
  const need = rows.filter((it) => !fmtWorkDate(it.date) || !parseActors(it.actors, it.title).length);
  if (!need.length) return;
  const codes = need.map((it) => it.id).slice(0, 12);
  get("/api/jable/meta?wait=0&codes=" + encodeURIComponent(codes.join(",")))
    .then((data) => {
      ((data && data.items) || []).forEach((it) => {
        applyWorkMeta(it);
        const merged = Object.assign({}, state.workMap[playKey(it.id)] || {}, it);
        patchCardMeta(state.root, merged);
      });
    })
    .catch(() => {});
}

export function inspectVisibleItems(items, code) {
  const page = (items || []).slice(0, PAGE_SIZE);
  const key = playKey(code || state.inspectCode);
  if (!key) return page;
  const idx = page.findIndex((it) => playKey(it && it.id) === key);
  if (idx < 0 || idx < PAGE_SIZE) return page.slice(0, PAGE_SIZE);
  return page.slice(0, PAGE_SIZE - 1).concat([page[idx]]);
}
