/*
 * Behaviour tests for ui/js/scenes.js: the built-in scene grid, the category
 * filtering/counts, the custom-preset gallery and the dialog/event wiring, all
 * observed through the commands that reach the backend bridge.
 *
 * ui/js/scenes.js is a browser module: it reads the catalog from the app state and
 * talks to `document`/`window`. This file installs a small in-memory document so the
 * exported functions can run under `node --test` without touching ui/js at all.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { appState } from "../../ui/js/store.js";
import {
  bindSceneEvents,
  openCustomSceneDialog,
  renderCustomScenesGrid,
  renderScenesGrid,
  updateSceneCategoryCounts
} from "../../ui/js/scenes.js";
import { resolveBackendApi } from "../../ui/js/bridge-client.js";

const SCENE_CATALOG = JSON.parse(readFileSync(new URL("../../ui/scenes.json", import.meta.url), "utf8"));

/* ------------------------------------------------------- in-memory document */

function createStyle() {
  const props = new Map();
  return {
    props,
    setProperty(name, value) {
      props.set(name, String(value));
    },
    getPropertyValue(name) {
      return props.get(name) ?? "";
    }
  };
}

function splitClasses(className) {
  return String(className || "")
    .split(/\s+/)
    .filter(Boolean);
}

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
    this.title = "";
    this.type = "";
    this.tabIndex = -1;
    this.focusCount = 0;
    this.selectCount = 0;
    this.showModalCount = 0;
    this.closeCount = 0;
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
        el.className = splitClasses(el.className)
          .filter((name) => !drop.has(name))
          .join(" ");
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
    this.attributes.set(name, String(value));
    if (name === "id") this.id = String(value);
    if (name === "class") this.className = String(value);
    if (name === "value") this.value = String(value);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
      this.dataset[key] = String(value);
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
    for (const child of [...this.children]) this.removeChild(child);
    this.append(...children);
  }

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }

  removeEventListener(type, handler) {
    const list = this.listeners.get(type) || [];
    this.listeners.set(
      type,
      list.filter((entry) => entry !== handler)
    );
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
  }

  select() {
    this.selectCount += 1;
  }

  showModal() {
    this.showModalCount += 1;
  }

  close() {
    this.closeCount += 1;
  }

  querySelectorAll(selector) {
    return queryAll(this, selector);
  }

  querySelector(selector) {
    return queryAll(this, selector)[0] || null;
  }
}

/* Every element ever created, so selectors can look past the seeded roots. */
let registered = new Set();
let roots = new Set();

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
    const match = /^\.([\w-]+)/.exec(rest);
    if (!match) throw new Error(`Unsupported selector part: ${part}`);
    checks.push((el) => el.classList.contains(match[1]));
    rest = rest.slice(match[0].length);
  }
  while (rest.startsWith("[")) {
    const match = /^\[([\w-]+)="([^"]*)"\]/.exec(rest);
    if (!match) throw new Error(`Unsupported selector part: ${part}`);
    checks.push((el) => el.getAttribute(match[1]) === match[2]);
    rest = rest.slice(match[0].length);
  }
  if (rest) throw new Error(`Unsupported selector part: ${part}`);
  return checks;
}

function matchesCompound(el, part) {
  return parseCompound(part).every((check) => check(el));
}

