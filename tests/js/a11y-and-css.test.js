/*
 * Stage 5b tests: accessibility semantics, focus/forced-colors CSS rules, GPU blur & scaleX
 * meter perf, unnested controls, keyboard HSV color wheel, and hex commit handling.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { appState } from "../../ui/js/store.js";
import { resolveBackendApi } from "../../ui/js/bridge-client.js";
import { renderMusicPanel } from "../../ui/js/music.js";
import { renderFixtureList } from "../../ui/js/fixtures.js";
import { bindStageControlEvents, positionReticleFromRgb } from "../../ui/js/stage-controls.js";

const INDEX_HTML = readFileSync(new URL("../../ui/index.html", import.meta.url), "utf8");
const STYLES_CSS = readFileSync(new URL("../../ui/styles.css", import.meta.url), "utf8");
const THEMES_CSS = readFileSync(new URL("../../ui/themes.css", import.meta.url), "utf8");
const I18N_JS = readFileSync(new URL("../../ui/i18n.js", import.meta.url), "utf8");

function makeMiniDom(ids) {
  const byId = new Map();
  const makeEl = (tag = "div") => ({
    tagName: tag.toLowerCase(),
    children: [],
    parentNode: null,
    attributes: new Map(),
    listeners: new Map(),
    dataset: {},
    className: "",
    textContent: "",
    value: "",
    type: "",
    clientWidth: 200,
    style: {
      props: new Map(),
      setProperty(k, v) { this.props.set(k, String(v)); },
      getPropertyValue(k) { return this.props.get(k) ?? ""; }
    },
    classList: {
      add() {}, remove() {}, contains() { return false; }, toggle() { return false; }
    },
    setAttribute(k, v) { this.attributes.set(k, String(v)); },
    getAttribute(k) { return this.attributes.has(k) ? this.attributes.get(k) : null; },
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => this.appendChild(c)); },
    replaceChildren(...cs) { this.children = []; this.append(...cs); },
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(fn);
    },
    dispatchEvent(evt) {
      const e = typeof evt === "string" ? { type: evt } : evt;
      e.preventDefault = e.preventDefault || (() => {});
      e.stopPropagation = e.stopPropagation || (() => {});
      (this.listeners.get(e.type) || []).forEach((fn) => fn(e));
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 200, height: 200 }; },
    setPointerCapture() {}
  });

  for (const [id, spec] of Object.entries(ids)) {
    const el = makeEl(spec.tag || "div");
    el.id = id;
    if (spec.value !== undefined) el.value = String(spec.value);
    byId.set(id, el);
  }

  const documentElement = makeEl("html");
  globalThis.document = {
    documentElement,
    createElement: (tag) => makeEl(tag),
    createElementNS: (_ns, tag) => makeEl(tag),
    getElementById: (id) => byId.get(id) || null,
    querySelectorAll: () => []
  };
  return { byId };
}

describe("static HTML/CSS/i18n Stage 5b invariants", () => {
  test("enforces maxlength on text inputs and unnested sleep-timer heading", () => {
    assert.match(INDEX_HTML, /id="manual-ip-input"[\s\S]*?maxlength="32"/);
    assert.match(INDEX_HTML, /id="manual-name-input"[\s\S]*?maxlength="80"/);
    assert.match(INDEX_HTML, /id="rename-bulb-name-input"[\s\S]*?maxlength="80"/);
    assert.match(INDEX_HTML, /id="custom-scene-name-input"[\s\S]*?maxlength="80"/);
    assert.match(INDEX_HTML, /<span id="sleep-timer-heading" class="well-title" data-i18n="sleep\.title">/);
    for (const m of INDEX_HTML.matchAll(/<summary\b[^>]*>([\s\S]*?)<\/summary>/g)) {
      assert.doesNotMatch(m[1], /<h[1-6]\b/i);
    }
  });

  test("makes color wheel keyboard focusable with slider ARIA and localizes preset group labels", () => {
    assert.match(INDEX_HTML, /id="color-wheel-canvas"[\s\S]*?tabindex="0"/);
    assert.match(INDEX_HTML, /id="color-wheel-canvas"[\s\S]*?role="slider"/);
    for (const key of ["ambi.smoothingPresetsAria", "music.sensitivityPresetsAria", "music.smoothingPresetsAria"]) {
      assert.ok(INDEX_HTML.includes(`data-i18n-aria-label="${key}"`), `missing ${key} in index.html`);
      const matches = I18N_JS.match(new RegExp(`"${key.replace(".", "\\.")}"`, "g")) || [];
      assert.equal(matches.length, 2, `expected EN+ES entries for ${key}`);
    }
  });

  test("styles focus-visible, forced-colors, scaleX meters, reduced motion, and scoped backdrop-filter", () => {
    assert.match(STYLES_CSS, /\.minutes-input-group:has\(input:focus-visible\)/);
    assert.match(STYLES_CSS, /\.field-group input\[type="number"\]:focus-visible/);
    assert.match(STYLES_CSS, /@media \(forced-colors: active\)[\s\S]*?\.minutes-input-group:focus-within/);
    assert.match(STYLES_CSS, /scaleX\(var\(--meter-scale, 0\)\)/);
    assert.match(STYLES_CSS, /transition:\s*transform 50ms linear/);
    assert.match(STYLES_CSS, /animation:\s*none !important/);
    assert.doesNotMatch(STYLES_CSS, /animation-duration:\s*0\.01ms/);

    const backdropMatch = THEMES_CSS.match(/html\[data-theme="atmospheric-dark"\] :is\(([\s\S]*?)\)\s*\{/);
    assert.ok(backdropMatch);
    for (const excluded of [".kelvin-card", ".scene-card", ".custom-scene-card", ".btn-power", "#master-power-btn"]) {
      assert.equal(backdropMatch[1].includes(excluded), false, `${excluded} should not use backdrop-filter`);
    }
  });
});

describe("behavioral Stage 5b fixes", () => {
  let calls;

  beforeEach(async () => {
    calls = [];
    globalThis.window = {
      localStorage: { getItem: () => null, setItem: () => {} },
      I18N: { t: (k) => k },
      pywebview: {
        api: {
          set_color: async (...args) => {
            calls.push(args);
            return { ok: true };
          }
        }
      },
      addEventListener() {},
      removeEventListener() {}
    };
    await resolveBackendApi();
  });

  afterEach(() => {
    delete globalThis.document;
    delete globalThis.window;
  });

  test("renderMusicPanel updates --meter-scale without mutating width", () => {
    const { byId } = makeMiniDom({
      "music-meter-bass-fill": {},
      "music-meter-bass-val": {},
      "music-meter-mid-fill": {},
      "music-meter-mid-val": {},
      "music-meter-treble-fill": {},
      "music-meter-treble-val": {},
      "music-meter-rms-fill": {},
      "music-meter-rms-val": {}
    });
    appState.musicSync = { active: true, bass: 0.75, mid: 0.5, treble: 0.25, rms: 0.6, frames_sent: 10 };
    renderMusicPanel();

    assert.equal(byId.get("music-meter-bass-fill").style.getPropertyValue("--meter-scale"), "0.750");
    assert.equal(byId.get("music-meter-bass-fill").style.width, undefined);
    assert.equal(byId.get("music-meter-bass-val").textContent, "75%");
  });

  test("renderFixtureList places rename button outside checkbox label", () => {
    const { byId } = makeMiniDom({ "fixture-list": {} });
    appState.bulbs = [{ ip: "192.168.1.20", mac: "aa:bb", name: "Lamp", is_online: true, state: { is_on: true } }];
    appState.selectedIps = ["192.168.1.20"];
    renderFixtureList();

    const card = byId.get("fixture-list").children[0];
    const topRow = card.children[0];
    assert.equal(topRow.children.length, 2);
    assert.equal(topRow.children[0].className, "fixture-select-label");
    assert.equal(topRow.children[1].className, "fixture-card-top-actions");
    assert.equal(topRow.children[1].children[0].className, "btn-icon-rename");
    assert.equal(topRow.children[1].children[1].className, "btn-icon-remove");
  });

  test("color wheel supports arrow keyboard control and #input-hex commits on change", async () => {
    const { byId } = makeMiniDom({
      "color-wheel-canvas": { tag: "canvas" },
      "wheel-reticle": {},
      "input-r": { tag: "input", value: "255" },
      "input-g": { tag: "input", value: "0" },
      "input-b": { tag: "input", value: "0" },
      "input-hex": { tag: "input", value: "#ff0000" }
    });
    positionReticleFromRgb(255, 0, 0);
    assert.equal(byId.get("color-wheel-canvas").getAttribute("aria-valuenow"), "0");

    bindStageControlEvents();
    byId.get("color-wheel-canvas").dispatchEvent({ type: "keydown", key: "ArrowRight", shiftKey: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(byId.get("color-wheel-canvas").getAttribute("aria-valuenow"), "30");
    assert.equal(calls.length, 1);

    byId.get("input-hex").value = "#00ff00";
    byId.get("input-hex").dispatchEvent({ type: "change" });
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(calls[1], [0, 255, 0, null, null]);
  });
});
