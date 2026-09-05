import { html, raw } from "../core/dom.js";
import { icon } from "./icons.js";
import { SITE_LABEL, isActiveStatus, taskTitle } from "../core/format.js";

export function TaskRow(task = {}, { compact = false } = {}) {
  const site = task.site || (task.preview && task.preview.site) || "";
  const status = task.status || "";
  const kind = task.kind || "";
  const pct = Math.max(0, Math.min(100, Number(task.percent) || 0));
  const active = isActiveStatus(status);
  const downloadDone = kind === "download" && status === "done";
  const parseDone = kind === "parse" && status === "done";
  const failed = status === "error";
  const statusText =
    status === "queued"
      ? "排队"
      : status === "running"
        ? `${pct}% · ${task.label || "进行中"}`
        : downloadDone
          ? "已完成"
          : parseDone
            ? "已解析"
            : status === "cancelled"
              ? "已取消"
              : task.error || "失败";
  const ico = site === "youtube" ? "youtube" : site === "douyin" ? "douyin" : site === "jable" ? "play" : "download";
  return html`<article class="task-row" data-task="${task.id}">
    <span aria-hidden="true">${raw(icon(ico))}</span>
    <div>
      <h3>${taskTitle(task)}</h3>
      <p>${SITE_LABEL[site] || site || task.kind || ""} · ${statusText}</p>
      ${active ? html`<div class="progress-bar" style="margin-top:6px"><i style="width:${pct}%"></i></div>` : ""}
    </div>
    ${compact
      ? ""
      : html`<div class="task-actions">
          ${active ? html`<button type="button" class="btn btn-ghost" data-act="cancel">取消</button>` : ""}
          ${downloadDone ? html`<button type="button" class="btn btn-ghost" data-act="open">打开目录</button>` : ""}
          ${failed
            ? html`<button type="button" class="btn btn-ghost" data-act="reopen">重试</button>`
            : html`<button type="button" class="btn btn-ghost" data-act="reopen">重开收藏单</button>`}
          ${!active ? html`<button type="button" class="btn btn-ghost" data-act="dismiss" aria-label="删除记录">${raw(icon("trash"))}</button>` : ""}
        </div>`}
  </article>`;
}
