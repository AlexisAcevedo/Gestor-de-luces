/*
 * Behavior tests for Global Windows Hotkeys UI inside #shortcuts-dialog.
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
import { applyBackendEnvelope, bindEvents, resetUiSyncCache } from "../../ui/js/app.js";

function buildShortcutsDom() {
  const actions = [
    "toggle_power",
    "brightness_up",
    "brightness_down",
    "toggle_ambilight",
    "toggle_music_sync",
    "toggle_window"
  ];
  const elementsById = {
    "status-banner": { tag: "div" },
    "toast-region": { tag: "div" },
    "shortcuts-dialog": { tag: "dialog" },
    "shortcuts-help-btn": { tag: "button" },
    "global-hotkeys-enabled": { tag: "input", type: "checkbox" },
    "global-hotkeys-unsupported": { tag: "p" },
    "global-hotkeys-error": { tag: "p" },
    "save-global-hotkeys-btn": { tag: "button" },
    "reset-global-hotkeys-btn": { tag: "button" }
  };
  actions.forEach((action) => {
    elementsById[`hotkey-input-${action}`] = { tag: "input", type: "text" };
    elementsById[`hotkey-error-${action}`] = { tag: "span" };
  });

  const dom = createDomEnvironment({ elementsById });
  const dialog = dom.getById("shortcuts-dialog");
  actions.forEach((action) => {
    const clearBtn = dom.document.createElement("button");
    clearBtn.setAttribute("data-hotkey-clear", action);
    dialog.appendChild(clearBtn);
  });
  dom.install();
  return dom;
}

describe("Global Windows Hotkeys settings in #shortcuts-dialog", () => {
  let dom;

  beforeEach(() => {
    dom = buildShortcutsDom();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.globalHotkeys = {
      enabled: false,
      supported: false,
      bindings: {
        toggle_power: "Ctrl+Alt+P",
        brightness_up: "Ctrl+Alt+Up",
        brightness_down: "Ctrl+Alt+Down",
        toggle_ambilight: "Ctrl+Alt+A",
        toggle_music_sync: "Ctrl+Alt+M",
        toggle_window: "Ctrl+Alt+W"
      },
      errors: {}
    };
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("hydrates bindings, captures keystrokes, rejects duplicates, saves, and shows Win32 conflict", async () => {
    const savedCalls = [];
    dom.window.pywebview = {
      api: {
        set_global_hotkeys: async (enabled, bindings) => {
          savedCalls.push([enabled, bindings]);
          return {
            ok: true,
            global_hotkeys: { enabled, bindings },
            global_hotkeys_supported: true,
            global_hotkey_errors: { toggle_ambilight: "in_use" },
            error: null
          };
        }
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindEvents();

    applyBackendEnvelope(
      {
        ok: true,
        global_hotkeys: {
          enabled: false,
          bindings: {
            toggle_power: "Ctrl+Alt+P",
            brightness_up: "Ctrl+Alt+Up",
            brightness_down: "Ctrl+Alt+Down",
            toggle_ambilight: "Ctrl+Alt+A",
            toggle_music_sync: "Ctrl+Alt+M",
            toggle_window: "Ctrl+Alt+W"
          }
        },
        global_hotkeys_supported: true,
        global_hotkey_errors: {},
        error: null
      },
      null,
      null,
      true
    );

    const enabledBox = dom.getById("global-hotkeys-enabled");
    const powerInput = dom.getById("hotkey-input-toggle_power");
    const windowInput = dom.getById("hotkey-input-toggle_window");

    assert.equal(dom.getById("global-hotkeys-unsupported").hidden, true);
    assert.equal(powerInput.value, "Ctrl+Alt+P");

    // Captures Ctrl+Shift+L keystroke cleanly
    powerInput.dispatchEvent({ type: "keydown", key: "l", ctrlKey: true, shiftKey: true });
    assert.equal(powerInput.value, "Ctrl+Shift+L");

    // Duplicate check rejects saving without hitting IPC
    windowInput.value = "Ctrl+Shift+L";
    enabledBox.checked = true;
    dom.getById("save-global-hotkeys-btn").click();
    assert.equal(savedCalls.length, 0);
    assert.equal(windowInput.getAttribute("aria-invalid"), "true");
    assert.equal(dom.getById("global-hotkeys-error").hidden, false);

    // Clear window shortcut and save validly
    dom.document.querySelector('[data-hotkey-clear="toggle_window"]').click();
    assert.equal(windowInput.value, "");
    dom.getById("save-global-hotkeys-btn").click();
    await new Promise((r) => setTimeout(r, 0));

    assert.equal(savedCalls.length, 1);
    assert.equal(savedCalls[0][0], true);
    assert.equal(savedCalls[0][1].toggle_power, "Ctrl+Shift+L");
    assert.equal(savedCalls[0][1].toggle_window, "");
    assert.equal(dom.getById("hotkey-input-toggle_ambilight").getAttribute("aria-invalid"), "true");
    assert.equal(dom.getById("hotkey-error-toggle_ambilight").hidden, false);

    // Reset Defaults restores all 6 default bindings in form
    dom.getById("reset-global-hotkeys-btn").click();
    assert.equal(powerInput.value, "Ctrl+Alt+P");
    assert.equal(windowInput.value, "Ctrl+Alt+W");
  });
});
