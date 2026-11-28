/*
 * Behaviour tests for selective envelope updates (app.js), polling guards & active-input
 * protection (ambilight.js, music.js, fixtures.js, stage-controls.js), and toasts.js.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createDomEnvironment } from "./dom-harness.js";
import { appState } from "../../ui/js/store.js";
import {
  resetBridgeStateForTests,
  resolveBackendApi
} from "../../ui/js/bridge-client.js";
import {
  activateTab,
  applyBackendEnvelope,
  bindEvents,
  resetUiSyncCache,
  syncLanguageUi,
  syncThemeUi
} from "../../ui/js/app.js";
import {
  bindAmbilightEvents,
  renderAmbilightPanel,
  syncAmbilightPolling
} from "../../ui/js/ambilight.js";
import {
  bindMusicEvents,
  renderMusicPanel,
  syncMusicPolling
} from "../../ui/js/music.js";
import {
  bindFixtureEvents,
  renderFixtureList,
  renderSleepTimer,
  syncSleepTimerPolling
} from "../../ui/js/fixtures.js";
import {
  bindStageControlEvents,
  drawColorWheel,
  renderStageHeaderAndControls
} from "../../ui/js/stage-controls.js";
import { setStatusMessage, showToast } from "../../ui/js/toasts.js";

const SCENE_CATALOG = JSON.parse(readFileSync(new URL("../../ui/scenes.json", import.meta.url), "utf8"));

function buildFullHarness() {
  const dom = createDomEnvironment({
    elementsById: {
      "status-banner": { tag: "div" },
      "toast-region": { tag: "div" },
      "console-shell": { tag: "div" },
      "theme-btn-stone": { tag: "button" },
      "theme-btn-dark": { tag: "button" },
      "fixture-list": { tag: "div" },
      "fixture-count-badge": { tag: "span" },
      "select-all-fixtures": { tag: "input" },
      "fixture-drawer-btn": { tag: "button" },
      "fixture-drawer": { tag: "dialog" },
      "scan-network-btn": { tag: "button" },
      "scan-btn-label": { tag: "span" },
      "open-add-dialog-btn": { tag: "button" },
      "add-bulb-dialog": { tag: "dialog" },
      "add-bulb-form": { tag: "form" },
      "manual-ip-input": { tag: "input" },
      "manual-name-input": { tag: "input" },
      "rename-bulb-dialog": { tag: "dialog" },
      "rename-bulb-form": { tag: "form" },
      "rename-bulb-ip-display": { tag: "p" },
      "rename-bulb-ip-input": { tag: "input" },
      "rename-bulb-name-input": { tag: "input" },
      "sync-now-btn": { tag: "button" },
      "auto-sync-toggle": { tag: "input" },
      "sleep-timer-details": { tag: "details" },
      "sleep-timer-badge": { tag: "span" },
      "sleep-minutes-input": { tag: "input", value: "30" },
      "start-sleep-timer-btn": { tag: "button" },
      "cancel-sleep-timer-btn": { tag: "button" },
      "target-summary": { tag: "div" },
      "live-state-pill": { tag: "span" },
      "telemetry-meta": { tag: "div" },
      "master-power-btn": { tag: "button" },
      "master-power-label": { tag: "span" },
      "photometric-aperture": { tag: "div" },
      "drawer-pill-label": { tag: "span" },
      "drawer-pill-dot": { tag: "span" },
      "brightness-slider": { tag: "input", min: 10, max: 100, value: 85 },
      "brightness-output": { tag: "output" },
      "color-wheel-canvas": { tag: "canvas" },
      "wheel-reticle": { tag: "div" },
      "input-r": { tag: "input", value: "255" },
      "input-g": { tag: "input", value: "140" },
      "input-b": { tag: "input", value: "66" },
      "input-hex": { tag: "input", value: "#ff8c42" },
      "apply-rgb-btn": { tag: "button" },
      "kelvin-slider": { tag: "input", min: 2200, max: 6500, value: 4200 },
      "kelvin-output": { tag: "output" },
      "scene-speed-container": { tag: "div" },
      "scene-speed-slider": { tag: "input", min: 10, max: 200, value: 100 },
      "scene-speed-output": { tag: "output" },
      "scenes-grid": { tag: "div" },
      "custom-scenes-grid": { tag: "div" },
      "custom-tab-label": { tag: "span" },
      "tab-ambilight-dot": { tag: "span" },
      "ambilight-monitor-select": { tag: "select" },
      "ambilight-status-badge": { tag: "span" },
      "ambilight-frames-readout": { tag: "span" },
      "ambilight-preview-swatch": { tag: "div" },
      "ambilight-color-readout": { tag: "span" },
      "toggle-ambilight-btn": { tag: "button" },
      "toggle-ambilight-label": { tag: "span" },
      "ambilight-smoothing-slider": { tag: "input", min: 0.1, max: 1, value: 0.38 },
      "ambilight-smoothing-output": { tag: "output" },
      "ambilight-auto-brightness": { tag: "input", checked: true },
      "ambilight-min-brightness-row": { tag: "div" },
      "ambilight-min-brightness-slider": { tag: "input", min: 5, max: 20, value: 10 },
      "ambilight-min-brightness-output": { tag: "output" },
      "tab-music-dot": { tag: "span" },
      "music-device-select": { tag: "select" },
      "music-status-badge": { tag: "span" },
      "music-frames-readout": { tag: "span" },
      "music-preview-swatch": { tag: "div" },
      "music-color-readout": { tag: "span" },
      "music-meter-bass-fill": { tag: "div" },
      "music-meter-bass-val": { tag: "span" },
      "music-meter-mid-fill": { tag: "div" },
      "music-meter-mid-val": { tag: "span" },
      "music-meter-treble-fill": { tag: "div" },
      "music-meter-treble-val": { tag: "span" },
      "music-meter-rms-fill": { tag: "div" },
      "music-meter-rms-val": { tag: "span" },
      "toggle-music-btn": { tag: "button" },
      "toggle-music-label": { tag: "span" },
      "music-sensitivity-slider": { tag: "input", min: 0.4, max: 2.5, value: 1.0 },
      "music-sensitivity-output": { tag: "output" },
      "music-smoothing-slider": { tag: "input", min: 0.1, max: 1.0, value: 0.5 },
      "music-smoothing-output": { tag: "output" },
      "music-audio-brightness": { tag: "input", checked: true }
    }
  });
  dom.seedElement("meta-cs", { tag: "meta", attrs: { name: "color-scheme", content: "light" } });
  const ambiMode = dom.seedElement("ambi-mode-v", { tag: "button", className: "ambilight-mode-btn active", dataset: { colorMode: "vibrant" } });
  const musicPal = dom.seedElement("music-pal-s", { tag: "button", className: "music-palette-btn active", dataset: { paletteMode: "spectrum" } });
  const scalePreset = dom.seedElement("scale-preset-1", { tag: "button", className: "scale-preset-btn", dataset: { targetSlider: "music-sensitivity-slider", value: "1.5" } });
  const briPreset = dom.seedElement("bri-preset-50", { tag: "button", className: "brightness-preset", dataset: { brightness: "50" } });
  const swatch = dom.seedElement("swatch-1", { tag: "button", className: "color-swatch", dataset: { r: "10", g: "20", b: "30" } });
  const kelvinCard = dom.seedElement("kelvin-1", { tag: "button", className: "kelvin-card", dataset: { kelvin: "2700" } });
  const sleepPreset = dom.seedElement("sleep-15", { tag: "button", className: "sleep-preset-btn", dataset: { minutes: "15" } });
  const langEn = dom.seedElement("lang-btn-en", { tag: "button", className: "lang-btn", dataset: { lang: "en" } });
  const langEs = dom.seedElement("lang-btn-es", { tag: "button", className: "lang-btn", dataset: { lang: "es" } });
  assert.ok(ambiMode && musicPal && scalePreset && briPreset && swatch && kelvinCard && sleepPreset && langEn && langEs);
  dom.install();
  return dom;
}

function makeFullEnvelope(overrides = {}) {
  return {
    ok: true,
    language: "en",
    theme: "architectural-stone",
    bulbs: [
      {
        ip: "192.168.0.10",
        mac: "a8bb50112233",
        name: "Desk",
        module_name: "ESP01",
        is_online: true,
        state: { is_on: true, brightness: 85, mode: "rgb", color: { r: 20, g: 40, b: 60, hex: "#14283c" }, temperature: 4200, scene_id: null, speed: 100 }
      }
    ],
    selected_ips: ["192.168.0.10"],
    scenes: SCENE_CATALOG.slice(),
    custom_scenes: [],
    sleep_timer: { active: false, remaining_seconds: 0, total_seconds: 0, target_ips: [] },
    ambilight: { active: false, monitor_index: 1, color_mode: "vibrant", auto_brightness: true, min_brightness: 10, brightness: 85, smoothing_alpha: 0.38, last_color: { r: 10, g: 20, b: 30 }, frames_sent: 0 },
    monitors: [{ index: 1, label: "Display 1", width: 1920, height: 1080 }],
    music_sync: { active: false, device_index: -1, palette_mode: "spectrum", sensitivity: 1.0, smoothing_alpha: 0.5, audio_brightness: true, brightness: 85, rms: 0, bass: 0, mid: 0, treble: 0, last_color: { r: 10, g: 20, b: 30 }, frames_sent: 0 },
    audio_devices: [{ index: -1, name: "Default", label: "Default", sample_rate: 48000, channels: 2, is_default: true }],
    error: null,
    ...overrides
  };
}

function clearTimers() {
  clearInterval(appState.autoSyncTimer);
  clearInterval(appState.sleepPollTimer);
  clearInterval(appState.ambilightPollTimer);
  clearInterval(appState.musicPollTimer);
  appState.autoSyncTimer = null;
  appState.sleepPollTimer = null;
  appState.ambilightPollTimer = null;
  appState.musicPollTimer = null;
}

describe("selective envelope updates (app.js)", () => {
  let dom;

  beforeEach(async () => {
    dom = buildFullHarness();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.language = "en";
    appState.theme = "architectural-stone";
    appState.bulbs = [];
    appState.selectedIps = [];
    appState.scenes = SCENE_CATALOG.slice();
    appState.customScenes = [];
    appState.ambilight = { active: false, monitor_index: 1, color_mode: "vibrant", auto_brightness: true, min_brightness: 10, brightness: 85, smoothing_alpha: 0.38, last_color: null, frames_sent: 0 };
    appState.musicSync = { active: false, device_index: -1, palette_mode: "spectrum", sensitivity: 1.0, smoothing_alpha: 0.5, audio_brightness: true, brightness: 85, rms: 0, bass: 0, mid: 0, treble: 0, last_color: null, frames_sent: 0 };
    clearTimers();
    dom.window.pywebview = { api: { refresh_states: async () => makeFullEnvelope() } };
    await resolveBackendApi();
  });

  afterEach(() => {
    clearTimers();
    resetBridgeStateForTests();
  });

  test("skips translateDom, localStorage writes, and unaffected grid rebuilds on delta polls", async () => {
    applyBackendEnvelope(makeFullEnvelope(), "connected", null, true);

    const translateCountAfterInit = dom.i18n.translateDomCalls.length;
    const storageWritesAfterInit = dom.storage.setCalls.length;
    const scenesRebuildsAfterInit = dom.getById("scenes-grid").replaceChildrenCalls;
    const customRebuildsAfterInit = dom.getById("custom-scenes-grid").replaceChildrenCalls;
    const fixtureRebuildsAfterInit = dom.getById("fixture-list").replaceChildrenCalls;

    applyBackendEnvelope({
      ok: true,
      ambilight: { active: true, monitor_index: 1, color_mode: "vibrant", auto_brightness: true, min_brightness: 10, brightness: 85, smoothing_alpha: 0.38, last_color: { r: 90, g: 120, b: 200 }, frames_sent: 12 },
      error: null
    }, null, null, true);

    applyBackendEnvelope({
      ok: true,
      music_sync: { active: true, device_index: -1, palette_mode: "spectrum", sensitivity: 1.0, smoothing_alpha: 0.5, audio_brightness: true, brightness: 85, rms: 0.6, bass: 0.8, mid: 0.4, treble: 0.2, last_color: { r: 200, g: 50, b: 90 }, frames_sent: 8 },
      error: null
    }, null, null, true);

    assert.equal(dom.i18n.translateDomCalls.length, translateCountAfterInit);
    assert.equal(dom.storage.setCalls.length, storageWritesAfterInit);
    assert.equal(dom.getById("scenes-grid").replaceChildrenCalls, scenesRebuildsAfterInit);
    assert.equal(dom.getById("custom-scenes-grid").replaceChildrenCalls, customRebuildsAfterInit);
    assert.equal(dom.getById("fixture-list").replaceChildrenCalls, fixtureRebuildsAfterInit);

    syncLanguageUi("en");
    syncThemeUi("architectural-stone");
    assert.equal(dom.i18n.translateDomCalls.length, translateCountAfterInit);
    assert.equal(dom.storage.setCalls.length, storageWritesAfterInit);

    applyBackendEnvelope(makeFullEnvelope({ language: "es", theme: "atmospheric-dark" }), null, null, true);
    assert.equal(dom.i18n.translateDomCalls.length, translateCountAfterInit + 1);
    assert.ok(dom.getById("scenes-grid").replaceChildrenCalls > scenesRebuildsAfterInit);
  });

  test("triggers silent refresh_states when a delta poll observes a stream stopped", async () => {
    let refreshes = 0;
    dom.window.pywebview = {
      api: {
        refresh_states: async () => {
          refreshes += 1;
          return makeFullEnvelope();
        }
      }
    };
    resetBridgeStateForTests();
    await resolveBackendApi();

    appState.ambilight = { active: true, monitor_index: 1, color_mode: "vibrant", auto_brightness: true, min_brightness: 10, brightness: 85, smoothing_alpha: 0.38, last_color: null, frames_sent: 5 };
    applyBackendEnvelope({
      ok: true,
      ambilight: { active: false, monitor_index: 1, color_mode: "vibrant", auto_brightness: true, min_brightness: 10, brightness: 85, smoothing_alpha: 0.38, last_color: null, frames_sent: 5 },
      error: null
    }, null, null, true);
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(refreshes, 1);
  });

  test("handles error envelopes and exercises app.js bootstrap, tabs, and visibilitychange", async () => {
    applyBackendEnvelope({ ok: false, error: "bulb offline" }, null, () => {}, false);
    assert.match(dom.getById("status-banner").textContent, /status\.warning/);

    const tab1 = dom.seedElement("tab-temp", { tag: "button", className: "mode-tab", dataset: { mode: "temperature" }, attrs: { "aria-controls": "panel-temp" } });
    const tab2 = dom.seedElement("tab-rgb", { tag: "button", className: "mode-tab", dataset: { mode: "rgb" }, attrs: { "aria-controls": "panel-rgb" } });
    dom.seedElement("panel-temp", { tag: "section" });
    dom.seedElement("panel-rgb", { tag: "section" });
    dom.seedElement("details-sleep", { tag: "details", attrs: { "data-persist-open": "sleep" } });
    dom.storage.setItem("wiz_console_ui_prefs", JSON.stringify({ activeTab: "rgb", openSections: { sleep: true }, theme: "atmospheric-dark" }));

    const apiCalls = [];
    dom.window.pywebview = {
      api: {
        get_initial_state: async () => { apiCalls.push("init"); return makeFullEnvelope(); },
        refresh_states: async () => { apiCalls.push("refresh"); return makeFullEnvelope(); },
        set_theme: async (th) => { apiCalls.push(["set_theme", th]); return makeFullEnvelope({ theme: th }); },
        set_language: async (lang) => { apiCalls.push(["set_language", lang]); return makeFullEnvelope({ language: lang }); },
        get_ambilight_status: async () => { apiCalls.push("ambi"); return { ok: true, ambilight: appState.ambilight, error: null }; },
        fit_window_height: () => ({ ok: true })
      }
    };
    resetBridgeStateForTests();
    await resolveBackendApi();

    bindEvents();
    activateTab("rgb", true);
    tab1.click();
    tab2.dispatchEvent({ type: "keydown", key: "ArrowLeft" });
    dom.getById("theme-btn-dark").click();
    dom.getById("lang-btn-es").click();
    dom.window.onTrayStateChanged();
    appState.ambilight.active = true;
    dom.document.hidden = false;
    dom.document.dispatchEvent("visibilitychange");
    await new Promise((r) => setTimeout(r, 15));

    assert.ok(apiCalls.some((c) => Array.isArray(c) && c[0] === "set_theme"));
    assert.ok(apiCalls.some((c) => Array.isArray(c) && c[0] === "set_language"));
    assert.ok(apiCalls.includes("refresh"));
    assert.ok(apiCalls.includes("ambi"));
  });
});

describe("polling guards, active-input protection, controls & toasts", () => {
  let dom;

  beforeEach(async () => {
    dom = buildFullHarness();
    resetBridgeStateForTests();
    resetUiSyncCache();
    clearTimers();
    appState.bulbs = makeFullEnvelope().bulbs;
    appState.selectedIps = ["192.168.0.10"];
    appState.scenes = SCENE_CATALOG.slice();
    appState.ambilight = makeFullEnvelope().ambilight;
    appState.monitors = makeFullEnvelope().monitors;
    appState.musicSync = makeFullEnvelope().music_sync;
    appState.audioDevices = makeFullEnvelope().audio_devices;
    appState.sleepTimer = { active: true, remaining_seconds: 90, total_seconds: 120, target_ips: [] };
  });

  afterEach(() => {
    clearTimers();
    resetBridgeStateForTests();
  });

  test("preserves focused sliders, selects, and RGB inputs during background re-renders", () => {
    const briSlider = dom.getById("brightness-slider");
    briSlider.value = "42";
    briSlider.focus();
    renderStageHeaderAndControls();
    assert.equal(briSlider.value, "42");

    const kelvinSlider = dom.getById("kelvin-slider");
    kelvinSlider.value = "3100";
    kelvinSlider.focus();
    renderStageHeaderAndControls();
    assert.equal(kelvinSlider.value, "3100");

    const rIn = dom.getById("input-r");
    rIn.value = "123";
    rIn.focus();
    renderStageHeaderAndControls();
    assert.equal(rIn.value, "123");

    const ambiAlpha = dom.getById("ambilight-smoothing-slider");
    ambiAlpha.value = "0.75";
    ambiAlpha.focus();
    renderAmbilightPanel();
    assert.equal(ambiAlpha.value, "0.75");

    const musicSens = dom.getById("music-sensitivity-slider");
    musicSens.value = "2.1";
    musicSens.focus();
    renderMusicPanel();
    assert.equal(musicSens.value, "2.1");

    const musicDev = dom.getById("music-device-select");
    musicDev.value = "99";
    musicDev.focus();
    renderMusicPanel();
    assert.equal(musicDev.value, "99");
  });

  test("autoSyncToggle polls silently without OK toast spam and stops cleanly", async () => {
    const calls = [];
    dom.window.pywebview = {
      api: {
        refresh_states: async () => {
          calls.push("refresh");
          return makeFullEnvelope();
        },
        get_ambilight_status: async () => ({ ok: true, ambilight: appState.ambilight, error: null }),
        get_music_sync_status: async () => ({ ok: true, music_sync: appState.musicSync, error: null }),
        get_sleep_timer_status: async () => makeFullEnvelope(),
        discover_bulbs: async () => makeFullEnvelope(),
        select_targets: async () => makeFullEnvelope(),
        set_power: async () => makeFullEnvelope(),
        start_sleep_timer: async () => makeFullEnvelope(),
        cancel_sleep_timer: async () => makeFullEnvelope()
      }
    };
    await resolveBackendApi();
    bindFixtureEvents();

    const originalSetInterval = globalThis.setInterval;
    const scheduled = [];
    globalThis.setInterval = (fn, ms) => {
      scheduled.push({ fn, ms });
      return scheduled.length;
    };
    try {
      const toggle = dom.getById("auto-sync-toggle");
      toggle.checked = true;
      toggle.dispatchEvent("change");
      assert.equal(scheduled.length, 1);
      assert.equal(scheduled[0].ms, 3000);

      await scheduled[0].fn();
      assert.equal(calls.length, 1);
      assert.equal(dom.getById("toast-region").children.length, 0);

      toggle.checked = false;
      toggle.dispatchEvent("change");
      assert.equal(appState.autoSyncTimer, null);

      appState.ambilight.active = true;
      appState.musicSync.active = true;
      syncAmbilightPolling();
      syncMusicPolling();
      syncSleepTimerPolling();
      assert.equal(scheduled.length, 4);

      dom.document.hidden = true;
      for (const entry of scheduled.slice(1)) await entry.fn();
      assert.equal(calls.length, 1);
    } finally {
      globalThis.setInterval = originalSetInterval;
    }

    renderFixtureList();
    renderSleepTimer();
    assert.equal(dom.getById("fixture-list").replaceChildrenCalls, 1);
  });

  test("binds and exercises stage, ambilight, music, and toast controls", async () => {
    const dispatched = [];
    dom.window.pywebview = {
      api: {
        set_power: async (...args) => { dispatched.push(["set_power", ...args]); return makeFullEnvelope(); },
        set_brightness: async (...args) => { dispatched.push(["set_brightness", ...args]); return makeFullEnvelope(); },
        set_color: async (...args) => { dispatched.push(["set_color", ...args]); return makeFullEnvelope(); },
        set_temperature: async (...args) => { dispatched.push(["set_temperature", ...args]); return makeFullEnvelope(); },
        start_ambilight: async (...args) => { dispatched.push(["start_ambilight", ...args]); return makeFullEnvelope(); },
        stop_ambilight: async () => { dispatched.push(["stop_ambilight"]); return makeFullEnvelope(); },
        start_music_sync: async (...args) => { dispatched.push(["start_music_sync", ...args]); return makeFullEnvelope(); },
        stop_music_sync: async () => { dispatched.push(["stop_music_sync"]); return makeFullEnvelope(); }
      }
    };
    await resolveBackendApi();

    drawColorWheel();
    bindStageControlEvents();
    bindAmbilightEvents();
    bindMusicEvents();

    dom.getById("master-power-btn").click();
    dom.getById("bri-preset-50").click();
    dom.getById("apply-rgb-btn").click();
    dom.getById("kelvin-1").click();
    dom.getById("toggle-ambilight-btn").click();
    dom.getById("toggle-music-btn").click();
    dom.getById("scale-preset-1").click();

    await new Promise((r) => setTimeout(r, 0));
    assert.ok(dispatched.some((d) => d[0] === "set_power"));
    assert.ok(dispatched.some((d) => d[0] === "set_brightness"));
    assert.ok(dispatched.some((d) => d[0] === "set_color"));
    assert.ok(dispatched.some((d) => d[0] === "set_temperature"));
    assert.ok(dispatched.some((d) => d[0] === "start_ambilight"));
    assert.ok(dispatched.some((d) => d[0] === "start_music_sync"));

    setStatusMessage("Ready");
    assert.equal(dom.getById("status-banner").textContent, "Ready");
    showToast({ kind: "ok", message: "First" });
    showToast({ kind: "ok", message: "Second" });
    assert.equal(dom.getById("toast-region").children.length, 1);
    showToast({ kind: "error", message: "Boom" });
    showToast({ kind: "error", message: "Boom" });
    assert.equal(dom.getById("toast-region").children.length, 2);
    dom.getById("toast-region").querySelector(".toast-close").click();
    assert.equal(dom.getById("toast-region").children.length, 1);
  });

  test("hydrates session prefs and migrates legacy favorite scenes once to backend", async () => {
    const migratedCalls = [];
    dom.storage.setItem("gestor_luces_fav_scenes", JSON.stringify([4, 12]));
    dom.window.pywebview = {
      api: {
        set_favorite_builtin_scenes: async (ids) => {
          migratedCalls.push(ids);
          return makeFullEnvelope({ favorite_builtin_scenes: ids });
        },
        set_auto_sync: async (enabled) => makeFullEnvelope({ auto_sync: enabled })
      }
    };
    resetBridgeStateForTests();
    await resolveBackendApi();

    applyBackendEnvelope(
      makeFullEnvelope({
        auto_sync: true,
        favorite_builtin_scenes: [],
        ambilight_prefs: {
          monitor_index: 2,
          color_mode: "average",
          auto_brightness: false,
          min_brightness: 12,
          smoothing_alpha: 0.5
        },
        music_prefs: {
          device_index: 3,
          palette_mode: "warm",
          sensitivity: 1.5,
          smoothing_alpha: 0.6,
          audio_brightness: false
        }
      }),
      null,
      null,
      true
    );

    assert.equal(appState.autoSync, true);
    assert.equal(appState.ambilightPrefs.monitor_index, 2);
    assert.equal(appState.ambilightPrefs.min_brightness, 12);
    assert.equal(appState.musicPrefs.device_index, 3);
    assert.equal(migratedCalls.length, 1);
    assert.deepEqual(migratedCalls[0], [4, 12]);
  });
});
