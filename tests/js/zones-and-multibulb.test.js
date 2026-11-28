/*
 * Behavior tests for Zones UI strip/dialog and multi-bulb custom scene capture/badges.
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
import { bindFixtureEvents, renderZonesStrip } from "../../ui/js/fixtures.js";
import { bindSceneEvents, openCustomSceneDialog, renderCustomScenesGrid } from "../../ui/js/scenes.js";

function buildZonesDom() {
  const dom = createDomEnvironment({
    elementsById: {
      "status-banner": { tag: "div" },
      "toast-region": { tag: "div" },
      "zone-list": { tag: "div" },
      "open-add-zone-btn": { tag: "button" },
      "zone-dialog": { tag: "dialog" },
      "zone-form": { tag: "form" },
      "zone-dialog-title": { tag: "h2" },
      "zone-id-input": { tag: "input", type: "hidden" },
      "zone-name-input": { tag: "input", type: "text" },
      "zone-bulbs-list": { tag: "div" },
      "zone-dialog-error": { tag: "p" },
      "zone-submit-btn": { tag: "button" },
      "custom-scenes-grid": { tag: "div" },
      "custom-tab-label": { tag: "span" },
      "custom-scene-dialog": { tag: "dialog" },
      "custom-scene-form": { tag: "form" },
      "custom-scene-dialog-title": { tag: "h2" },
      "custom-scene-dialog-subtitle": { tag: "p" },
      "custom-scene-id-input": { tag: "input", type: "hidden" },
      "custom-scene-name-input": { tag: "input", type: "text" },
      "custom-scene-overwrite-row": { tag: "div" },
      "custom-scene-overwrite-checkbox": { tag: "input", type: "checkbox" },
      "custom-scene-multibulb-row": { tag: "div" },
      "custom-scene-multibulb-input": { tag: "input", type: "checkbox" },
      "custom-scene-error": { tag: "p" },
      "custom-scene-submit-btn": { tag: "button" }
    }
  });
  dom.install();
  return dom;
}

describe("Zones UI and Multi-Bulb Custom Scenes (PR 2A.2)", () => {
  let dom;

  beforeEach(() => {
    dom = buildZonesDom();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.bulbs = [
      { ip: "192.168.1.10", mac: "aa11", name: "Left Lamp", is_online: true, state: { is_on: true, mode: "rgb", brightness: 80, color: { r: 255, g: 0, b: 0 } } },
      { ip: "192.168.1.11", mac: "aa12", name: "Right Lamp", is_online: true, state: { is_on: true, mode: "temperature", brightness: 50, temperature: 2700 } }
    ];
    appState.selectedIps = ["192.168.1.10", "192.168.1.11"];
    appState.zones = [];
    appState.customScenes = [];
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("renders zones strip, validates empty bulbs, creates/selects/deletes zones, and captures multi-bulb scenes", async () => {
    const calls = [];
    const zoneObj = { id: "z1", name: "Studio", bulb_ips: ["192.168.1.10", "192.168.1.11"], icon: "room" };
    const multiPreset = {
      id: "p1",
      name: "Dual Mood",
      mode: "rgb",
      brightness: 80,
      color: { r: 255, g: 0, b: 0, hex: "#ff0000" },
      temperature: null,
      built_in_scene_id: null,
      speed: 100,
      is_favorite: false,
      bulb_states: {
        "192.168.1.10": { is_on: true, mode: "rgb", brightness: 80, color: { r: 255, g: 0, b: 0 }, temperature: null, built_in_scene_id: null, speed: 100 },
        "192.168.1.11": { is_on: true, mode: "temperature", brightness: 50, color: null, temperature: 2700, built_in_scene_id: null, speed: 100 }
      }
    };

    dom.window.pywebview = {
      api: {
        save_zone: async (name, ips, id, icon) => {
          calls.push(["save_zone", name, ips, id, icon]);
          return { ok: true, zones: [zoneObj], bulbs: appState.bulbs, selected_ips: appState.selectedIps, error: null };
        },
        select_zone: async (zoneId) => {
          calls.push(["select_zone", zoneId]);
          return { ok: true, zones: [zoneObj], selected_ips: ["192.168.1.10", "192.168.1.11"], error: null };
        },
        delete_zone: async (zoneId) => {
          calls.push(["delete_zone", zoneId]);
          return { ok: true, zones: [], error: null };
        },
        save_custom_scene: async (name, sourceIp, captureAll) => {
          calls.push(["save_custom_scene", name, sourceIp, captureAll]);
          return { ok: true, custom_scenes: [multiPreset], error: null };
        }
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindFixtureEvents();
    bindSceneEvents({ activateTab: () => {} });

    renderZonesStrip();
    assert.equal(dom.getById("zone-list").children[0].className, "zone-empty");

    // Open zone dialog, uncheck all bulbs -> inline error
    dom.getById("open-add-zone-btn").click();
    assert.equal(dom.getById("zone-dialog").open, true);
    dom.getById("zone-name-input").value = "Studio";
    dom.getById("zone-bulbs-list").querySelectorAll("input").forEach((cb) => { cb.checked = false; });
    dom.getById("zone-form").dispatchEvent({ type: "submit" });
    assert.equal(dom.getById("zone-dialog-error").hidden, false);
    assert.equal(calls.length, 0);

    // Check both bulbs and submit
    dom.getById("zone-bulbs-list").querySelectorAll("input").forEach((cb) => { cb.checked = true; });
    dom.getById("zone-form").dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[0][0], "save_zone");
    assert.deepEqual(calls[0][2], ["192.168.1.10", "192.168.1.11"]);
    assert.equal(dom.getById("zone-dialog").open, false);

    // Selecting and deleting zone via strip
    dom.getById("zone-list").querySelector(".zone-chip-trigger").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(calls[1], ["select_zone", "z1"]);

    // Multi-bulb capture checkbox visible when >= 2 targets and renders badge
    openCustomSceneDialog(null);
    assert.equal(dom.getById("custom-scene-multibulb-row").hidden, false);
    dom.getById("custom-scene-name-input").value = "Dual Mood";
    dom.getById("custom-scene-multibulb-input").checked = true;
    dom.getById("custom-scene-form").dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(calls[2], ["save_custom_scene", "Dual Mood", "192.168.1.10", true]);

    renderCustomScenesGrid();
    assert.ok(dom.getById("custom-scenes-grid").querySelector(".custom-scene-multibulb-badge"));

    const delButtons = dom.getById("zone-list").querySelectorAll(".zone-chip-action");
    delButtons[1].click();
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(calls[3], ["delete_zone", "z1"]);
  });
});
