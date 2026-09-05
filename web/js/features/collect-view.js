import { html, raw } from "../core/dom.js";
import { coverUrl } from "../core/format.js";
import { Button } from "../ui/button.js";
import { MediaCard } from "../ui/media-card.js";
import { ProgressBar, progressExtra } from "../ui/progress.js";

export function stepMarkup(phase) {
  const steps = [
    { id: "parse", label: "解析" },
    { id: "preview", label: "预览" },
    { id: "save", label: "保存" },
  ];
  const map = { detecting: "parse", parsing: "parse", preview: "preview", downloading: "save", done: "save", error: "parse" };
  const cur = map[phase] || "parse";
  const idx = steps.findIndex((s) => s.id === cur);
  return html`<ol class="collect-steps" aria-label="收藏进度">${steps.map((s, i) => {
    const on = s.id === cur;
    const done = i < idx;
    return html`<li class="${on ? "is-on" : done ? "is-done" : ""}" ${on ? raw('aria-current="step"') : ""}><span class="collect-step-n" aria-hidden="true">${done ? "✓" : i + 1}</span>${s.label}</li>`;
  })}</ol>`;
}

export function buildParseBody({ query, site, tab, jable, limit = 40, dmode }) {
  const text = String(query || "").trim();
  const mode = dmode || tab;
  if (jable) {
    return { site: "jable", query: text || jable.mode || "", limit, jable };
  }
  if (site === "douyin" && mode === "feed") {
    return { query: "https://www.douyin.com/?recommend=1", site: "douyin", limit };
  }
  if (site === "douyin" && mode === "follow") {
    return { query: "https://www.douyin.com/follow", site: "douyin", limit };
  }
  if (site === "douyin" && mode === "hashtag") {
    const tag = text.replace(/^#/, "");
    return { query: tag ? `#${tag}` : "", site: "douyin", limit };
  }
  if (site === "douyin" && mode === "likes") {
    let likes = text;
    if (likes && /douyin\.com\/user\//i.test(likes) && !/showTab=/i.test(likes)) {
      likes += (likes.includes("?") ? "&" : "?") + "showTab=like";
    }
    return { query: likes, site: "douyin", limit };
  }
  const body = { query: text, site: site || "auto", limit };
  if (site === "youtube") body.tab = tab === "all" || !tab ? "" : tab;
  return body;
}

export function visibleIds(state) {
  const q = state.filter.trim().toLowerCase();
  return (state.preview && state.preview.items ? state.preview.items : [])
    .filter((it) => !q || String(it.title || "").toLowerCase().includes(q))
    .map((it) => it.id);
}

export function bodyHtml(state) {
  if (state.phase === "detecting") return html`<p>正在识别来源…</p>`;
  if (state.phase === "parsing") {
    return html`<p>正在拉取预览</p>
        <button type="button" class="btn btn-ghost" data-toggle-log aria-expanded="${state.logOpen ? "true" : "false"}">解析日志</button>
        <pre id="collect-log" class="collect-log" ${state.logOpen ? "" : "hidden"}>${state.logs.join("\n")}</pre>`;
  }
  if (state.phase === "error") {
    return html`<div class="empty">
        <h3>解析失败</h3>
        <p>${state.error || "无法完成解析。检查网络或 Cookie 后重试。"}</p>
        ${state.needSite
          ? html`<div class="site-pick">
              <button type="button" class="btn btn-secondary" data-pick-site="jable">Jable</button>
              <button type="button" class="btn btn-secondary" data-pick-site="youtube">YouTube</button>
              <button type="button" class="btn btn-secondary" data-pick-site="douyin">抖音</button>
            </div>`
          : ""}
      </div>`;
  }
  if (state.phase === "downloading") {
    const rec = state.progress || {};
    return html`${ProgressBar({ percent: rec.percent, phase: rec.phase, label: rec.label || "保存中", extra: progressExtra(rec) })}
        <button type="button" class="btn btn-ghost" data-toggle-log aria-expanded="${state.logOpen ? "true" : "false"}">引擎日志</button>
        <pre id="collect-log" class="collect-log" ${state.logOpen ? "" : "hidden"}>${state.logs.join("\n")}</pre>`;
  }
  if (state.phase === "done") {
    return html`<div class="empty">
        <h3>已收入馆藏</h3>
        <p>成品已按来源放入本地目录。</p>
      </div>`;
  }
  if (state.phase === "preview" && state.preview) return previewHtml(state);
  return html`<p>输入链接后开始解析。</p>`;
}

function previewHtml(state) {
  const preview = state.preview;
  const items = preview.items || [];
  const vis = visibleIds(state);
  const blocked = preview.downloadable === false;
  const qOn = preview.options && preview.options.quality;
  const sOn = preview.options && preview.options.subs;
  return html`
      ${preview.cover ? html`<div class="collect-banner"><img alt="" src="${coverUrl(preview.cover)}"></div>` : ""}
      <h3>${preview.title || "待确认"}</h3>
      <p class="source-note">${[preview.author, `${items.length} 条`].filter(Boolean).join(" · ")}</p>
      ${blocked ? html`<p class="collect-hint">${preview.hint || "该结果不能下载"}</p>` : html`<p class="source-note">${preview.hint || "勾选后确认保存"}</p>`}
      <div class="collect-tools">
        <label class="chip"><input type="checkbox" data-sel-all ${vis.length && vis.every((id) => state.selected.has(id)) ? "checked" : ""}> 全选</label>
        <span data-sel-count>已选 ${state.selected.size} / ${items.length}</span>
        <input type="search" data-card-filter placeholder="筛选标题" value="${state.filter}">
        <div class="seg-tabs" role="group" aria-label="清单视图">
          <button type="button" class="seg-tab" data-view="grid" aria-pressed="${state.view === "grid" ? "true" : "false"}">卡片</button>
          <button type="button" class="seg-tab" data-view="list" aria-pressed="${state.view === "list" ? "true" : "false"}">列表</button>
        </div>
        ${qOn
          ? html`<div role="radiogroup" aria-label="分辨率">
              ${["1080p", "2k", "4k"].map((q) => html`<label class="chip ${state.quality === q ? "is-on" : ""}"><input type="radio" name="quality" value="${q}" ${state.quality === q ? "checked" : ""}> ${q === "2k" ? "2K" : q === "4k" ? "4K" : "1080p"}</label>`)}
            </div>`
          : ""}
        ${sOn ? html`<label class="chip ${state.subs ? "is-on" : ""}"><input type="checkbox" data-subs ${state.subs ? "checked" : ""}> 字幕</label>` : ""}
      </div>
      <div class="collect-cards ${state.view === "list" ? "is-list" : ""}">
        ${items.map((item) => {
          const hide = state.filter && !String(item.title || "").toLowerCase().includes(state.filter.toLowerCase());
          const on = state.selected.has(item.id);
          return html`<div class="collect-item ${on ? "" : "is-off"}" data-id="${item.id}" data-title="${item.title || ""}" ${hide ? "hidden" : ""}>
            ${raw(MediaCard({
              title: item.title,
              cover: item.cover,
              duration: item.duration,
              meta: [item.author, item.subtitle].filter(Boolean).join(" · "),
              checkbox: true,
              checked: on,
              id: item.id,
            }))}
          </div>`;
        })}
      </div>`;
}

export function footHtml(state) {
  if (state.phase === "error") return Button({ variant: "primary", label: "重试", attrs: 'data-collect-retry' });
  if (state.phase === "downloading") return Button({ variant: "danger", label: "取消", attrs: 'data-collect-cancel' });
  if (state.phase === "done") {
    return html`${Button({ variant: "secondary", label: "打开目录", attrs: 'data-collect-folder' })}
        ${Button({ variant: "secondary", label: "查看馆藏", attrs: 'data-collect-library' })}
        ${Button({ variant: "primary", label: "新收藏单", attrs: 'data-collect-new' })}`;
  }
  if (state.phase === "preview") {
    const n = state.selected.size;
    const blocked = state.preview && state.preview.downloadable === false;
    return Button({
      variant: "primary",
      label: `确认保存 (${n})`,
      disabled: !n || blocked,
      attrs: 'data-collect-save',
    });
  }
  return "";
}
