/*
 * Stage 4 regression tests: EN/ES dictionary parity, pruning unused i18n keys,
 * localized Ambilight/Music toast enum values, localized Plantgrowth custom scene
 * names, placeholder display/device localization, and HTML data-i18n coverage.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import vm from "node:vm";

import { createDomEnvironment } from "./dom-harness.js";
import { appState } from "../../ui/js/store.js";
import { resolveBackendApi, setEnvelopeHandler, resetBridgeStateForTests } from "../../ui/js/bridge-client.js";
import { renderAmbilightPanel, bindAmbilightEvents } from "../../ui/js/ambilight.js";
import { renderMusicPanel, bindMusicEvents } from "../../ui/js/music.js";
import { renderCustomScenesGrid, resetPendingPresetDeleteForTests } from "../../ui/js/scenes.js";

const INDEX_HTML = readFileSync(new URL("../../ui/index.html", import.meta.url), "utf8");
const I18N_JS = readFileSync(new URL("../../ui/i18n.js", import.meta.url), "utf8");

function loadI18nDictionaries() {
  const sandboxWindow = {};
  const sandboxDocument = {
    documentElement: { lang: "en" },
    title: "",
    querySelectorAll: () => []
  };
  vm.runInNewContext(I18N_JS, { window: sandboxWindow, document: sandboxDocument });
  return sandboxWindow.I18N;
}

function collectUiSources() {
  const jsDir = new URL("../../ui/js/", import.meta.url);
  const jsFiles = readdirSync(jsDir)
    .filter((name) => name.endsWith(".js"))
    .map((name) => readFileSync(new URL(name, jsDir), "utf8"));
  return [INDEX_HTML, ...jsFiles].join("\n");
}

describe("Stage 4 static i18n parity, pruning, and HTML contracts", () => {
  test("EN and ES dictionaries have identical key sets and exclude the 8 pruned unused keys", () => {
    const i18n = loadI18nDictionaries();
    const enKeys = Object.keys(i18n.dictionaries.en).sort();
    const esKeys = Object.keys(i18n.dictionaries.es).sort();

    assert.deepEqual(enKeys, esKeys);

    const prunedKeys = [
      "ambi.framesSent",
      "ambi.statusStreaming",
      "music.framesSent",
      "music.statusActive",
      "rail.powerOff",
      "rail.powerOn",
      "rail.renameBtn",
      "stage.controllingOne"
    ];
    for (const removed of prunedKeys) {
      assert.equal(Object.hasOwn(i18n.dictionaries.en, removed), false, `EN should prune ${removed}`);
      assert.equal(Object.hasOwn(i18n.dictionaries.es, removed), false, `ES should prune ${removed}`);
    }
  });

  test("every key defined in ui/i18n.js is referenced in ui/index.html or ui/js/*.js", () => {
    const i18n = loadI18nDictionaries();
    const sources = collectUiSources();
    const unreferenced = [];

    for (const key of Object.keys(i18n.dictionaries.en)) {
      if (!sources.includes(key)) {
        unreferenced.push(key);
      }
    }

    assert.deepEqual(unreferenced, []);
  });

  test("annotates initial Ambilight/Music readouts and default selects with data-i18n", () => {
    assert.match(INDEX_HTML, /id="ambilight-frames-readout"[^>]*data-i18n="ambi\.telemetryZero"/);
    assert.match(INDEX_HTML, /id="music-frames-readout"[^>]*data-i18n="music\.telemetryZero"/);
    assert.match(INDEX_HTML, /<option value="1" data-i18n="ambi\.defaultDisplay">/);
    assert.match(INDEX_HTML, /<option value="-1" data-i18n="music\.defaultDevice">/);
  });

  test("unifies Spanish custom preset wording as Presets instead of Escenas Personalizadas", () => {
    const i18n = loadI18nDictionaries();
    const es = i18n.dictionaries.es;
    assert.equal(es["custom.title"], "Presets Guardados");
    assert.equal(es["dialog.presetSaveTitle"], "Guardar Preset");
    assert.equal(es["dialog.presetEditTitle"], "Editar Preset");
    assert.match(es["custom.favoriteAddTitle"], /Presets favoritos/);
    assert.match(es["status.presetSaved"], /^Preset /);
  });
});

describe("Stage 4 behavioral localization and enum formatting", () => {
  let dom;
  let apiCalls;
  let initialMonitors;
  let initialAudioDevices;

  beforeEach(async () => {
    resetBridgeStateForTests();
    resetPendingPresetDeleteForTests();
    initialMonitors = appState.monitors;
    initialAudioDevices = appState.audioDevices;
    apiCalls = [];

    dom = createDomEnvironment({
      elementsById: {
        "console-shell": { tag: "div" },
        "ambilight-monitor-select": { tag: "select", value: "1" },
        "ambilight-status-badge": { tag: "span" },
        "ambilight-frames-readout": { tag: "span" },
        "ambilight-preview-swatch": { tag: "div" },
        "ambilight-color-readout": { tag: "p" },
        "toggle-ambilight-btn": { tag: "button" },
        "toggle-ambilight-label": { tag: "span" },
        "ambilight-smoothing-slider": { tag: "input", min: 0.15, max: 0.75, value: 0.38 },
        "ambilight-smoothing-output": { tag: "output" },
        "ambilight-auto-brightness": { tag: "input", checked: true },
        "ambilight-min-brightness-row": { tag: "div" },
        "ambilight-min-brightness-slider": { tag: "input", min: 5, max: 20, value: 10 },
        "ambilight-min-brightness-output": { tag: "output" },
        "music-device-select": { tag: "select", value: "-1" },
        "music-status-badge": { tag: "span" },
        "music-frames-readout": { tag: "span" },
        "music-preview-swatch": { tag: "div" },
        "music-color-readout": { tag: "p" },
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
        "music-smoothing-slider": { tag: "input", min: 0.2, max: 0.85, value: 0.5 },
        "music-smoothing-output": { tag: "output" },
        "music-audio-brightness": { tag: "input", checked: true },
        "brightness-slider": { tag: "input", min: 10, max: 100, value: 85 },
        "custom-scenes-grid": { tag: "div" },
        "custom-tab-label": { tag: "span" },
        "status-banner": { tag: "p" },
        "toast-region": { tag: "div" }
      }
    });

    dom.seedElement("ambi-mode-vibrant", {
      tag: "button",
      className: "chip-btn ambilight-mode-btn active",
      dataset: { colorMode: "vibrant" }
    });
    dom.seedElement("ambi-mode-average", {
      tag: "button",
      className: "chip-btn ambilight-mode-btn",
      dataset: { colorMode: "average" }
    });

    dom.seedElement("music-palette-spectrum", {
      tag: "button",
      className: "chip-btn music-palette-btn active",
      dataset: { paletteMode: "spectrum" }
    });
    dom.seedElement("music-palette-club", {
      tag: "button",
      className: "chip-btn music-palette-btn",
      dataset: { paletteMode: "club" }
    });
    dom.seedElement("music-palette-chill", {
      tag: "button",
      className: "chip-btn music-palette-btn",
      dataset: { paletteMode: "chill" }
    });

    dom.install();

    globalThis.window.pywebview = {
      api: {
        start_ambilight: async (...args) => {
          apiCalls.push(["start_ambilight", ...args]);
          return { ok: true, ambilight: appState.ambilight };
        },
        start_music_sync: async (...args) => {
          apiCalls.push(["start_music_sync", ...args]);
          return { ok: true, music_sync: appState.musicSync };
        }
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler((_resp, successMsg) => {
      const msg = typeof successMsg === "function" ? successMsg() : successMsg;
      if (msg) dom.getById("status-banner").textContent = msg;
    });

    appState.ambilight = {
      active: true,
      monitor_index: 1,
      color_mode: "vibrant",
      auto_brightness: true,
      min_brightness: 10,
      brightness: 85,
      smoothing_alpha: 0.38,
      frames_sent: 5
    };
    appState.musicSync = {
      active: true,
      device_index: -1,
      palette_mode: "spectrum",
      sensitivity: 1.0,
      smoothing_alpha: 0.5,
      audio_brightness: true,
      brightness: 85,
      frames_sent: 5,
      bass: 0.1,
      mid: 0.1,
      treble: 0.1,
      rms: 0.1
    };
  });

  afterEach(() => {
    setEnvelopeHandler(null);
    appState.monitors = initialMonitors;
    appState.audioDevices = initialAudioDevices;
    appState.ambilight.active = false;
    appState.musicSync.active = false;
    resetPendingPresetDeleteForTests();
    resetBridgeStateForTests();
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.Event;
    delete globalThis.HTMLDialogElement;
  });

  test("localizes Ambilight color extraction mode in status toast instead of leaking raw enum", async () => {
    bindAmbilightEvents();
    const avgBtn = dom.getById("ambi-mode-average");
    avgBtn.dispatchEvent({ type: "click" });
    await new Promise((r) => setTimeout(r, 0));

    assert.equal(appState.ambilight.color_mode, "average");
    assert.equal(dom.getById("status-banner").textContent, "T(status.ambiModeChanged|mode=T(ambi.modeAverage))");
  });

  test("localizes Music Sync palette mode in status toast instead of leaking raw enum", async () => {
    bindMusicEvents();
    const clubBtn = dom.getById("music-palette-club");
    clubBtn.dispatchEvent({ type: "click" });
    await new Promise((r) => setTimeout(r, 0));

    assert.equal(appState.musicSync.palette_mode, "club");
    assert.equal(dom.getById("status-banner").textContent, "T(status.musicPaletteChanged|palette=T(music.paletteClub))");
  });

  test("formats built-in scene #19 (Plantgrowth) via formatSceneDisplayName inside custom presets", () => {
    appState.scenes = [{ scene_id: 19, name: "Plantgrowth", category: "nature", supports_speed: false }];
    appState.customScenes = [
      { id: "p19", name: "Botanical Desk", mode: "scene", built_in_scene_id: 19, brightness: 75, is_favorite: false }
    ];

    renderCustomScenesGrid();
    const card = dom.getById("custom-scenes-grid").children[0];
    const summary = card.children[0].children[1].children[1];
    assert.equal(summary.textContent, "T(custom.summaryScene|scene=T(scenes.plantGrowth),brightness=75)");
  });

  test("localizes placeholder monitor and audio device labels via translator", () => {
    renderAmbilightPanel();
    renderMusicPanel();

    const monOpt = dom.getById("ambilight-monitor-select").children[0];
    const devOpt = dom.getById("music-device-select").children[0];
    assert.equal(monOpt.textContent, "T(ambi.defaultDisplay)");
    assert.equal(devOpt.textContent, "T(music.defaultDevice)");
  });

  test("localizes backend-populated monitor and WASAPI audio device labels cleanly", () => {
    appState.monitors = [
      { index: 1, label: "Display 1 (2560x1440)", width: 2560, height: 1440 },
      { index: 0, label: "All displays (4480x1440)", width: 4480, height: 1440 }
    ];
    appState.audioDevices = [
      { index: -1, name: "System Audio Loopback", label: "Default System Output (WASAPI Loopback)", sample_rate: 48000, is_default: true },
      { index: 3, name: "Speakers (Realtek) [Loopback]", label: "Default · Speakers (Realtek) [Loopback] (48000 Hz)", sample_rate: 48000, is_default: true }
    ];

    renderAmbilightPanel();
    renderMusicPanel();

    const monOpts = dom.getById("ambilight-monitor-select").children.map((o) => o.textContent);
    const devOpts = dom.getById("music-device-select").children.map((o) => o.textContent);

    assert.deepEqual(monOpts, [
      "T(ambi.displayItem|index=1,width=2560,height=1440)",
      "T(ambi.allDisplays|width=4480,height=1440)"
    ]);
    assert.deepEqual(devOpts, [
      "T(music.defaultDevice)",
      "T(music.defaultPrefix) · Speakers (Realtek) (48000 Hz)"
    ]);
  });
});
