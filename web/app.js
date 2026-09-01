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
    auto: "粘贴链接，或输入用户名 / 番号 / 抖音号",
    jable: "链接、番号，或创作者用户名（三上悠亜 / yua-mikami）",
    youtube: "视频链接、@频道 或用户名",
    douyin: "作品 / 主页链接，或抖音号",
  };

  const COPY = {
    auto: {
      title: "你想探索什么？",
      lede: "粘贴链接或输入用户名，从四座馆藏里找出要保存的作品。",
      eyebrow: "本地馆藏 · 解析 · 确认 · 收藏",
    },
    jable: {
      title: "从 Jable 开始探索",
      lede: "输入番号或创作者，也可以用热门与选片浏览公开列表。",
      eyebrow: "链接 · 热门 · 选片",
    },
    youtube: {
      title: "从 YouTube 开始探索",
      lede: "输入视频链接、@频道或用户名。频道可先选分栏，清晰度与字幕在预览里再定。",
      eyebrow: "视频 · 频道 · 分栏",
    },
    douyin: {
      title: "从抖音开始探索",
      lede: "公开作品链接可直接解析。主页、推荐、关注、话题和喜欢需要 cookie。",
      eyebrow: "作品 · 主页 · 登录功能",
    },
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
    desktopPath: "",
    detectTimer: 0,
    toastTimer: 0,
    cardView: "grid",
    filter: "",
  };

  function hashParts() {
    const raw = (location.hash || "").replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    const head = parts[0] || "auto";
    if (head === "setup" || head === "library") {
      return { site: state.site || "auto", jmode: "link", dmode: "link", panel: head };
    }
    const site = ["auto", "jable", "youtube", "douyin"].includes(head) ? head : "auto";
    const jmode = site === "jable" && ["hot", "pick", "link"].includes(parts[1] || "") ? parts[1] : "link";
    const dmode =
      site === "douyin" && ["feed", "follow", "hashtag", "likes", "link"].includes(parts[1] || "")
        ? parts[1]
        : "link";
    return { site, jmode, dmode, panel: "" };
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

  function setJableMode(mode, pushHash) {
    state.jmode = mode || "link";
    const tools = $("jable-tools");
    if (tools) tools.classList.toggle("hidden", state.site !== "jable");
    document.querySelectorAll("#jable-tools [data-jmode]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.jmode === state.jmode);
    });
    show($("jable-hot"), state.site === "jable" && state.jmode === "hot");
    show($("jable-pick"), state.site === "jable" && state.jmode === "pick");
    if (state.site === "jable") {
      query.placeholder =
        state.jmode === "pick" && state.pickGroup === "按女優"
          ? "创作者用户名或 slug，例如 yua-mikami"
          : PLACEHOLDERS.jable;
    }
    if (pushHash && state.site === "jable") {
      const next = state.jmode === "link" ? "#/jable" : `#/jable/${state.jmode}`;
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
  }

  function applyCopy(site) {
    const copy = COPY[site] || COPY.auto;
    const title = $("hero-title");
    const lede = $("hero-lede");
    const eyebrow = $("hero-eyebrow");
    if (title) title.textContent = copy.title;
    if (lede) lede.textContent = copy.lede;
    if (eyebrow) eyebrow.textContent = copy.eyebrow;
  }

  function setSite(site) {
    state.site = site;
    document.body.dataset.site = site;
    document.querySelectorAll(".site-router a, .source-card, .exhibit").forEach((el) => {
      const on = el.dataset.site === site;
      el.classList.toggle("active", on);
      if (el.getAttribute("role") === "tab") {
        el.setAttribute("aria-selected", on ? "true" : "false");
      }
    });
    query.placeholder = PLACEHOLDERS[site] || PLACEHOLDERS.auto;
    applyCopy(site);
    if (!hint.dataset.sticky) hint.textContent = "";
    show($("jable-tools"), site === "jable");
    show($("youtube-tools"), site === "youtube");
    show($("douyin-tools"), site === "douyin");
    const parts = hashParts();
    setJableMode(site === "jable" ? parts.jmode : "link", false);
    setDouyinMode(site === "douyin" ? parts.dmode : "link", false);
    if (site === "youtube") renderYtTabs();
    if (site === "jable") loadJableCatalog();
    liveDetect();
  }

  function labelOf(site) {
    return { auto: "自动", jable: "Jable", youtube: "YouTube", douyin: "抖音" }[site] || site;
  }

  function setBoard(active, extras = {}) {
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
    } catch (err) {
      hint.textContent = String(err.message || err);
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
    if (isBrowse() && state.jmode === "hot") {
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
      const meta = [item.author, item.duration, item.subtitle].filter(Boolean).join("  ·  ");
      el.innerHTML = `
        <span class="card-media">
          ${img}
          <input type="checkbox" checked>
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
      host.innerHTML = `<p class="lib-empty">还没有收入任何成品。解析并确认后，文件会按来源放进这个目录（默认是桌面）。</p>`;
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
    state.desktopPath = settings.desktop || "";
    $("set-library").value = settings.library || state.desktopPath || "";
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
  $("btn-use-desktop").addEventListener("click", () => {
    const path = state.desktopPath;
    if (path) $("set-library").value = path;
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
    });
    router.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        router.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
      });
    });
  }

  document.querySelectorAll("#jable-tools [data-jmode]").forEach((btn) => {
    btn.addEventListener("click", () => setJableMode(btn.dataset.jmode, true));
  });
  document.querySelectorAll("#douyin-tools [data-dmode]").forEach((btn) => {
    btn.addEventListener("click", () => setDouyinMode(btn.dataset.dmode, true));
  });

  query.addEventListener("input", () => {
    clearTimeout(state.detectTimer);
    state.detectTimer = setTimeout(liveDetect, 280);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (settingsDlg.open) settingsDlg.close();
      if (libraryDlg.open) libraryDlg.close();
    }
  });

  function restoreSiteHash() {
    const next = `#/${state.site}${
      state.site === "jable" && state.jmode !== "link"
        ? `/${state.jmode}`
        : state.site === "douyin" && state.dmode !== "link"
          ? `/${state.dmode}`
          : ""
    }`;
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
        hint.textContent = "缺少 " + miss.join("、") + "，保存可能失败。点右上角「环境」查看安装说明。";
      }
    })
    .catch(() => {});
})();