function matchesSelector(el, selector) {
  const parts = selector.trim().split(/\s+/);
  if (!matchesCompound(el, parts[parts.length - 1])) return false;
  let node = el.parentNode;
  for (let index = parts.length - 2; index >= 0; index -= 1) {
    let found = false;
    while (node) {
      if (matchesCompound(node, parts[index])) {
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

function isInside(el, root) {
  let node = el;
  while (node) {
    if (node === root) return true;
    node = node.parentNode;
  }
  return false;
}

function createDocument() {
  registered = new Set();
  roots = new Set();

  const document = {
    createElement(tagName) {
      const el = new FakeElement(tagName);
      registered.add(el);
      return el;
    },
    createElementNS(_namespace, tagName) {
      return document.createElement(tagName);
    },
    getElementById(id) {
      const seeded = [...roots].find((el) => el.id === id);
      return seeded || [...registered].find((el) => el.id === id) || null;
    },
    querySelectorAll(selector) {
      return queryAll(null, selector);
    },
    querySelector(selector) {
      return document.querySelectorAll(selector)[0] || null;
    },
    seed(tagName, options = {}) {
      const el = document.createElement(tagName);
      if (options.id) el.setAttribute("id", options.id);
      if (options.className) el.className = options.className;
      for (const [name, value] of Object.entries(options.attributes || {})) {
        el.setAttribute(name, value);
      }
      for (const [name, value] of Object.entries(options.dataset || {})) {
        el.dataset[name] = value;
        el.setAttribute(
          `data-${name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`,
          value
        );
      }
      if ("value" in options) el.value = options.value;
      if ("min" in options) el.min = options.min;
      if ("max" in options) el.max = options.max;
      if ("checked" in options) el.checked = options.checked;
      roots.add(el);
      registered.add(el);
      return el;
    }
  };
  return document;
}

/* ------------------------------------------------------------- page/backends */

const CATEGORY_TABS = ["all", "white", "ambient", "nature", "dynamic", "holiday", "favorites"];

function createMemoryStorage() {
  const data = new Map();
  return {
    data,
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    }
  };
}

function createFakeI18n() {
  return {
    t(key, vars) {
      if (!vars) return `T(${key})`;
      const rendered = Object.entries(vars)
        .map(([name, value]) => `${name}=${value}`)
        .join(",");
      return `T(${key}|${rendered})`;
    }
  };
}

function createFakeBackend() {
  const calls = [];
  const record =
    (name) =>
    (...args) => {
      calls.push({ name, args });
      return { ok: true };
    };
  return {
    calls,
    calledWith(name) {
      return calls.filter((call) => call.name === name).map((call) => call.args);
    },
    api: {
      set_builtin_scene: record("set_builtin_scene"),
      apply_custom_scene: record("apply_custom_scene"),
      set_custom_scene_favorite: record("set_custom_scene_favorite"),
      delete_custom_scene: record("delete_custom_scene"),
      save_custom_scene: record("save_custom_scene"),
      update_custom_scene: record("update_custom_scene")
    }
  };
}

function buildPage({ skip = [] } = {}) {
  const document = createDocument();
  const page = { document };

  page.categoryBar = document.seed("div", { id: "scene-category-bar", className: "scene-category-bar" });
  page.filters = new Map();
  for (const category of CATEGORY_TABS) {
    const button = document.seed("button", {
      className: "scene-filter",
      attributes: { type: "button" },
      dataset: { category }
    });
    page.categoryBar.appendChild(button);
    page.filters.set(category, button);
  }

  const wanted = {
    "status-banner": () => document.seed("p", { id: "status-banner" }),
    "scenes-grid": () => document.seed("div", { id: "scenes-grid", className: "scenes-grid" }),
    "scene-cat-favorites-label": () => document.seed("span", { id: "scene-cat-favorites-label" }),
    "scene-speed-container": () => document.seed("div", { id: "scene-speed-container" }),
    "scene-speed-slider": () =>
      document.seed("input", { id: "scene-speed-slider", min: "10", max: "200", value: "100" }),
    "scene-speed-output": () => document.seed("output", { id: "scene-speed-output" }),
    "custom-scenes-grid": () => document.seed("div", { id: "custom-scenes-grid" }),
    "custom-tab-label": () => document.seed("span", { id: "custom-tab-label" }),
    "custom-scene-dialog": () => document.seed("dialog", { id: "custom-scene-dialog" }),
    "custom-scene-dialog-title": () => document.seed("h3", { id: "custom-scene-dialog-title" }),
    "custom-scene-dialog-subtitle": () => document.seed("p", { id: "custom-scene-dialog-subtitle" }),
    "custom-scene-id-input": () => document.seed("input", { id: "custom-scene-id-input", value: "" }),
    "custom-scene-name-input": () => document.seed("input", { id: "custom-scene-name-input", value: "" }),
    "custom-scene-overwrite-row": () => document.seed("div", { id: "custom-scene-overwrite-row" }),
    "custom-scene-overwrite-checkbox": () =>
      document.seed("input", { id: "custom-scene-overwrite-checkbox", checked: false }),
    "custom-scene-submit-btn": () => document.seed("button", { id: "custom-scene-submit-btn" }),
    "quick-save-preset-btn": () => document.seed("button", { id: "quick-save-preset-btn" }),
    "open-save-scene-dialog-btn": () => document.seed("button", { id: "open-save-scene-dialog-btn" }),
    "custom-scene-form": () => document.seed("form", { id: "custom-scene-form" })
  };
  for (const [id, build] of Object.entries(wanted)) {
    if (!skip.includes(id)) page[id] = build();
  }
  for (const [key, value] of Object.entries(wanted)) {
    if (!skip.includes(key)) continue;
    page[key] = null;
  }

  page.grid = page["scenes-grid"] || null;
  page.customGrid = page["custom-scenes-grid"] || null;
  page.dialog = page["custom-scene-dialog"] || null;
  page.slider = page["scene-speed-slider"] || null;
  page.speedContainer = page["scene-speed-container"] || null;
  page.speedOutput = page["scene-speed-output"] || null;
  page.statusBanner = page["status-banner"] || null;
  page.idInput = page["custom-scene-id-input"] || null;
  page.nameInput = page["custom-scene-name-input"] || null;
  page.overwriteRow = page["custom-scene-overwrite-row"] || null;
  page.overwriteCheckbox = page["custom-scene-overwrite-checkbox"] || null;
  page.submitBtn = page["custom-scene-submit-btn"] || null;
  page.form = page["custom-scene-form"] || null;
  page.favoriteLabel = page["scene-cat-favorites-label"] || null;
  page.customTabLabel = page["custom-tab-label"] || null;
  page.quickSaveBtn = page["quick-save-preset-btn"] || null;
  page.openSaveBtn = page["open-save-scene-dialog-btn"] || null;
  page.dialogTitle = page["custom-scene-dialog-title"] || null;
  page.dialogSubtitle = page["custom-scene-dialog-subtitle"] || null;

  return page;
}

/* ---------------------------------------------------------- DOM test helpers */

function descendants(el) {
  const out = [];
  const walk = (node) => {
    for (const child of node.children) {
      out.push(child);
      walk(child);
    }
  };
  walk(el);
  return out;
}

function findByClass(root, className) {
  return descendants(root).find((el) => el.classList.contains(className)) || null;
}

function findAllByClass(root, className) {
  return descendants(root).filter((el) => el.classList.contains(className));
}

/* Texto propio mas el de los hijos: los botones con icono guardan la etiqueta en un <span>. */
function flattenText(el) {
  return el.children.reduce((acc, child) => acc + flattenText(child), el.textContent || "");
}

function cardNames(grid) {
  return grid.children.map((card) => findByClass(card, "scene-name")?.textContent ?? null);
}

function cardFor(grid, name) {
  return grid.children.find((card) => findByClass(card, "scene-name")?.textContent === name) || null;
}

function buttonByLabel(root, label) {
  return descendants(root).find((el) => el.tagName === "button" && flattenText(el) === label) || null;
}

/* Los nombres visibles del catalogo, con la unica excepcion que traduce la escena 19. */
function expectedNames(entries) {
  return entries.map((entry) => (entry.scene_id === 19 ? "T(scenes.plantGrowth)" : entry.name));
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

function scene(spec) {
  const found = SCENE_CATALOG.find((entry) => entry.scene_id === spec);
  if (!found) throw new Error(`Unknown built-in scene id ${spec}`);
  return found;
}

/* ------------------------------------------------------------- test harness */

let page;
let backend;

beforeEach(async () => {
  page = buildPage();
  backend = createFakeBackend();
  globalThis.document = page.document;
  globalThis.window = {
    localStorage: createMemoryStorage(),
    I18N: createFakeI18n(),
    pywebview: { api: backend.api }
  };

  appState.scenes = structuredClone(SCENE_CATALOG);
  appState.favoriteSceneIds = [];
  appState.customScenes = [];
  appState.sceneCategory = "all";
  appState.bulbs = [];
  appState.selectedIps = [];

  await resolveBackendApi();
});

afterEach(() => {
  delete globalThis.document;
  delete globalThis.window;
});

/* ------------------------------------------------ built-in scene -> command */

describe("renderScenesGrid(): built-in scene grid", () => {
  test("renders every catalog scene, in scene-id order when nothing is a favourite", () => {
    renderScenesGrid();

    assert.equal(page.grid.children.length, SCENE_CATALOG.length);
    assert.deepEqual(cardNames(page.grid), expectedNames(SCENE_CATALOG));
    const firstCard = page.grid.children[0];
    assert.equal(findByClass(firstCard, "scene-id-badge").textContent, "#01");
  });

  test("each card click dispatches exactly set_builtin_scene(id, speed, null, null)", async () => {
    renderScenesGrid();

    const dynamicScene = scene(1);
    assert.equal(dynamicScene.supports_speed, true);
    cardFor(page.grid, dynamicScene.name).click();
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [[1, 100, null, null]]);
    assert.deepEqual(
      backend.calls.map((call) => call.name),
      ["set_builtin_scene"]
    );
  });

  test("a static scene sends no speed even when the slider has a value", async () => {
    renderScenesGrid();

    const staticScene = scene(34);
    assert.equal(staticScene.supports_speed, false);
    cardFor(page.grid, staticScene.name).click();
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [[34, null, null, null]]);
  });

  test("a scene with speed support always forwards the numeric slider value", async () => {
    page.slider.value = "175";
    renderScenesGrid();

    cardFor(page.grid, scene(4).name).click();
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [[4, 175, null, null]]);
  });

  test("Enter and Space on a card map to the same command, other keys do not", async () => {
    renderScenesGrid();
    const card = cardFor(page.grid, scene(2).name);

    card.dispatchEvent({ type: "keydown", key: "a", target: card });
    card.dispatchEvent({ type: "keydown", key: "Enter", target: card });
    card.dispatchEvent({ type: "keydown", key: " ", target: card });
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [
      [2, 100, null, null],
      [2, 100, null, null]
    ]);
  });

  test("keydown bubbling from a card child does not activate the scene", async () => {
    renderScenesGrid();
    const card = cardFor(page.grid, scene(2).name);
    const star = findByClass(card, "scene-fav-btn");

    card.dispatchEvent({ type: "keydown", key: "Enter", target: star });
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), []);
  });

  test("the active scene is marked and enables the speed control", () => {
    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "scene", scene_id: 4 } }];
    renderScenesGrid();

    const activeCard = cardFor(page.grid, scene(4).name);
    assert.equal(activeCard.classList.contains("active"), true);
    assert.equal(findByClass(activeCard, "scene-active-badge").textContent, "T(scenes.badgeActive)");
    assert.equal(page.speedContainer.classList.contains("is-disabled"), false);
    assert.equal(page.slider.disabled, false);

    const otherCard = cardFor(page.grid, scene(1).name);
    assert.equal(otherCard.classList.contains("active"), false);
    assert.equal(findByClass(otherCard, "scene-active-badge"), null);
  });

  test("a white scene never offers the speed control, even when active", () => {
    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "scene", scene_id: 34 } }];
    appState.sceneCategory = "white";
    renderScenesGrid();

    assert.equal(page.speedContainer.classList.contains("is-disabled"), true);
    assert.equal(page.slider.disabled, true);
  });

  test("static scenes are tagged as static and dynamic ones as dynamic", () => {
    renderScenesGrid();

    const dynamicCard = cardFor(page.grid, scene(4).name);
    assert.equal(findByClass(dynamicCard, "scene-tag").textContent, "T(scenes.tagDynamic)");
    const staticCard = cardFor(page.grid, scene(34).name);
    assert.equal(findByClass(staticCard, "scene-tag").textContent, "T(scenes.tagStatic)");
  });

  test("scene 19 is rendered with its translated label", () => {
    renderScenesGrid();
    assert.ok(cardNames(page.grid).includes("T(scenes.plantGrowth)"));
    assert.ok(!cardNames(page.grid).includes("Plantgrowth"));
  });

  test("a scene without a curated chroma falls back to its category colour", () => {
    appState.scenes = [
      { scene_id: 99, name: "Custom holiday", category: "holiday", supports_speed: false },
      { scene_id: 98, name: "Unknown category", category: "experimental", supports_speed: false }
    ];
    renderScenesGrid();

    const holidayCard = cardFor(page.grid, "Custom holiday");
    const unknownCard = cardFor(page.grid, "Unknown category");
    assert.equal(holidayCard.style.getPropertyValue("--scene-accent"), "#F43F5E");
    assert.equal(holidayCard.style.getPropertyValue("--scene-gradient"), "#F43F5E");
    assert.equal(unknownCard.style.getPropertyValue("--scene-accent"), "#38bdf8");
    assert.equal(unknownCard.style.getPropertyValue("--scene-gradient"), "#38bdf8");
  });

  test("a curated scene keeps its own accent colour", () => {
    renderScenesGrid();
    const card = cardFor(page.grid, scene(1).name);
    assert.equal(card.style.getPropertyValue("--scene-accent"), "#00b4d8");
  });

  test("a missing grid element is tolerated", () => {
    page = buildPage({ skip: ["scenes-grid"] });
    appState.scenes = [scene(1)];
    assert.doesNotThrow(() => renderScenesGrid());
  });
});

