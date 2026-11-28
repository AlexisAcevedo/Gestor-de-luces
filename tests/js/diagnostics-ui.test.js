/*
 * Behavior tests for fixture RSSI/FW diagnostics and adaptive RGB capability UI (PR 3.2).
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { createDomEnvironment } from "./dom-harness.js";
import { appState } from "../../ui/js/store.js";
import { resetBridgeStateForTests } from "../../ui/js/bridge-client.js";
import { renderFixtureList } from "../../ui/js/fixtures.js";
import { renderStageHeaderAndControls } from "../../ui/js/stage-controls.js";

describe("Bulb Diagnostics & Adaptive Capability UI (PR 3.2)", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "fixture-list": { tag: "div" },
        "zone-list": { tag: "div" },
        "drawer-title-badge": { tag: "span" },
        "tab-btn-rgb": { tag: "button" },
        "apply-rgb-btn": { tag: "button", disabled: false },
        "brightness-slider": { tag: "input", type: "range", min: "10", max: "100", value: "80" },
        "brightness-output": { tag: "output" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    appState.bulbs = [
      {
        ip: "192.168.1.50",
        mac: "a8bb50112233",
        name: "Hallway Tunable",
        module_name: "ESP03_SHTW1_01",
        is_online: true,
        rssi: -52,
        fw_version: "1.32.0",
        capabilities: {
          supports_rgb: false,
          supports_tunable_white: true,
          supports_dimming: true,
          min_kelvin: 2700,
          max_kelvin: 6500
        },
        state: { is_on: true, brightness: 80, mode: "temperature", temperature: 4000, color: null }
      }
    ];
    appState.selectedIps = ["192.168.1.50"];
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("renders RSSI & firmware version and gates RGB button for non-RGB targets", () => {
    renderFixtureList();
    renderStageHeaderAndControls();

    const listEl = dom.getById("fixture-list");
    const addrText = listEl.querySelectorAll("p").map((p) => p.textContent).join(" ");
    assert.ok(addrText.includes("-52 dBm"));
    assert.ok(addrText.includes("v1.32.0"));

    assert.equal(dom.getById("apply-rgb-btn").disabled, true);
    assert.equal(dom.getById("tab-btn-rgb").getAttribute("data-unsupported"), "true");
  });
});
