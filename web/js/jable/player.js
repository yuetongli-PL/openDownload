import { get } from "../core/api.js";
import { FAST_HLS_CONFIG, PLAY_TTL_MS, playKey, state } from "./state.js";

let hlsLoader = null;

export function loadHls() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (hlsLoader) return hlsLoader;
  hlsLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/static/vendor/hls.min.js";
    script.async = true;
    script.onload = () => (window.Hls ? resolve(window.Hls) : reject(new Error("Hls 不可用")));
    script.onerror = () => reject(new Error("无法加载播放器"));
    document.head.appendChild(script);
  });
  return hlsLoader;
}

export function playErrorMessage(err) {
  const msg = String((err && err.message) || err || "");
  if (/1015|限流|拦截|cloudflare|rate limited/i.test(msg)) {
    return "站点限流，完整视频暂不可用。请过几分钟再试完整视频";
  }
  return msg || "完整视频暂不可用";
}

export function dmmPlayUrl(code) {
  return "/api/dmm/preview/play?code=" + encodeURIComponent(playKey(code));
}

export function getPlayInfo(code) {
  const key = playKey(code);
  if (!key) return Promise.reject(new Error("缺少番号"));
  const hit = state.playCache.get(key);
  if (hit && Date.now() - hit.at < PLAY_TTL_MS && hit.data && hit.data.stream) return Promise.resolve(hit.data);
  if (state.playInflight.has(key)) return state.playInflight.get(key);
  const pending = Promise.race([
    get("/api/jable/play?code=" + encodeURIComponent(key)),
    new Promise((_, reject) => setTimeout(() => reject(new Error("解析超时")), 28000)),
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

export function cachedPlayStream(code) {
  const key = playKey(code);
  if (!key) return "";
  const hit = state.playCache.get(key);
  if (hit && Date.now() - hit.at < PLAY_TTL_MS && hit.data && hit.data.stream) return hit.data.stream;
  return "";
}

export function warmHlsBrowser(src) {
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

function bindHlsErrors(hls, statusEl) {
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
    if (statusEl) statusEl.textContent = "播放失败，可改用下载";
  });
}

function attachNativeOrHls(hlsRef, setHls, getSrc, setSrc, video, src, statusEl, onParsed) {
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  if (getSrc() === src && hlsRef()) {
    video.play().catch(() => {});
    return;
  }
  setSrc(src);
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    if (video.getAttribute("src") !== src) video.src = src;
    video.play().catch(() => {});
    return;
  }
  const hls = hlsRef();
  if (hls) {
    try {
      hls.stopLoad();
    } catch {
      /* ignore */
    }
    if (hls.media !== video) {
      try {
        hls.attachMedia(video);
      } catch {
        /* ignore */
      }
    }
    hls.loadSource(src);
    video.play().catch(() => {});
    return;
  }
  if (window.Hls && window.Hls.isSupported()) {
    const next = new window.Hls(FAST_HLS_CONFIG);
    setHls(next);
    if (onParsed) next.on(window.Hls.Events.MANIFEST_PARSED, onParsed);
    bindHlsErrors(next, statusEl);
    next.attachMedia(video);
    next.loadSource(src);
    video.play().catch(() => {});
    return;
  }
  video.src = src;
  video.play().catch(() => {});
}

export function destroyHls(hard) {
  const video = document.getElementById("jb-video");
  if (state.hls) {
    try {
      state.hls.stopLoad();
    } catch {
      /* ignore */
    }
    if (hard) {
      try {
        state.hls.destroy();
      } catch {
        /* ignore */
      }
      state.hls = null;
    }
  }
  state.hlsSrc = "";
  if (video) video.pause();
}

export function destroyInspectHls(hard) {
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

export function attachWatchHls(video, src) {
  attachNativeOrHls(
    () => state.hls,
    (h) => {
      state.hls = h;
    },
    () => state.hlsSrc,
    (s) => {
      state.hlsSrc = s;
    },
    video,
    src,
    document.getElementById("jb-watch-status"),
    () => {
      const el = document.getElementById("jb-video");
      if (el) el.play().catch(() => {});
    }
  );
}

export function attachInspectHls(video, src) {
  attachNativeOrHls(
    () => state.inspectHls,
    (h) => {
      state.inspectHls = h;
    },
    () => state.inspectHlsSrc,
    (s) => {
      state.inspectHlsSrc = s;
    },
    video,
    src,
    document.getElementById("jb-inspect-status"),
    () => {
      const el = document.getElementById("jb-inspect-video");
      if (el && document.body.classList.contains("jb-inspect-open")) el.play().catch(() => {});
    }
  );
}

export function attachDmmPreview(code, video, statusEl, mine) {
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
}

export function resetInspectVideo() {
  const video = document.getElementById("jb-inspect-video");
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

export function handoverInspectToWatch() {
  const from = document.getElementById("jb-inspect-video");
  const to = document.getElementById("jb-video");
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

export function destroyAllPlayers() {
  destroyHls(true);
  destroyInspectHls(true);
  const inspect = document.getElementById("jb-inspect-video");
  const watch = document.getElementById("jb-video");
  [inspect, watch].forEach((video) => {
    if (!video) return;
    video.pause();
    video.removeAttribute("src");
    try {
      video.load();
    } catch {
      /* ignore */
    }
  });
}
