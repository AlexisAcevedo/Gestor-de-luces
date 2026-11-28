/*
 * Minimal in-memory DOM, Window, LocalStorage, and I18N test harness for ui/js modules.
 */

function splitClasses(className) {
  return String(className || "").split(/\s+/).filter(Boolean);
}

export function createMemoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  const setCalls = [];
  return {
    data,
    setCalls,
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      setCalls.push({ key, value: String(value) });
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    }
  };
}

export function createFakeI18n() {
  const calls = [];
  const translateDomCalls = [];
  let currentLang = "en";
  return {
    calls,
    translateDomCalls,
    getLanguage() {
      return currentLang;
    },
    setLanguage(lang) {
      currentLang = lang;
    },
    translateDom() {
      translateDomCalls.push(currentLang);
    },
    t(key, vars) {
      calls.push({ key, vars });
      if (!vars) return `T(${key})`;
      const rendered = Object.entries(vars)
        .map(([k, v]) => `${k}=${v}`)
        .join(",");
      return `T(${key}|${rendered})`;
    }
  };
}

export function createStyle() {
  const props = new Map();
  return {
    props,
    setProperty(name, value) {
      props.set(name, String(value));
    },
    getPropertyValue(name) {
      return props.get(name) ?? "";
    },
    removeProperty(name) {
      props.delete(name);
    }
  };
}

