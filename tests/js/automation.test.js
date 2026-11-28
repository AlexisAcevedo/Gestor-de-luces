/*
 * Behavior tests for Circadian & Wake-Up Sunrise Ramp UI (PR 2B.1).
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
import { bindAutomationEvents, renderAutomationPanel } from "../../ui/js/automation.js";

describe("Automation UI: Circadian & Wake-Up Ramp (PR 2B.1)", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" },
        "automation-badge": { tag: "span" },
        "circadian-enabled": { tag: "input", type: "checkbox", checked: false },
        "circadian-sunrise": { tag: "input", type: "time", value: "07:00" },
        "circadian-sunset": { tag: "input", type: "time", value: "20:00" },
        "save-circadian-btn": { tag: "button" },
        "wakeup-enabled": { tag: "input", type: "checkbox", checked: false },
        "wakeup-time": { tag: "input", type: "time", value: "07:00" },
        "wakeup-duration": { tag: "input", type: "number", value: "20" },
        "save-wakeup-btn": { tag: "button" },
        "trigger-wakeup-btn": { tag: "button" },
        "cancel-wakeup-btn": { tag: "button", disabled: true },
        "session-off-on-lock": { tag: "input", type: "checkbox", checked: false },
        "session-restore-on-unlock": { tag: "input", type: "checkbox", checked: false },
        "session-off-on-sleep": { tag: "input", type: "checkbox", checked: false },
        "context-enabled": { tag: "input", type: "checkbox", checked: false },
        "on-air-enabled": { tag: "input", type: "checkbox", checked: false },
        "on-air-color": { tag: "input", type: "color", value: "#ff2a55" },
        "context-status-pill": { tag: "span" },
        "context-rule-process": { tag: "input", type: "text", value: "" },
        "context-rule-scene": { tag: "input", type: "number", value: "12" },
        "add-context-rule-btn": { tag: "button" },
        "context-rules-list": { tag: "div" },
        "local-api-enabled": { tag: "input", type: "checkbox", checked: false },
        "local-api-port": { tag: "input", type: "number", value: "18899" },
        "local-api-token": { tag: "input", type: "text", value: "" },
        "rotate-local-api-token-btn": { tag: "button" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.circadian = {
      enabled: false,
      sunrise_hour: 6.5,
      sunset_hour: 19.5,
      day_kelvin: 5600,
      night_kelvin: 2700,
      day_brightness: 95,
      night_brightness: 40,
      interval_seconds: 60
    };
    appState.wakeupRamp = {
      enabled: false,
      target_hour: 7,
      target_minute: 30,
      duration_minutes: 15,
      start_kelvin: 2200,
      end_kelvin: 5000,
      start_brightness: 10,
      end_brightness: 100,
      target_ips: []
    };
    appState.wakeupRampStatus = { active: false, progress: 0.0 };
    appState.sessionTriggers = { off_on_lock: true, restore_on_unlock: false, off_on_sleep: false };
    appState.contextAutomation = {
      enabled: false,
      poll_seconds: 5,
      on_air: { enabled: false, watch_mic: true, watch_camera: true, color_hex: "#ff2a55", brightness: 90, target_ips: [] },
      rules: []
    };
    appState.contextStatus = { supported: true, active_reason: null, on_air_active: false, foreground_process: null };
    appState.localApi = { enabled: false, port: 18899, token: "" };
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("hydrates circadian & wakeup inputs and invokes bridge automation endpoints", async () => {
    const calls = [];
    dom.window.pywebview = {
      api: {
        set_circadian_config: async (cfg) => {
          calls.push(["set_circadian_config", cfg]);
          return { ok: true, circadian: cfg, wakeup_ramp: appState.wakeupRamp, wakeup_ramp_status: appState.wakeupRampStatus, error: null };
        },
        set_wakeup_ramp_config: async (cfg) => {
          calls.push(["set_wakeup_ramp_config", cfg]);
          return { ok: true, circadian: appState.circadian, wakeup_ramp: cfg, wakeup_ramp_status: appState.wakeupRampStatus, error: null };
        },
        trigger_wakeup_ramp: async (ips) => {
          calls.push(["trigger_wakeup_ramp", ips]);
          return { ok: true, wakeup_ramp_status: { active: true, progress: 0.1 }, error: null };
        },
        cancel_wakeup_ramp: async () => {
          calls.push(["cancel_wakeup_ramp"]);
          return { ok: true, wakeup_ramp_status: { active: false, progress: 0.0 }, error: null };
        },
        set_session_triggers: async (cfg) => {
          calls.push(["set_session_triggers", cfg]);
          return { ok: true, session_triggers: cfg, error: null };
        },
        set_context_automation: async (cfg) => {
          calls.push(["set_context_automation", cfg]);
          return { ok: true, context_automation: cfg, error: null };
        },
        set_local_api_config: async (cfg) => {
          calls.push(["set_local_api_config", cfg]);
          return { ok: true, local_api: Object.assign({}, cfg, { token: "tok-1" }), error: null };
        },
        rotate_local_api_token: async () => {
          calls.push(["rotate_local_api_token"]);
          return { ok: true, local_api: { enabled: true, port: 18899, token: "tok-2" }, error: null };
        }
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindAutomationEvents();
    renderAutomationPanel();

    assert.equal(dom.getById("circadian-sunrise").value, "06:30");
    assert.equal(dom.getById("circadian-sunset").value, "19:30");
    assert.equal(dom.getById("wakeup-time").value, "07:30");
    assert.equal(dom.getById("wakeup-duration").value, "15");

    dom.getById("circadian-enabled").checked = true;
    dom.getById("save-circadian-btn").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[0][0], "set_circadian_config");
    assert.equal(calls[0][1].enabled, true);
    assert.equal(dom.getById("automation-badge").getAttribute("data-active"), "true");

    dom.getById("trigger-wakeup-btn").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[1][0], "trigger_wakeup_ramp");
    assert.equal(dom.getById("cancel-wakeup-btn").disabled, false);

    dom.getById("cancel-wakeup-btn").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[2][0], "cancel_wakeup_ramp");
    assert.equal(dom.getById("cancel-wakeup-btn").disabled, true);

    assert.equal(dom.getById("session-off-on-lock").checked, true);
    dom.getById("session-restore-on-unlock").checked = true;
    dom.getById("session-restore-on-unlock").dispatchEvent("change");
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[3][0], "set_session_triggers");
    assert.equal(calls[3][1].off_on_lock, true);
    assert.equal(calls[3][1].restore_on_unlock, true);

    dom.getById("on-air-enabled").checked = true;
    dom.getById("context-rule-process").value = "code.exe";
    dom.getById("context-rule-scene").value = "12";
    dom.getById("add-context-rule-btn").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[4][0], "set_context_automation");
    assert.equal(calls[4][1].rules[0].process_name, "code.exe");
    assert.equal(calls[4][1].rules[0].value, "12");

    dom.getById("local-api-enabled").checked = true;
    dom.getById("local-api-enabled").dispatchEvent("change");
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[5][0], "set_local_api_config");
    assert.equal(calls[5][1].enabled, true);

    dom.getById("rotate-local-api-token-btn").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[6][0], "rotate_local_api_token");
    assert.equal(dom.getById("local-api-token").value, "tok-2");
  });
});
