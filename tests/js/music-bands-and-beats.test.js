/*
 * Behavior tests for Music Sync per-bulb bands, beat boost, and custom palette (PR 2A.4).
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { createDomEnvironment } from "./dom-harness.js";
import { appState } from "../../ui/js/store.js";
import {
  resetBridgeStateForTests,
  resolveBackendApi,
  setEnvelopeHandler
} from "../../ui/js/bridge-client.js";
import { applyBackendEnvelope, resetUiSyncCache } from "../../ui/js/app.js";
import { bindMusicEvents, renderMusicPanel } from "../../ui/js/music.js";

describe("Music Sync Per-Bulb Bands & Custom Palette UI (PR 2A.4)", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" },
        "music-device-select": { tag: "select", value: "-1" },
        "music-sensitivity-slider": { tag: "input", type: "range", value: "1.0", min: "0.4", max: "2.5" },
        "music-sensitivity-output": { tag: "output" },
        "music-smoothing-slider": { tag: "input", type: "range", value: "0.50", min: "0.20", max: "0.85" },
        "music-smoothing-output": { tag: "output" },
        "music-audio-brightness": { tag: "input", type: "checkbox", checked: true },
        "music-beat-boost": { tag: "input", type: "checkbox", checked: true },
        "music-beat-pill": { tag: "span" },
        "music-custom-palette-row": { tag: "div", hidden: true },
        "music-custom-bass": { tag: "input", type: "color", value: "#ff2a55" },
        "music-custom-mid": { tag: "input", type: "color", value: "#22e58b" },
        "music-custom-treble": { tag: "input", type: "color", value: "#389bff" },
        "music-band-map": { tag: "div" },
        "brightness-slider": { tag: "input", type: "range", value: "85", min: "10", max: "100" },
        "toggle-music-btn": { tag: "button" },
        "toggle-music-label": { tag: "span" },
        "music-custom-palette-btn": { tag: "button", className: "chip-btn music-palette-btn active", dataset: { paletteMode: "custom" } }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.bulbs = [
      { ip: "192.168.1.10", mac: "aa11", name: "Subwoofer Lamp", is_online: true, state: { is_on: true } },
      { ip: "192.168.1.11", mac: "aa12", name: "Ceiling Strip", is_online: true, state: { is_on: true } }
    ];
    appState.selectedIps = ["192.168.1.10", "192.168.1.11"];
    appState.musicSync = {
      active: false,
      device_index: -1,
      palette_mode: "custom",
      sensitivity: 1.0,
      smoothing_alpha: 0.50,
      audio_brightness: true,
      brightness: 85,
      beat: false,
      band_map: { "192.168.1.10": "bass", "192.168.1.11": "treble" },
      beat_boost: true,
      custom_palette: { bass: "#ff0044", mid: "#00ff88", treble: "#0088ff" }
    };
  });

  afterEach(() => {
    if (appState.musicPollTimer) {
      clearInterval(appState.musicPollTimer);
      appState.musicPollTimer = null;
    }
    resetBridgeStateForTests();
  });

  test("renders band selects + custom palette inputs and forwards bandMap, beatBoost, and customPalette", async () => {
    const calls = [];
    dom.window.pywebview = {
      api: {
        start_music_sync: async (...args) => {
          calls.push(args);
          return {
            ok: true,
            music_sync: Object.assign({}, appState.musicSync, {
              active: true,
              beat: true,
              band_map: args[7],
              beat_boost: args[8],
              custom_palette: args[9]
            }),
            error: null
          };
        },
        stop_music_sync: async () => ({ ok: true, music_sync: { active: false }, error: null })
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindMusicEvents();
    renderMusicPanel();

    assert.equal(dom.getById("music-custom-palette-row").hidden, false);
    const selects = dom.getById("music-band-map").querySelectorAll("select");
    assert.equal(selects.length, 2);
    assert.equal(selects[0].value, "bass");
    assert.equal(selects[1].value, "treble");

    dom.getById("music-beat-boost").checked = false;
    dom.getById("toggle-music-btn").click();
    await new Promise((r) => setTimeout(r, 0));

    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], "custom");
    assert.deepEqual(calls[0][7], { "192.168.1.10": "bass", "192.168.1.11": "treble" });
    assert.equal(calls[0][8], false);
    assert.deepEqual(calls[0][9], { bass: "#ff0044", mid: "#00ff88", treble: "#0088ff" });
    assert.equal(dom.getById("music-beat-pill").getAttribute("data-beat"), "true");
  });
});