/* --------------------------------------------------------- category filtering */

describe("category filtering and counts", () => {
  const expectedCounts = { white: 10, ambient: 6, nature: 10, dynamic: 7, holiday: 3 };

  test("category counts are published per filter pill", () => {
    updateSceneCategoryCounts();

    assert.equal(page.filters.get("all").textContent, `T(scenes.catAllCount|count=${SCENE_CATALOG.length})`);
    for (const [category, count] of Object.entries(expectedCounts)) {
      const key = `scenes.cat${category[0].toUpperCase()}${category.slice(1)}Count`;
      assert.equal(page.filters.get(category).textContent, `T(${key}|count=${count})`);
    }
    assert.equal(page.favoriteLabel.textContent, "T(scenes.catFavoritesCount|count=0)");
  });

  test("the favourite count follows the stored favourites", () => {
    appState.favoriteSceneIds = [1, 4, 34];
    updateSceneCategoryCounts();
    assert.equal(page.favoriteLabel.textContent, "T(scenes.catFavoritesCount|count=3)");
  });

  test("a single category renders only its own scenes, by ascending id", () => {
    appState.sceneCategory = "white";
    renderScenesGrid();

    assert.deepEqual(
      cardNames(page.grid),
      expectedNames(SCENE_CATALOG.filter((entry) => entry.category === "white"))
    );
  });

  test("'all' lists favourites first and then keeps the id order", () => {
    appState.favoriteSceneIds = [34, 12];
    renderScenesGrid();

    const names = cardNames(page.grid);
    assert.equal(names.length, SCENE_CATALOG.length);
    assert.deepEqual(names.slice(0, 2), [scene(12).name, scene(34).name]);
    const rest = names.slice(2);
    assert.deepEqual(
      rest,
      expectedNames(SCENE_CATALOG.filter((entry) => ![12, 34].includes(entry.scene_id)))
    );
  });

  test("'favorites' renders only the favourite scenes", () => {
    appState.favoriteSceneIds = [34, 4];
    appState.sceneCategory = "favorites";
    renderScenesGrid();

    assert.deepEqual(cardNames(page.grid), [scene(4).name, scene(34).name]);
  });

  test("'favorites' without favourites shows the documented empty state", () => {
    appState.sceneCategory = "favorites";
    renderScenesGrid();

    assert.equal(page.grid.children.length, 1);
    const empty = findAllByClass(page.grid, "empty-fixtures-state");
    assert.equal(empty.length, 1);
    assert.equal(page.grid.children[0], empty[0]);
    assert.deepEqual(
      descendants(empty[0]).map((el) => flattenText(el)),
      ["T(scenes.emptyFavorites)"]
    );
  });
});

