(() => {
  const $ = (id) => document.getElementById(id);
  const query = $("query");
  const hint = $("hint");
  const board = $("board");
  const form = $("go");
  const btnParse = $("btn-parse");
  const logPanel = $("panel-log");
  const logEl = $("log");
  const logTitle = $("log-title");
  const logStatus = $("log-status");
  const confirmPanel = $("panel-confirm");
  const cardsEl = $("cards");
  const selAll = $("sel-all");
  const selCount = $("sel-count");
  const optQuality = $("opt-quality");
  const optSubs = $("opt-subs");
  const btnDownload = $("btn-download");
  const progressPanel = $("panel-progress");
  const barFill = $("bar-fill");
  const pctEl = $("pct");
  const progLabel = $("prog-label");
  const progExtra = $("prog-extra");
  const dlog = $("dlog");
  const btnCancel = $("btn-cancel");
  const settingsDlg = $("settings");
  const libraryDlg = $("library-dlg");
  const detectBadge = $("detect-badge");
  const toastEl = $("toast");

  const PLACEHOLDERS = {
    auto: "粘贴链接，或输入用户名 / 番号",
    jable: "链接、番号，或创作者用户名（三上悠亜 / yua-mikami）",
    youtube: "视频链接、@频道 或用户名",
    douyin: "作品 / 主页链接，或抖音号",
  };

  const KIND_LABEL = {
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

  const YT_TABS = [
    { id: "all", name: "全部上传" },
    { id: "videos", name: "视频" },
    { id: "shorts", name: "Shorts" },
    { id: "streams", name: "直播" },
  ];

  const PHASE_ORDER = ["queued", "download", "decrypt", "remux", "done"];
  const PHASE_ALIAS = {
    parse: "download",
    m3u8: "download",
    running: "download",
    cancelled: "queued",
    error: "download",
  };

  const state = {
    site: "auto",
    jmode: "link",
    dmode: "link",
    ytTab: "all",
    parseId: "",
    downloadId: "",
    preview: null,
    selected: new Set(),
    es: null,
    jableCatalog: null,
    hotTerm: "video_viewed_today",
    hotCat: "",
    pickGroup: "衣著",
    pickTag: "",
    pickTerm: "post_date_and_popularity",
    health: null,
    detectTimer: 0,
    toastTimer: 0,
    cardView: "grid",
    filter: "",
    jableHome: null,
    jableHomeLoading: false,
    watchCode: "",
    hls: null,
    hlsSrc: "",
    playCache: new Map(),
    playInflight: new Map(),
    hlsWarm: new Set(),
    dmmHit: new Map(),
    dmmWarm: new Set(),
    dmmWarmInflight: new Map(),
    dmmSeq: 0,
    heroIndex: 0,
    heroItems: [],
    heroTimer: 0,
    showHot: 12,
    showLatest: 12,
    homeHotPage: 1,
    homeLatestPage: 1,
    listKind: "latest",
    listSlug: "",
    listSort: "post_date",
    listYear: "",
    listMonth: "",
    listGroup: "",
    listItems: [],
    listShow: 12,
    listPage: 1,
    listPageMap: {},
    listHasMore: true,
    listTotal: 0,
    listPageCount: 0,
    listReq: 0,
    listCodes: [],
    listSnapKey: "",
    listSitePages: {},
    workMap: {},
    snapCache: {},
    inspectCode: "",
    inspectReturnCode: "",
    inspectSource: "",
    inspectPlay: "preview",
    inspectHls: null,
    inspectHlsSrc: "",
    watchFrom: "",
    modelNames: {},
  };
  try {
    const saved = JSON.parse(localStorage.getItem("od-jable-models") || "{}");
    if (saved && typeof saved === "object") state.modelNames = saved;
  } catch {
    /* ignore */
  }

  const PAGE_SIZE = 12;
  const DMM_PREFETCH_END = 131071;

  function dmmPlayUrl(code) {
    return "/api/dmm/preview/play?code=" + encodeURIComponent(playKey(code));
  }

  function warmDmmBatch(codes) {
    const keys = [];
    const seen = new Set();
    (codes || []).forEach((raw) => {
      const key = playKey(raw);
      if (!key || seen.has(key) || state.dmmHit.has(key)) return;
      seen.add(key);
      keys.push(key);
    });
    if (!keys.length) return;
    if (keys[0]) prefetchDmm(keys[0]);
    fetch("/api/dmm/preview/warm?codes=" + encodeURIComponent(keys.slice(0, 3).join(","))).catch(
      () => {}
    );
    keys.slice(1, 4).forEach((key) => prefetchDmm(key));
  }

  function prefetchDmm(code) {
    const key = playKey(code);
    if (!key || state.dmmHit.has(key) || state.dmmWarm.has(key)) return;
    state.dmmWarm.add(key);
    const src = dmmPlayUrl(key);
    const pending = fetch(src, {
      cache: "no-store",
      headers: { Range: "bytes=0-" + DMM_PREFETCH_END },
    })
      .then((res) => {
        if (res.ok || res.status === 206) state.dmmHit.set(key, src);
        else state.dmmWarm.delete(key);
      })
      .catch(() => {
        state.dmmWarm.delete(key);
      })
      .finally(() => {
        state.dmmWarmInflight.delete(key);
      });
    state.dmmWarmInflight.set(key, pending);
  }

  function attachDmmPreview(code, video, statusEl, mine) {
    if (!video) return;
    const key = playKey(code);
    const src = dmmPlayUrl(key);
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.preload = "auto";
    video.onerror = () => {
      if (!mine()) return;
      if (state.inspectPlay === "full") return;
      if (statusEl) statusEl.textContent = "暂无公开预览";
    };
    video.onloadeddata = () => {
      if (!mine()) return;
      state.dmmHit.set(key, src);
      if (statusEl) statusEl.textContent = "";
    };
    if (video.getAttribute("src") !== src) video.src = src;
    const play = video.play();
    if (play && play.catch) play.catch(() => {});
    const inflight = state.dmmWarmInflight.get(key);
    if (inflight && inflight.then) {
      inflight.then(() => {
        if (!mine()) return;
        if (video.readyState >= 2) return;
        if (video.getAttribute("src") !== src) video.src = src;
        const again = video.play();
        if (again && again.catch) again.catch(() => {});
      });
    }
  }

  function pageSizeNow() {
    return PAGE_SIZE;
  }

  function hashParts() {
    const rawFull = (location.hash || "").replace(/^#\/?/, "");
    const qAt = rawFull.indexOf("?");
    const raw = qAt >= 0 ? rawFull.slice(0, qAt) : rawFull;
    const inspect = (new URLSearchParams(qAt >= 0 ? rawFull.slice(qAt + 1) : "").get("p") || "").trim();
    const parts = raw.split("/").filter(Boolean);
    const head = parts[0] || "auto";
    if (head === "setup" || head === "library") {
      return { site: state.site || "auto", jmode: "link", dmode: "link", panel: head, inspect: "" };
    }
    const site = ["auto", "jable", "youtube", "douyin"].includes(head) ? head : "auto";
    let jmode = "link";
    let video = "";
    let listSlug = "";
    let listYear = "";
    let listMonth = "";
    let listGroup = "";
    let listSort = "";
    if (site === "jable") {
      const second = parts[1] || "";
      if (second === "v" && parts[2]) {
        jmode = "watch";
        video = parts[2];
      } else if (second === "cat" && parts[2]) {
        jmode = "cat";
        listSlug = decodeURIComponent(parts[2]);
      } else if (second === "tag" && parts[2]) {
        jmode = "tag";
        listSlug = decodeURIComponent(parts[2]);
      } else if ((second === "model" || second === "actor") && parts[2]) {
        jmode = "model";
        listSlug = decodeURIComponent(parts[2]);
        listSort = parts[3] === "viewed" || parts[3] === "video_viewed" ? "video_viewed" : "post_date";
      } else if (second === "type") {
        jmode = "type";
        if (parts[2]) listGroup = decodeURIComponent(parts[2]);
      } else if (second === "latest") {
        jmode = "latest";
        if (/^\d{4}$/.test(parts[2] || "")) {
          listYear = parts[2];
          if (/^(0?[1-9]|1[0-2])$/.test(parts[3] || "")) listMonth = String(Number(parts[3]));
        } else if (parts[2] === "m" && /^(0?[1-9]|1[0-2])$/.test(parts[3] || "")) {
          listMonth = String(Number(parts[3]));
        }
      } else if (["hot", "pick", "week", "month", "all", "link"].includes(second)) {
        jmode = second;
      }
    }
    const dmode =
      site === "douyin" && ["feed", "follow", "hashtag", "likes", "link"].includes(parts[1] || "")
        ? parts[1]
        : "link";
    return { site, jmode, dmode, video, listSlug, listYear, listMonth, listGroup, listSort, inspect, panel: "" };
  }

  function siteFromHash() {
    return hashParts().site;
  }

  function show(el, on) {
    if (el) el.classList.toggle("hidden", !on);
  }

  function setPhase(phase) {
    document.body.dataset.phase = phase;
  }

  function toast(text) {
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      toastEl.hidden = true;
    }, 2600);
  }

  function isJableList(mode) {
    return ["latest", "hot", "week", "month", "all", "cat", "tag", "type", "pick", "model"].includes(mode || state.jmode);
  }

  function latestHash(year, month) {
    const y = year === undefined ? state.listYear : year;
    const m = month === undefined ? state.listMonth : month;
    if (y && m) return `#/jable/latest/${y}/${m}`;
    if (y) return `#/jable/latest/${y}`;
    if (m) return `#/jable/latest/m/${m}`;
    return "#/jable/latest";
  }

  function listHashBase() {
    if (state.site !== "jable") return `#/${state.site || "auto"}`;
    if (state.jmode === "cat" && state.listSlug) return `#/jable/cat/${encodeURIComponent(state.listSlug)}`;
    if (state.jmode === "tag" && state.listSlug) return `#/jable/tag/${encodeURIComponent(state.listSlug)}`;
    if (state.jmode === "model" && state.listSlug) {
      const base = `#/jable/model/${encodeURIComponent(state.listSlug)}`;
      return state.listSort === "video_viewed" ? `${base}/viewed` : base;
    }
    if (state.jmode === "type" && state.listGroup) return `#/jable/type/${encodeURIComponent(state.listGroup)}`;
    if (state.jmode === "latest") return latestHash();
    if (state.jmode && state.jmode !== "link" && state.jmode !== "watch") return `#/jable/${state.jmode}`;
    return "#/jable";
  }

  function inspectHash(code) {
    const raw = String(code || "").trim();
    if (!raw) return listHashBase();
    return `${listHashBase()}?p=${encodeURIComponent(raw)}`;
  }

  function setJableMode(mode, pushHash, opts) {
    const nextMode = mode || "link";
    const prevMode = state.jmode;
    const prevKey =
      (opts && opts.before) ||
      `${prevMode}|${state.listSlug}|${state.listYear}|${state.listMonth}|${state.listGroup}|${state.listSort}`;
    const modeChanged = prevMode !== nextMode;
    if (modeChanged) {
      state.listShow = PAGE_SIZE;
      if (nextMode === "hot") state.listSort = "video_viewed_today";
      else if (nextMode === "week") state.listSort = "video_viewed_week";
      else if (nextMode === "month") state.listSort = "video_viewed_month";
      else if (nextMode === "all") state.listSort = "video_viewed";
      else if (nextMode === "latest") state.listSort = "post_date";
      else if (nextMode === "cat" || nextMode === "tag" || nextMode === "type") {
        state.listSort = "post_date_and_popularity";
      } else if (nextMode === "model" && prevMode !== "model") {
        state.listSort = "post_date";
      }
      if (state.inspectCode) closeJableInspect({ skipHash: true, skipPaint: true });
    }
    if (nextMode === "model") {
      const fromHash = hashParts();
      if (fromHash.listSort) state.listSort = fromHash.listSort;
    }
    state.jmode = nextMode;
    document.body.dataset.jmode = state.jmode;
    const tools = $("jable-tools");
    if (tools) tools.classList.add("hidden");
    document.querySelectorAll("#jb-av-nav [data-jmode]").forEach((btn) => {
      const tab = btn.dataset.jmode;
      let on = tab === state.jmode;
      if (tab === "hot") on = ["hot", "week", "month", "all"].includes(state.jmode);
      if (tab === "type") on = ["type", "cat", "tag"].includes(state.jmode);
      btn.classList.toggle("active", on);
      if (on) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    const onHome = state.site === "jable" && state.jmode === "link";
    const onList = state.site === "jable" && isJableList(state.jmode);
    const onWatch = state.site === "jable" && state.jmode === "watch";
    show($("jable-feed"), onHome);
    show($("jable-list"), onList);
    show($("jable-watch"), onWatch);
    show($("jable-empty"), false);
    show($("jable-hot"), false);
    show($("jable-pick"), false);
    if (state.site === "jable") query.placeholder = "搜索番号、标题或创作者";
    updateParseLabel();
    const routeChanged = prevKey !== `${state.jmode}|${state.listSlug}|${state.listYear}|${state.listMonth}|${state.listGroup}|${state.listSort}`;
    if (onHome) {
      if (state.jableHome && !routeChanged) renderJableHome(state.jableHome);
      else loadJableHome();
    }
    if (onList) {
      if (nextMode === "model" || routeChanged || !state.listItems.length) openJableList();
      else paintJableList(state.listItems, listTitle());
    }
    if (!onWatch) closeJableWatch(false);
    if (pushHash && state.site === "jable" && !onWatch) {
      const next = state.inspectCode ? inspectHash(state.inspectCode) : listHashBase();
      if (location.hash !== next) location.hash = next;
    }
  }

  function setDouyinMode(mode, pushHash) {
    state.dmode = mode || "link";
    const tools = $("douyin-tools");
    if (tools) tools.classList.toggle("hidden", state.site !== "douyin");
    document.querySelectorAll("#douyin-tools [data-dmode]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.dmode === state.dmode);
    });
    const notes = {
      link: "公开作品链接可游客解析。主页、推荐、关注、话题、喜欢需要 cookie。",
      feed: "解析登录后的推荐流。需要 cookie；游客公开推荐也可试。",
      follow: "解析关注作品流，需要 cookie。",
      hashtag: "输入话题名，例如 旅行 或 #旅行。需要 cookie。",
      likes: "粘贴用户主页链接，解析其喜欢列表。需要 cookie。",
    };
    const note = $("douyin-note");
    if (note) note.textContent = notes[state.dmode] || notes.link;
    document.body.dataset.dmode = state.dmode;
    if (state.site === "douyin") {
      query.placeholder =
        state.dmode === "hashtag"
          ? "话题名，例如 旅行 或 #旅行"
          : state.dmode === "likes"
            ? "粘贴用户主页链接"
            : state.dmode === "feed" || state.dmode === "follow"
              ? "可留空，直接点解析"
              : PLACEHOLDERS.douyin;
    }
    const dyTitle = $("douyin-empty-title");
    const dyCopy = $("douyin-empty-copy");
    const dyEmpty = {
      link: ["作品 / 主页", "粘贴作品或主页链接，也可以输入抖音号。"],
      feed: ["推荐", "解析登录后的推荐流。需要 cookie；游客公开推荐也可试。"],
      follow: ["关注", "解析关注作品流，需要 cookie。"],
      hashtag: ["话题", "输入话题名，例如 旅行 或 #旅行。"],
      likes: ["喜欢", "粘贴用户主页链接，解析其喜欢列表。"],
    };
    if (dyTitle && dyCopy) {
      const pair = dyEmpty[state.dmode] || dyEmpty.link;
      dyTitle.textContent = pair[0];
      dyCopy.textContent = pair[1];
    }
    const dyGo = document.querySelector("#douyin-empty [data-submit]");
    if (dyGo) {
      dyGo.textContent = state.dmode === "feed" || state.dmode === "follow" ? "解析此流" : "解析";
    }
    updateParseLabel();
    if (pushHash && state.site === "douyin") {
      const next = state.dmode === "link" ? "#/douyin" : `#/douyin/${state.dmode}`;
      if (location.hash !== next) location.hash = next;
    }
  }

  function renderYtTabs() {
    const host = $("yt-tabs");
    if (!host) return;
    host.innerHTML = "";
    YT_TABS.forEach((tab) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (tab.id === state.ytTab ? " active" : "");
      btn.textContent = tab.name;
      btn.addEventListener("click", () => {
        state.ytTab = tab.id;
        renderYtTabs();
      });
      host.appendChild(btn);
    });
    document.querySelectorAll("[data-yttab]").forEach((el) => {
      el.classList.toggle("active", el.dataset.yttab === state.ytTab);
    });
    const homeNav = document.querySelector("[data-yt-nav='home']");
    if (homeNav) homeNav.classList.toggle("active", state.ytTab === "all");
  }

  function updateParseLabel() {
    if (!btnParse) return;
    if (state.site === "jable") {
      btnParse.textContent = "搜索";
    } else if (state.site === "douyin" && (state.dmode === "feed" || state.dmode === "follow")) {
      btnParse.textContent = "解析此流";
    } else {
      btnParse.textContent = state.site === "auto" ? "解析内容" : "解析";
    }
  }

  function placeSearch(site) {
    const bundle = $("search-bundle");
    const homeSlot = $("slot-search-home");
    const mastSlot = $("slot-search-mast");
    if (!bundle || !homeSlot || !mastSlot) return;
    if (site === "auto") homeSlot.appendChild(bundle);
    else if (site === "jable" && $("slot-search-jable")) $("slot-search-jable").appendChild(bundle);
    else mastSlot.appendChild(bundle);
  }

  function showView(site) {
    const home = $("view-home");
    const jable = $("view-jable");
    const youtube = $("view-youtube");
    const douyin = $("view-douyin");
    if (home) home.classList.toggle("hidden", site !== "auto");
    if (jable) jable.classList.toggle("hidden", site !== "jable");
    if (youtube) youtube.classList.toggle("hidden", site !== "youtube");
    if (douyin) douyin.classList.toggle("hidden", site !== "douyin");
    placeSearch(site);
    const mark = $("wordmark");
    if (mark) {
      mark.setAttribute("href", "#/auto");
      mark.setAttribute("aria-label", "openDownload 首页");
    }
    $("crumb-parent").textContent = site === "auto" ? "工作台" : "来源";
    $("crumb-current").textContent = site === "auto" ? "首页" : labelOf(site);
    if (document.body.dataset.phase === "idle") {
      document.title = site === "auto" ? "openDownload" : `${labelOf(site)} · openDownload`;
    }
    updateParseLabel();
  }

  function setSite(site) {
    const siteChanged = state.site !== site;
    state.site = site;
    document.body.dataset.site = site;
    document.querySelectorAll(".site-router a, .source-card, .exhibit").forEach((el) => {
      const on = el.dataset.site === site;
      el.classList.toggle("active", on);
      if (on) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
      if (el.getAttribute("role") === "tab") {
        el.setAttribute("aria-selected", on ? "true" : "false");
      }
    });
    query.placeholder = PLACEHOLDERS[site] || PLACEHOLDERS.auto;
    query.setAttribute("aria-label", site === "jable" ? "搜索番号、标题或创作者" : "添加内容");
    showView(site);
    if (siteChanged) window.scrollTo({ top: 0, behavior: "instant" });
    if (hint && !hint.dataset.sticky) hint.textContent = "";
    show($("jable-tools"), site === "jable");
    show($("youtube-tools"), site === "youtube");
    show($("douyin-tools"), site === "douyin");
    const parts = hashParts();
    const before = `${state.jmode}|${state.listSlug}|${state.listYear}|${state.listMonth}|${state.listGroup}|${state.listSort}`;
    if (site === "jable") {
      const nextSlug = parts.listSlug || "";
      const nextYear = parts.listYear || "";
      const nextMonth = parts.listMonth || "";
      let nextGroup = parts.listGroup || "";
      if (!nextGroup && parts.jmode === "tag" && nextSlug) nextGroup = findTagGroup(nextSlug);
      if (
        state.listSlug !== nextSlug ||
        state.listYear !== nextYear ||
        state.listMonth !== nextMonth ||
        state.listGroup !== nextGroup
      ) {
        state.listShow = PAGE_SIZE;
      }
      state.listSlug = nextSlug;
      state.listYear = nextYear;
      state.listMonth = nextMonth;
      state.listGroup = nextGroup;
    }
    setJableMode(site === "jable" ? parts.jmode : "link", false, { before });
    setDouyinMode(site === "douyin" ? parts.dmode : "link", false);
    if (site === "youtube") renderYtTabs();
    if (site === "jable") loadJableCatalog();
    if (site !== "jable") {
      closeJableWatch(false);
      closeJableInspect({ skipHash: true, skipPaint: true });
    }
    liveDetect();
  }

  function labelOf(site) {
    return { auto: "自动", jable: "Jable", youtube: "YouTube", douyin: "抖音" }[site] || site;
  }

  function setBoard(active, extras = {}) {
    if (!board) return;
    board.querySelectorAll("li").forEach((li) => {
      const step = li.dataset.step;
      li.classList.remove("active", "done", "error");
      if (extras.error === step) li.classList.add("error");
      else if (extras.done && extras.done.includes(step)) li.classList.add("done");
      else if (step === active) li.classList.add("active");
    });
  }

  function appendLog(el, line) {
    el.textContent += (el.textContent ? "\n" : "") + line;
    el.scrollTop = el.scrollHeight;
  }

  function coverUrl(url) {
    if (!url) return "";
    return "/api/proxy?url=" + encodeURIComponent(url);
  }

  function closeStream() {
    if (state.es) {
      state.es.close();
      state.es = null;
    }
  }

  function listen(taskId, handlers) {
    closeStream();
    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    state.es = es;
    es.onmessage = (ev) => {
      let rec;
      try {
        rec = JSON.parse(ev.data);
      } catch {
        return;
      }
      const type = rec.event;
      if (type === "log" && rec.text) handlers.onLog && handlers.onLog(rec.text);
      if (type === "progress") handlers.onProgress && handlers.onProgress(rec);
      else if (rec.percent != null && rec.percent !== "" && handlers.onProgress && type !== "done" && type !== "close") {
        handlers.onProgress(rec);
      }
      if (type === "preview") handlers.onPreview && handlers.onPreview(rec.preview, rec);
      if (type === "error") handlers.onError && handlers.onError(rec.message || "失败");
      if (type === "done" || type === "close") {
        handlers.onDone && handlers.onDone(rec);
        if (type === "close") es.close();
      }
    };
    es.onerror = () => {};
  }

  function renderChips(host, items, current, onPick, labelKey, valueKey) {
    if (!host) return;
    host.innerHTML = "";
    items.forEach((item) => {
      const value = typeof item === "string" ? item : item[valueKey];
      const label = typeof item === "string" ? item : item[labelKey];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (value === current ? " active" : "");
      btn.textContent = label;
      btn.addEventListener("click", () => onPick(value));
      host.appendChild(btn);
    });
  }

  function renderHot() {
    const cat = state.jableCatalog;
    if (!cat) return;
    const terms = cat.hot_terms || [];
    const cats = [{ slug: "", name: "热门" }, ...(cat.categories || [])];
    renderChips($("hot-terms"), terms, state.hotTerm, (id) => {
      state.hotTerm = id;
      renderHot();
    }, "name", "id");
    renderChips($("hot-cats"), cats, state.hotCat, (id) => {
      state.hotCat = id;
      renderHot();
    }, "name", "slug");
  }

  function renderPick() {
    const cat = state.jableCatalog;
    if (!cat) return;
    const groups = [...(cat.groups || []).map((g) => g.name), ...(cat.extra_groups || [])];
    renderChips($("pick-groups"), groups, state.pickGroup, (name) => {
      state.pickGroup = name;
      state.pickTag = "";
      if (name === "熱度優先") state.pickTerm = "video_viewed_today";
      else if (name === "新片優先") state.pickTerm = "post_date";
      else state.pickTerm = "post_date_and_popularity";
      renderPick();
      setJableMode(state.jmode, false);
    }, "name", "name");
    const groupObj = (cat.groups || []).find((g) => g.name === state.pickGroup);
    let tags = groupObj ? groupObj.tags : [];
    if (state.pickGroup === "按主題") tags = cat.categories || [];
    const tagHost = $("pick-tags");
    if (!tags.length) {
      tagHost.innerHTML = `<span class="tool-note">${
        state.pickGroup === "按女優"
          ? "在输入框填写创作者名"
          : state.pickGroup === "新片優先" || state.pickGroup === "熱度優先"
            ? "无需子类"
            : ""
      }</span>`;
    } else {
      const valueKey = tags[0].slug !== undefined ? "slug" : "name";
      renderChips(tagHost, tags, state.pickTag, (id) => {
        state.pickTag = id;
        renderPick();
      }, "name", valueKey);
    }
    const termSource = state.pickGroup === "熱度優先" ? cat.hot_terms : cat.pick_terms;
    renderChips($("pick-terms"), termSource || [], state.pickTerm, (id) => {
      state.pickTerm = id;
      renderPick();
    }, "name", "id");
  }

  async function loadJableCatalog() {
    if (state.jableCatalog) {
      renderHot();
      renderPick();
      fillJableMenus();
      prefetchWorksAndOrders();
      return;
    }
    try {
      state.jableCatalog = await api("/api/jable/catalog");
      const g = (state.jableCatalog.groups || [])[0];
      if (g) {
        state.pickGroup = g.name;
        state.pickTag = (g.tags && g.tags[0] && g.tags[0].slug) || "";
      }
      renderHot();
      renderPick();
      fillJableMenus();
      prefetchWorksAndOrders();
    } catch (err) {
      hint.textContent = String(err.message || err);
    }
  }

  function ddOption(attr, id, name, on) {
    return `<button type="button" ${attr}="${escapeHtml(id)}" class="${on ? "on" : ""}">${escapeHtml(name)}</button>`;
  }

  function ddHtml(key, label, value, menuHtml, wide) {
    return `<div class="av-dd" data-dd="${escapeHtml(key)}">
      <button type="button" class="av-dd-btn" aria-expanded="false">
        <span class="av-dd-label">${escapeHtml(label)}:</span>
        <span class="av-dd-value">${escapeHtml(value)}</span>
        <span class="av-dd-chev" aria-hidden="true"></span>
      </button>
      <div class="av-dd-menu${wide ? " wide" : ""}">${menuHtml}</div>
    </div>`;
  }

  function cascadeHtml(groups, currentGroup, currentTag) {
    const left =
      ddOption("data-group", "", "全部", !currentGroup) +
      groups
        .map(
          (g) =>
            `<button type="button" data-group="${escapeHtml(g.name)}" class="${
              g.name === currentGroup ? "on" : ""
            }">${escapeHtml(g.name)}<span class="av-dd-more">›</span></button>`
        )
        .join("");
    const groupObj = groups.find((g) => g.name === currentGroup);
    const right = !currentGroup
      ? `<p class="av-dd-hint">请选择一级</p>`
      : ddOption("data-tag", "", "全部", !currentTag) +
        (groupObj && groupObj.tags ? groupObj.tags : [])
          .map((t) => ddOption("data-tag", t.slug, t.name, t.slug === currentTag))
          .join("");
    return `<div class="av-cascade">
      <div class="av-cascade-col" data-cascade="1">
        <div class="av-cascade-hd">一级</div>
        <div class="av-cascade-list">${left}</div>
      </div>
      <div class="av-cascade-col" data-cascade="2">
        <div class="av-cascade-hd">二级</div>
        <div class="av-cascade-list">${right}</div>
      </div>
    </div>`;
  }

  function fillCascadeLevel2() {
    const list = document.querySelector('#jb-filters [data-cascade="2"] .av-cascade-list');
    const groups = (state.jableCatalog && state.jableCatalog.groups) || [];
    const groupObj = groups.find((g) => g.name === state.listGroup);
    const currentTag = state.jmode === "tag" ? state.listSlug : "";
    if (list) {
      if (!state.listGroup) {
        list.innerHTML = `<p class="av-dd-hint">请选择一级</p>`;
      } else {
        list.innerHTML =
          ddOption("data-tag", "", "全部", !currentTag) +
          (groupObj && groupObj.tags ? groupObj.tags : [])
            .map((t) => ddOption("data-tag", t.slug, t.name, t.slug === currentTag))
            .join("");
      }
    }
    document.querySelectorAll('#jb-filters [data-cascade="1"] [data-group]').forEach((btn) => {
      btn.classList.toggle("on", (btn.dataset.group || "") === (state.listGroup || ""));
    });
    const val = document.querySelector('#jb-filters [data-dd="tag"] .av-dd-value');
    if (val) {
      val.textContent = currentTag
        ? findListName(currentTag) || currentTag
        : state.listGroup || "全部";
    }
  }

  function closeFilterMenus(except) {
    document.querySelectorAll("#jb-filters .av-dd.open").forEach((el) => {
      if (el === except) return;
      el.classList.remove("open");
      const btn = el.querySelector(".av-dd-btn");
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }

  function fillJableMenus() {
    renderFilterBar();
  }

  function renderFilterBar() {
    const left = $("jb-filter-left");
    const right = $("jb-filter-right");
    if (!left || !right) return;
    const cat = state.jableCatalog || {};
    const isHot = ["hot", "week", "month", "all"].includes(state.jmode);
    const isLatest = state.jmode === "latest";
    const isType = ["type", "cat", "tag"].includes(state.jmode);
    const isModel = state.jmode === "model";
    let leftHtml = "";
    let rightHtml = "";

    if (isHot) {
      const sorts = cat.hot_sorts && cat.hot_sorts.length
        ? cat.hot_sorts
        : [
            { id: "hot", name: "今日观看" },
            { id: "week", name: "每周观看" },
            { id: "month", name: "每月观看" },
            { id: "all", name: "最多观看" },
          ];
      const current = sorts.find((s) => s.id === state.jmode) || sorts[0];
      rightHtml = ddHtml(
        "sort",
        "排序",
        current.name,
        sorts.map((s) => ddOption("data-sort", s.id, s.name, s.id === state.jmode)).join("")
      );
    } else if (isLatest) {
      const years = cat.years && cat.years.length
        ? cat.years
        : Array.from({ length: 27 }, (_, i) => String(2026 - i));
      const months = cat.months && cat.months.length
        ? cat.months
        : Array.from({ length: 12 }, (_, i) => ({ id: String(i + 1), name: `${i + 1}月` }));
      const yearVal = state.listYear || "全部";
      const monthVal = state.listMonth ? `${state.listMonth}月` : "全部";
      leftHtml =
        ddHtml(
          "year",
          "年份",
          yearVal,
          ddOption("data-year", "", "全部", !state.listYear) +
            years.map((y) => ddOption("data-year", String(y), String(y), String(y) === state.listYear)).join("")
        ) +
        ddHtml(
          "month",
          "月份",
          monthVal,
          ddOption("data-month", "", "全部", !state.listMonth) +
            months
              .map((m) => {
                const id = m.id || String(m);
                const name = m.name || `${id}月`;
                return ddOption("data-month", id, name, id === state.listMonth);
              })
              .join("")
        );
    } else if (isModel) {
      const sorts = [
        { id: "post_date", name: "发布时间" },
        { id: "video_viewed", name: "最多观看" },
      ];
      const current = sorts.find((s) => s.id === state.listSort) || sorts[0];
      rightHtml = ddHtml(
        "sort",
        "排序",
        current.name,
        sorts.map((s) => ddOption("data-sort", s.id, s.name, s.id === state.listSort)).join("")
      );
    } else if (isType) {
      const cats = cat.categories || [];
      const groups = cat.groups || [];
      if (state.jmode === "tag" && state.listSlug && !state.listGroup) {
        state.listGroup = findTagGroup(state.listSlug);
      }
      const catVal =
        state.jmode === "cat" ? findListName(state.listSlug) || state.listSlug || "全部" : "全部";
      const currentTag = state.jmode === "tag" ? state.listSlug : "";
      const tagVal = currentTag
        ? findListName(currentTag) || currentTag
        : state.listGroup || "全部";
      const catMenu =
        ddOption("data-cat", "", "全部", state.jmode !== "cat") +
        cats
          .map((c) => ddOption("data-cat", c.slug, c.name, state.jmode === "cat" && c.slug === state.listSlug))
          .join("");
      leftHtml =
        ddHtml("cat", "分类", catVal, catMenu) +
        ddHtml("tag", "标签", tagVal, cascadeHtml(groups, state.listGroup, currentTag), true);
    }
    left.innerHTML = leftHtml;
    right.innerHTML = rightHtml;
  }

  function syncListFilters() {
    renderFilterBar();
  }

  function findListName(slug) {
    if (!slug) return "";
    const cat = state.jableCatalog || {};
    const hit = (cat.categories || []).find((c) => c.slug === slug);
    if (hit) return hit.name;
    for (const group of cat.groups || []) {
      const tag = (group.tags || []).find((t) => t.slug === slug);
      if (tag) return tag.name;
    }
    return slug;
  }

  function findTagGroup(slug) {
    if (!slug) return "";
    const groups = (state.jableCatalog && state.jableCatalog.groups) || [];
    for (const group of groups) {
      if ((group.tags || []).some((t) => t.slug === slug)) return group.name;
    }
    return "";
  }

  function fmtViews(n) {
    const num = Number(n) || 0;
    if (num >= 1000000) return (num / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (num >= 1000) return (num / 1000).toFixed(1).replace(/\.0$/, "") + "K";
    return String(num);
  }

  function slugForActorName(name) {
    const names = state.modelNames || {};
    const want = String(name || "").trim();
    if (!want) return "";
    for (const slug of Object.keys(names)) {
      if (names[slug] === want) return slug;
    }
    return "";
  }

  function actorsFromTitle(title) {
    let text = String(title || "").trim();
    if (!text) return [];
    text = text.replace(/^[A-Z]{2,10}-?\d+\S*\s+/i, "").trim();
    const bits = text.split(/[\s　]+/).filter(Boolean);
    const skip = { 作品: 1, 出演: 1, 女優: 1, 女优: 1, デビュー: 1, SP: 1, SEX: 1, AV: 1 };
    let names = [];
    for (let i = bits.length - 1; i >= 0; i -= 1) {
      const token = bits[i].replace(/[·・,，。.!！?？]+$/g, "");
      if (
        !token ||
        skip[token] ||
        !/^(?:[A-Za-z][A-Za-z.\-]{1,19}|[\u4e00-\u9fff\u3040-\u30ff]{2,12})$/.test(token)
      ) {
        break;
      }
      names.unshift(token);
    }
    if (names.length > 2) names = names.slice(-2);
    if (!names.length) {
      const m = text.match(/([\u4e00-\u9fff\u3040-\u30ff]{2,12})$/);
      if (m) names.push(m[1]);
    }
    return names.map((name) => ({ name, slug: slugForActorName(name) }));
  }

  function parseActors(raw, title) {
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
      return listed
        .filter((a) => a.name && !junkActorName(a.name))
        .map((a) => (a.slug ? a : { name: a.name, slug: slugForActorName(a.name) }));
    }
    return actorsFromTitle(title).filter((a) => a.name && !junkActorName(a.name));
  }

  function fmtDate(raw) {
    const text = String(raw || "").trim();
    const full = text.match(/(20\d{2})[./-](\d{1,2})[./-](\d{1,2})/);
    if (full) {
      return `${full[1]}-${String(full[2]).padStart(2, "0")}-${String(full[3]).padStart(2, "0")}`;
    }
    const ym = text.match(/^(20\d{2})[./-](\d{1,2})$/);
    if (ym) return `${ym[1]}-${String(ym[2]).padStart(2, "0")}`;
    const year = text.match(/^(20\d{2})$/);
    return year ? year[1] : "";
  }

  function rememberWork(it) {
    if (!it || !it.id) return;
    const id = playKey(it.id);
    const cur = state.workMap[id] || { id };
    if (it.title && it.title !== id) cur.title = it.title;
    if (it.cover) cur.cover = it.cover;
    if (it.preview) cur.preview = it.preview;
    if (it.duration) cur.duration = it.duration;
    if (it.views != null && it.views !== "") cur.views = it.views;
    if (it.likes != null) cur.likes = it.likes;
    if (fmtDate(it.date) && (!fmtDate(cur.date) || fmtDate(it.date).length >= fmtDate(cur.date).length)) {
      cur.date = it.date;
    }
    const actors = parseActors(it.actors, it.title || cur.title);
    if (actors.length) cur.actors = actors;
    cur.id = id;
    state.workMap[id] = cur;
  }

  function hydrateItem(it) {
    if (!it || !it.id) return it;
    const id = playKey(it.id);
    const known = state.workMap[id] || {};
    const row = Object.assign({ id, title: id, cover: "", duration: "", views: 0, date: "", actors: [] }, known, it, {
      id,
    });
    if (known.title && known.title !== id && (!row.title || row.title === id)) row.title = known.title;
    if (known.cover && !row.cover) row.cover = known.cover;
    if (known.duration && !row.duration) row.duration = known.duration;
    if ((row.views == null || row.views === "") && known.views != null) row.views = known.views;
    if (fmtDate(known.date) && (!fmtDate(row.date) || fmtDate(known.date).length > fmtDate(row.date).length)) {
      row.date = known.date;
    }
    const actors = parseActors(row.actors && row.actors.length ? row.actors : known.actors, row.title || known.title);
    if (actors.length) row.actors = actors;
    rememberWork(row);
    row.actors = attachPageActor(actors.length ? actors : parseActors(row.actors, row.title));
    return row;
  }

  function cardForCode(id) {
    const code = String(id || "").toLowerCase();
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

  function iconEye() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
  }

  function iconCal() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>`;
  }

  function iconUser() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="8" r="4"/></svg>`;
  }

  function avCardMetaHtml(item) {
    const bits = [];
    if (item.views != null && item.views !== "") {
      bits.push(
        `<span class="av-card-views" title="观看">${iconEye()}${escapeHtml(fmtViews(item.views))}</span>`
      );
    }
    const date = fmtDate(item.date);
    if (date) {
      bits.push(`<span class="av-card-date" title="发布时间">${iconCal()}${escapeHtml(date)}</span>`);
    }
    const actors = attachPageActor(parseActors(item.actors, item.title)).slice(0, 2);
    if (actors.length) {
      const names = actors
        .map((a) => {
          const label = escapeHtml(a.name);
          if (a.slug) {
            rememberModelName(a.slug, a.name);
            return `<a class="av-card-actor" href="#/jable/model/${encodeURIComponent(a.slug)}">${label}</a>`;
          }
          return `<span>${label}</span>`;
        })
        .join('<span class="av-card-actor-sep">·</span>');
      bits.push(`<span class="av-card-actors" title="演员">${iconUser()}${names}</span>`);
    }
    return bits.length ? `<span class="av-card-meta">${bits.join("")}</span>` : "";
  }

  function avCardHtml(item) {
    const id = escapeHtml(item.id || "");
    const title = escapeHtml(item.title || item.id || "");
    const img = item.cover
      ? `<img alt="" src="${coverUrl(item.cover)}" loading="eager" decoding="async">`
      : `<span class="av-skel"></span>`;
    const dur = item.duration
      ? `<span class="av-dur">${escapeHtml(item.duration)}</span>`
      : "";
    const meta = avCardMetaHtml(item);
    const on = state.inspectCode && playKey(item.id) === playKey(state.inspectCode);
    return `<article class="av-card${on ? " is-inspect" : ""}" data-code="${id}" data-href="#/jable/v/${encodeURIComponent(id)}">
      <a class="av-card-link" href="#/jable/v/${encodeURIComponent(item.id || "")}" aria-label="查看详情：${title}" aria-haspopup="dialog" aria-expanded="${on ? "true" : "false"}">
      <span class="av-thumb">${img}<span class="av-shade"></span>${dur}</span>
      <span class="av-card-body"><span class="av-card-title">${title}</span></span></a>${meta}
    </article>`;
  }

  function avHeroHtml(item, kind) {
    const id = escapeHtml(item.id || "");
    const title = escapeHtml((item.id || item.title || "").toUpperCase());
    const img = item.cover
      ? `<img alt="" src="${coverUrl(item.cover)}">`
      : "";
    const dur = item.duration ? `<span class="av-dur">${escapeHtml(item.duration)}</span>` : "";
    const on = state.inspectCode && playKey(item.id) === playKey(state.inspectCode);
    return `<a class="av-hero-card ${kind}${on ? " is-inspect" : ""}" href="#/jable/v/${encodeURIComponent(id)}" data-code="${id}">
      ${img}<span class="av-hero-title">${title}</span>${dur}
    </a>`;
  }

  function inspectVisibleItems(items, code) {
    // The detail drawer overlays the grid; opening it must not remove list items.
    if (document.body.classList.contains("workbench")) return (items || []).slice(0, PAGE_SIZE);
    const page = (items || []).slice(0, PAGE_SIZE);
    const key = playKey(code || state.inspectCode);
    if (!key) return page;
    const keep = pageSizeNow();
    const idx = page.findIndex((it) => playKey(it && it.id) === key);
    if (idx < 0 || idx < keep) return page.slice(0, keep);
    return page.slice(0, keep - 1).concat([page[idx]]);
  }

  function applyWorkMeta(it) {
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

  function patchCardMeta(it) {
    if (!it || !it.id) return;
    const card = document.querySelector(`.av-card[data-code="${it.id}"] .av-card-meta`);
    const wrap = document.querySelector(`.av-card[data-code="${it.id}"] .av-card-body`);
    const html = avCardMetaHtml(it);
    if (card) {
      if (html) {
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        const next = tmp.firstElementChild;
        if (next) card.replaceWith(next);
      }
      return;
    }
    if (wrap && html) wrap.insertAdjacentHTML("beforeend", html);
  }

  function enrichCardMeta(items) {
    const rows = (items || []).filter((it) => it && it.id);
    if (!rows.length) return;
    const need = rows.filter((it) => !fmtDate(it.date) || !parseActors(it.actors, it.title).length);
    if (!need.length) return;
    const codes = need.map((it) => it.id).slice(0, 12);
    api("/api/jable/meta?wait=0&codes=" + encodeURIComponent(codes.join(",")))
      .then((data) => {
        ((data && data.items) || []).forEach((it) => {
          applyWorkMeta(it);
          const merged = Object.assign({}, state.workMap[playKey(it.id)] || {}, it);
          patchCardMeta(merged);
        });
      })
      .catch(() => {});
  }

  function fillAvGrid(host, items, skeletons, skipWarm) {
    if (!host) return;
    host.setAttribute("aria-busy", skeletons ? "true" : "false");
    if (skeletons) {
      host.innerHTML = `<span class="sr-only" role="status">正在加载作品…</span>` + Array.from({ length: 12 }, () => `<div class="av-skel" aria-hidden="true"></div>`).join("");
      return;
    }
    const page = (items || []).slice(0, PAGE_SIZE).map(hydrateItem);
    host.innerHTML = page.map(avCardHtml).join("") || `<p class="av-status" role="status">暂无作品，可以调整筛选条件后再试。</p>`;
    bindPlayPrefetch(host);
    if (!skipWarm) {
      warmDmmBatch(page.map((it) => it && it.id));
    }
    if (host.id === "jb-list-grid" || host.id === "jb-hot-grid" || host.id === "jb-latest") {
      enrichCardMeta(page);
    }
  }

  function renderHero() {
    const items = state.heroItems || [];
    const host = $("jb-hero");
    const dots = $("jb-hero-dots");
    if (!host || !items.length) {
      if (host) host.innerHTML = "";
      return;
    }
    const n = items.length;
    const i = ((state.heroIndex % n) + n) % n;
    const left = items[(i - 1 + n) % n];
    const mid = items[i];
    const right = items[(i + 1) % n];
    host.innerHTML = avHeroHtml(left, "side") + avHeroHtml(mid, "main") + avHeroHtml(right, "side");
    warmDmmBatch([left && left.id, mid && mid.id, right && right.id]);
    bindPlayPrefetch(host);
    if (dots) {
      dots.innerHTML = items
        .map((_, idx) => `<button type="button" class="${idx === i ? "on" : ""}" data-hero="${idx}"></button>`)
        .join("");
    }
  }

  function heroTick(delta) {
    const n = (state.heroItems || []).length;
    if (!n) return;
    state.heroIndex = (state.heroIndex + delta + n) % n;
    renderHero();
  }

  function startHeroTimer() {
    clearInterval(state.heroTimer);
    state.heroTimer = setInterval(() => {
      if (state.site === "jable" && state.jmode === "link") heroTick(1);
    }, 4500);
  }

  function pageCountOf(total, hasMore, page) {
    const n = Math.max(1, Math.ceil(Math.max(0, Number(total) || 0) / PAGE_SIZE));
    if (hasMore) return Math.max(n, (page || 1) + 1);
    return n;
  }

  const PAGER_WINDOW = 5;

  function pagerRange(page, pageCount, size) {
    const count = Math.max(1, Number(pageCount) || 1);
    const cur = Math.min(Math.max(1, Number(page) || 1), count);
    const win = Math.max(1, Number(size) || PAGER_WINDOW);
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

  function renderPager(host, page, pageCount) {
    if (!host) return;
    pageCount = Math.max(1, Number(pageCount) || 1);
    page = Math.min(Math.max(1, Number(page) || 1), pageCount);
    host.classList.remove("hidden");
    host.dataset.pages = String(pageCount);
    const { start, end } = pagerRange(page, pageCount, PAGER_WINDOW);
    const atFirst = page <= 1;
    const atLast = page >= pageCount;
    let html = `<button type="button" class="av-pager-nav av-pager-first" data-go="1" ${
      atFirst ? "disabled" : ""
    } aria-label="首页" title="首页">&lt;&lt;</button>`;
    html += `<button type="button" class="av-pager-nav av-pager-prev" data-go="${Math.max(1, page - 1)}" ${
      atFirst ? "disabled" : ""
    } aria-label="上一页" title="上一页">&lt;</button>`;
    html += `<span class="av-pager-pages">`;
    for (let i = start; i <= end; i += 1) {
      html += `<button type="button" data-go="${i}" class="${i === page ? "on" : ""}" ${i === page ? 'aria-current="page"' : ""} aria-label="第 ${i} 页">${i}</button>`;
    }
    html += `</span>`;
    html += `<button type="button" class="av-pager-nav av-pager-next" data-go="${Math.min(pageCount, page + 1)}" ${
      atLast ? "disabled" : ""
    } aria-label="下一页" title="下一页">&gt;</button>`;
    html += `<button type="button" class="av-pager-nav av-pager-last" data-go="${pageCount}" ${
      atLast ? "disabled" : ""
    } aria-label="末页" title="末页">&gt;&gt;</button>`;
    html += `<span class="av-pager-jump"><input class="av-pager-input" type="number" min="1" max="${pageCount}" value="${page}" aria-label="页码"><span class="av-pager-max">/ ${pageCount}</span></span>`;
    const arrow = (path) => `<svg class="pager-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
    host.innerHTML = html.replace("&lt;&lt;", arrow("m13 6-6 6 6 6M18 6v12")).replace("&lt;", arrow("m15 6-6 6 6 6")).replace("&gt;&gt;", arrow("m11 6 6 6-6 6M6 6v12")).replace("&gt;", arrow("m9 6 6 6-6 6"));
    host.setAttribute("aria-label", "作品分页");
  }

  function renderJableHome(data) {
    const latest = (data && data.latest && data.latest.items) || [];
    const hot = (data && data.hot && data.hot.items) || [];
    const hotPages = pageCountOf(hot.length, false, state.homeHotPage);
    const latestPages = pageCountOf(latest.length, false, state.homeLatestPage);
    state.homeHotPage = Math.min(Math.max(1, state.homeHotPage || 1), hotPages);
    state.homeLatestPage = Math.min(Math.max(1, state.homeLatestPage || 1), latestPages);
    const hs = (state.homeHotPage - 1) * PAGE_SIZE;
    const ls = (state.homeLatestPage - 1) * PAGE_SIZE;
    fillAvGrid($("jb-hot-grid"), inspectVisibleItems(hot.slice(hs, hs + PAGE_SIZE), state.inspectCode));
    fillAvGrid($("jb-latest"), inspectVisibleItems(latest.slice(ls, ls + PAGE_SIZE), state.inspectCode));
    renderPager($("jb-pager-hot"), state.homeHotPage, hotPages);
    renderPager($("jb-pager-latest"), state.homeLatestPage, latestPages);
    state.heroItems = (hot.length ? hot : latest).slice(0, 10);
    if (!state.heroItems.length) state.heroIndex = 0;
    renderHero();
    clearInterval(state.heroTimer);
    const related = $("jb-related");
    if (related && !state.watchCode) fillAvGrid(related, hot.slice(0, PAGE_SIZE));
  }

  function readLocalHome() {
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

  function parseDuration(s) {
    const parts = String(s || "")
      .split(":")
      .map((n) => Number(n) || 0);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return 0;
  }

  function sortListItems(items, sort) {
    const arr = (items || []).slice();
    if (sort === "likes") arr.sort((a, b) => (b.likes || 0) - (a.likes || 0));
    else if (sort === "duration") arr.sort((a, b) => parseDuration(b.duration) - parseDuration(a.duration));
    return arr;
  }

  function homeFallbackItems(kind) {
    const home = state.jableHome || readLocalHome() || {};
    const hot = (home.hot && home.hot.items) || [];
    const latest = (home.latest && home.latest.items) || [];
    if (["hot", "week", "month", "all", "type"].includes(kind)) return hot.length ? hot : latest;
    return latest.length ? latest : hot;
  }

  function isHexSlug(text) {
    return /^[a-f0-9]{32}$/i.test(String(text || "").trim());
  }

  function junkActorName(name) {
    const t = String(name || "").trim();
    if (!t) return true;
    if (["演员", "女優", "女优", "首頁", "首页"].includes(t)) return true;
    if (/[«»‹›]/.test(t) || /首[頁页]/.test(t)) return true;
    if (isHexSlug(t)) return true;
    return false;
  }

  function attachPageActor(actors) {
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

  function rememberModelName(slug, name) {
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

  function listTitle() {
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
      pick: "集合",
    };
    if (state.jmode === "model") {
      const named = (state.modelNames && state.modelNames[state.listSlug]) || "";
      if (named && !isHexSlug(named)) return named;
      return "演员";
    }
    if (state.jmode === "cat" || state.jmode === "tag") {
      return findListName(state.listSlug) || state.listSlug || "分类浏览";
    }
    return names[state.jmode] || "影片";
  }

  function expectedListPageSize(page) {
    const p = Math.max(1, Number(page) || 1);
    const total = Number(state.listTotal) || 0;
    if (total > 0) {
      const last = Math.ceil(total / PAGE_SIZE);
      if (p === last) return (total % PAGE_SIZE) || PAGE_SIZE;
    }
    return PAGE_SIZE;
  }

  function normalizeSitePages(raw) {
    const pages = {};
    Object.entries(raw || {}).forEach(([key, rows]) => {
      const ids = (rows || []).map((id) => String(id || "").toLowerCase()).filter(Boolean);
      if (ids.length) pages[String(key)] = ids;
    });
    return pages;
  }

  function itemsFromSitePages(page, need) {
    const hit = state.snapCache[listCacheKey()] || {};
    const pages = hit.pages || state.listSitePages || {};
    const sitePage = Math.floor((Math.max(1, page) - 1) * PAGE_SIZE / 24) + 1;
    const offset = ((Math.max(1, page) - 1) * PAGE_SIZE) % 24;
    const rows = pages[String(sitePage)] || pages[sitePage] || [];
    if (!rows.length || rows.length < offset + need) return [];
    return rows.slice(offset, offset + PAGE_SIZE).map((id) => cardForCode(id)).filter(Boolean);
  }

  function itemsForListPage(page) {
    const p = Math.max(1, Number(page) || 1);
    const start = (p - 1) * PAGE_SIZE;
    const need = expectedListPageSize(p);
    if (state.listSnapKey === listCacheKey() && state.listCodes.length > start) {
      const ids = state.listCodes.slice(start, start + PAGE_SIZE);
      if (ids.length >= need && ids.every(Boolean)) {
        return ids.map((id) => cardForCode(id)).filter(Boolean);
      }
    }
    const siteItems = itemsFromSitePages(p, need);
    if (siteItems.length >= need) return siteItems;
    if (state.listPageMap && state.listPageMap[p] && state.listPageMap[p].length) {
      return state.listPageMap[p].map(hydrateItem);
    }
    return [];
  }

  function listPageReady(page) {
    return itemsForListPage(page).length >= expectedListPageSize(page);
  }

  function listPageCount() {
    if (state.listPageCount) return state.listPageCount;
    return pageCountOf(state.listTotal || 0, state.listHasMore, state.listPage);
  }

  function paintJableList(items, title) {
    if (items) state.listItems = items;
    const page = Math.max(1, state.listPage || 1);
    warmDmmBatch(itemsForListPage(page).map((it) => it && it.id));
    const shown = inspectVisibleItems(itemsForListPage(page), state.inspectCode);
    if (!shown.length && (state.listPageCount > 1 || state.listHasMore)) {
      fillAvGrid($("jb-list-grid"), [], true);
    } else {
      fillAvGrid($("jb-list-grid"), shown);
    }
    document.body.dataset.listSnap = state.listCodes.length > PAGE_SIZE ? "1" : "0";
    const titleEl = $("jb-list-title");
    const countEl = $("jb-list-count");
    if (titleEl) titleEl.textContent = title || listTitle();
    if (countEl) {
      const total = state.listTotal || 0;
      countEl.textContent = total ? `${total.toLocaleString()} 部影片` : "";
    }
    const pages = listPageCount();
    renderPager($("jb-pager"), page, pages);
    syncListFilters();
  }

  function paintListJump(page, opts) {
    state.listPage = Math.max(1, Number(page) || 1);
    const forceSkel = opts && opts.skeleton;
    const shown = inspectVisibleItems(itemsForListPage(state.listPage), state.inspectCode);
    if (forceSkel || !shown.length) {
      fillAvGrid($("jb-list-grid"), [], true);
    } else {
      fillAvGrid($("jb-list-grid"), shown, false, true);
      const codes = shown.map((it) => it && it.id);
      setTimeout(() => warmDmmBatch(codes), 0);
    }
    const titleEl = $("jb-list-title");
    const countEl = $("jb-list-count");
    if (titleEl) titleEl.textContent = listTitle();
    if (countEl && state.listTotal) {
      countEl.textContent = `${state.listTotal.toLocaleString()} 部影片`;
    }
    renderPager($("jb-pager"), state.listPage, listPageCount());
  }

  function listCacheKey(jmode, slug, sort, year, month) {
    const mode = jmode == null ? state.jmode : jmode;
    const s = (slug == null ? state.listSlug : slug) || "";
    const so = (sort == null ? state.listSort : sort) || "";
    const y = (year == null ? state.listYear : year) || "";
    const m = (month == null ? state.listMonth : month) || "";
    return `od-jable-list-${mode}-${s}-${so}-${y}-${m}`;
  }

  function listTerm(kind, sort) {
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

  function listRequestUrl(opts) {
    const o = opts || {};
    const jmode = o.jmode == null ? state.jmode : o.jmode;
    const kind = jmode === "pick" ? "latest" : jmode;
    const sort = o.sort == null ? state.listSort : o.sort;
    const queryStr = new URLSearchParams({
      kind,
      slug: (o.slug == null ? state.listSlug : o.slug) || "",
      term: listTerm(kind, sort) || "",
      year: (o.year == null ? state.listYear : o.year) || "",
      month: (o.month == null ? state.listMonth : o.month) || "",
      page: String(o.page || 1),
      pages: "1",
    });
    return "/api/jable/list?" + queryStr.toString();
  }

  function pageRequestUrl(opts) {
    const o = opts || {};
    const jmode = o.jmode == null ? state.jmode : o.jmode;
    const kind = jmode === "pick" ? "latest" : jmode;
    const sort = o.sort == null ? state.listSort : o.sort;
    const queryStr = new URLSearchParams({
      kind,
      slug: (o.slug == null ? state.listSlug : o.slug) || "",
      term: listTerm(kind, sort) || "",
      year: (o.year == null ? state.listYear : o.year) || "",
      month: (o.month == null ? state.listMonth : o.month) || "",
      page: String(o.page || 1),
    });
    return "/api/jable/page?" + queryStr.toString();
  }

  function snapshotUrl(opts) {
    const o = opts || {};
    const jmode = o.jmode == null ? state.jmode : o.jmode;
    const kind = jmode === "pick" ? "latest" : jmode;
    const sort = o.sort == null ? state.listSort : o.sort;
    const queryStr = new URLSearchParams({
      kind,
      slug: (o.slug == null ? state.listSlug : o.slug) || "",
      term: listTerm(kind, sort) || "",
      year: (o.year == null ? state.listYear : o.year) || "",
      month: (o.month == null ? state.listMonth : o.month) || "",
    });
    return "/api/jable/snapshot?" + queryStr.toString();
  }

  function unpackCover(value, bases) {
    const text = String(value || "");
    if (!text) return "";
    if (text[1] === "/" && text[0] >= "0" && text[0] <= "9") {
      const i = Number(text[0]);
      const base = (bases && bases[i]) || "";
      return base + text.slice(1);
    }
    return text;
  }

  function ingestSnapshot(data, key, keepCurrent) {
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
    if (prev && prev.pages) Object.keys(prev.pages).forEach((k) => {
      if (!pages[k]) pages[k] = prev.pages[k];
    });
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
    const pageCount = Math.max(
      Number((data && data.page_count) || 0) || 0,
      Math.ceil(total / PAGE_SIZE),
      1
    );
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

  function applyCachedSnap(key) {
    const hit = state.snapCache[key];
    const hasCodes = !!(hit && hit.codes && hit.codes.length);
    const hasPages = !!(hit && hit.pages && Object.keys(hit.pages).length);
    if (!hasCodes && !hasPages) return false;
    if (hasCodes) state.listCodes = hit.codes;
    state.listSitePages = (hit && hit.pages) || {};
    state.listSnapKey = key;
    state.listTotal = Math.max(hit.total || 0, (hit.codes || []).length, state.listTotal || 0);
    state.listPageCount = Math.max(
      hit.pageCount || 0,
      Math.ceil((state.listTotal || (hit.codes || []).length) / PAGE_SIZE),
      1
    );
    state.listHasMore = ((hit.codes || []).length || 0) < (state.listTotal || 0);
    return true;
  }

  async function loadListSnapshot(req) {
    const key = listCacheKey();
    try {
      const data = await api(snapshotUrl());
      if (req != null && req !== state.listReq) return false;
      if (!ingestSnapshot(data, key)) return false;
      if (req != null && req !== state.listReq) return false;
      paintJableList(state.listItems, listTitle());
      return true;
    } catch {
      return false;
    }
  }

  function scheduleModelSnapRefresh(req) {
    if (state.jmode !== "model") return;
    [1200, 3200, 7000, 14000].forEach((ms) => {
      setTimeout(() => {
        if (req !== state.listReq) return;
        if (state.jmode !== "model") return;
        const total = Number(state.listTotal) || 0;
        if (total && (state.listCodes || []).length >= total) return;
        loadListSnapshot(req).then(() => {
          if (req !== state.listReq) return;
          if (listPageReady(state.listPage || 1)) paintListJump(state.listPage || 1);
        });
      }, ms);
    });
  }

  function rememberOrderSnap(jmode, slug, row) {
    const sort = jmode === "tag" || jmode === "cat" ? "post_date_and_popularity" : "";
    const key = listCacheKey(jmode, slug, sort, "", "");
    const codes = [];
    const seen = new Set();
    ((row && row.codes) || []).forEach((raw) => {
      const id = String(raw || "").toLowerCase();
      if (!id || seen.has(id)) return;
      seen.add(id);
      codes.push(id);
      if (!state.workMap[id]) {
        state.workMap[id] = { id, title: id, cover: "", duration: "", views: 0 };
      }
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
    if (
      prev &&
      prev.codes &&
      prev.codes.length >= codes.length &&
      (prev.total || 0) >= total &&
      Object.keys(prevPages).length >= Object.keys(pages).length
    ) {
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

  function applyOrdersPayload(data) {
    Object.entries((data && data.tags) || {}).forEach(([slug, row]) => rememberOrderSnap("tag", slug, row));
    Object.entries((data && data.cats) || {}).forEach(([slug, row]) => rememberOrderSnap("cat", slug, row));
    if (state.jmode === "tag" || state.jmode === "cat") {
      const key = listCacheKey();
      if (applyCachedSnap(key) && listPageReady(state.listPage || 1)) {
        paintListJump(state.listPage || 1);
      }
    }
    if (data && data.lists && data.complete >= data.lists && state.orderTimer) {
      clearInterval(state.orderTimer);
      state.orderTimer = 0;
    }
  }

  function ingestWorksPayload(data) {
    ingestSnapshot(data, "od-jable-works", true);
    state.worksKnown = Math.max(state.worksKnown || 0, ((data && data.cards) || []).length, Number((data && data.total) || 0) || 0);
    if (state.listCodes.length && listPageReady(state.listPage || 1)) {
      paintListJump(state.listPage || 1);
    }
  }

  function prefetchWorksAndOrders() {
    if (!state.worksPrefetch) {
      state.worksPrefetch = true;
      api("/api/jable/works")
        .then(ingestWorksPayload)
        .catch(() => {
          state.worksPrefetch = false;
        });
    }
    const pull = () => {
      api("/api/jable/orders")
        .then((data) => {
          applyOrdersPayload(data);
          const n = Number((data && data.cache && data.cache.works) || 0);
          if (n > (state.worksKnown || 0)) {
            api("/api/jable/works").then(ingestWorksPayload).catch(() => {});
          }
        })
        .catch(() => {});
    };
    pull();
    if (!state.orderTimer) state.orderTimer = setInterval(pull, 8000);
  }

  function prefetchCatalogSnapshots() {
    prefetchWorksAndOrders();
    const targets = [
      { jmode: "hot", slug: "", sort: "video_viewed_today", year: "", month: "" },
      { jmode: "latest", slug: "", sort: "post_date", year: "", month: "" },
      { jmode: "type", slug: "", sort: "video_viewed", year: "", month: "" },
    ];
    targets.forEach((target) => {
      const key = listCacheKey(target.jmode, target.slug, target.sort, target.year, target.month);
      if (state.snapCache[key] && state.snapCache[key].codes && state.snapCache[key].codes.length) return;
      api(snapshotUrl(target))
        .then((data) => ingestSnapshot(data, key, true))
        .catch(() => {});
    });
  }

  function listLooksLikeFallback(items, kind) {
    if (!Array.isArray(items) || !items.length) return true;
    const fb = homeFallbackItems(kind === "type" ? "hot" : kind);
    if (!fb.length) return false;
    return (items[0] && items[0].id) === (fb[0] && fb[0].id);
  }

  const listPrefetchQueue = [];
  let listPrefetchBusy = 0;
  let listJumpSeq = 0;

  function enqueueListPrefetch(target) {
    const key = listCacheKey(target.jmode, target.slug, target.sort, target.year, target.month);
    if (listPrefetchQueue.some((t) => listCacheKey(t.jmode, t.slug, t.sort, t.year, t.month) === key)) return;
    listPrefetchQueue.push(target);
    pumpListPrefetch();
  }

  function pumpListPrefetch() {
    while (listPrefetchBusy < 10 && listPrefetchQueue.length) {
      const target = listPrefetchQueue.shift();
      listPrefetchBusy += 1;
      prefetchJableList(target).finally(() => {
        listPrefetchBusy -= 1;
        pumpListPrefetch();
      });
    }
  }

  async function prefetchJableList(target) {
    const key = listCacheKey(target.jmode, target.slug, target.sort, target.year, target.month);
    try {
      let existing = null;
      try {
        existing = JSON.parse(localStorage.getItem(key) || "null");
      } catch {
        existing = null;
      }
      if (existing && existing.pages && Number(existing.pageCount) > 1) return;
      const data = await api(listRequestUrl(target));
      const items = (data && data.items) || [];
      if (!items.length || data.pending) return;
      localStorage.setItem(
        key,
        JSON.stringify({
          total: data.total || items.length,
          hasMore: !!data.has_more,
          pageCount: data.page_count || 0,
          pages: { 1: items },
        })
      );
    } catch {
      /* ignore */
    }
  }

  function prefetchJableSiblings() {
    const mode = state.jmode;
    const targets = [];
    const current = listCacheKey();
    if (["hot", "week", "month", "all"].includes(mode)) {
      const sorts = {
        hot: "video_viewed_today",
        week: "video_viewed_week",
        month: "video_viewed_month",
        all: "video_viewed",
      };
      ["hot", "week", "month", "all"].forEach((m) => {
        if (m !== mode) targets.push({ jmode: m, slug: "", sort: sorts[m], year: "", month: "" });
      });
    } else if (mode === "latest") {
      ["2026", "2025", "2024"].forEach((y) => {
        targets.push({ jmode: "latest", slug: "", sort: "post_date", year: y, month: "" });
      });
      if (state.listYear) {
        const month = state.listMonth || String(new Date().getMonth() + 1);
        targets.push({
          jmode: "latest",
          slug: "",
          sort: "post_date",
          year: state.listYear,
          month,
        });
      }
    } else if (["type", "cat", "tag"].includes(mode)) {
      const cats =
        state.jableCatalog && state.jableCatalog.categories && state.jableCatalog.categories.length
          ? state.jableCatalog.categories
          : [
              { slug: "bdsm" },
              { slug: "sex-only" },
              { slug: "chinese-subtitle" },
              { slug: "insult" },
              { slug: "uniform" },
              { slug: "roleplay" },
              { slug: "private-cam" },
              { slug: "uncensored" },
              { slug: "pov" },
              { slug: "groupsex" },
              { slug: "pantyhose" },
              { slug: "lesbian" },
            ];
      cats.forEach((c) => {
        if (c && c.slug) {
          targets.push({ jmode: "cat", slug: c.slug, sort: "post_date_and_popularity", year: "", month: "" });
        }
      });
      const groups = (state.jableCatalog && state.jableCatalog.groups) || [];
      const groupObj = groups.find((g) => g.name === state.listGroup);
      ((groupObj && groupObj.tags) || []).forEach((t) => {
        if (t && t.slug) {
          targets.push({ jmode: "tag", slug: t.slug, sort: "post_date_and_popularity", year: "", month: "" });
        }
      });
    }
    targets.forEach((t) => {
      if (listCacheKey(t.jmode, t.slug, t.sort, t.year, t.month) === current) return;
      enqueueListPrefetch(t);
    });
  }

  function mergeListItems(base, extra) {
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

  function rememberListItems() {
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

  function stashListPage(data, page) {
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
    if (data && data.total != null) {
      state.listTotal = Math.max(
        state.listTotal || 0,
        Number(data.total) || 0,
        (data.items || []).length
      );
    } else {
      state.listTotal = Math.max(state.listTotal || 0, state.listItems.length);
    }
    if (data && data.page_count != null) {
      state.listPageCount = Math.max(
        state.listPageCount || 0,
        Number(data.page_count) || 0,
        Math.ceil((state.listTotal || 0) / PAGE_SIZE),
        1
      );
    } else {
      state.listPageCount = Math.max(1, Math.ceil((state.listTotal || 0) / PAGE_SIZE));
    }
    if (data && data.has_more != null) state.listHasMore = !!data.has_more;
    rememberListItems();
  }

  function applyListPage(data, page, title) {
    stashListPage(data, page);
    if (state.jmode === "model" && data && data.title) rememberModelName(state.listSlug, data.title);
    paintListJump(page);
  }

  function prefetchListPages(fromPage) {
    const max = listPageCount();
    const ahead = state.jmode === "model" ? [1, 2, 3, 4] : [1, 2];
    ahead.forEach((d) => {
      const p = fromPage + d;
      if (p < 1) return;
      if (!state.listHasMore && p > max) return;
      if (listPageReady(p)) return;
      api(pageRequestUrl({ page: p }))
        .then((data) => {
          if (data && data.items && data.items.length) stashListPage(data, p);
          else if (data && data.pending) {
            api(listRequestUrl({ page: p }))
              .then((row) => {
                if (row && row.items && row.items.length) stashListPage(row, p);
              })
              .catch(() => {});
          }
        })
        .catch(() => {});
    });
  }

  async function fetchJumpPage(page) {
    try {
      const data = await api(pageRequestUrl({ page }));
      if (data && data.items && data.items.length) return data;
    } catch {
      /* fall through to list */
    }
    return api(listRequestUrl({ page }));
  }

  async function gotoListPage(page) {
    const raw = Math.max(1, Number(page) || 1);
    const max = listPageCount();
    page = state.listHasMore && raw > max ? raw : Math.min(raw, Math.max(max, 1));
    const jump = ++listJumpSeq;
    const req = state.listReq;
    if (state.jmode === "model") {
      paintListJump(page, { skeleton: !itemsForListPage(page).length });
      await loadModelPage(page, req, jump);
      return;
    }
    if (listPageReady(page)) {
      paintListJump(page);
      fetchJumpPage(page)
        .then((data) => {
          if (jump !== listJumpSeq || req !== state.listReq) return;
          if (data && data.items && data.items.length) applyListPage(data, page, listTitle());
        })
        .catch(() => {});
      prefetchListPages(page);
      return;
    }
    paintListJump(page, { skeleton: true });
    try {
      const data = await fetchJumpPage(page);
      if (jump !== listJumpSeq || req !== state.listReq) return;
      if (data && data.items && data.items.length) applyListPage(data, page, listTitle());
      else if (state.jmode === "model" && data && data.pending) {
        setTimeout(() => {
          if (jump !== listJumpSeq || req !== state.listReq) return;
          fetchJumpPage(page)
            .then((row) => {
              if (jump !== listJumpSeq || req !== state.listReq) return;
              if (row && row.items && row.items.length) applyListPage(row, page, listTitle());
            })
            .catch(() => {});
        }, 900);
      }
      prefetchListPages(page);
    } catch {
      /* ignore */
    }
  }

  async function pullJableList(req, title, retryPending) {
    try {
      const p1 = await api(listRequestUrl({ page: 1 }));
      if (req !== state.listReq) return;
      stashListPage(p1, 1);
      if (state.listPage === 1) paintJableList(state.listItems, listTitle() || (p1 && p1.title) || title);
      else renderPager($("jb-pager"), state.listPage, listPageCount());
      api(listRequestUrl({ page: 2 }))
        .then((p2) => {
          if (req !== state.listReq) return;
          stashListPage(p2, 2);
          renderPager($("jb-pager"), state.listPage, listPageCount());
        })
        .catch(() => {});
      api(listRequestUrl({ page: 3 })).then((p3) => {
        if (req !== state.listReq) return;
        stashListPage(p3, 3);
      }).catch(() => {});
      prefetchJableSiblings();
      if (p1 && p1.pending && retryPending) {
        [400, 900].forEach((ms) => {
          setTimeout(() => {
            if (req !== state.listReq) return;
            pullJableList(req, title, false);
          }, ms);
        });
      }
    } catch (err) {
      if (req !== state.listReq) return;
      if (!retryPending) return;
      const countEl = $("jb-list-count");
      if (countEl && !(state.listItems && state.listItems.length)) {
        countEl.textContent = String(err.message || err);
      }
    }
  }

  function readListCache() {
    let raw = null;
    try {
      raw = JSON.parse(localStorage.getItem(listCacheKey()) || "null");
    } catch {
      raw = null;
    }
    if (Array.isArray(raw) && raw.length) {
      const pages = {};
      for (let i = 0; i < raw.length; i += PAGE_SIZE) {
        pages[Math.floor(i / PAGE_SIZE) + 1] = raw.slice(i, i + PAGE_SIZE);
      }
      return { total: raw.length, hasMore: true, pageCount: 0, pages };
    }
    if (raw && raw.pages) return raw;
    return null;
  }

  async function loadModelPage(page, req, jump = listJumpSeq) {
    const url = pageRequestUrl({ page });
    const current = () => req === state.listReq && jump === listJumpSeq && state.jmode === "model";
    for (let attempt = 0; attempt < 15 && current(); attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (!current()) return;
        if (data.items && data.items.length) {
          applyListPage(data, page, listTitle());
          return;
        }
        if (!data.pending) {
          stashListPage(data, page);
          fillAvGrid($("jb-list-grid"), []);
          $("jb-list-count").textContent = "暂无作品";
          renderPager($("jb-pager"), page, listPageCount());
          return;
        }
      } catch {
        if (!current()) return;
      } finally {
        clearTimeout(timer);
      }
      if (itemsForListPage(page).length) return;
      $("jb-list-count").textContent = "正在获取演员作品…";
      if (attempt < 14) await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    if (!current()) return;
    const grid = $("jb-list-grid");
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "false");
    const message = document.createElement("div");
    message.style.gridColumn = "1 / -1";
    message.setAttribute("role", "status");
    message.textContent = "暂时无法获取演员作品，请稍后重试。 ";
    const retry = document.createElement("button");
    retry.className = "btn";
    retry.textContent = "重新加载";
    retry.addEventListener("click", () => {
      if (!current()) return;
      paintListJump(page, { skeleton: true });
      loadModelPage(page, req, ++listJumpSeq);
    });
    message.append(retry);
    grid.append(message);
    $("jb-list-count").textContent = "加载未完成";
  }

  async function openJableList() {
    const req = ++state.listReq;
    const kind = state.jmode === "pick" ? "latest" : state.jmode;
    const title = listTitle();
    state.listPage = 1;
    state.listShow = PAGE_SIZE;
    state.listHasMore = true;
    state.listPageMap = {};
    state.listItems = [];
    state.listTotal = 0;
    state.listPageCount = 0;
    const snapKey = listCacheKey();
    if (state.listSnapKey !== snapKey) {
      state.listCodes = [];
      state.listSnapKey = "";
    }
    const cached = readListCache();
    let instant = [];
    if (cached && cached.pages) {
      state.listPageMap = cached.pages;
      state.listTotal = cached.total || 0;
      state.listPageCount = cached.pageCount || Math.ceil((cached.total || 0) / PAGE_SIZE);
      state.listHasMore = !!cached.hasMore;
      instant = cached.pages[1] || [];
      const flat = [];
      Object.keys(cached.pages)
        .map(Number)
        .sort((a, b) => a - b)
        .forEach((p) => (cached.pages[p] || []).forEach((it) => flat.push(it)));
      state.listItems = flat;
    }
    if (!instant.length && !["model", "cat", "tag"].includes(kind)) {
      instant = homeFallbackItems(kind === "type" ? "hot" : kind) || [];
      state.listItems = instant;
      state.listPageMap = { 1: instant.slice(0, PAGE_SIZE) };
    }
    paintJableList(state.listItems, title);
    if (!itemsForListPage(1).length) fillAvGrid($("jb-list-grid"), [], true);
    if (kind === "model") {
      await loadModelPage(1, req, ++listJumpSeq);
      return;
    }
    const snapped = applyCachedSnap(listCacheKey());
    if (snapped) {
      paintJableList(state.listItems, title);
      loadListSnapshot(req).then(() => scheduleModelSnapRefresh(req));
      fetchJumpPage(1)
        .then((data) => {
          if (req !== state.listReq) return;
          if (data && data.items && data.items.length) applyListPage(data, 1, title);
          prefetchListPages(1);
        })
        .catch(() => {});
      return;
    }
    const snap = loadListSnapshot(req);
    await pullJableList(req, title, true);
    await snap;
    scheduleModelSnapRefresh(req);
  }

  async function loadJableHome(force) {
    if (state.site !== "jable") return;
    state.showHot = PAGE_SIZE;
    state.showLatest = PAGE_SIZE;
    state.homeHotPage = 1;
    state.homeLatestPage = 1;
    const local = state.jableHome || readLocalHome();
    if (local) {
      state.jableHome = local;
      ["hot", "latest"].forEach((k) => (((local[k] || {}).items || []).forEach(rememberWork)));
      renderJableHome(local);
      prefetchCatalogSnapshots();
    } else {
      fillAvGrid($("jb-latest"), [], true);
      fillAvGrid($("jb-hot-grid"), [], true);
    }
    if (state.jableHomeLoading && !force) return;
    state.jableHomeLoading = true;
    const status = $("jb-feed-status");
    $("jb-retry").hidden = true;
    if (!local) {
      status.hidden = false;
      status.textContent = "正在加载作品…";
      fillAvGrid($("jb-hot-grid"), [], true);
      fillAvGrid($("jb-latest"), [], true);
    }
    try {
      const data = await api("/api/jable/home?pages=2");
      state.jableHome = data;
      ["hot", "latest"].forEach((k) => (((data[k] || {}).items || []).forEach(rememberWork)));
      try {
        localStorage.setItem("od-jable-home-v1", JSON.stringify(data));
      } catch {
        /* ignore */
      }
      renderJableHome(data);
      prefetchCatalogSnapshots();
      if (status) {
        const n = ((data.latest && data.latest.items) || []).length + ((data.hot && data.hot.items) || []).length;
        status.textContent = n ? "" : "暂时没有可显示的作品，请稍后重试。";
        status.hidden = !!n;
        $("jb-retry").hidden = !!n;
      }
    } catch (err) {
      if (status) {
        status.hidden = false;
        status.textContent = local ? "更新未完成，当前显示上次加载的内容。" : "加载未完成，请检查网络后重试。";
        $("jb-retry").hidden = false;
        if (!local) {
          fillAvGrid($("jb-hot-grid"), [], false, true);
          fillAvGrid($("jb-latest"), [], false, true);
        }
      }
    } finally {
      state.jableHomeLoading = false;
    }
  }

  const PLAY_TTL_MS = 4 * 60 * 1000;
  const FAST_HLS_CONFIG = {
    enableWorker: true,
    lowLatencyMode: false,
    testBandwidth: false,
    startLevel: 0,
    startFragPrefetch: true,
    progressive: false,
    autoStartLoad: true,
    maxBufferLength: 36,
    maxMaxBufferLength: 90,
    maxBufferSize: 80 * 1000 * 1000,
    maxBufferHole: 0.5,
    backBufferLength: 24,
    nudgeMaxRetry: 8,
    fragLoadingTimeOut: 20000,
    fragLoadingMaxRetry: 6,
    fragLoadingRetryDelay: 400,
    fragLoadingMaxRetryTimeout: 8000,
    manifestLoadingTimeOut: 20000,
    levelLoadingTimeOut: 20000,
  };

  function playKey(code) {
    return String(code || "").trim().toLowerCase();
  }

  function playErrorMessage(err) {
    const msg = String((err && err.message) || err || "");
    if (/1015|限流|拦截|cloudflare|rate limited/i.test(msg)) {
      return "站点限流，完整视频暂不可用。后台抓取已暂停，请过几分钟再点「播放完整视频」";
    }
    return msg || "完整视频暂不可用";
  }

  function getPlayInfo(code) {
    const key = playKey(code);
    if (!key) return Promise.reject(new Error("缺少番号"));
    const hit = state.playCache.get(key);
    if (hit && Date.now() - hit.at < PLAY_TTL_MS && hit.data && hit.data.stream) {
      return Promise.resolve(hit.data);
    }
    if (state.playInflight.has(key)) return state.playInflight.get(key);
    const pending = Promise.race([
      api("/api/jable/play?code=" + encodeURIComponent(key)),
      new Promise((_, reject) => {
        setTimeout(() => reject(new Error("解析超时")), 28000);
      }),
    ])
      .then((data) => {
        state.playCache.set(key, { data, at: Date.now() });
        if (data && data.stream) warmHlsBrowser(data.stream);
        return data;
      })
      .finally(() => {
        state.playInflight.delete(key);
      });
    state.playInflight.set(key, pending);
    return pending;
  }

  function cachedPlayStream(code) {
    const key = playKey(code);
    if (!key) return "";
    const hit = state.playCache.get(key);
    if (hit && Date.now() - hit.at < PLAY_TTL_MS && hit.data && hit.data.stream) {
      return hit.data.stream;
    }
    return "";
  }

  function warmHlsBrowser(src) {
    if (!src || state.hlsWarm.has(src)) return;
    state.hlsWarm.add(src);
    fetch(src, { cache: "force-cache" })
      .then((res) => res.text())
      .then((txt) => {
        String(txt || "")
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.includes("/api/jable/seg?url="))
          .slice(0, 12)
          .forEach((line) => fetch(line, { cache: "force-cache" }).catch(() => {}));
      })
      .catch(() => {
        state.hlsWarm.delete(src);
      });
  }

  function prefetchPlay(code, warmHls) {
    const key = playKey(code);
    if (!key) return;
    const fresh = cachedPlayStream(key);
    if (fresh) {
      warmHlsBrowser(fresh);
      if (warmHls) preloadHlsSource(fresh);
      return;
    }
    if (!warmHls) return;
    if (state.playInflight.size >= 2 && !state.playInflight.has(key)) return;
    getPlayInfo(key)
      .then((data) => {
        if (!data || !data.stream) return;
        warmHlsBrowser(data.stream);
        preloadHlsSource(data.stream);
      })
      .catch(() => {});
  }

  function bindPlayPrefetch(host) {
    if (!host) return;
    host.querySelectorAll(".av-card[data-code], a.av-hero-card[data-code]").forEach((el) => {
      if (el.dataset.prefetchBound) return;
      el.dataset.prefetchBound = "1";
      const code = el.dataset.code;
      let dwell = 0;
      el.addEventListener(
        "pointerenter",
        () => {
          prefetchDmm(code);
          clearTimeout(dwell);
          dwell = setTimeout(() => prefetchPlay(code, false), 180);
        },
        { passive: true }
      );
      el.addEventListener(
        "pointerleave",
        () => {
          clearTimeout(dwell);
        },
        { passive: true }
      );
      el.addEventListener(
        "pointerdown",
        () => {
          clearTimeout(dwell);
          prefetchDmm(code);
          prefetchPlay(code, true);
        },
        { passive: true }
      );
    });
  }

  function knownItem(code) {
    const key = playKey(code);
    if (state.workMap[key]) return hydrateItem(state.workMap[key]);
    const pools = [
      state.listItems || [],
      (((state.jableHome || {}).hot || {}).items) || [],
      (((state.jableHome || {}).latest || {}).items) || [],
    ];
    for (const pool of pools) {
      const hit = pool.find((it) => playKey(it && it.id) === key);
      if (hit) return hydrateItem(hit);
    }
    return null;
  }

  function knownCover(code) {
    const hit = knownItem(code);
    return (hit && hit.cover) || "";
  }

  function destroyHls() {
    const video = $("jb-video");
    if (state.hls) {
      try {
        state.hls.stopLoad();
      } catch {
        /* ignore */
      }
    }
    if (video) video.pause();
  }

  function bindHlsErrors(hls, statusId) {
    if (!hls || !window.Hls) return;
    let fatalTries = 0;
    hls.on(window.Hls.Events.FRAG_LOADED, () => {
      fatalTries = 0;
    });
    hls.on(window.Hls.Events.ERROR, (_ev, data) => {
      if (!data || !data.fatal) return;
      const network = data.type === window.Hls.ErrorTypes.NETWORK_ERROR;
      const media = data.type === window.Hls.ErrorTypes.MEDIA_ERROR;
      if ((network || media) && fatalTries < 4) {
        fatalTries += 1;
        try {
          if (network) hls.startLoad();
          else hls.recoverMediaError();
        } catch {
          /* ignore */
        }
        return;
      }
      const st = $(statusId);
      if (st) st.textContent = "播放失败，可改用下载";
    });
  }

  function ensureHls(video) {
    if (state.hls) {
      if (video && state.hls.media !== video) {
        try {
          state.hls.attachMedia(video);
        } catch {
          /* ignore */
        }
      }
      return state.hls;
    }
    if (!(window.Hls && window.Hls.isSupported())) return null;
    state.hls = new window.Hls(FAST_HLS_CONFIG);
    if (video) state.hls.attachMedia(video);
    state.hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
      const el = $("jb-video");
      if (el) el.play().catch(() => {});
    });
    bindHlsErrors(state.hls, "jb-watch-status");
    return state.hls;
  }

  function attachHls(video, src) {
    if (!video || !src) return;
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    if (state.hlsSrc === src && state.hls) {
      video.play().catch(() => {});
      return;
    }
    state.hlsSrc = src;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.play().catch(() => {});
      return;
    }
    const hls = ensureHls(video);
    if (hls) {
      try {
        hls.stopLoad();
      } catch {
        /* ignore */
      }
      hls.loadSource(src);
      video.play().catch(() => {});
      return;
    }
    video.src = src;
    video.play().catch(() => {});
  }

  function inspectSourceFromCard(card) {
    if (!card) return "";
    if (card.closest("#jb-hot-grid, #jb-sec-hot")) return "hot";
    if (card.closest("#jb-latest, #jb-sec-latest")) return "latest";
    return "";
  }

  function inferHomeInspectSource(code) {
    const key = playKey(code);
    if (!key) return "hot";
    const home = state.jableHome || {};
    const hot = ((home.hot || {}).items) || [];
    const latest = ((home.latest || {}).items) || [];
    const inHot = hot.some((it) => playKey(it && it.id) === key);
    const inLatest = latest.some((it) => playKey(it && it.id) === key);
    if (inLatest && !inHot) return "latest";
    return "hot";
  }

  function applyInspectSource(source) {
    if (state.jmode === "link") {
      const src = source || "hot";
      state.inspectSource = src;
      document.body.classList.toggle("jb-inspect-from-hot", src === "hot");
      document.body.classList.toggle("jb-inspect-from-latest", src === "latest");
      return;
    }
    state.inspectSource = "";
    document.body.classList.remove("jb-inspect-from-hot", "jb-inspect-from-latest");
  }

  function showInspectPanel(on) {
    const panel = $("jb-inspect");
    if (!panel) return;
    if (on) {
      panel.hidden = false;
      panel.removeAttribute("hidden");
      panel.classList.remove("hidden");
    } else {
      panel.hidden = true;
      panel.setAttribute("hidden", "");
    }
  }

  function destroyInspectHls(hard) {
    if (state.inspectHls) {
      try {
        state.inspectHls.stopLoad();
      } catch {
        /* ignore */
      }
      try {
        state.inspectHls.detachMedia();
      } catch {
        /* ignore */
      }
      if (hard) {
        try {
          state.inspectHls.destroy();
        } catch {
          /* ignore */
        }
        state.inspectHls = null;
      }
    }
    state.inspectHlsSrc = "";
  }

  function resetInspectVideo() {
    const video = $("jb-inspect-video");
    if (state.inspectHls) {
      try {
        state.inspectHls.stopLoad();
      } catch {
        /* ignore */
      }
    }
    if (!video) return;
    video.pause();
  }

  function setInspectPlayUi(mode) {
    state.inspectPlay = mode === "full" ? "full" : "preview";
    const badge = $("jb-inspect-badge");
    const fullBtn = $("jb-inspect-full");
    if (badge) badge.textContent = state.inspectPlay === "full" ? "完整视频" : "预览";
    if (fullBtn) {
      fullBtn.disabled = false;
      fullBtn.textContent = state.inspectPlay === "full" ? "预览短片" : "播放完整视频";
    }
  }

  function ensureInspectHls(video) {
    if (!state.inspectHls) {
      if (!(window.Hls && window.Hls.isSupported())) return null;
      const hls = new window.Hls(FAST_HLS_CONFIG);
      state.inspectHls = hls;
      hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        const el = $("jb-inspect-video");
        if (el && document.body.classList.contains("jb-inspect-open")) {
          el.play().catch(() => {});
        }
      });
      bindHlsErrors(hls, "jb-inspect-status");
    }
    if (video && state.inspectHls.media !== video) {
      try {
        state.inspectHls.attachMedia(video);
      } catch {
        /* ignore */
      }
    }
    return state.inspectHls;
  }

  function preloadHlsSource(src) {
    if (!src || !(window.Hls && window.Hls.isSupported())) return;
    if (state.inspectHlsSrc === src && state.inspectHls) return;
    const hls = ensureInspectHls(null);
    if (!hls) return;
    state.inspectHlsSrc = src;
    try {
      hls.stopLoad();
    } catch {
      /* ignore */
    }
    hls.loadSource(src);
  }

  function attachInspectHls(video, src) {
    if (!video || !src) return;
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    if (state.inspectHlsSrc === src && state.inspectHls) {
      ensureInspectHls(video);
      video.play().catch(() => {});
      return;
    }
    state.inspectHlsSrc = src;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      if (video.getAttribute("src") !== src) video.src = src;
      video.play().catch(() => {});
      return;
    }
    const hls = ensureInspectHls(video);
    if (hls) {
      try {
        hls.stopLoad();
      } catch {
        /* ignore */
      }
      hls.loadSource(src);
      video.play().catch(() => {});
      return;
    }
    video.src = src;
    video.play().catch(() => {});
  }

  function watchHash(code) {
    const raw = playKey(code);
    return raw ? `#/jable/v/${encodeURIComponent(raw)}` : "#/jable";
  }

  function handoverInspectToWatch() {
    const from = $("jb-inspect-video");
    const to = $("jb-video");
    if (!from || !to || !state.inspectHlsSrc) return false;
    const t = from.currentTime || 0;
    const src = state.inspectHlsSrc;
    if (state.inspectHls) {
      const hls = state.inspectHls;
      try {
        hls.detachMedia();
      } catch {
        /* ignore */
      }
      if (state.hls && state.hls !== hls) {
        try {
          state.hls.destroy();
        } catch {
          /* ignore */
        }
      }
      state.hls = hls;
      state.hlsSrc = src;
      state.inspectHls = null;
      state.inspectHlsSrc = "";
      hls.attachMedia(to);
      to.muted = true;
      to.autoplay = true;
      to.playsInline = true;
      const resume = () => {
        try {
          if (t > 0.25) to.currentTime = t;
        } catch {
          /* ignore */
        }
        to.play().catch(() => {});
      };
      if (window.Hls) hls.once(window.Hls.Events.MEDIA_ATTACHED, resume);
      else resume();
      return true;
    }
    if (from.getAttribute("src")) {
      to.src = src;
      state.hlsSrc = src;
      to.play().catch(() => {});
      return true;
    }
    return false;
  }

  function startFullWatchPage(code) {
    const raw = playKey(code || state.inspectCode);
    if (!raw) return;
    state.watchFrom = listHashBase() || "#/jable";
    handoverInspectToWatch();
    closeJableInspect({ skipHash: true, skipPaint: true });
    openJableWatch(raw);
    const next = watchHash(raw);
    if (location.hash !== next) location.hash = next;
  }

  async function startInspectHls(code) {
    const raw = playKey(code || state.inspectCode);
    const video = $("jb-inspect-video");
    const statusEl = $("jb-inspect-status");
    const fullBtn = $("jb-inspect-full");
    if (!raw || !video) return;
    const seq = state.dmmSeq;
    const stillMine = () => playKey(state.inspectCode) === raw && state.dmmSeq === seq;
    const cached = cachedPlayStream(raw);
    const clearProgressive = () => {
      if (video.getAttribute("src")) {
        video.pause();
        video.removeAttribute("src");
      }
    };
    if (cached) {
      clearProgressive();
      attachInspectHls(video, cached);
      setInspectPlayUi("full");
      if (statusEl) statusEl.textContent = "";
      fillInspectFromApi(raw);
      return;
    }
    if (fullBtn) {
      fullBtn.disabled = true;
      fullBtn.textContent = "正在解析 m3u8…";
    }
    if (statusEl) statusEl.textContent = "正在解析 m3u8…";
    try {
      const data = await getPlayInfo(raw);
      if (!stillMine()) return;
      if (!data || !data.stream) throw new Error("没有播放地址");
      clearProgressive();
      attachInspectHls(video, data.stream);
      setInspectPlayUi("full");
      if (statusEl) statusEl.textContent = "";
      fillInspectFromApi(raw);
    } catch (err) {
      if (!stillMine()) return;
      if (statusEl) statusEl.textContent = playErrorMessage(err);
      setInspectPlayUi("preview");
      const mine = () => stillMine() && state.inspectPlay === "preview";
      attachDmmPreview(raw, video, statusEl, mine);
    } finally {
      if (fullBtn && stillMine()) {
        fullBtn.disabled = false;
        fullBtn.textContent = state.inspectPlay === "full" ? "预览短片" : "播放完整视频";
      }
    }
  }

  async function playInspectFull(code) {
    const raw = playKey(code || state.inspectCode);
    const video = $("jb-inspect-video");
    const statusEl = $("jb-inspect-status");
    if (!raw || !video) return;
    if (state.inspectPlay === "full") {
      state.dmmSeq += 1;
      setInspectPlayUi("preview");
      if (statusEl) statusEl.textContent = "";
      destroyInspectHls(true);
      video.pause();
      video.removeAttribute("src");
      try {
        video.load();
      } catch {
        /* ignore */
      }
      const mine = () => playKey(state.inspectCode) === raw && state.inspectPlay === "preview";
      attachDmmPreview(raw, video, statusEl, mine);
      return;
    }
    await startInspectHls(raw);
  }

  function refreshInspectGrids() {
    if (state.site !== "jable") return;
    if (state.jmode === "link" && state.jableHome) renderJableHome(state.jableHome);
    else if (isJableList(state.jmode)) paintJableList(state.listItems, listTitle());
  }

  function inspectChip(name, href) {
    const label = escapeHtml(name || "");
    if (!label) return "";
    const safeHref = escapeHtml(href || "#");
    return `<a class="jb-chip" href="${safeHref}">${label}</a>`;
  }

  function fillInspectChips(host, items, kind) {
    if (!host) return;
    if (!state.modelNames) state.modelNames = {};
    host.innerHTML = (items || [])
      .map((it) => {
        const name = typeof it === "string" ? it : (it && (it.name || it.title)) || "";
        const slug = typeof it === "string" ? "" : (it && it.slug) || "";
        if (kind === "tag") {
          const path = it && it.kind === "cat" ? "cat" : "tag";
          return inspectChip(name, slug ? `#/jable/${path}/${encodeURIComponent(slug)}` : "#/jable");
        }
        if (kind === "actor") {
          if (slug) rememberModelName(slug, name);
          return inspectChip(name, slug ? `#/jable/model/${encodeURIComponent(slug)}` : "#");
        }
        return inspectChip(name, "#");
      })
      .join("");
  }

  function codeFromCard(card) {
    if (!card) return "";
    if (card.dataset.code) return card.dataset.code;
    const href = card.getAttribute("href") || "";
    const m = href.match(/#\/jable\/v\/([^/?#]+)/i);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function closeJableInspect(opts) {
    const fromHash = opts && opts.fromHash;
    const skipHash = (opts && opts.skipHash) || fromHash;
    const skipPaint = opts && opts.skipPaint;
    const wasOpen = !!state.inspectCode || document.body.classList.contains("jb-inspect-open");
    const previousCode = state.inspectCode;
    const returnFocus = $("jb-inspect").contains(document.activeElement);
    state.inspectCode = "";
    state.inspectSource = "";
    document.body.classList.remove("jb-inspect-open", "jb-inspect-from-hot", "jb-inspect-from-latest");
    showInspectPanel(false);
    resetInspectVideo();
    setInspectPlayUi("preview");
    const status = $("jb-inspect-status");
    if (status) status.textContent = "";
    if (wasOpen && !skipPaint) refreshInspectGrids();
    if (wasOpen && returnFocus && !skipPaint) {
      state.inspectReturnCode = previousCode;
      const source = Array.from(document.querySelectorAll(".av-card")).find((el) => el.dataset.code === previousCode);
      source?.querySelector(".av-card-link")?.focus({ preventScroll: true });
    }
    if (wasOpen && !skipHash) {
      const next = listHashBase();
      if (location.hash !== next) location.hash = next;
    }
  }

  async function openJableInspect(code, opts) {
    let raw = String(code || "").trim();
    try {
      raw = decodeURIComponent(raw);
    } catch {
      /* keep raw */
    }
    if (!raw) return;
    const fromHash = opts && opts.fromHash;
    const source = (opts && opts.source) || "";
    if (playKey(state.inspectCode) === playKey(raw) && document.body.classList.contains("jb-inspect-open")) {
      if (source) applyInspectSource(source);
      if (!fromHash) {
        const next = inspectHash(raw);
        if (location.hash !== next) location.hash = next;
      }
      return;
    }
    state.inspectCode = raw;
    document.body.classList.add("jb-inspect-open");
    applyInspectSource(source || (state.jmode === "link" ? inferHomeInspectSource(raw) : ""));
    showInspectPanel(true);
    $("jb-inspect-close").focus({ preventScroll: true });
    setInspectPlayUi("full");
    const watchLink = $("jb-inspect-watch");
    if (watchLink) watchLink.href = watchHash(raw);
    const known = knownItem(raw);
    const titleEl = $("jb-inspect-title");
    const dateEl = $("jb-inspect-date");
    const statusEl = $("jb-inspect-status");
    const video = $("jb-inspect-video");
    if (titleEl) titleEl.textContent = (known && (known.title || known.id)) || raw.toUpperCase();
    if (dateEl) dateEl.textContent = (known && fmtDate(known.date)) || "";
    fillInspectChips($("jb-inspect-actors"), (known && parseActors(known.actors, known.title)) || [], "actor");
    fillInspectChips($("jb-inspect-tags"), []);
    if (statusEl) statusEl.textContent = "正在准备播放…";
    state.dmmSeq += 1;
    if (video) {
      const poster = (known && known.cover) || knownCover(raw);
      if (poster) video.poster = coverUrl(poster);
      startInspectHls(raw);
    }
    if (!fromHash) {
      const next = inspectHash(raw);
      if (location.hash !== next) location.hash = next;
    }
    refreshInspectGrids();
  }

  function fillInspectFromApi(code) {
    const raw = playKey(code);
    if (!raw) return;
    api("/api/jable/inspect?code=" + encodeURIComponent(raw))
      .then((data) => {
        if (playKey(state.inspectCode) !== raw) return;
        const titleEl = $("jb-inspect-title");
        const dateEl = $("jb-inspect-date");
        const video = $("jb-inspect-video");
        if (titleEl) titleEl.textContent = data.title || titleEl.textContent;
        if (dateEl) dateEl.textContent = data.date || "";
        fillInspectChips($("jb-inspect-actors"), data.actors, "actor");
        fillInspectChips($("jb-inspect-tags"), data.tags, "tag");
        if (video && data.cover && !video.poster) video.poster = coverUrl(data.cover);
      })
      .catch(() => {});
  }

  function closeJableWatch(updateHash) {
    state.watchCode = "";
    destroyHls();
    show($("jable-watch"), false);
    if (updateHash && state.site === "jable" && state.jmode === "watch") {
      state.jmode = "link";
      document.body.dataset.jmode = "link";
    }
  }

  async function openJableWatch(code) {
    const raw = decodeURIComponent(code || "").trim();
    if (!raw) return;
    if (state.inspectCode) closeJableInspect({ skipHash: true, skipPaint: true });
    const back = $("jb-watch-back");
    if (back) back.href = state.watchFrom || listHashBase() || "#/jable";
    if (state.watchCode === raw && state.hlsSrc) {
      const video = $("jb-video");
      if (video) video.play().catch(() => {});
      show($("jable-feed"), false);
      show($("jable-empty"), false);
      show($("jable-watch"), true);
      return;
    }
    state.watchCode = raw;
    state.jmode = "watch";
    document.body.dataset.jmode = "watch";
    show($("jable-feed"), false);
    show($("jable-empty"), false);
    show($("jable-watch"), true);
    const title = $("jb-watch-title");
    const sub = $("jb-watch-sub");
    const status = $("jb-watch-status");
    const video = $("jb-video");
    if (title) title.textContent = raw.toUpperCase();
    if (sub) sub.textContent = "正在获取播放地址…";
    if (status) status.textContent = "";
    const poster = knownCover(raw);
    if (video && poster) video.poster = coverUrl(poster);
    document.title = `${raw.toUpperCase()} · Jable`;
    const homeItems = [
      ...(((state.jableHome || {}).hot || {}).items || []),
      ...(((state.jableHome || {}).latest || {}).items || []),
      ...(state.listItems || []),
    ].filter((it) => playKey(it.id) !== playKey(raw));
    fillAvGrid($("jb-related"), homeItems.slice(0, 12));
    const ready = state.hlsSrc || cachedPlayStream(raw);
    if (ready && video) {
      attachHls(video, ready);
      if (sub) sub.textContent = "";
    }
    try {
      const data = await getPlayInfo(raw);
      if (state.watchCode !== raw) return;
      if (data.stream && video) attachHls(video, data.stream);
      if (title) title.textContent = data.title || raw;
      if (sub) sub.textContent = [data.id, data.expires_at].filter(Boolean).join("  ·  ");
      if (video && data.cover && !video.poster) video.poster = coverUrl(data.cover);
      if (data.related && data.related.length) {
        requestAnimationFrame(() => fillAvGrid($("jb-related"), data.related));
      }
      if (!data.stream && status) status.textContent = "没有播放地址";
      document.title = `${data.title || raw} · Jable`;
    } catch (err) {
      if (status) status.textContent = playErrorMessage(err);
      if (sub) sub.textContent = "播放失败";
    }
  }

  async function api(path, body) {
    const res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail || data.message || res.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  function isBrowse() {
    return state.site === "jable" && (state.jmode === "hot" || state.jmode === "pick");
  }

  function isDouyinPreset() {
    return state.site === "douyin" && (state.dmode === "feed" || state.dmode === "follow");
  }

  async function liveDetect() {
    const text = query.value.trim();
    if (!detectBadge) return;
    if (!text || isBrowse() || isDouyinPreset()) {
      detectBadge.textContent = "";
      detectBadge.classList.remove("warn");
      return;
    }
    try {
      const det = await api("/api/detect", { query: text, site: state.site });
      if (det.kind === "empty") {
        detectBadge.textContent = "";
        return;
      }
      const key = det.kind === "need-site" ? "need-site" : `${det.site}/${det.kind}`;
      const label = KIND_LABEL[key] || `识别为 ${labelOf(det.site)} / ${det.kind}`;
      detectBadge.textContent = label;
      detectBadge.classList.toggle("warn", det.kind === "need-site");
    } catch {
      detectBadge.textContent = "";
    }
  }

  function buildParseBody() {
    const text = query.value.trim();
    const limit = Number($("set-limit").value || 40);
    if (isBrowse() && state.jmode === "hot" && !text) {
      return {
        site: "jable",
        query: "hot",
        limit,
        jable: {
          mode: "hot",
          term: state.hotTerm,
          category: state.hotCat,
          pages: Number($("hot-pages").value || 2),
        },
      };
    }
    if (isBrowse() && state.jmode === "pick") {
      return {
        site: "jable",
        query: text || state.pickGroup,
        limit,
        jable: {
          mode: "pick",
          group: state.pickGroup,
          tag: state.pickTag,
          term: state.pickTerm,
          model: text,
          pages: Number($("pick-pages").value || 2),
        },
      };
    }
    if (state.site === "douyin" && state.dmode === "feed") {
      return { query: "https://www.douyin.com/?recommend=1", site: "douyin", limit };
    }
    if (state.site === "douyin" && state.dmode === "follow") {
      return { query: "https://www.douyin.com/follow", site: "douyin", limit };
    }
    if (state.site === "douyin" && state.dmode === "hashtag") {
      const tag = text.replace(/^#/, "");
      return { query: tag ? `#${tag}` : "", site: "douyin", limit };
    }
    if (state.site === "douyin" && state.dmode === "likes") {
      let likes = text;
      if (likes && /douyin\.com\/user\//i.test(likes) && !/showTab=/i.test(likes)) {
        likes += (likes.includes("?") ? "&" : "?") + "showTab=like";
      }
      return { query: likes, site: "douyin", limit };
    }
    const body = { query: text, site: state.site, limit };
    if (state.site === "youtube") body.tab = state.ytTab === "all" ? "" : state.ytTab;
    return body;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = query.value.trim();
    if (state.site === "jable" && !text) {
      query.focus();
      hint.textContent = "输入番号、标题或创作者后搜索。";
      return;
    }
    if (!isBrowse() && !isDouyinPreset() && !text) {
      query.focus();
      return;
    }
    if (isBrowse() && state.jmode === "pick" && state.pickGroup === "按女優" && !text) {
      query.focus();
      hint.textContent = "按创作者请输入用户名或 slug";
      return;
    }
    if (state.site === "douyin" && state.dmode === "hashtag" && !text) {
      query.focus();
      hint.textContent = "请输入话题名";
      return;
    }
    if (state.site === "douyin" && state.dmode === "likes" && !text) {
      query.focus();
      hint.textContent = "请粘贴用户主页链接";
      return;
    }
    closeStream();
    state.parseId = "";
    state.downloadId = "";
    state.preview = null;
    logEl.textContent = "";
    dlog.textContent = "";
    show(confirmPanel, false);
    show(progressPanel, false);
    show(logPanel, true);
    show(logEl, false);
    $("btn-toggle-log").setAttribute("aria-expanded", "false");
    logTitle.textContent = "解析";
    logStatus.textContent = "正在识别来源…";
    btnParse.disabled = true;
    setPhase("parse");
    setBoard("detect", { done: [] });
    try {
      const body = buildParseBody();
      if (!body.query && !body.jable) {
        throw new Error("请输入链接或选择列表");
      }
      const det = await api("/api/detect", body);
      if (det.kind === "need-site" || det.site === "unknown") {
        throw new Error(det.message || "请先选择来源");
      }
      appendLog(logEl, `识别 ${labelOf(det.site)} / ${det.kind}`);
      logStatus.textContent = `已识别 ${labelOf(det.site)}，正在拉取预览`;
      setBoard("parse", { done: ["detect"] });
      const task = await api("/api/parse", body);
      state.parseId = task.id;
      listen(task.id, {
        onLog: (line) => {
          appendLog(logEl, line);
          logStatus.textContent = line.slice(0, 80);
        },
        onPreview: (preview) => renderPreview(preview),
        onError: (msg) => {
          logStatus.textContent = "解析失败";
          show(logEl, true);
          setBoard("parse", { done: ["detect"], error: "parse" });
          hint.textContent = msg;
        },
        onDone: (rec) => {
          if (rec && rec.status === "error") return;
          logStatus.textContent = "预览已就绪";
        },
      });
    } catch (err) {
      logStatus.textContent = "失败";
      show(logEl, true);
      appendLog(logEl, String(err.message || err));
      setBoard("detect", { error: "detect" });
      hint.textContent = String(err.message || err);
    } finally {
      btnParse.disabled = false;
    }
  });

  function renderPreview(preview) {
    state.preview = preview;
    const items = preview.items || [];
    state.selected = new Set(items.map((it) => it.id));
    state.filter = "";
    $("card-filter").value = "";
    $("head-title").textContent = preview.title || "待确认";
    $("head-kicker").textContent = `${labelOf(preview.site)} · ${preview.kind || "预览"}`;
    $("head-sub").textContent = [preview.author, preview.hint, `${items.length} 条`]
      .filter(Boolean)
      .join("  ·  ");
    const cover = $("head-cover");
    const visual = $("head-visual");
    if (preview.cover) {
      cover.src = coverUrl(preview.cover);
      cover.hidden = false;
      visual.hidden = false;
      visual.style.backgroundImage = `url("${coverUrl(preview.cover)}")`;
    } else {
      cover.hidden = true;
      visual.hidden = true;
      visual.style.backgroundImage = "";
    }
    optQuality.classList.toggle("hidden", !preview.options || !preview.options.quality);
    optSubs.classList.toggle("hidden", !preview.options || !preview.options.subs);
    $("subs").checked = false;
    selAll.checked = true;
    cardsEl.innerHTML = "";
    items.forEach((item, index) => {
      const el = document.createElement("label");
      el.className = "card";
      el.dataset.id = item.id;
      el.dataset.title = (item.title || "").toLowerCase();
      el.style.setProperty("--i", String(index));
      const img = item.cover
        ? `<img alt="" src="${coverUrl(item.cover)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'无封面'}))">`
        : `<span class="ph">无封面</span>`;
      const dur = item.duration ? `<span class="card-dur">${escapeHtml(item.duration)}</span>` : "";
      let stats = "";
      let meta = [item.author, item.duration, item.subtitle].filter(Boolean).join("  ·  ");
      if (state.site === "jable") {
        stats = item.subtitle ? `<span class="card-stats">${escapeHtml(item.subtitle)}</span>` : "";
        meta = item.author && item.author !== "jable.tv" ? item.author : "";
      } else if (state.site === "youtube" || state.site === "douyin") {
        meta = [item.author, item.subtitle].filter(Boolean).join("  ·  ");
      }
      el.innerHTML = `
        <span class="card-media">
          ${img}
          <input type="checkbox" checked>
          ${dur}
          ${stats}
        </span>
        <span class="card-copy">
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(meta)}</p>
        </span>`;
      const box = el.querySelector("input");
      box.addEventListener("change", () => {
        if (box.checked) state.selected.add(item.id);
        else state.selected.delete(item.id);
        el.classList.toggle("off", !box.checked);
        updateSel();
      });
      cardsEl.appendChild(el);
    });
    updateSel();
    applyCardView();
    applyCardFilter();
    show(confirmPanel, true);
    setPhase("confirm");
    setBoard("confirm", { done: ["detect", "parse"] });
    confirmPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    const blocked = preview.downloadable === false;
    btnDownload.disabled = blocked || items.length === 0;
    if (blocked) hint.textContent = preview.hint || "该结果不能下载";
    else hint.textContent = preview.hint || "勾选后确认下载";
    document.title = `${preview.title || "openDownload"} · openDownload`;
  }

  function visibleCards() {
    return [...cardsEl.querySelectorAll(".card")].filter((card) => !card.classList.contains("hidden"));
  }

  function updateSel() {
    const n = state.selected.size;
    const total = (state.preview && state.preview.items && state.preview.items.length) || 0;
    selCount.textContent = `已选 ${n} / ${total}`;
    const vis = visibleCards();
    selAll.checked = vis.length > 0 && vis.every((card) => state.selected.has(card.dataset.id));
    btnDownload.disabled = n === 0 || (state.preview && state.preview.downloadable === false);
  }

  function applyCardFilter() {
    const q = state.filter.trim().toLowerCase();
    cardsEl.querySelectorAll(".card").forEach((card) => {
      const on = !q || (card.dataset.title || "").includes(q);
      card.classList.toggle("hidden", !on);
    });
    updateSel();
  }

  function applyCardView() {
    cardsEl.classList.toggle("list", state.cardView === "list");
    $("view-grid").classList.toggle("active", state.cardView === "grid");
    $("view-list").classList.toggle("active", state.cardView === "list");
    $("view-grid").setAttribute("aria-pressed", state.cardView === "grid" ? "true" : "false");
    $("view-list").setAttribute("aria-pressed", state.cardView === "list" ? "true" : "false");
  }

  selAll.addEventListener("change", () => {
    const on = selAll.checked;
    const vis = visibleCards();
    vis.forEach((card) => {
      const box = card.querySelector("input");
      box.checked = on;
      card.classList.toggle("off", !on);
      if (on) state.selected.add(card.dataset.id);
      else state.selected.delete(card.dataset.id);
    });
    updateSel();
  });

  $("card-filter").addEventListener("input", (e) => {
    state.filter = e.target.value || "";
    applyCardFilter();
  });
  $("view-grid").addEventListener("click", () => {
    state.cardView = "grid";
    applyCardView();
  });
  $("view-list").addEventListener("click", () => {
    state.cardView = "list";
    applyCardView();
  });

  btnDownload.addEventListener("click", async () => {
    if (!state.parseId || state.selected.size === 0) return;
    const quality = (document.querySelector('input[name="quality"]:checked') || {}).value || "1080p";
    const subs = $("subs").checked;
    show(progressPanel, true);
    show(dlog, false);
    $("btn-toggle-dlog").setAttribute("aria-expanded", "false");
    dlog.textContent = "";
    progressPanel.dataset.running = "true";
    setProgress({ percent: 1, label: "排队保存", speed: "", eta: "", item: 1, items: state.selected.size, phase: "queued" });
    setPhase("download");
    setBoard("download", { done: ["detect", "parse", "confirm"] });
    btnDownload.disabled = true;
    try {
      const task = await api("/api/download", {
        parse_id: state.parseId,
        ids: [...state.selected],
        quality,
        subs,
      });
      state.downloadId = task.id;
      listen(task.id, {
        onLog: (line) => appendLog(dlog, line),
        onProgress: (rec) => setProgress(rec),
        onError: (msg) => {
          hint.textContent = msg;
          progressPanel.dataset.running = "false";
          setBoard("download", { done: ["detect", "parse", "confirm"], error: "download" });
        },
        onDone: (rec) => {
          progressPanel.dataset.running = "false";
          if (rec.status === "error" || rec.status === "cancelled") {
            progLabel.textContent = rec.status === "cancelled" ? "已取消" : "失败";
            return;
          }
          setProgress({ percent: 100, label: "完成", speed: "", eta: "", phase: "done" });
          setPhase("done");
          setBoard("download", { done: ["detect", "parse", "confirm", "download"] });
          hint.textContent = "已收入本地馆藏，可打开目录查看";
          toast("保存完成");
        },
      });
    } catch (err) {
      progressPanel.dataset.running = "false";
      hint.textContent = String(err.message || err);
      setBoard("download", { error: "download", done: ["detect", "parse", "confirm"] });
    } finally {
      btnDownload.disabled = false;
    }
  });

  function setProgress(rec) {
    const pct = Math.max(0, Math.min(100, Number(rec.percent || 0)));
    barFill.style.width = pct + "%";
    pctEl.textContent = pct + "%";
    progLabel.textContent = rec.label || rec.phase || "";
    const bits = [];
    if (rec.items) bits.push(`${rec.item || 1}/${rec.items}`);
    if (rec.speed) bits.push(rec.speed);
    if (rec.eta) bits.push("剩余 " + rec.eta);
    if (rec.detail) bits.push(rec.detail);
    progExtra.textContent = bits.join("  ·  ");
    const raw = rec.phase || "";
    const phase = PHASE_ALIAS[raw] || raw;
    const idx = PHASE_ORDER.indexOf(phase);
    $("phases").querySelectorAll("li").forEach((li) => {
      const i = PHASE_ORDER.indexOf(li.dataset.phase);
      li.classList.toggle("active", li.dataset.phase === phase);
      li.classList.toggle("done", idx > 0 && i >= 0 && i < idx);
    });
  }

  btnCancel.addEventListener("click", async () => {
    if (!state.downloadId) return;
    try {
      await api(`/api/tasks/${state.downloadId}/cancel`, {});
    } catch (err) {
      hint.textContent = String(err.message || err);
    }
  });

  function toggleLog(btn, el) {
    const open = el.classList.toggle("hidden") === false;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  $("btn-toggle-log").addEventListener("click", () => toggleLog($("btn-toggle-log"), logEl));
  $("btn-toggle-dlog").addEventListener("click", () => toggleLog($("btn-toggle-dlog"), dlog));

  function formatSize(n) {
    if (!n) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    return (n / 1024 / 1024 / 1024).toFixed(1) + " GB";
  }

  function formatTime(ts) {
    if (!ts) return "";
    const delta = Date.now() / 1000 - ts;
    if (delta < 60) return "刚刚";
    if (delta < 3600) return Math.floor(delta / 60) + " 分钟前";
    if (delta < 86400) return Math.floor(delta / 3600) + " 小时前";
    if (delta < 86400 * 7) return Math.floor(delta / 86400) + " 天前";
    return new Date(ts * 1000).toLocaleDateString();
  }

  const SITE_NAME = { jable: "Jable", youtube: "YouTube", douyin: "抖音" };

  async function openLibrary() {
    const data = await api("/api/library");
    $("lib-path").textContent = data.path || "";
    const host = $("lib-body");
    const sites = data.sites || [];
    const any = sites.some((s) => s.count > 0);
    if (!any) {
      host.innerHTML = `<p class="lib-empty">还没有收入任何成品。解析并确认后，文件会按来源放进这个目录。</p>`;
    } else {
      host.innerHTML = sites
        .map((s) => {
          const rows = (s.recent || [])
            .map(
              (f) =>
                `<li><span class="name" title="${escapeHtml(f.rel)}">${escapeHtml(f.name)}</span><span class="meta">${escapeHtml(
                  [formatSize(f.size), formatTime(f.mtime)].filter(Boolean).join(" · ")
                )}</span></li>`
            )
            .join("");
          return `<section class="lib-site"><h3>${SITE_NAME[s.site] || s.site} · ${s.count} 个文件</h3>${
            rows ? `<ul>${rows}</ul>` : `<p class="lib-empty">此来源还是空的</p>`
          }</section>`;
        })
        .join("");
    }
    if (!libraryDlg.open) libraryDlg.showModal();
  }

  $("btn-library").addEventListener("click", () => {
    openLibrary().catch((err) => {
      hint.textContent = String(err.message || err);
    });
  });
  $("btn-open-folder").addEventListener("click", () => api("/api/open-library", {}));

  function renderHealth(health) {
    state.health = health;
    const items = [
      { ok: !!health.python, name: "Python", help: "运行工作台", detail: health.python || "未找到" },
      { ok: !!health.ffmpeg, name: "FFmpeg", help: "YouTube / Jable 封装 mp4", detail: health.ffmpeg || "未找到" },
      { ok: !!health.yt_dlp, name: "yt-dlp", help: "YouTube 解析与下载", detail: health.yt_dlp || "未找到" },
      { ok: !!health.playwright, name: "Playwright", help: "抖音登录类页面", detail: health.playwright ? "已安装" : "未安装" },
      { ok: !!health.cookie, name: "抖音 cookie", help: "主页 / 喜欢 / 关注 / 话题", detail: health.cookie ? "已加载" : "未找到" },
    ];
    const list = $("set-health-list");
    if (list) {
      list.innerHTML = items
        .map(
          (it) =>
            `<li><span>${escapeHtml(it.name)}<small style="display:block;color:var(--faint)">${escapeHtml(
              it.help
            )}</small></span><span class="${it.ok ? "ok" : "bad"}">${escapeHtml(it.ok ? "就绪" : "缺少")}</span></li>`
        )
        .join("");
    }
    $("set-health").textContent = items.map((it) => `${it.name} ${it.ok ? "就绪" : "缺少"}`).join("  ·  ");
    const critical = items.slice(1, 3);
    const dot = $("health-dot");
    dot.classList.remove("ok", "warn", "bad");
    if (critical.every((it) => it.ok)) {
      const softMiss = !health.cookie || !health.playwright;
      dot.classList.add(softMiss ? "warn" : "ok");
      dot.title = softMiss ? "核心依赖就绪，抖音登录功能未齐" : "环境就绪";
    } else {
      dot.classList.add("bad");
      dot.title = "缺少 FFmpeg 或 yt-dlp，下载可能失败";
    }
    return items;
  }

  async function openSettings() {
    const [settings, health] = await Promise.all([api("/api/settings"), api("/api/health")]);
    $("set-library").value = settings.library || "";
    $("set-limit").value = settings.limit || 40;
    $("set-workers").value = settings.workers || 64;
    renderHealth(health);
    if (!settingsDlg.open) settingsDlg.showModal();
  }

  $("btn-settings").addEventListener("click", () => {
    openSettings().catch((err) => {
      hint.textContent = String(err.message || err);
    });
  });
  $("health-dot").addEventListener("click", () => $("btn-settings").click());

  $("btn-save-settings").addEventListener("click", async (e) => {
    e.preventDefault();
    await api("/api/settings", {
      library: $("set-library").value,
      limit: Number($("set-limit").value || 40),
      workers: Number($("set-workers").value || 64),
    });
    const cookie = $("set-cookie").value.trim();
    if (cookie) await api("/api/cookie", { text: cookie });
    settingsDlg.close();
    hint.textContent = "环境已保存";
    toast("环境已保存");
    api("/api/health").then(renderHealth).catch(() => {});
  });

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const menuBtn = $("btn-menu");
  const router = $("site-router");
  if (menuBtn && router) {
    menuBtn.addEventListener("click", () => {
      const open = router.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
      menuBtn.setAttribute("aria-label", open ? "收起导航" : "展开导航");
    });
    router.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        router.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.setAttribute("aria-label", "展开导航");
      });
    });
  }

  document.querySelectorAll("[data-jmode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const before = `${state.jmode}|${state.listSlug}|${state.listYear}|${state.listMonth}|${state.listGroup}|${state.listSort}`;
      if (btn.dataset.listSlug) state.listSlug = btn.dataset.listSlug;
      if (btn.tagName === "A" && btn.getAttribute("href")) return;
      setJableMode(btn.dataset.jmode, true, { before });
    });
  });
  document.querySelectorAll("[data-dmode]").forEach((btn) => {
    btn.addEventListener("click", () => setDouyinMode(btn.dataset.dmode, true));
  });
  document.querySelectorAll("[data-yttab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.ytTab = btn.dataset.yttab;
      renderYtTabs();
      document.querySelectorAll("[data-yttab]").forEach((el) => {
        el.classList.toggle("active", el.dataset.yttab === state.ytTab);
      });
    });
  });
  document.querySelectorAll("[data-submit]").forEach((btn) => {
    btn.addEventListener("click", () => form.requestSubmit());
  });
  const ytLib = $("yt-guide-library");
  const ytSet = $("yt-guide-settings");
  if (ytLib) ytLib.addEventListener("click", () => $("btn-library").click());
  if (ytSet) ytSet.addEventListener("click", () => $("btn-settings").click());
  const searchBtn = $("jb-search-btn");
  if (searchBtn) {
    searchBtn.addEventListener("click", () => {
      document.body.classList.toggle("jb-search-open");
      if (document.body.classList.contains("jb-search-open")) query.focus();
    });
  }
  const heroPrev = $("jb-hero-prev");
  const heroNext = $("jb-hero-next");
  if (heroPrev) heroPrev.addEventListener("click", () => heroTick(-1));
  if (heroNext) heroNext.addEventListener("click", () => heroTick(1));
  const heroDots = $("jb-hero-dots");
  if (heroDots) {
    heroDots.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-hero]");
      if (!btn) return;
      state.heroIndex = Number(btn.dataset.hero) || 0;
      renderHero();
    });
  }
  document.addEventListener("click", (e) => {
    const host = e.target.closest(".av-pager");
    if (!host) return;
    const btn = e.target.closest("[data-go]");
    if (!btn || btn.disabled) return;
    const go = Number(btn.getAttribute("data-go"));
    if (!go || go < 1) return;
    const kind = host.getAttribute("data-pager");
    if (kind === "list") gotoListPage(go);
    else if (kind === "hot") {
      state.homeHotPage = go;
      if (state.jableHome) renderJableHome(state.jableHome);
    } else if (kind === "latest") {
      state.homeLatestPage = go;
      if (state.jableHome) renderJableHome(state.jableHome);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const input = e.target.closest(".av-pager-input");
    if (!input) return;
    const host = input.closest(".av-pager");
    if (!host) return;
    const go = Number(input.value);
    const kind = host.getAttribute("data-pager");
    if (kind === "list") gotoListPage(go);
    else if (kind === "hot") {
      state.homeHotPage = go;
      if (state.jableHome) renderJableHome(state.jableHome);
    } else if (kind === "latest") {
      state.homeLatestPage = go;
      if (state.jableHome) renderJableHome(state.jableHome);
    }
  });
  const listRoot = $("jable-list");
  if (listRoot) {
    listRoot.addEventListener("click", (e) => {
      const ddBtn = e.target.closest(".av-dd-btn");
      if (ddBtn) {
        const box = ddBtn.closest(".av-dd");
        const open = box && !box.classList.contains("open");
        closeFilterMenus(box);
        if (box) {
          box.classList.toggle("open", open);
          ddBtn.setAttribute("aria-expanded", open ? "true" : "false");
        }
        e.stopPropagation();
        return;
      }
      const sortBtn = e.target.closest("[data-sort]");
      if (sortBtn) {
        if (state.jmode === "model") {
          const sort = sortBtn.dataset.sort || "post_date";
          const base = `#/jable/model/${encodeURIComponent(state.listSlug)}`;
          location.hash = sort === "video_viewed" ? `${base}/viewed` : base;
          return;
        }
        location.hash = `#/jable/${sortBtn.dataset.sort || "hot"}`;
        return;
      }
      const yearBtn = e.target.closest("[data-year]");
      if (yearBtn) {
        location.hash = latestHash(yearBtn.dataset.year || "", state.listMonth);
        return;
      }
      const monthBtn = e.target.closest("[data-month]");
      if (monthBtn) {
        location.hash = latestHash(state.listYear, monthBtn.dataset.month || "");
        return;
      }
      const catBtn = e.target.closest("[data-cat]");
      if (catBtn) {
        const slug = catBtn.dataset.cat || "";
        state.listGroup = "";
        location.hash = slug ? `#/jable/cat/${encodeURIComponent(slug)}` : "#/jable/type";
        return;
      }
      const groupBtn = e.target.closest("[data-group]");
      if (groupBtn) {
        const group = groupBtn.dataset.group || "";
        state.listGroup = group;
        e.stopPropagation();
        if (!group) {
          location.hash = "#/jable/type";
          return;
        }
        fillCascadeLevel2();
        return;
      }
      const tagBtn = e.target.closest("[data-tag]");
      if (tagBtn) {
        const slug = tagBtn.dataset.tag || "";
        location.hash = slug
          ? `#/jable/tag/${encodeURIComponent(slug)}`
          : state.listGroup
            ? `#/jable/type/${encodeURIComponent(state.listGroup)}`
            : "#/jable/type";
      }
    });
  }
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#jb-filters .av-dd")) closeFilterMenus();
    const catBtn = e.target.closest("[data-hot-cat]");
    if (catBtn && catBtn.dataset.hotCat) state.hotCat = catBtn.dataset.hotCat;
    const pickBtn = e.target.closest("[data-pick-group]");
    if (pickBtn && pickBtn.dataset.pickGroup) {
      state.pickGroup = pickBtn.dataset.pickGroup;
      state.pickTag = "";
    }
  });
  const viewJable = $("view-jable");
  if (viewJable) {
    viewJable.addEventListener("click", (e) => {
      const actorChip = e.target.closest("#jb-inspect-actors a.jb-chip");
      if (actorChip) {
        const href = actorChip.getAttribute("href") || "";
        if (!href || href === "#") e.preventDefault();
        return;
      }
      const actorLink = e.target.closest("a.av-card-actor");
      if (actorLink) {
        e.stopPropagation();
        return;
      }
      const card = e.target.closest(".av-card, a.av-hero-card");
      if (!card) return;
      if (state.jmode === "watch") return;
      if (card.closest("#jable-watch")) return;
      e.preventDefault();
      const code = codeFromCard(card);
      if (!code) return;
      if (state.inspectCode && playKey(state.inspectCode) === playKey(code)) {
        closeJableInspect();
        return;
      }
      openJableInspect(code, { source: inspectSourceFromCard(card) });
    });
  }
  const inspectClose = $("jb-inspect-close");
  if (inspectClose) {
    inspectClose.addEventListener("click", () => closeJableInspect());
  }
  const inspectFull = $("jb-inspect-full");
  if (inspectFull) {
    inspectFull.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      playInspectFull(state.inspectCode);
    });
  }
  const inspectWatch = $("jb-inspect-watch");
  if (inspectWatch) {
    inspectWatch.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startFullWatchPage(state.inspectCode);
    });
  }
  async function startJableSave(code) {
    const raw = playKey(code);
    if (!raw) return;
    closeStream();
    state.downloadId = "";
    dlog.textContent = "";
    show(progressPanel, true);
    show(dlog, true);
    $("btn-toggle-dlog").setAttribute("aria-expanded", "true");
    progressPanel.dataset.running = "true";
    setProgress({ percent: 1, label: "准备下载 " + raw.toUpperCase(), speed: "", eta: "", item: 1, items: 1, phase: "queued" });
    setPhase("download");
    setBoard("download", { done: ["detect", "parse", "confirm"] });
    hint.textContent = "正在保存 " + raw.toUpperCase();
    $("workbench")?.scrollIntoView({ behavior: "smooth", block: "start" });
    const saveBtn = $("jb-inspect-save");
    const watchBtn = $("jb-watch-dl");
    if (saveBtn) saveBtn.disabled = true;
    if (watchBtn) watchBtn.disabled = true;
    try {
      const task = await api("/api/jable/save", { code: raw, subs: false });
      state.downloadId = task.id;
      listen(task.id, {
        onLog: (line) => appendLog(dlog, line),
        onProgress: (rec) => setProgress(rec),
        onError: (msg) => {
          hint.textContent = msg;
          progressPanel.dataset.running = "false";
          setBoard("download", { done: ["detect", "parse", "confirm"], error: "download" });
        },
        onDone: (rec) => {
          progressPanel.dataset.running = "false";
          if (rec.status === "error" || rec.status === "cancelled") {
            progLabel.textContent = rec.status === "cancelled" ? "已取消" : "失败";
            return;
          }
          setProgress({ percent: 100, label: "完成", speed: "", eta: "", phase: "done" });
          setPhase("done");
          setBoard("download", { done: ["detect", "parse", "confirm", "download"] });
          hint.textContent = "已收入本地馆藏，可打开目录查看";
          toast("保存完成 " + raw.toUpperCase());
        },
      });
    } catch (err) {
      progressPanel.dataset.running = "false";
      hint.textContent = String((err && err.message) || err);
      setBoard("download", { error: "download", done: ["detect", "parse", "confirm"] });
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (watchBtn) watchBtn.disabled = false;
    }
  }

  const inspectSave = $("jb-inspect-save");
  if (inspectSave) {
    inspectSave.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startJableSave(state.inspectCode);
    });
  }
  const watchDl = $("jb-watch-dl");
  if (watchDl) {
    watchDl.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startJableSave(state.watchCode || state.inspectCode);
    });
  }
  const cookieBtn = $("btn-cookie-settings");
  if (cookieBtn) {
    cookieBtn.addEventListener("click", () => {
      $("btn-settings").click();
      setTimeout(() => {
        const box = $("set-cookie");
        if (box) box.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 200);
    });
  }

  query.addEventListener("input", () => {
    clearTimeout(state.detectTimer);
    state.detectTimer = setTimeout(liveDetect, 280);
  });

  $("jb-retry").addEventListener("click", () => loadJableHome(true));
  $("jb-reset-filters").addEventListener("click", () => {
    const base = ["hot", "week", "month", "all"].includes(state.jmode) ? "hot" : state.jmode === "latest" ? "latest" : state.jmode === "model" ? "model" : "type";
    state.listYear = "";
    state.listMonth = "";
    state.listGroup = "";
    if (base !== "model") state.listSlug = "";
    state.listSort = base === "hot" ? "video_viewed_today" : base === "type" ? "post_date_and_popularity" : "post_date";
    state.listPage = 1;
    closeFilterMenus();
    const target = base === "model" ? `#/jable/model/${encodeURIComponent(state.listSlug)}` : `#/jable/${base}`;
    if (location.hash === target) setJableMode(base, false);
    else location.hash = target;
  });
  $("jb-filters").addEventListener("keydown", (e) => {
    const dropdown = e.target.closest(".av-dd");
    if (!dropdown) return;
    if (e.key === "ArrowDown" && e.target.matches(".av-dd-btn")) {
      e.preventDefault();
      closeFilterMenus(dropdown);
      dropdown.classList.add("open");
      e.target.setAttribute("aria-expanded", "true");
      dropdown.querySelector(".av-dd-menu button")?.focus();
    } else if (e.key === "Escape") {
      closeFilterMenus();
      dropdown.querySelector(".av-dd-btn")?.focus();
    }
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !settingsDlg.open && !libraryDlg.open) {
      e.preventDefault();
      query.focus();
      query.select();
    }
    if (e.key === "Escape") {
      if (state.inspectCode) closeJableInspect();
      closeFilterMenus();
      if (settingsDlg.open) settingsDlg.close();
      if (libraryDlg.open) libraryDlg.close();
      if (router.classList.contains("open")) {
        router.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.setAttribute("aria-label", "展开导航");
        menuBtn.focus();
      }
    }
  });

  function restoreSiteHash() {
    let next =
      state.site === "jable" && state.jmode === "watch" && state.watchCode
        ? `#/jable/v/${encodeURIComponent(state.watchCode)}`
        : state.site === "jable"
          ? listHashBase()
          : `#/${state.site}${
              state.site === "douyin" && state.dmode !== "link" ? `/${state.dmode}` : ""
            }`;
    if (state.site === "jable" && state.inspectCode && state.jmode !== "watch") {
      next = inspectHash(state.inspectCode);
    }
    if (location.hash !== next) location.hash = next;
  }

  settingsDlg.addEventListener("close", () => {
    if (hashParts().panel === "setup") restoreSiteHash();
  });
  libraryDlg.addEventListener("close", () => {
    if (hashParts().panel === "library") restoreSiteHash();
  });

  function applyHash() {
    const parts = hashParts();
    if (parts.panel === "setup") {
      openSettings().catch(() => {});
      return;
    }
    if (parts.panel === "library") {
      openLibrary().catch(() => {});
      return;
    }
    setSite(parts.site);
    if (parts.site === "jable" && parts.inspect) {
      const same =
        playKey(state.inspectCode) === playKey(parts.inspect) &&
        document.body.classList.contains("jb-inspect-open");
      if (!same) openJableInspect(parts.inspect, { fromHash: true });
    } else if (parts.site === "jable" && parts.video) {
      openJableWatch(parts.video);
    } else {
      closeJableInspect({ fromHash: true });
    }
    if (state.inspectReturnCode && !state.inspectCode) {
      const source = Array.from(document.querySelectorAll(".av-card")).find((el) => el.dataset.code === state.inspectReturnCode);
      source?.querySelector(".av-card-link")?.focus({ preventScroll: true });
      state.inspectReturnCode = "";
    }
  }

  window.addEventListener("hashchange", applyHash);
  if (!location.hash) location.hash = "#/auto";
  applyHash();
  renderYtTabs();

  api("/api/health")
    .then((h) => {
      renderHealth(h);
      const miss = [];
      if (!h.ffmpeg) miss.push("FFmpeg");
      if (!h.yt_dlp) miss.push("yt-dlp");
      if (miss.length) {
        hint.dataset.sticky = "1";
        hint.textContent = "缺少 " + miss.join("、") + "，保存可能失败。打开「设置」查看依赖状态。";
      }
    })
    .catch(() => {});
})();
