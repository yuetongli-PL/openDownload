import { state } from "./state.js";
import { findListName } from "./filters.js";

function decode(part) {
  try {
    return decodeURIComponent(part || "");
  } catch {
    return String(part || "");
  }
}

export function defaultSort(mode) {
  if (mode === "hot") return "video_viewed_today";
  if (mode === "week") return "video_viewed_week";
  if (mode === "month") return "video_viewed_month";
  if (mode === "all" || mode === "type") return "video_viewed";
  if (mode === "latest") return "post_date";
  if (mode === "cat" || mode === "tag") return "post_date_and_popularity";
  if (mode === "model") return "post_date";
  return "";
}

export function parseJable(ctx) {
  const segs = (ctx && ctx.route && ctx.route.segments) || [];
  const params = (ctx && ctx.route && ctx.route.params) || {};
  const query = (ctx && ctx.route && ctx.route.query) || {};
  const rest = Array.isArray(params.rest) ? params.rest : segs.slice(2);
  let mode = params.mode || segs[1] || "home";
  if (mode === "link" || mode === "home" || !mode) mode = "home";
  if (mode === "actor") mode = "model";
  let video = "";
  let slug = "";
  let year = "";
  let month = "";
  let group = "";
  let sort = "";
  if (mode === "v") {
    mode = "watch";
    video = decode(rest[0] || segs[2] || "");
  } else if (mode === "cat" || mode === "tag") {
    slug = decode(rest[0] || "");
  } else if (mode === "model") {
    slug = decode(rest[0] || "");
    sort = rest[1] === "viewed" || rest[1] === "video_viewed" ? "video_viewed" : "post_date";
  } else if (mode === "type") {
    if (rest[0]) group = decode(rest[0]);
  } else if (mode === "latest") {
    if (/^\d{4}$/.test(rest[0] || "")) {
      year = rest[0];
      if (/^(0?[1-9]|1[0-2])$/.test(rest[1] || "")) month = String(Number(rest[1]));
    } else if (rest[0] === "m" && /^(0?[1-9]|1[0-2])$/.test(rest[1] || "")) {
      month = String(Number(rest[1]));
    }
  } else if (mode === "pick") {
    mode = "latest";
  }
  if (!sort) sort = defaultSort(mode);
  return {
    mode,
    video,
    slug,
    year,
    month,
    group,
    sort,
    inspect: String(query.p || "").trim(),
  };
}

export function isListMode(mode) {
  return ["latest", "hot", "week", "month", "all", "cat", "tag", "type", "model"].includes(mode);
}

export function latestHash(year, month) {
  const y = year === undefined ? state.listYear : year;
  const m = month === undefined ? state.listMonth : month;
  if (y && m) return `#/jable/latest/${y}/${m}`;
  if (y) return `#/jable/latest/${y}`;
  if (m) return `#/jable/latest/m/${m}`;
  return "#/jable/latest";
}

export function listHashBase() {
  const mode = state.jmode;
  if (mode === "cat" && state.listSlug) return `#/jable/cat/${encodeURIComponent(state.listSlug)}`;
  if (mode === "tag" && state.listSlug) return `#/jable/tag/${encodeURIComponent(state.listSlug)}`;
  if (mode === "model" && state.listSlug) {
    const base = `#/jable/model/${encodeURIComponent(state.listSlug)}`;
    return state.listSort === "video_viewed" ? `${base}/viewed` : base;
  }
  if (mode === "type" && state.listGroup) return `#/jable/type/${encodeURIComponent(state.listGroup)}`;
  if (mode === "latest") return latestHash();
  if (mode && mode !== "home" && mode !== "watch") return `#/jable/${mode}`;
  return "#/jable";
}

export function inspectHash(code) {
  const raw = String(code || "").trim();
  if (!raw) return listHashBase();
  return `${listHashBase()}?p=${encodeURIComponent(raw)}`;
}

export function watchHash(code) {
  const raw = String(code || "").trim().toLowerCase();
  return raw ? `#/jable/v/${encodeURIComponent(raw)}` : "#/jable";
}

export function listKeyOf(row) {
  const r = row || state;
  return [r.jmode || r.mode, r.listSlug || r.slug || "", r.listYear || r.year || "", r.listMonth || r.month || "", r.listGroup || r.group || "", r.listSort || r.sort || ""].join("|");
}

export function routeKeyOf(row) {
  return `${listKeyOf(row)}|${row.inspect || ""}|${row.video || ""}|${row.mode || row.jmode || ""}`;
}

export function applyParsed(parsed) {
  state.jmode = parsed.mode;
  state.listSlug = parsed.slug || "";
  state.listYear = parsed.year || "";
  state.listMonth = parsed.month || "";
  state.listGroup = parsed.group || "";
  state.listSort = parsed.sort || defaultSort(parsed.mode);
  if (parsed.mode === "tag" && parsed.slug && !state.listGroup) {
    /* filled later from catalog */
  }
}

export function listTitle() {
  let latestName = "最近添加";
  if (state.listYear && state.listMonth) latestName = `最近添加 · ${state.listYear}年${state.listMonth}月`;
  else if (state.listYear) latestName = `最近添加 · ${state.listYear}`;
  else if (state.listMonth) latestName = `最近添加 · ${state.listMonth}月`;
  const names = {
    latest: latestName,
    hot: "热门",
    week: "本周热门",
    month: "本月热门",
    all: "热门",
    type: "分类浏览",
  };
  if (state.jmode === "model") {
    const named = (state.modelNames && state.modelNames[state.listSlug]) || "";
    if (named && !/^[a-f0-9]{32}$/i.test(named)) return named;
    return "演员";
  }
  if (state.jmode === "cat" || state.jmode === "tag") {
    return findListName(state.listSlug) || state.listSlug || "分类浏览";
  }
  return names[state.jmode] || "影片";
}

export function tabOf(mode) {
  if (["hot", "week", "month", "all"].includes(mode)) return "hot";
  if (["type", "cat", "tag"].includes(mode)) return "type";
  if (mode === "latest") return "latest";
  if (mode === "model") return "model";
  if (mode === "watch") return "watch";
  return "home";
}