/* ------------------------------------------------------------- favourites */

describe("favourite toggling from the grid", () => {
  test("adding a favourite updates the state, the storage, the card and the banner", async () => {
    renderScenesGrid();
    const card = cardFor(page.grid, scene(4).name);
    const favButton = findByClass(card, "scene-fav-btn");
    assert.equal(favButton.getAttribute("aria-pressed"), "false");
    assert.equal(favButton.getAttribute("aria-label"), "T(scenes.favAddAria|name=Party)");

    favButton.click();
    await tick();

    assert.deepEqual(appState.favoriteSceneIds, [4]);
    assert.equal(window.localStorage.getItem("gestor_luces_fav_scenes"), "[4]");
    assert.equal(page.statusBanner.textContent, "T(status.sceneFavAdded|name=Party)");
    assert.deepEqual(backend.calledWith("set_builtin_scene"), []);

    const updatedButton = findByClass(cardFor(page.grid, scene(4).name), "scene-fav-btn");
    assert.equal(updatedButton.getAttribute("aria-pressed"), "true");
    assert.equal(updatedButton.getAttribute("aria-label"), "T(scenes.favRemoveAria|name=Party)");
  });

  test("clicking an existing favourite removes it again", async () => {
    appState.favoriteSceneIds = [4];
    renderScenesGrid();

    findByClass(cardFor(page.grid, scene(4).name), "scene-fav-btn").click();
    await tick();

    assert.deepEqual(appState.favoriteSceneIds, []);
    assert.equal(window.localStorage.getItem("gestor_luces_fav_scenes"), "[]");
    assert.equal(page.statusBanner.textContent, "T(status.sceneFavRemoved|name=Party)");
  });

  test("other favourites are preserved when one is removed", async () => {
    appState.favoriteSceneIds = [4, 12, 34];
    renderScenesGrid();

    findByClass(cardFor(page.grid, scene(12).name), "scene-fav-btn").click();
    await tick();

    assert.deepEqual(appState.favoriteSceneIds, [4, 34]);
  });
});

