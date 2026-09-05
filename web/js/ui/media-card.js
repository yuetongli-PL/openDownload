import { html, raw } from "../core/dom.js";
import { coverUrl, parseDuration } from "../core/format.js";

/**
 * MediaCard({
 *   title, cover, duration, meta, views, date, actors,
 *   checkbox, checked, active, href, priority, id
 * })
 * 封面 16:10；priority=true 时输出 fetchpriority="high"
 */
export function MediaCard({
  title = "",
  cover = "",
  duration = "",
  meta = "",
  views = "",
  date = "",
  actors = [],
  checkbox = false,
  checked = false,
  active = false,
  href = "",
  priority = false,
  id = "",
} = {}) {
  const src = coverUrl(cover);
  const dur = parseDuration(duration);
  const bits = [meta, views, date].filter(Boolean);
  const actorLine = (actors || [])
    .map((a) => (typeof a === "string" ? a : a.name))
    .filter(Boolean)
    .join(" · ");
  if (actorLine) bits.push(actorLine);
  const img = src
    ? html`<img alt="" src="${src}" loading="${priority ? "eager" : "lazy"}" decoding="async" ${priority ? raw('fetchpriority="high"') : ""}>`
    : html`<span class="ph"></span>`;
  const inner = html`<article class="media-card ${active ? "is-active" : ""}" data-id="${id}">
    <div class="media-card-cover">
      ${img}
      ${dur ? html`<span class="media-card-dur">${dur}</span>` : ""}
      ${checkbox ? html`<label class="media-card-check"><input type="checkbox" ${checked ? "checked" : ""} aria-label="选择"></label>` : ""}
    </div>
    <h3 class="media-card-title">${title}</h3>
    <p class="media-card-meta">${bits.join(" · ")}</p>
  </article>`;
  return href ? html`<a href="${href}" class="media-card-link">${raw(inner)}</a>` : inner;
}
