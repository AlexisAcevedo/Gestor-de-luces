/*
 * Stage 2 regression tests: modal validation & close-after-success, Undo toast action,
 * zero-fixture / zero-selection empty states, slider pointer-release sync, Sleep Timer
 * collapse respect, UDP button busy state, and active stream header ownership.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { createDomEnvironment } from "./dom-harness.js";
import {
  appState,
  bindSliderInteraction,
  isSliderProtected,
  isValidIpv4,
  withButtonBusy
} from "../../ui/js/store.js";
import { invokeApi, resetBridgeStateForTests, resolveBackendApi } from "../../ui/js/bridge-client.js";
import { applyBackendEnvelope, resetUiSyncCache } from "../../ui/js/app.js";
import {
  bindFixtureEvents,
  flushPendingBulbDelete,
  renderFixtureList,
  renderSleepTimer,
  resetFixtureUiStateForTests
} from "../../ui/js/fixtures.js";
import { bindSceneEvents, resetPendingPresetDeleteForTests } from "../../ui/js/scenes.js";
import { renderStageHeaderAndControls } from "../../ui/js/stage-controls.js";
import { renderAmbilightPanel } from "../../ui/js/ambilight.js";
import { showToast } from "../../ui/js/toasts.js";

function makeBaseDom() {
  return createDomEnvironment({
    elementsById: {
      "status-banner": { tag: "p" },
      "toast-region": { tag: "div", attrs: { popover: "manual" } },
      "console-shell": { tag: "div" },
      "target-summary": { tag: "p" },
      "live-state-pill": { tag: "span" },
      "telemetry-meta": { tag: "span" },
      "master-power-btn": { tag: "button" },
      "master-power-label": { tag: "span" },
      "quick-save-preset-btn": { tag: "button" },
      "photometric-aperture": { tag: "div" },
      "drawer-pill-label": { tag: "span" },
      "drawer-pill-dot": { tag: "span" },
      "brightness-slider": { tag: "input", min: 10, max: 100, value: 85 },
      "brightness-output": { tag: "output" },
      "kelvin-slider": { tag: "input", min: 2200, max: 6500, value: 4200 },
      "kelvin-output": { tag: "output" },
      "scene-speed-container": { tag: "div" },
      "scene-speed-slider": { tag: "input", min: 10, max: 200, value: 100 },
      "scene-speed-output": { tag: "output" },
      "stage-empty-banner": { tag: "section" },
      "stage-empty-message": { tag: "p" },
      "stage-empty-scan-btn": { tag: "button" },
      "stage-empty-add-btn": { tag: "button" },
      "stage-empty-select-all-btn": { tag: "button" },
      "add-bulb-dialog": { tag: "dialog" },
      "add-bulb-form": { tag: "form" },
      "manual-ip-input": { tag: "input", value: "" },
      "manual-name-input": { tag: "input", value: "" },
      "add-bulb-error": { tag: "p" },
      "submit-add-bulb-btn": { tag: "button" },
      "rename-bulb-dialog": { tag: "dialog" },
      "rename-bulb-form": { tag: "form" },
      "rename-bulb-ip-input": { tag: "input", value: "192.168.0.10" },
      "rename-bulb-name-input": { tag: "input", value: "Kitchen" },
      "rename-bulb-error": { tag: "p" },
      "custom-scene-dialog": { tag: "dialog" },
      "custom-scene-form": { tag: "form" },
      "custom-scene-id-input": { tag: "input", value: "" },
      "custom-scene-name-input": { tag: "input", value: "Night" },
      "custom-scene-error": { tag: "p" },
      "custom-scene-overwrite-checkbox": { tag: "input", checked: false },
      "custom-scene-submit-btn": { tag: "button" },
      "sleep-timer-details": { tag: "details" },
      "sleep-timer-badge": { tag: "span" },
      "cancel-sleep-timer-btn": { tag: "button" },
      "ambilight-preview-swatch": { tag: "div" },
      "ambilight-color-readout": { tag: "p" },
      "fixture-list": { tag: "div" }
    }
  });
}

describe("Stage 2 UX flows & validation", () => {
  let dom;

  beforeEach(async () => {
    resetBridgeStateForTests();
    resetUiSyncCache();
    resetFixtureUiStateForTests();
    resetPendingPresetDeleteForTests();
    dom = makeBaseDom();
    dom.install();
    appState.bulbs = [
      {
        ip: "192.168.0.10",
        mac: "aa:bb",
        name: "Desk",
        module_name: "ESP01",
        is_online: true,
        state: { is_on: true, brightness: 85, mode: "temperature", temperature: 4200, color: null, scene_id: null, speed: 100 }
      }
    ];
    appState.selectedIps = ["192.168.0.10"];
    appState.ambilight = { active: false, last_color: { r: 20, g: 120, b: 220 } };
    appState.musicSync = { active: false, last_color: null };
    appState.sleepTimer = { active: false, remaining_seconds: 0, total_seconds: 0 };
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

  test("isValidIpv4 validates 4 decimal octets strictly", () => {
    assert.equal(isValidIpv4("192.168.1.45"), true);
    assert.equal(isValidIpv4(" 0.0.0.0 "), true);
    assert.equal(isValidIpv4("255.255.255.255"), true);
    assert.equal(isValidIpv4("256.1.1.1"), false);
    assert.equal(isValidIpv4("192.168.1"), false);
    assert.equal(isValidIpv4("192.168.1.1.1"), false);
    assert.equal(isValidIpv4("abc.def.0.1"), false);
  });

  test("add-bulb-form validates IPv4, keeps input open on backend failure, and closes on ok", async () => {
    let shouldFail = true;
    const apiCalls = [];
    dom.window.pywebview = {
      api: {
        add_manual_bulb: async (ip, name) => {
          apiCalls.push([ip, name]);
          if (shouldFail) return { ok: false, error: "unreachable" };
          return { ok: true, bulbs: appState.bulbs, selected_ips: appState.selectedIps };
        }
      }
    };
    await resolveBackendApi();
    bindFixtureEvents();

    const dialog = dom.getById("add-bulb-dialog");
    const ipInput = dom.getById("manual-ip-input");
    const nameInput = dom.getById("manual-name-input");
    const errEl = dom.getById("add-bulb-error");
    const form = dom.getById("add-bulb-form");

    ipInput.value = "999.1.1.1";
    nameInput.value = "Hall";
    form.dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(apiCalls.length, 0);
    assert.equal(dialog.closeCount, 0);
    assert.equal(ipInput.getAttribute("aria-invalid"), "true");
    assert.equal(errEl.hidden, false);

    ipInput.value = "192.168.1.50";
    form.dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(apiCalls.length, 1);
    assert.equal(dialog.closeCount, 0);
    assert.equal(ipInput.value, "192.168.1.50");
    assert.equal(nameInput.value, "Hall");
    assert.equal(errEl.hidden, false);

    shouldFail = false;
    form.dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(dialog.closeCount, 1);
    assert.equal(ipInput.value, "");
    assert.equal(nameInput.value, "");
    assert.equal(errEl.hidden, true);
  });

  test("rename-bulb-form and custom-scene-form keep dialog open when backend returns ok:false", async () => {
    let okResult = false;
    dom.window.pywebview = {
      api: {
        rename_bulb: async () => ({ ok: okResult, error: okResult ? null : "fail" }),
        save_custom_scene: async () => ({ ok: okResult, error: okResult ? null : "fail" })
      }
    };
    await resolveBackendApi();
    bindFixtureEvents();
    bindSceneEvents({ activateTab: () => {} });

    const renameDialog = dom.getById("rename-bulb-dialog");
    dom.getById("rename-bulb-form").dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(renameDialog.closeCount, 0);
    assert.equal(dom.getById("rename-bulb-error").hidden, false);

    const customDialog = dom.getById("custom-scene-dialog");
    dom.getById("custom-scene-form").dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(customDialog.closeCount, 0);
    assert.equal(dom.getById("custom-scene-error").hidden, false);

    okResult = true;
    dom.getById("rename-bulb-form").dispatchEvent({ type: "submit" });
    dom.getById("custom-scene-form").dispatchEvent({ type: "submit" });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(renameDialog.closeCount, 1);
    assert.equal(customDialog.closeCount, 1);
  });

  test("showToast action button invokes onAction without calling onDismiss", (ctx) => {
    ctx.mock.timers.enable({ apis: ["setTimeout"] });
    let actions = 0;
    let dismisses = 0;

    showToast({
      kind: "ok",
      message: "Deleted",
      actionLabel: "Undo",
      durationMs: 5000,
      onAction: () => { actions += 1; },
      onDismiss: () => { dismisses += 1; }
    });
    const btn = dom.getById("toast-region").querySelector(".toast-action");
    assert.ok(btn);
    btn.click();
    ctx.mock.timers.tick(5500);
    assert.equal(actions, 1);
    assert.equal(dismisses, 0);

    showToast({
      kind: "ok",
      message: "Auto-expire",
      actionLabel: "Undo",
      durationMs: 5000,
      onAction: () => { actions += 1; },
      onDismiss: () => { dismisses += 1; }
    });
    ctx.mock.timers.tick(5100);
    assert.equal(actions, 1);
    assert.equal(dismisses, 1);
  });

  test("handles zero-bulbs and zero-selected states honestly on stage", () => {
    const briPreset = dom.seedElement("bri-50", { tag: "button", className: "brightness-preset", dataset: { brightness: "50" } });

    appState.selectedIps = [];
    renderStageHeaderAndControls();
    assert.equal(dom.getById("console-shell").getAttribute("data-has-targets"), "false");
    assert.equal(dom.getById("stage-empty-banner").hidden, false);
    assert.equal(dom.getById("stage-empty-select-all-btn").hidden, false);
    assert.equal(dom.getById("stage-empty-scan-btn").hidden, true);
    assert.equal(dom.getById("target-summary").textContent, "T(stage.noneSelected)");
    assert.equal(dom.getById("master-power-btn").disabled, true);
    assert.equal(dom.getById("brightness-slider").disabled, true);
    assert.equal(briPreset.disabled, true);

    appState.bulbs = [];
    renderStageHeaderAndControls();
    assert.equal(dom.getById("stage-empty-scan-btn").hidden, false);
    assert.equal(dom.getById("stage-empty-select-all-btn").hidden, true);
    assert.equal(dom.getById("target-summary").textContent, "T(stage.noFixture)");
  });

  test("isSliderProtected allows updates after pointerup even when focused", () => {
    const slider = dom.getById("brightness-slider");
    bindSliderInteraction(slider);

    slider.focus();
    assert.equal(isSliderProtected(slider), true);

    slider.dispatchEvent({ type: "pointerdown" });
    assert.equal(isSliderProtected(slider), true);

    slider.dispatchEvent({ type: "pointerup" });
    assert.equal(isSliderProtected(slider), false);

    slider.dispatchEvent({ type: "keydown" });
    assert.equal(isSliderProtected(slider), true);

    dom.document.activeElement = null;
    slider.dispatchEvent({ type: "blur" });
    assert.equal(isSliderProtected(slider), false);
  });

  test("renderSleepTimer respects manual collapse while timer remains active", () => {
    const details = dom.getById("sleep-timer-details");
    assert.equal(details.open, false);

    appState.sleepTimer = { active: true, remaining_seconds: 120, total_seconds: 120 };
    renderSleepTimer();
    assert.equal(details.open, true);

    details.open = false;
    appState.sleepTimer = { active: true, remaining_seconds: 119, total_seconds: 120 };
    renderSleepTimer();
    assert.equal(details.open, false);

    appState.sleepTimer = { active: false, remaining_seconds: 0, total_seconds: 0 };
    renderSleepTimer();
    appState.sleepTimer = { active: true, remaining_seconds: 60, total_seconds: 60 };
    renderSleepTimer();
    assert.equal(details.open, true);
  });

  test("withButtonBusy prevents concurrent clicks and restores disabled state", async () => {
    const btn = dom.getById("master-power-btn");
    let runs = 0;
    let release;
    const p1 = withButtonBusy(btn, () => new Promise((r) => {
      runs += 1;
      release = r;
    }));
    assert.equal(btn.disabled, true);
    assert.equal(btn.getAttribute("aria-busy"), "true");

    const p2 = await withButtonBusy(btn, async () => { runs += 1; });
    assert.equal(p2, false);
    assert.equal(runs, 1);

    release(true);
    await p1;
    assert.equal(btn.disabled, false);
    assert.equal(btn.getAttribute("aria-busy"), null);
  });

  test("shows active stream in #live-state-pill and skips --beam-color mutation when power is off", async () => {
    appState.ambilight = { active: true, monitor_index: 1, color_mode: "vibrant", last_color: { r: 10, g: 200, b: 150 }, frames_sent: 5 };
    renderStageHeaderAndControls();
    assert.equal(dom.getById("live-state-pill").textContent, "T(stage.stateStreamingAmbi)");
    assert.equal(dom.document.documentElement.style.getPropertyValue("--beam-color"), "rgb(10, 200, 150)");

    dom.getById("console-shell").setAttribute("data-power", "off");
    dom.document.documentElement.style.setProperty("--beam-color", "var(--beam-standby)");
    renderAmbilightPanel();
    assert.equal(dom.document.documentElement.style.getPropertyValue("--beam-color"), "var(--beam-standby)");

    dom.window.pywebview = { api: { test_fail: async () => ({ ok: false, error: "bad" }) } };
    await resolveBackendApi();
    const res = await invokeApi(() => dom.window.pywebview.api.test_fail(), null, { silent: true });
    assert.equal(res, false);
    applyBackendEnvelope({ ok: true, ambilight: { active: false, last_color: null, frames_sent: 5 }, error: null }, null, null, true);
    assert.notEqual(dom.getById("live-state-pill").textContent, "T(stage.stateStreamingAmbi)");
  });

  test("fixture remove button sits outside label, supports 5s Undo, and commits via flush", async () => {
    const removedCalls = [];
    dom.window.pywebview = {
      api: {
        remove_bulb: async (ip) => {
          removedCalls.push(ip);
          return { ok: true, bulbs: [], selected_ips: [], error: null };
        }
      }
    };
    await resolveBackendApi();

    const listEl = dom.getById("fixture-list");
    renderFixtureList();

    const removeBtn = listEl.querySelectorAll(".btn-icon-remove")[0];
    assert.ok(removeBtn);
    assert.equal(removeBtn.parentNode.className, "fixture-card-top-actions");

    // Click remove -> hides bulb optimistically and shows Undo toast.
    removeBtn.click();
    assert.equal(listEl.querySelectorAll(".fixture-card").length, 0);
    const undoBtn = dom.getById("toast-region").querySelectorAll(".toast-action")[0];
    assert.ok(undoBtn);
    assert.equal(removedCalls.length, 0);

    // Undo restores card without calling backend.
    undoBtn.click();
    assert.equal(listEl.querySelectorAll(".fixture-card").length, 1);
    assert.equal(removedCalls.length, 0);

    // Second click + flush commits remove_bulb(ip).
    listEl.querySelectorAll(".btn-icon-remove")[0].click();
    flushPendingBulbDelete();
    assert.deepEqual(removedCalls, ["192.168.0.10"]);
  });

  test("ok toast pauses dismissal on focusin and resumes on focusout", async () => {
    let dismissed = false;
    showToast({
      kind: "ok",
      message: "Saved",
      actionLabel: "Undo",
      durationMs: 260,
      onAction: () => {},
      onDismiss: () => { dismissed = true; }
    });
    const toast = dom.getById("toast-region").querySelectorAll(".toast")[0];
    const actionBtn = toast.querySelectorAll(".toast-action")[0];
    toast.dispatchEvent({ type: "focusin", target: actionBtn });
    await new Promise((r) => setTimeout(r, 320));
    assert.equal(dismissed, false);
    assert.equal(dom.getById("toast-region").children.length, 1);

    toast.dispatchEvent({ type: "focusout", target: actionBtn, relatedTarget: dom.getById("console-shell") });
    await new Promise((r) => setTimeout(r, 340));
    assert.equal(dismissed, true);
    assert.equal(dom.getById("toast-region").children.length, 0);
  });
});