/* --------------------------------------------------------- custom presets */

const RGB_PRESET = {
  id: "preset-rgb",
  name: "Sunset red",
  mode: "rgb",
  color: { r: 255, g: 0, b: 0 },
  brightness: 80,
  is_favorite: false
};
const SCENE_PRESET = {
  id: "preset-scene",
  name: "Party time",
  mode: "scene",
  built_in_scene_id: 4,
  brightness: 90,
  is_favorite: true
};
const TEMPERATURE_PRESET = {
  id: "preset-temp",
  name: "Reading",
  mode: "temperature",
  temperature: 4200,
  brightness: 60,
  is_favorite: false
};

function customSummaryFor(preset) {
  return findByClass(
    page.customGrid.children.find((card) => findByClass(card, "custom-scene-title")?.textContent === preset.name),
    "custom-scene-summary"
  ).textContent;
}

describe("renderCustomScenesGrid(): custom presets", () => {
  test("a RGB preset shows its colour and hex summary", () => {
    appState.customScenes = [RGB_PRESET];
    renderCustomScenesGrid();

    assert.equal(customSummaryFor(RGB_PRESET), "RGB #FF0000 · 80%");
    const swatch = findByClass(page.customGrid.children[0], "custom-scene-swatch");
    assert.equal(swatch.style.getPropertyValue("--preset-swatch"), "rgb(255, 0, 0)");
    assert.equal(page.customTabLabel.textContent, "T(tabs.customWithCount|count=1)");
  });

  test("a RGB preset without a hex string derives it from the channels", () => {
    appState.customScenes = [{ ...RGB_PRESET, color: { r: 0, g: 180, b: 216 } }];
    renderCustomScenesGrid();
    assert.equal(customSummaryFor(RGB_PRESET), "RGB #00B4D8 · 80%");
  });

  test("a scene preset uses the catalog category colour and name", () => {
    appState.customScenes = [SCENE_PRESET];
    renderCustomScenesGrid();

    assert.equal(customSummaryFor(SCENE_PRESET), "T(custom.summaryScene|scene=Party,brightness=90)");
    const swatch = findByClass(page.customGrid.children[0], "custom-scene-swatch");
    assert.equal(swatch.style.getPropertyValue("--preset-swatch"), "#C084FC");
  });

  test("a scene preset pointing at an unknown scene falls back to the dynamic swatch and the raw id", () => {
    appState.customScenes = [{ ...SCENE_PRESET, id: "preset-ghost", name: "Ghost", built_in_scene_id: 999 }];
    renderCustomScenesGrid();

    assert.equal(customSummaryFor({ name: "Ghost" }), "T(custom.summaryScene|scene=#999,brightness=90)");
    const swatch = findByClass(page.customGrid.children[0], "custom-scene-swatch");
    assert.equal(swatch.style.getPropertyValue("--preset-swatch"), "#C084FC");
  });

  test("a temperature preset shows kelvin and brightness, defaulting to 4200K", () => {
    appState.customScenes = [TEMPERATURE_PRESET, { ...TEMPERATURE_PRESET, id: "preset-default", name: "Default", temperature: 0 }];
    renderCustomScenesGrid();

    assert.equal(customSummaryFor(TEMPERATURE_PRESET), "4200 K · 60%");
    assert.equal(customSummaryFor({ name: "Default" }), "4200 K · 60%");
    const swatch = findByClass(page.customGrid.children[0], "custom-scene-swatch");
    assert.equal(swatch.style.getPropertyValue("--preset-swatch"), "rgb(255, 241, 224)");
  });

  test("an empty gallery shows the documented empty state and a zero count", () => {
    renderCustomScenesGrid();

    assert.equal(page.customGrid.children.length, 1);
    const empty = findAllByClass(page.customGrid, "empty-fixtures-state");
    assert.equal(empty.length, 1);
    assert.deepEqual(
      descendants(empty[0]).map((el) => flattenText(el)),
      ["T(custom.emptyTitle)", "T(custom.emptySubtitle)"]
    );
    assert.equal(page.customTabLabel.textContent, "T(tabs.customWithCount|count=0)");
  });

  test("applying a preset dispatches apply_custom_scene(id, null)", async () => {
    appState.customScenes = [RGB_PRESET];
    renderCustomScenesGrid();

    findByClass(page.customGrid.children[0], "custom-scene-top").click();
    await tick();

    assert.deepEqual(backend.calledWith("apply_custom_scene"), [["preset-rgb", null]]);
    assert.deepEqual(backend.calls.map((call) => call.name), ["apply_custom_scene"]);
  });

  test("keyboard activation of a preset behaves like a click", async () => {
    appState.customScenes = [RGB_PRESET];
    renderCustomScenesGrid();

    const topArea = findByClass(page.customGrid.children[0], "custom-scene-top");
    topArea.dispatchEvent({ type: "keydown", key: "Enter", target: topArea });
    await tick();

    assert.deepEqual(backend.calledWith("apply_custom_scene"), [["preset-rgb", null]]);
  });

  test("the favourite button dispatches the inverted flag and its label follows the state", async () => {
    appState.customScenes = [RGB_PRESET, SCENE_PRESET];
    renderCustomScenesGrid();

    const [rgbCard, sceneCard] = page.customGrid.children;
    assert.equal(buttonByLabel(rgbCard, "T(custom.favoriteBtn)").getAttribute("aria-pressed"), "false");
    assert.equal(buttonByLabel(sceneCard, "T(custom.favoritedBtn)").getAttribute("aria-pressed"), "true");

    buttonByLabel(rgbCard, "T(custom.favoriteBtn)").click();
    buttonByLabel(sceneCard, "T(custom.favoritedBtn)").click();
    await tick();

    assert.deepEqual(backend.calledWith("set_custom_scene_favorite"), [
      ["preset-rgb", true],
      ["preset-scene", false]
    ]);
  });

  test("delete dispatches delete_custom_scene(id)", async () => {
    appState.customScenes = [RGB_PRESET];
    renderCustomScenesGrid();

    buttonByLabel(page.customGrid.children[0], "T(custom.deleteBtn)").click();
    await tick();

    assert.deepEqual(backend.calledWith("delete_custom_scene"), [["preset-rgb"]]);
  });

  test("edit opens the dialog prefilled with the preset", () => {
    appState.customScenes = [SCENE_PRESET];
    renderCustomScenesGrid();

    buttonByLabel(page.customGrid.children[0], "T(custom.editBtn)").click();

    assert.equal(page.dialog.showModalCount, 1);
    assert.equal(page.idInput.value, "preset-scene");
    assert.equal(page.nameInput.value, "Party time");
    assert.deepEqual(backend.calls, []);
  });

  test("apply dispatched from the dedicated button uses the same command", async () => {
    appState.customScenes = [TEMPERATURE_PRESET];
    renderCustomScenesGrid();

    buttonByLabel(page.customGrid.children[0], "T(custom.applyBtn)").click();
    await tick();

    assert.deepEqual(backend.calledWith("apply_custom_scene"), [["preset-temp", null]]);
  });

  test("a missing grid element is tolerated", () => {
    page = buildPage({ skip: ["custom-scenes-grid"] });
    appState.customScenes = [RGB_PRESET];
    assert.doesNotThrow(() => renderCustomScenesGrid());
  });
});

