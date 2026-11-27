/*
 * Stage 3 regression tests: WCAG AA contrast tokens, heading outline, topbar shortcuts
 * trigger, target sizes >= 24px, focus retention across replaceChildren(), indeterminate
 * select-all, aria-pressed toggles, tablist Home/End, Alt+Arrow brightness, and localized
 * color-wheel valuetext.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createDomEnvironment } from "./dom-harness.js";
import { appState, updateSliderFill } from "../../ui/js/store.js";
import { resolveBackendApi, resetBridgeStateForTests } from "../../ui/js/bridge-client.js";
import { bindEvents, resetUiSyncCache } from "../../ui/js/app.js";
import { renderFixtureList, resetFixtureUiStateForTests } from "../../ui/js/fixtures.js";
import { renderScenesGrid, renderCustomScenesGrid, resetPendingPresetDeleteForTests } from "../../ui/js/scenes.js";
import { positionReticleFromRgb, renderStageHeaderAndControls } from "../../ui/js/stage-controls.js";
import { renderAmbilightPanel } from "../../ui/js/ambilight.js";
import { renderMusicPanel } from "../../ui/js/music.js";

const INDEX_HTML = readFileSync(new URL("../../ui/index.html", import.meta.url), "utf8");
const STYLES_CSS = readFileSync(new URL("../../ui/styles.css", import.meta.url), "utf8");
const THEMES_CSS = readFileSync(new URL("../../ui/themes.css", import.meta.url), "utf8");

describe("Stage 3 static WCAG AA, outline, and target-size invariants", () => {
  test("uses WCAG AA contrast tokens and distinct dark primary CTA tokens", () => {
    assert.match(THEMES_CSS, /--ink-3:\s*#5E5951;/);
    assert.match(THEMES_CSS, /--accent-favorite:\s*#9A5B00;/);
    assert.match(THEMES_CSS, /--ink-3:\s*#96A1B5;/);
    assert.match(THEMES_CSS, /--primary-btn-bg:\s*linear-gradient/);
    assert.match(THEMES_CSS, /--primary-btn-ink:\s*#0F131A;/);
    assert.match(THEMES_CSS, /color-mix\(in oklab,\s*var\(--beam-color\)\s*24%/);
  });

  test("places sole h1 inside <main>, uses h2 in drawer, and puts #shortcuts-help-btn in topbar", () => {
    assert.match(INDEX_HTML, /<main\b[^>]*>[\s\S]*?<h1 class="sr-only" data-i18n="app\.windowTitle">/);
    const asideHtml = INDEX_HTML.match(/<aside class="fixture-rail"[\s\S]*?<\/aside>/)?.[0] || "";
    assert.doesNotMatch(asideHtml, /<h1\b/);
    assert.match(asideHtml, /<h2 class="console-title"/);
    const topbarHtml = INDEX_HTML.match(/<header class="compact-topbar">[\s\S]*?<\/header>/)?.[0] || "";
    assert.match(topbarHtml, /id="shortcuts-help-btn"/);
    const railFooterHtml = INDEX_HTML.match(/<footer class="rail-footer">[\s\S]*?<\/footer>/)?.[0] || "";
    assert.doesNotMatch(railFooterHtml, /id="shortcuts-help-btn"/);
  });

  test("enforces >= 24px interactive target sizes on compact controls", () => {
    for (const sel of [".theme-btn", ".scale-preset-btn", ".chip-btn", ".btn-icon-rename", ".scene-fav-btn", "#shortcuts-help-btn"]) {
      const escaped = sel.replace(".", "\\.");
      const match = STYLES_CSS.match(new RegExp(`${escaped}[^{]*\\{[^}]*min-height:\\s*(2[4-9]|3\\d)px`));
      assert.ok(match, `${sel} should define min-height >= 24px`);
    }
  });
});

describe("Stage 3 behavioral focus, ARIA, and keyboard ergonomics", () => {
  let dom;

  beforeEach(async () => {
    resetBridgeStateForTests();
    resetUiSyncCache();
    resetFixtureUiStateForTests();
    resetPendingPresetDeleteForTests();
    dom = createDomEnvironment({
      elementsById: {
        "console-shell": { tag: "div" },
        "fixture-list": { tag: "div" },
        "fixture-count-badge": { tag: "span" },
        "select-all-fixtures": { tag: "input" },
        "scenes-grid": { tag: "div" },
        "scene-category-bar": { tag: "div" },
        "scene-cat-favorites-label": { tag: "span" },
        "scene-speed-container": { tag: "div" },
        "scene-speed-slider": { tag: "input", min: 10, max: 200, value: 100 },
        "scene-speed-output": { tag: "output" },
        "custom-scenes-grid": { tag: "div" },
        "custom-tab-label": { tag: "span" },
        "target-summary": { tag: "p" },
        "live-state-pill": { tag: "span" },
        "telemetry-meta": { tag: "span" },
        "master-power-btn": { tag: "button" },
        "master-power-label": { tag: "span" },
        "quick-save-preset-btn": { tag: "button" },
        "photometric-aperture": { tag: "div" },
        "drawer-pill-label": { tag: "span" },
        "drawer-pill-dot": { tag: "span" },
        "brightness-slider": { tag: "input", min: 10, max: 100, value: 50 },
        "brightness-output": { tag: "output" },
        "kelvin-slider": { tag: "input", min: 2200, max: 6500, value: 2700 },
        "kelvin-output": { tag: "output" },
        "color-wheel-canvas": { tag: "canvas" },
        "wheel-reticle": { tag: "div" },
        "stage-empty-banner": { tag: "section" },
        "stage-empty-message": { tag: "p" },
        "stage-empty-scan-btn": { tag: "button" },
        "stage-empty-add-btn": { tag: "button" },
        "stage-empty-select-all-btn": { tag: "button" },
        "ambilight-smoothing-slider": { tag: "input", min: 0.15, max: 0.75, value: 0.38 },
        "ambilight-smoothing-output": { tag: "output" },
        "music-sensitivity-slider": { tag: "input", min: 0.4, max: 2.5, value: 1.0 }
      }
    });
    dom.install();
    appState.bulbs = [
      { ip: "192.168.0.10", mac: "aa", name: "A", module_name: "M", is_online: true, state: { is_on: true, brightness: 50, mode: "temperature", temperature: 2700, scene_id: null, speed: 100 } },
      { ip: "192.168.0.11", mac: "bb", name: "B", module_name: "M", is_online: true, state: { is_on: true, brightness: 50, mode: "scene", scene_id: 1, speed: 100 } }
    ];
    appState.selectedIps = ["192.168.0.10"];
    appState.scenes = [{ scene_id: 1, name: "Ocean", category: "nature", supports_speed: true }];
    appState.customScenes = [{ id: "p1", name: "Warm", mode: "temperature", temperature: 2700, brightness: 50, is_favorite: false }];
  });

  afterEach(() => {
    resetPendingPresetDeleteForTests();
    resetFixtureUiStateForTests();
    resetBridgeStateForTests();
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.Event;
    delete globalThis.HTMLDialogElement;
    delete globalThis.requestAnimationFrame;
  });

  test("preserves focus across replaceChildren() in fixtures, scenes, and custom presets", () => {
    renderFixtureList();
    const powerBtn = dom.getById("fixture-list").querySelector('[data-focus-key="fixture-power:192.168.0.10"]');
    powerBtn.focus();
    renderFixtureList();
    assert.equal(dom.document.activeElement.getAttribute("data-focus-key"), "fixture-power:192.168.0.10");

    renderScenesGrid();
    const favBtn = dom.getById("scenes-grid").querySelector('[data-focus-key="scene-fav:1"]');
    favBtn.focus();
    renderScenesGrid();
    assert.equal(dom.document.activeElement.getAttribute("data-focus-key"), "scene-fav:1");

    renderCustomScenesGrid();
    const editBtn = dom.getById("custom-scenes-grid").querySelector('[data-focus-key="preset-edit:p1"]');
    editBtn.focus();
    renderCustomScenesGrid();
    assert.equal(dom.document.activeElement.getAttribute("data-focus-key"), "preset-edit:p1");
  });

  test("sets #select-all-fixtures.indeterminate on partial selection", () => {
    const selectAll = dom.getById("select-all-fixtures");
    appState.selectedIps = ["192.168.0.10"];
    renderFixtureList();
    assert.equal(selectAll.checked, false);
    assert.equal(selectAll.indeterminate, true);

    appState.selectedIps = ["192.168.0.10", "192.168.0.11"];
    renderFixtureList();
    assert.equal(selectAll.checked, true);
    assert.equal(selectAll.indeterminate, false);

    appState.selectedIps = [];
    renderFixtureList();
    assert.equal(selectAll.checked, false);
    assert.equal(selectAll.indeterminate, false);
  });

  test("syncs aria-pressed across toggle/preset groups and localizes wheel valuetext", () => {
    const bri50 = dom.seedElement("bri50", { tag: "button", className: "brightness-preset", dataset: { brightness: "50" } });
    const k2700 = dom.seedElement("k2700", { tag: "button", className: "kelvin-card", dataset: { kelvin: "2700" } });
    const ambiViv = dom.seedElement("ambi-v", { tag: "button", className: "ambilight-mode-btn", dataset: { colorMode: "vibrant" } });
    const ambiAvg = dom.seedElement("ambi-a", { tag: "button", className: "ambilight-mode-btn", dataset: { colorMode: "average" } });
    const musSpec = dom.seedElement("mus-s", { tag: "button", className: "music-palette-btn", dataset: { paletteMode: "spectrum" } });
    const scaleBal = dom.seedElement("scale-b", {
      tag: "button",
      className: "scale-preset-btn",
      attrs: { "data-target-slider": "ambilight-smoothing-slider", "data-value": "0.38" }
    });

    renderStageHeaderAndControls();
    assert.equal(bri50.getAttribute("aria-pressed"), "true");
    assert.equal(k2700.getAttribute("aria-pressed"), "true");

    appState.ambilight = { active: false, color_mode: "average", smoothing_alpha: 0.38 };
    renderAmbilightPanel();
    assert.equal(ambiViv.getAttribute("aria-pressed"), "false");
    assert.equal(ambiAvg.getAttribute("aria-pressed"), "true");

    appState.musicSync = { active: false, palette_mode: "spectrum", sensitivity: 1.0, smoothing_alpha: 0.5 };
    renderMusicPanel();
    assert.equal(musSpec.getAttribute("aria-pressed"), "true");

    updateSliderFill(dom.getById("ambilight-smoothing-slider"));
    assert.equal(scaleBal.getAttribute("aria-pressed"), "true");

    positionReticleFromRgb(255, 0, 0);
    assert.match(dom.getById("color-wheel-canvas").getAttribute("aria-valuetext"), /^T\(rgb\.wheelValueText\|/);
  });

  test("supports Home/End in tablist and moves brightness shortcut to Alt+ArrowUp/Down", async () => {
    const t1 = dom.seedElement("tab-btn-temperature", { tag: "button", className: "mode-tab", dataset: { mode: "temperature" }, attrs: { "aria-controls": "p1" } });
    const t2 = dom.seedElement("tab-btn-rgb", { tag: "button", className: "mode-tab", dataset: { mode: "rgb" }, attrs: { "aria-controls": "p2" } });
    const t3 = dom.seedElement("tab-btn-music", { tag: "button", className: "mode-tab", dataset: { mode: "music" }, attrs: { "aria-controls": "p3" } });
    dom.seedElement("p1", { tag: "section" });
    dom.seedElement("p2", { tag: "section" });
    dom.seedElement("p3", { tag: "section" });

    const briCalls = [];
    dom.window.pywebview = {
      api: {
        set_brightness: async (v) => { briCalls.push(v); return { ok: true }; }
      }
    };
    await resolveBackendApi();
    bindEvents();

    t2.dispatchEvent({ type: "keydown", key: "End" });
    assert.equal(appState.activeTab, "music");
    assert.equal(t3.getAttribute("aria-selected"), "true");

    t3.dispatchEvent({ type: "keydown", key: "Home" });
    assert.equal(appState.activeTab, "temperature");
    assert.equal(t1.getAttribute("aria-selected"), "true");

    let plainDefaultPrevented = false;
    dom.document.dispatchEvent({
      type: "keydown",
      key: "ArrowUp",
      preventDefault() { plainDefaultPrevented = true; }
    });
    assert.equal(plainDefaultPrevented, false);

    let altDefaultPrevented = false;
    dom.document.dispatchEvent({
      type: "keydown",
      key: "ArrowUp",
      altKey: true,
      preventDefault() { altDefaultPrevented = true; }
    });
    assert.equal(altDefaultPrevented, true);
    assert.equal(dom.getById("brightness-slider").value, "55");
  });
});