export function createDomEnvironment({ elementsById = {}, hash = "", storageInitial = {} } = {}) {
  const registered = new Set();
  const roots = new Set();
  const windowListeners = new Map();
  const docListeners = new Map();

  class FakeElement {
    constructor(tagName) {
      this.tagName = String(tagName).toLowerCase();
      this.parentNode = null;
      this.children = [];
      this.attributes = new Map();
      this.listeners = new Map();
      this.style = createStyle();
      this.dataset = {};
      this.className = "";
      this.textContent = "";
      this.id = "";
      this.value = "";
      this.min = "";
      this.max = "";
      this.checked = false;
      this.disabled = false;
      this.hidden = false;
      this.open = false;
      this.title = "";
      this.type = "";
      this.tabIndex = -1;
      this.width = 200;
      this.height = 200;
      this.clientWidth = 200;
      this.replaceChildrenCalls = 0;
      this.focusCount = 0;
      this.selectCount = 0;
      this.showModalCount = 0;
      this.closeCount = 0;
    }

    get options() {
      return this.children.filter((c) => c.tagName === "option");
    }

    get classList() {
      const el = this;
      return {
        add(...names) {
          const set = new Set(splitClasses(el.className));
          for (const name of names) set.add(name);
          el.className = [...set].join(" ");
        },
        remove(...names) {
          const drop = new Set(names);
          el.className = splitClasses(el.className).filter((n) => !drop.has(n)).join(" ");
        },
        contains(name) {
          return splitClasses(el.className).includes(name);
        },
        toggle(name, force) {
          const has = splitClasses(el.className).includes(name);
          const on = force === undefined ? !has : Boolean(force);
          if (on) this.add(name);
          else this.remove(name);
          return on;
        }
      };
    }

    setAttribute(name, value) {
      const str = String(value);
      this.attributes.set(name, str);
      if (name === "id") this.id = str;
      if (name === "class") this.className = str;
      if (name === "value") this.value = str;
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-([a-z])/g, (_m, l) => l.toUpperCase());
        this.dataset[key] = str;
      }
    }

    getAttribute(name) {
      if (name === "class") return this.className || null;
      if (name === "id") return this.id || null;
      if (name === "value") return this.value;
      return this.attributes.has(name) ? this.attributes.get(name) : null;
    }

    removeAttribute(name) {
      this.attributes.delete(name);
    }

    appendChild(child) {
      if (child.parentNode) child.parentNode.removeChild(child);
      child.parentNode = this;
      this.children.push(child);
      registered.add(child);
      return child;
    }

    append(...children) {
      for (const child of children) this.appendChild(child);
    }

    removeChild(child) {
      this.children = this.children.filter((entry) => entry !== child);
      if (child.parentNode === this) child.parentNode = null;
      registered.delete(child);
      return child;
    }

    replaceChildren(...children) {
      this.replaceChildrenCalls += 1;
      for (const child of [...this.children]) this.removeChild(child);
      this.append(...children);
    }

    contains(node) {
      if (!node) return false;
      let cur = node;
      while (cur) {
        if (cur === this) return true;
        cur = cur.parentNode;
      }
      return false;
    }

    addEventListener(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(handler);
    }

    removeEventListener(type, handler) {
      const list = this.listeners.get(type) || [];
      this.listeners.set(type, list.filter((e) => e !== handler));
    }

    dispatchEvent(event) {
      const evt = typeof event === "string" ? { type: event } : event;
      if (!evt.target) evt.target = this;
      if (!evt.preventDefault) evt.preventDefault = () => {};
      if (!evt.stopPropagation) evt.stopPropagation = () => {};
      for (const handler of this.listeners.get(evt.type) || []) handler(evt);
      return true;
    }

    click() {
      this.dispatchEvent({ type: "click", target: this });
    }

    focus() {
      this.focusCount += 1;
      documentObj.activeElement = this;
    }

    select() {
      this.selectCount += 1;
    }

    showModal() {
      this.open = true;
      this.showModalCount += 1;
    }

    close() {
      this.open = false;
      this.closeCount += 1;
    }

    setPointerCapture() {}

    getBoundingClientRect() {
      return { left: 0, top: 0, width: this.clientWidth || 200, height: this.height || 200 };
    }

    getContext() {
      return {
        createImageData(w, h) {
          return { data: new Uint8ClampedArray(w * h * 4) };
        },
        putImageData() {}
      };
    }

    querySelectorAll(selector) {
      return queryAll(this, selector);
    }

    querySelector(selector) {
      return queryAll(this, selector)[0] || null;
    }
  }

  function isInside(el, root) {
    let cur = el;
    while (cur) {
      if (cur === root) return true;
      cur = cur.parentNode;
    }
    return false;
  }

  function parseCompound(part) {
    const checks = [];
    let rest = part;
    const tag = /^([a-zA-Z][\w-]*)/.exec(rest);
    if (tag) {
      const name = tag[1].toLowerCase();
      checks.push((el) => el.tagName === name);
      rest = rest.slice(tag[0].length);
    }
    const id = /^#([\w-]+)/.exec(rest);
    if (id) {
      checks.push((el) => el.id === id[1]);
      rest = rest.slice(id[0].length);
    }
    while (rest.startsWith(".")) {
      const m = /^\.([\w-]+)/.exec(rest);
      if (!m) throw new Error(`Unsupported selector part: ${part}`);
      checks.push((el) => el.classList.contains(m[1]));
      rest = rest.slice(m[0].length);
    }
    while (rest.startsWith("[")) {
      const mEq = /^\[([\w-]+)="([^"]*)"\]/.exec(rest);
      if (mEq) {
        checks.push((el) => el.getAttribute(mEq[1]) === mEq[2]);
        rest = rest.slice(mEq[0].length);
        continue;
      }
      const mBare = /^\[([\w-]+)\]/.exec(rest);
      if (!mBare) throw new Error(`Unsupported selector part: ${part}`);
      checks.push((el) => el.attributes.has(mBare[1]) || (mBare[1] === "open" && Boolean(el.open)));
      rest = rest.slice(mBare[0].length);
    }
    if (rest) throw new Error(`Unsupported selector part: ${part}`);
    return checks;
  }

  function matchesSelector(el, selector) {
    const parts = selector.trim().split(/\s+/);
    if (!parseCompound(parts[parts.length - 1]).every((c) => c(el))) return false;
    let node = el.parentNode;
    for (let i = parts.length - 2; i >= 0; i -= 1) {
      let found = false;
      while (node) {
        if (parseCompound(parts[i]).every((c) => c(node))) {
          found = true;
          node = node.parentNode;
          break;
        }
        node = node.parentNode;
      }
      if (!found) return false;
    }
    return true;
  }

  function queryAll(root, selector) {
    const candidates = new Set(registered);
    for (const el of roots) candidates.add(el);
    const pool = root ? [...candidates].filter((el) => isInside(el, root)) : [...candidates];
    return pool.filter((el) => matchesSelector(el, selector));
  }

  function seedElement(id, spec = {}) {
    const el = new FakeElement(spec.tag || "div");
    el.id = id;
    el.attributes.set("id", id);
    if (spec.className) el.className = spec.className;
    if (spec.value !== undefined) el.value = String(spec.value);
    if (spec.min !== undefined) el.min = String(spec.min);
    if (spec.max !== undefined) el.max = String(spec.max);
    if (spec.checked !== undefined) el.checked = Boolean(spec.checked);
    if (spec.dataset) Object.assign(el.dataset, spec.dataset);
    if (spec.attrs) {
      for (const [k, v] of Object.entries(spec.attrs)) el.setAttribute(k, v);
    }
    roots.add(el);
    registered.add(el);
    return el;
  }

  const byId = new Map();
  for (const [id, spec] of Object.entries(elementsById)) {
    byId.set(id, seedElement(id, spec));
  }

  const storage = createMemoryStorage(storageInitial);
  const i18n = createFakeI18n();
  const documentElement = seedElement("html", { tag: "html" });
  documentElement.dataset.theme = "architectural-stone";

  const documentObj = {
    hidden: false,
    activeElement: null,
    documentElement,
    createElement(tag) {
      const el = new FakeElement(tag);
      registered.add(el);
      return el;
    },
    createElementNS(_ns, tag) {
      const el = new FakeElement(tag);
      registered.add(el);
      return el;
    },
    getElementById(id) {
      if (byId.has(id)) return byId.get(id);
      for (const el of registered) {
        if (el.id === id) return el;
      }
      return null;
    },
    querySelectorAll(selector) {
      return selector
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .flatMap((s) => queryAll(null, s));
    },
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
    addEventListener(type, handler) {
      if (!docListeners.has(type)) docListeners.set(type, []);
      docListeners.get(type).push(handler);
    },
    dispatchEvent(event) {
      const evt = typeof event === "string" ? { type: event } : event;
      for (const handler of docListeners.get(evt.type) || []) handler(evt);
    }
  };

  const windowObj = {
    location: { hash },
    localStorage: storage,
    I18N: i18n,
    addEventListener(type, handler, opts) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push({ handler, once: Boolean(opts && opts.once) });
    },
    removeEventListener(type, handler) {
      const list = windowListeners.get(type) || [];
      windowListeners.set(type, list.filter((e) => e.handler !== handler));
    },
    dispatchEvent(event) {
      const evt = typeof event === "string" ? { type: event } : event;
      const list = [...(windowListeners.get(evt.type) || [])];
      for (const entry of list) {
        if (entry.once) windowObj.removeEventListener(evt.type, entry.handler);
        entry.handler(evt);
      }
    }
  };

  function install() {
    globalThis.window = windowObj;
    globalThis.document = documentObj;
    globalThis.Event = class Event {
      constructor(type, init = {}) {
        this.type = type;
        this.bubbles = Boolean(init.bubbles);
      }
    };
    globalThis.HTMLDialogElement = class HTMLDialogElement {};
    globalThis.requestAnimationFrame = (cb) => {
      cb(0);
      return 1;
    };
  }

  return {
    window: windowObj,
    document: documentObj,
    storage,
    i18n,
    seedElement,
    getById: (id) => documentObj.getElementById(id),
    install
  };
}
