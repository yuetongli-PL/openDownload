export function createStore(initial = {}, options = {}) {
  const persistKey = options.persistKey || "";
  const persistKeys = options.persistKeys || null;
  let state = { ...initial };

  if (persistKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(persistKey) || "null");
      if (saved && typeof saved === "object") {
        state = persistKeys
          ? { ...state, ...Object.fromEntries(persistKeys.map((k) => [k, saved[k] ?? state[k]])) }
          : { ...state, ...saved };
      }
    } catch {
      /* ignore */
    }
  }

  const listeners = new Set();

  function persist() {
    if (!persistKey) return;
    const payload = persistKeys
      ? Object.fromEntries(persistKeys.map((k) => [k, state[k]]))
      : state;
    try {
      localStorage.setItem(persistKey, JSON.stringify(payload));
    } catch {
      /* ignore */
    }
  }

  function notify() {
    listeners.forEach((fn) => fn(state));
  }

  return {
    get(key) {
      return key == null ? state : state[key];
    },
    set(next) {
      state = typeof next === "function" ? next(state) : { ...next };
      persist();
      notify();
      return state;
    },
    patch(partial) {
      state = { ...state, ...(typeof partial === "function" ? partial(state) : partial) };
      persist();
      notify();
      return state;
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