/* ---------------------------------------------------------------- dialog */

describe("openCustomSceneDialog()", () => {
  test("opening without a preset clears the form for a new save", () => {
    page.idInput.value = "leftover";
    page.nameInput.value = "leftover name";

    openCustomSceneDialog(null);

    assert.equal(page.idInput.value, "");
    assert.equal(page.nameInput.value, "");
    assert.equal(page.dialogTitle.textContent, "T(dialog.presetSaveTitle)");
    assert.equal(page.dialogSubtitle.textContent, "T(dialog.presetSaveSubtitle)");
    assert.equal(page.overwriteRow.hidden, true);
    assert.equal(page.overwriteCheckbox.checked, false);
    assert.equal(page.submitBtn.textContent, "T(dialog.presetSaveSubmit)");
    assert.equal(page.dialog.showModalCount, 1);
    assert.equal(page.nameInput.focusCount, 1);
    assert.equal(page.nameInput.selectCount, 0);
  });

  test("opening with a preset switches to update mode and preselects the name", () => {
    openCustomSceneDialog({ id: "preset-rgb", name: "Sunset red" });

    assert.equal(page.idInput.value, "preset-rgb");
    assert.equal(page.nameInput.value, "Sunset red");
    assert.equal(page.dialogTitle.textContent, "T(dialog.presetEditTitle)");
    assert.equal(page.dialogSubtitle.textContent, "T(dialog.presetEditSubtitle)");
    assert.equal(page.overwriteRow.hidden, false);
    assert.equal(page.overwriteCheckbox.checked, false);
    assert.equal(page.submitBtn.textContent, "T(dialog.presetUpdateSubmit)");
    assert.equal(page.dialog.showModalCount, 1);
    assert.equal(page.nameInput.selectCount, 1);
  });

  test("does nothing when the dialog markup is absent", () => {
    page = buildPage({ skip: ["custom-scene-dialog"] });
    assert.doesNotThrow(() => openCustomSceneDialog(null));
  });
});

