const TIMEOUT = 30000;

function normalizeError(err, status = 0) {
  if (err && typeof err === "object" && "message" in err && "status" in err) return err;
  const message =
    (err && err.message) ||
    (typeof err === "string" ? err : "请求失败");
  return { message, status };
}

async function request(method, url, body) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT);
  try {
    const init = {
      method,
      signal: ctrl.signal,
      headers: {},
    };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(url, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText || "请求失败";
      throw normalizeError({ message: typeof detail === "string" ? detail : JSON.stringify(detail), status: res.status });
    }
    return data;
  } catch (err) {
    if (err && err.name === "AbortError") throw normalizeError({ message: "请求超时", status: 0 });
    throw normalizeError(err, err.status || 0);
  } finally {
    clearTimeout(timer);
  }
}

export function get(url) {
  return request("GET", url);
}

export function post(url, body = {}) {
  return request("POST", url, body);
}

export function del(url) {
  return request("DELETE", url);
}

export function sse(url, handlers = {}) {
  const es = new EventSource(url);
  es.onmessage = (ev) => {
    let rec;
    try {
      rec = JSON.parse(ev.data);
    } catch {
      return;
    }
    const type = rec.event;
    if (type === "log" && rec.text && handlers.log) handlers.log(rec.text, rec);
    if (type === "progress" && handlers.progress) handlers.progress(rec);
    else if (rec.percent != null && rec.percent !== "" && handlers.progress && type !== "done" && type !== "close") {
      handlers.progress(rec);
    }
    if (type === "preview" && handlers.preview) handlers.preview(rec.preview, rec);
    if (type === "error" && handlers.error) handlers.error(rec.message || "失败", rec);
    if (type === "done" && handlers.done) handlers.done(rec);
    if (type === "close") {
      if (handlers.close) handlers.close(rec);
      es.close();
    }
  };
  es.onerror = () => {
    if (handlers.fail) handlers.fail();
  };
  return () => es.close();
}

export const api = { get, post, del, sse };
