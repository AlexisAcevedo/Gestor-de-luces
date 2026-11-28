/*
 * Behavior tests for Multi-Zone Ambilight controls & letterbox crop (PR 2A.3).
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
import { bindAmbilightEvents, renderAmbilightPanel } from "../../ui/js/ambilight.js";

describe("Ambilight Multi-Zone UI (PR 2A.3)", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" },
        "ambilight-monitor-select": { tag: "select", value: "1" },
        "ambilight-smoothing-slider": { tag: "input", type: "range", value: "0.38", min: "0.15", max: "0.75" },
        "ambilight-smoothing-output": { tag: "output" },
        "ambilight-auto-brightness": { tag: "input", type: "checkbox", checked: true },
        "ambilight-min-brightness-row": { tag: "div" },
        "ambilight-min-brightness-slider": { tag: "input", type: "range", value: "10", min: "10", max: "20" },
        "ambilight-min-brightness-output": { tag: "output" },
        "ambilight-letterbox-crop": { tag: "input", type: "checkbox", checked: true },
        "ambilight-region-map": { tag: "div" },
        "brightness-slider": { tag: "input", type: "range", value: "85", min: "10", max: "100" },
        "toggle-ambilight-btn": { tag: "button" },
        "toggle-ambilight-label": { tag: "span" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.bulbs = [
      { ip: "192.168.1.10", mac: "aa11", name: "Left Lamp", is_online: true, state: { is_on: true } },
      { ip: "192.168.1.11", mac: "aa12", name: "Right Lamp", is_online: true, state: { is_on: true } }
    ];
    appState.selectedIps = ["192.168.1.10", "192.168.1.11"];
    appState.ambilight = {
      active: false,
      monitor_index: 1,
      color_mode: "vibrant",
      auto_brightness: true,
      min_brightness: 10,
      brightness: 85,
      smoothing_alpha: 0.38,
      region_map: { "192.168.1.10": "left", "192.168.1.11": "right" },
      letterbox_crop: true
    };
  });

  afterEach(() => {
    if (appState.ambilightPollTimer) {
      clearInterval(appState.ambilightPollTimer);
      appState.ambilightPollTimer = null;
    }
    resetBridgeStateForTests();
  });

  test("renders per-bulb screen region selects and forwards regionMap + letterboxCrop", async () => {
    const calls = [];
    dom.window.pywebview = {
      api: {
        start_ambilight: async (...args) => {
          calls.push(args);
          return {
            ok: true,
            ambilight: Object.assign({}, appState.ambilight, { active: true, region_map: args[7], letterbox_crop: args[8] }),
            error: null
          };
        },
        stop_ambilight: async () => ({ ok: true, ambilight: { active: false }, error: null })
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindAmbilightEvents();
    renderAmbilightPanel();

    const selects = dom.getById("ambilight-region-map").querySelectorAll("select");
    assert.equal(selects.length, 2);
    assert.equal(selects[0].value, "left");
    assert.equal(selects[1].value, "right");

    dom.getById("ambilight-letterbox-crop").checked = false;
    dom.getById("toggle-ambilight-btn").click();
    await new Promise((r) => setTimeout(r, 0));

    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0][7], { "192.168.1.10": "left", "192.168.1.11": "right" });
    assert.equal(calls[0][8], false);
  });
});
