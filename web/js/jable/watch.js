import { html, qs } from "../core/dom.js";
import { coverUrl } from "../core/format.js";
import { playKey, state } from "./state.js";
import { listHashBase } from "./route.js";
import { fillGrid } from "./cards.js";
import { knownItem } from "./data.js";
import { attachWatchHls, cachedPlayStream, destroyHls, getPlayInfo, loadHls, playErrorMessage } from "./player.js";

export function watchSectionHtml() {
  return html`<div id="jable-watch" hidden>
    <a id="jb-watch-back" class="jable-back" href="#/jable">返回列表</a>
    <video id="jb-video" class="jable-watch-video" controls playsinline muted></video>
    <div class="jable-watch-meta">
      <h2 id="jb-watch-title"></h2>
      <p id="jb-watch-sub"></p>
      <p id="jb-watch-status" class="jable-status"></p>
      <button type="button" id="jb-watch-dl" class="btn btn-primary">下载此片</button>
    </div>
    <section class="jable-sec">
      <h2>相关视频</h2>
      <div id="jb-related" class="media-grid av-grid"></div>
    </section>
  </div>`;
}

export function closeJableWatch() {
  state.watchCode = "";
  destroyHls(false);
  const watch = qs("#jable-watch");
  if (watch) watch.hidden = true;
}

export async function openJableWatch(code) {
  let raw = String(code || "").trim();
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* keep */
  }
  raw = playKey(raw);
  if (!raw) return;
  const feed = qs("#jable-feed");
  const list = qs("#jable-list");
  const watch = qs("#jable-watch");
  if (feed) feed.hidden = true;
  if (list) list.hidden = true;
  if (watch) watch.hidden = false;
  const back = qs("#jb-watch-back");
  if (back) back.href = state.watchFrom || listHashBase() || "#/jable";
  document.body.dataset.jmode = "watch";
  const title = qs("#jb-watch-title");
  const sub = qs("#jb-watch-sub");
  const status = qs("#jb-watch-status");
  const video = qs("#jb-video");
  if (state.watchCode === raw && state.hlsSrc && video) {
    video.play().catch(() => {});
    return;
  }
  state.watchCode = raw;
  if (title) title.textContent = raw.toUpperCase();
  if (sub) sub.textContent = "正在获取播放地址…";
  if (status) status.textContent = "";
  const known = knownItem(raw);
  if (video && known && known.cover) video.poster = coverUrl(known.cover);
  const homeItems = [
    ...(((state.jableHome || {}).hot || {}).items || []),
    ...(((state.jableHome || {}).latest || {}).items || []),
    ...(state.listItems || []),
  ].filter((it) => playKey(it.id) !== raw);
  fillGrid(qs("#jb-related"), homeItems.slice(0, 12));
  try {
    await loadHls();
  } catch {
    /* native */
  }
  const ready = state.hlsSrc || cachedPlayStream(raw);
  if (ready && video) {
    attachWatchHls(video, ready);
    if (sub) sub.textContent = "";
  }
  try {
    const data = await getPlayInfo(raw);
    if (state.watchCode !== raw) return;
    if (data.stream && video) attachWatchHls(video, data.stream);
    if (title) title.textContent = data.title || raw;
    if (sub) sub.textContent = [data.id, data.expires_at].filter(Boolean).join("  ·  ");
    if (video && data.cover && !video.poster) video.poster = coverUrl(data.cover);
    if (data.related && data.related.length) fillGrid(qs("#jb-related"), data.related);
    if (!data.stream && status) status.textContent = "没有播放地址";
  } catch (err) {
    if (status) status.textContent = playErrorMessage(err);
    if (sub) sub.textContent = "播放失败";
  }
}
