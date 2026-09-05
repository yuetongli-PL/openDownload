export function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function raw(value) {
  return mark(String(value ?? ""));
}

function mark(text) {
  const boxed = new String(text);
  boxed.__html = text;
  return boxed;
}

function interp(value) {
  if (value == null || value === false) return "";
  if (Array.isArray(value)) return value.map(interp).join("");
  if (typeof value === "object" && value && Object.prototype.hasOwnProperty.call(value, "__html")) {
    return String(value.__html);
  }
  return esc(value);
}

export function html(strings, ...values) {
  let out = "";
  for (let i = 0; i < strings.length; i += 1) {
    out += strings[i];
    if (i < values.length) out += interp(values[i]);
  }
  return mark(out);
}

export function qs(sel, root = document) {
  return root.querySelector(sel);
}

export function qsa(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

export function delegate(root, type, selector, handler) {
  const onEvent = (event) => {
    const node = event.target.closest(selector);
    if (!node || !root.contains(node)) return;
    handler(event, node);
  };
  root.addEventListener(type, onEvent);
  return () => root.removeEventListener(type, onEvent);
}

export function focusTrap(root, { autoFocus = true } = {}) {
  const selector =
    'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
  const getFocusable = () => qsa(selector, root).filter((el) => !el.hasAttribute("disabled") && !el.closest("[hidden]"));
  const onKey = (event) => {
    if (event.key !== "Tab") return;
    const items = getFocusable();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  root.addEventListener("keydown", onKey);
  if (autoFocus) {
    const first = getFocusable()[0];
    if (first) first.focus();
  }
  return () => root.removeEventListener("keydown", onKey);
}
