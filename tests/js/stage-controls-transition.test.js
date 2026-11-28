/*
 * Behavior tests for transition crossfade duration selector in Stage Controls (PR 3.1).
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
import { bindStageControlEvents, renderStageHeaderAndControls } from "../../ui/js/stage-controls.js";

describe("Stage Controls Crossfade Transition Selector (PR 3.1)", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" },
        "brightness-slider": { tag: "input", type: "range", min: "10", max: "100", value: "80" },
        "brightness-output": { tag: "output" },
        "transition-seconds-select": { tag: "select", value: "0" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    resetUiSyncCache();
    appState.transitionSeconds = 2;
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("hydrates transitionSeconds and forwards set_transition_seconds changes", async () => {
    const calls = [];
    dom.window.pywebview = {
      api: {
        set_transition_seconds: async (seconds) => {
          calls.push(seconds);
          return { ok: true, transition_seconds: seconds, error: null };
        }
      }
    };
    await resolveBackendApi();
    setEnvelopeHandler(applyBackendEnvelope);
    bindStageControlEvents();
    renderStageHeaderAndControls();

    const sel = dom.getById("transition-seconds-select");
    assert.equal(sel.value, "2");
    sel.value = "3.5";
    sel.dispatchEvent("change");
    await new Promise((r) => setTimeout(r, 0));

    assert.deepEqual(calls, [3.5]);
    assert.equal(appState.transitionSeconds, 3.5);
  });
});
