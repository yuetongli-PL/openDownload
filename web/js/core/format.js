export const SITE_LABEL = { auto: "自动", jable: "Jable", youtube: "YouTube", douyin: "抖音" };

export const KIND_LABEL = {
  "youtube/video": "识别为 YouTube 视频",
  "youtube/channel": "识别为 YouTube 频道",
  "youtube/playlist": "识别为 YouTube 播放列表",
  "youtube/url": "识别为 YouTube 链接",
  "jable/video": "识别为 Jable 作品",
  "jable/user": "识别为 Jable 创作者",
  "jable/list": "识别为 Jable 列表",
  "jable/hot": "识别为 Jable 热门",
  "jable/pick": "识别为 Jable 选片",
  "douyin/video": "识别为抖音作品",
  "douyin/user": "识别为抖音主页",
  "douyin/hashtag": "识别为抖音话题",
  "douyin/feed": "识别为抖音推荐",
  "douyin/follow_feed": "识别为抖音关注流",
  "douyin/like": "识别为抖音喜欢",
  "need-site": "无法判断来源，请先选择 Jable / YouTube / 抖音",
};

export const PLACEHOLDERS = {
  auto: "粘贴链接，或输入用户名 / 番号",
  jable: "链接、番号，或创作者用户名（三上悠亜 / yua-mikami）",
  youtube: "视频链接、@频道 或用户名",
  douyin: "作品 / 主页链接，或抖音号",
};

export const YT_TABS = [
  { id: "all", name: "全部上传" },
  { id: "videos", name: "视频" },
  { id: "shorts", name: "Shorts" },
  { id: "streams", name: "直播" },
];

export const DY_MODES = [
  { id: "link", name: "作品 / 主页", hash: "#/douyin", placeholder: PLACEHOLDERS.douyin, note: "公开作品链接可游客解析。主页、推荐、关注、话题、喜欢需要 cookie。", empty: ["作品 / 主页", "粘贴作品或主页链接，也可以输入抖音号。"] },
  { id: "feed", name: "推荐", hash: "#/douyin/feed", placeholder: "可留空，直接点解析", note: "解析登录后的推荐流。需要 cookie；游客公开推荐也可试。", empty: ["推荐", "解析登录后的推荐流。需要 cookie；游客公开推荐也可试。"] },
  { id: "follow", name: "关注", hash: "#/douyin/follow", placeholder: "可留空，直接点解析", note: "解析关注作品流，需要 cookie。", empty: ["关注", "解析关注作品流，需要 cookie。"] },
  { id: "hashtag", name: "话题", hash: "#/douyin/hashtag", placeholder: "话题名，例如 旅行 或 #旅行", note: "输入话题名，例如 旅行 或 #旅行。需要 cookie。", empty: ["话题", "输入话题名，例如 旅行 或 #旅行。"] },
  { id: "likes", name: "喜欢", hash: "#/douyin/likes", placeholder: "粘贴用户主页链接", note: "粘贴用户主页链接，解析其喜欢列表。需要 cookie。", empty: ["喜欢", "粘贴用户主页链接，解析其喜欢列表。"] },
];

export const PHASE_ORDER = ["queued", "download", "decrypt", "remux", "done"];
export const PHASE_LABEL = { queued: "排队", download: "下载", decrypt: "解密", remux: "封装", done: "完成" };
export const PHASE_ALIAS = {
  parse: "download",
  m3u8: "download",
  running: "download",
  cancelled: "queued",
  error: "download",
};

export function kindLabel(det) {
  if (!det) return "";
  if (det.kind === "empty") return "";
  const key = det.kind === "need-site" ? "need-site" : `${det.site}/${det.kind}`;
  return KIND_LABEL[key] || `识别为 ${SITE_LABEL[det.site] || det.site} / ${det.kind}`;
}

export function fmtViews(n) {
  const num = Number(n);
  if (!Number.isFinite(num) || num <= 0) return "";
  if (num >= 1e6) return (num / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (num >= 1e3) return (num / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(Math.floor(num));
}

export function fmtDate(value) {
  if (!value) return "";
  const d = value instanceof Date ? value : new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function fmtSize(n) {
  const num = Number(n);
  if (!Number.isFinite(num) || num <= 0) return "";
  if (num < 1024) return num + " B";
  if (num < 1024 * 1024) return (num / 1024).toFixed(1) + " KB";
  if (num < 1024 * 1024 * 1024) return (num / 1024 / 1024).toFixed(1) + " MB";
  return (num / 1024 / 1024 / 1024).toFixed(1) + " GB";
}

export function relTime(ts) {
  if (!ts) return "";
  const sec = ts > 1e12 ? ts / 1000 : ts;
  const delta = Date.now() / 1000 - sec;
  if (delta < 60) return "刚刚";
  if (delta < 3600) return Math.floor(delta / 60) + " 分钟前";
  if (delta < 86400) return Math.floor(delta / 3600) + " 小时前";
  if (delta < 86400 * 7) return Math.floor(delta / 86400) + " 天前";
  return fmtDate(sec);
}

export function parseDuration(raw) {
  if (raw == null || raw === "") return "";
  if (typeof raw === "number") {
    const s = Math.max(0, Math.floor(raw));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  }
  return String(raw);
}

export function coverUrl(url) {
  if (!url) return "";
  if (url.startsWith("/api/")) return url;
  return "/api/proxy?url=" + encodeURIComponent(url);
}

export function normalizePhase(raw) {
  const key = String(raw || "");
  return PHASE_ALIAS[key] || key;
}

export function isActiveStatus(status) {
  return status === "queued" || status === "running";
}

export function taskTitle(task) {
  return task.title || (task.preview && task.preview.title) || task.label || "未命名任务";
}

export function todayStart() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}
