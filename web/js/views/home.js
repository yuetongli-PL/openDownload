import { html, raw, qs, delegate } from "../core/dom.js";
import { get } from "../core/api.js";
import { kindLabel, PLACEHOLDERS, relTime, fmtSize, SITE_LABEL, isActiveStatus, taskTitle } from "../core/format.js";
import { Button } from "../ui/button.js";
import { EmptyState } from "../ui/empty.js";
import { TaskRow } from "../ui/task-row.js";
import { icon } from "../ui/icons.js";

let ctx = null;
let root = null;
let timer = 0;
let off = null;
let unsub = null;

function detectBadge(text, warn) {
  const el = qs("#home-detect", root);
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("is-warn", Boolean(warn));
}

async function liveDetect() {
  const input = qs("#home-query", root);
  const text = input ? input.value.trim() : "";
  if (!text) {
    detectBadge("");
    return;
  }
  try {
    if (!ctx) return;
    const det = await ctx.api.post("/api/detect", { query: text, site: "auto" });
    if (!ctx) return;
    if (det.kind === "empty") {
      detectBadge("");
      return;
    }
    detectBadge(kindLabel(det), det.kind === "need-site");
  } catch {
    detectBadge("");
  }
}

function openCollect() {
  const input = qs("#home-query", root);
  const query = input ? input.value.trim() : "";
  if (!query) {
    if (input) input.focus();
    return;
  }
  ctx.collect.open({ query, site: "auto" });
  if (input) input.value = "";
}

async function recentLibrary() {
  try {
    const data = await get("/api/library?sort=mtime&order=desc&limit=8");
    if (data.items) return data.items.slice(0, 8);
    const rows = [];
    (data.sites || []).forEach((s) => {
      (s.recent || []).forEach((f) => rows.push({ ...f, site: s.site }));
    });
    rows.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
    return rows.slice(0, 8);
  } catch {
    return [];
  }
}

function libThumb(item) {
  if (item.cover) {
    return html`<img alt="" src="/api/library/file?rel=${encodeURIComponent(item.cover)}" loading="lazy" decoding="async">`;
  }
  return "";
}

function paint(tasks, libs) {
  const recentTasks = (tasks || []).slice(0, 5);
  const prev = qs("#home-query", root);
  const kept = prev ? prev.value : "";
  root.innerHTML = html`<section class="view view-home">
    <div class="hero">
      <h1>把喜欢的内容，留在本地。</h1>
      <p class="hero-lead">粘贴链接，预览确认后再收入馆藏。浏览不中断，任务可恢复。</p>
      <div class="home-composer">
        <div class="home-row">
          <input id="home-query" type="text" spellcheck="false" placeholder="${PLACEHOLDERS.auto}" aria-describedby="home-detect" value="${kept}">
          ${Button({ variant: "primary", label: "解析", attrs: 'data-home-parse' })}
        </div>
        <p id="home-detect" class="detect-badge" aria-live="polite"></p>
        <p class="steps-line"><strong>01</strong> 粘贴链接 <strong>02</strong> 预览与选择 <strong>03</strong> 确认保存</p>
      </div>
    </div>
    <div class="source-cards">
      <article class="source-card">
        <h3><i class="source-dot jable"></i> Jable</h3>
        <p>浏览热门、最新与分类</p>
        <nav aria-label="Jable 快捷">${["热门|#/jable/hot", "最新|#/jable/latest", "分类|#/jable/type"].map((x) => {
          const [n, h] = x.split("|");
          return html`<a href="${h}">${n}</a>`;
        })}</nav>
      </article>
      <article class="source-card">
        <h3><i class="source-dot youtube"></i> YouTube</h3>
        <p>视频、频道与播放列表</p>
        <nav aria-label="YouTube 快捷">
          <a href="#/youtube/videos">视频</a>
          <a href="#/youtube">频道</a>
          <a href="#/youtube">播放列表</a>
        </nav>
      </article>
      <article class="source-card">
        <h3><i class="source-dot douyin"></i> 抖音</h3>
        <p>作品与创作者主页</p>
        <nav aria-label="抖音快捷">
          <a href="#/douyin">作品 / 主页</a>
          <a href="#/douyin/feed">推荐</a>
          <a href="#/douyin/follow">关注</a>
          <a href="#/douyin/hashtag">话题</a>
          <a href="#/douyin/likes">喜欢</a>
        </nav>
      </article>
    </div>
    <div class="home-cols">
      <section class="home-col">
        <h2>最近任务</h2>
        ${recentTasks.length
          ? recentTasks.map((t) => TaskRow(t, { compact: true }))
          : EmptyState({ title: "还没有任务", text: "在上方粘贴链接并解析。", action: { label: "去解析", id: "focus" } })}
      </section>
      <section class="home-col">
        <h2>最近收入馆藏</h2>
        ${libs.length
          ? libs.map(
              (it) => html`<a class="home-lib-item" href="#/library?site=${it.site || ""}">
                <span class="home-lib-thumb is-${it.site || ""}">${libThumb(it)}</span>
                <span title="${it.name || ""}">${it.name || "未命名"} · ${[fmtSize(it.size), relTime(it.mtime)].filter(Boolean).join(" · ")}</span>
              </a>`
            )
          : EmptyState({ title: "馆藏还是空的", text: "确认保存后，成品会出现在这里。", action: { label: "查看馆藏", id: "lib" } })}
      </section>
    </div>
  </section>`;
}

export default {
  mount(el, next) {
    root = el;
    ctx = next;
    paint(ctx.tasks.list(), []);
    recentLibrary().then((libs) => {
      if (!ctx || !root) return;
      paint(ctx.tasks.list(), libs);
    });
    if (unsub) unsub();
    unsub = ctx.tasks.subscribe(() => {
      recentLibrary().then((libs) => {
        if (!ctx || !root) return;
        paint(ctx.tasks.list(), libs);
      });
    });
    off = delegate(root, "click", "[data-home-parse], [data-empty-action], [data-task]", (event, node) => {
      if (node.matches("[data-home-parse]") || node.dataset.emptyAction === "focus") {
        if (node.dataset.emptyAction === "focus") qs("#home-query", root)?.focus();
        else openCollect();
        return;
      }
      if (node.dataset.emptyAction === "lib") {
        ctx.navigate("#/library");
        return;
      }
    });
    root.addEventListener("keydown", onKey);
    root.addEventListener("input", onInput);
  },
  update(next) {
    ctx = next;
  },
  unmount() {
    if (off) off();
    if (unsub) unsub();
    if (root) {
      root.removeEventListener("keydown", onKey);
      root.removeEventListener("input", onInput);
    }
    off = unsub = null;
    root = null;
    ctx = null;
    clearTimeout(timer);
  },
};

function onKey(event) {
  if (event.key === "Enter" && event.target && event.target.id === "home-query") {
    event.preventDefault();
    openCollect();
  }
}

function onInput(event) {
  if (event.target && event.target.id === "home-query") {
    clearTimeout(timer);
    timer = setTimeout(liveDetect, 280);
  }
}