/* ----------------------------------------------------------- event wiring */

describe("bindSceneEvents()", () => {
  const activateTab = (...args) => {
    activateTab.calls.push(args);
  };
  activateTab.calls = [];

  beforeEach(() => {
    activateTab.calls = [];
  });

  test("a filter click updates the category, the active pill and the grid", () => {
    page.filters.get("all").classList.add("active");
    bindSceneEvents({ activateTab });

    page.filters.get("white").click();

    assert.equal(appState.sceneCategory, "white");
    assert.equal(page.filters.get("white").classList.contains("active"), true);
    assert.equal(page.filters.get("all").classList.contains("active"), false);
    assert.deepEqual(
      cardNames(page.grid),
      SCENE_CATALOG.filter((entry) => entry.category === "white").map((entry) => entry.name)
    );
  });

  test("a filter without a category falls back to 'all'", () => {
    const button = page.document.seed("button", { className: "scene-filter" });
    page.categoryBar.appendChild(button);
    bindSceneEvents({ activateTab });

    button.click();

    assert.equal(appState.sceneCategory, "all");
  });

  test("dragging the speed slider mirrors the value into its output", () => {
    bindSceneEvents({ activateTab });

    page.slider.value = "150";
    page.slider.dispatchEvent({ type: "input", target: page.slider });

    assert.equal(page.speedOutput.textContent, "150");
  });

  test("committing the speed slider re-sends the active scene with the clamped speed", async () => {
    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "scene", scene_id: 4 } }];
    bindSceneEvents({ activateTab });

    page.slider.value = "175";
    page.slider.dispatchEvent({ type: "change", target: page.slider });
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [[4, 175, null, null]]);
    assert.equal(page.slider.style.getPropertyValue("--slider-progress"), "86.84%");
  });

  test("the committed speed is clamped into 10..200", async () => {
    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "scene", scene_id: 4 } }];
    bindSceneEvents({ activateTab });

    page.slider.value = "5";
    page.slider.dispatchEvent({ type: "change", target: page.slider });
    page.slider.value = "500";
    page.slider.dispatchEvent({ type: "change", target: page.slider });
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), [
      [4, 10, null, null],
      [4, 200, null, null]
    ]);
  });

  test("the speed slider never sends anything without a bulb in scene mode", async () => {
    bindSceneEvents({ activateTab });

    page.slider.dispatchEvent({ type: "change", target: page.slider });

    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "rgb", scene_id: 4 } }];
    page.slider.dispatchEvent({ type: "change", target: page.slider });

    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "scene", scene_id: 0 } }];
    page.slider.dispatchEvent({ type: "change", target: page.slider });
    await tick();

    assert.deepEqual(backend.calledWith("set_builtin_scene"), []);
  });

  test("both save-preset buttons open the empty dialog", () => {
    bindSceneEvents({ activateTab });

    page.quickSaveBtn.click();
    page.openSaveBtn.click();

    assert.equal(page.dialog.showModalCount, 2);
    assert.equal(page.idInput.value, "");
    assert.equal(page.nameInput.value, "");
  });

  test("saving a new preset dispatches save_custom_scene(name, primary ip) and switches tab", async () => {
    appState.bulbs = [{ ip: "10.0.0.5", state: { mode: "temperature" } }];
    appState.selectedIps = ["10.0.0.5"];
    bindSceneEvents({ activateTab });

    page.nameInput.value = "  New preset  ";
    page.form.dispatchEvent({ type: "submit", target: page.form });
    await tick();

    assert.deepEqual(backend.calledWith("save_custom_scene"), [["New preset", "10.0.0.5"]]);
    assert.equal(page.dialog.closeCount, 1);
    assert.deepEqual(activateTab.calls, [["custom", false]]);
  });

  test("saving without any bulb sends a null target", async () => {
    bindSceneEvents({ activateTab });

    page.nameInput.value = "Standalone";
    page.form.dispatchEvent({ type: "submit", target: page.form });
    await tick();

    assert.deepEqual(backend.calledWith("save_custom_scene"), [["Standalone", null]]);
  });

  test("updating an existing preset dispatches update_custom_scene with the overwrite flag", async () => {
    bindSceneEvents({ activateTab });

    page.idInput.value = "preset-rgb";
    page.nameInput.value = "Renamed";
    page.overwriteCheckbox.checked = true;
    page.form.dispatchEvent({ type: "submit", target: page.form });
    await tick();

    assert.deepEqual(backend.calledWith("update_custom_scene"), [["preset-rgb", "Renamed", true]]);
    assert.deepEqual(backend.calledWith("save_custom_scene"), []);
    assert.deepEqual(activateTab.calls, []);
    assert.deepEqual(backend.calls.map((call) => call.name), ["update_custom_scene"]);
  });

  test("a nameless submit is ignored and the dialog stays open", async () => {
    bindSceneEvents({ activateTab });

    page.nameInput.value = "   ";
    page.form.dispatchEvent({ type: "submit", target: page.form });
    await tick();

    assert.deepEqual(backend.calls, []);
    assert.equal(page.dialog.closeCount, 0);
    assert.deepEqual(activateTab.calls, []);
  });

  test("binding without the optional controls does not throw", () => {
    page = buildPage({
      skip: [
        "scene-speed-slider",
        "scene-speed-output",
        "quick-save-preset-btn",
        "open-save-scene-dialog-btn",
        "custom-scene-form",
        "custom-scene-dialog"
      ]
    });
    assert.doesNotThrow(() => bindSceneEvents({ activateTab }));
  });
});
