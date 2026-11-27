/*
 * Stage 1 regression tests: global [hidden] safeguard, flex scale presets, responsive
 * 480px breakpoints, selective .well-description visibility, HTML cleanup, and top-layer
 * popover toast management.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createDomEnvironment } from "./dom-harness.js";
import { showToast } from "../../ui/js/toasts.js";

const INDEX_HTML = readFileSync(new URL("../../ui/index.html", import.meta.url), "utf8");
const STYLES_CSS = readFileSync(new URL("../../ui/styles.css", import.meta.url), "utf8");

describe("Stage 1 static HTML & CSS invariants", () => {
  test("defines global [hidden] rule so flex containers respect HTML hidden", () => {
    assert.match(STYLES_CSS, /@layer utilities\s*\{[\s\S]*?\[hidden\]\s*\{\s*display:\s*none !important;\s*\}/);
  });

  test("uses flex layout for .slider-scale-anchored instead of absolute positioning", () => {
    const scaleRule = STYLES_CSS.match(/\.slider-scale-anchored\s*\{([^}]*)\}/);
    assert.ok(scaleRule, ".slider-scale-anchored rule missing");
    assert.match(scaleRule[1], /display:\s*flex/);
    assert.match(scaleRule[1], /flex-wrap:\s*wrap/);

    const btnRule = STYLES_CSS.match(/\.scale-preset-btn\s*\{([^}]*)\}/);
    assert.ok(btnRule, ".scale-preset-btn rule missing");
    assert.doesNotMatch(btnRule[1], /position:\s*absolute/);
    assert.doesNotMatch(STYLES_CSS, /\.scale-preset-btn\.pos-/);
  });

  test("promotes #toast-region to manual popover anchored at top-right", () => {
    assert.match(INDEX_HTML, /<div\b[^>]*id="toast-region"[^>]*popover="manual"/);
    const toastRule = STYLES_CSS.match(/\.toast-region\s*\{([^}]*)\}/);
    assert.ok(toastRule, ".toast-region rule missing");
    assert.match(toastRule[1], /inset:\s*56px 16px auto auto/);
    assert.doesNotMatch(toastRule[1], /bottom:\s*16px/);
    assert.match(STYLES_CSS, /\.toast-region:not\(\[popover\]\),\s*\.toast-region:popover-open\s*\{[\s\S]*?display:\s*flex/);
  });

  test("enables functional .well-description helpers and 480px stage responsive rules", () => {
    assert.match(STYLES_CSS, /\.floor-hint,[\s\S]*?\.custom-scenes-toolbar \.well-description,[\s\S]*?details\.sleep-timer-well\[open\] \.well-description\s*\{[\s\S]*?display:\s*block/);
    assert.match(STYLES_CSS, /@container stage \(max-width:\s*480px\)\s*\{\s*\.mode-tabs\s*\{\s*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
    assert.match(STYLES_CSS, /@container stage \(max-width:\s*480px\)\s*\{[\s\S]*?\.stage-header\s*\{\s*flex-wrap:\s*wrap/);
  });

  test("cleans up .ambilight-toggle-row and duplicate data-i18n-aria attribute", () => {
    assert.doesNotMatch(INDEX_HTML, /ambilight-Toggle-row/);
    assert.doesNotMatch(STYLES_CSS, /\.ambilight-Toggle-row/);
    assert.match(INDEX_HTML, /class="ambilight-toggle-row"/);
    assert.match(STYLES_CSS, /\.ambilight-toggle-row\s*\{/);
    assert.doesNotMatch(INDEX_HTML, /data-i18n-aria="/);
  });
});

describe("Stage 1 top-layer toast popover lifecycle", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "toast-region": { tag: "div", attrs: { popover: "manual" } }
      }
    });
    dom.install();
  });

  afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.Event;
    delete globalThis.HTMLDialogElement;
    delete globalThis.requestAnimationFrame;
  });

  test("calls showPopover on showToast, re-promotes when already open, and hides when last toast dismisses", () => {
    const region = dom.getById("toast-region");
    const calls = [];
    let isOpen = false;
    region.matches = (selector) => selector === ":popover-open" && isOpen;
    region.showPopover = () => {
      calls.push("show");
      isOpen = true;
    };
    region.hidePopover = () => {
      calls.push("hide");
      isOpen = false;
    };

    showToast({ kind: "error", message: "First failure" });
    assert.deepEqual(calls, ["show"]);
    assert.equal(region.children.length, 1);

    showToast({ kind: "error", message: "Second failure" });
    assert.deepEqual(calls, ["show", "hide", "show"]);
    assert.equal(region.children.length, 2);

    const closeButtons = region.querySelectorAll(".toast-close");
    closeButtons[0].click();
    assert.equal(region.children.length, 1);
    assert.deepEqual(calls, ["show", "hide", "show"]);

    closeButtons[1].click();
    assert.equal(region.children.length, 0);
    assert.deepEqual(calls, ["show", "hide", "show", "hide"]);
  });

  test("auto-dismissing an ok toast closes the popover", (ctx) => {
    ctx.mock.timers.enable({ apis: ["setTimeout"] });
    const region = dom.getById("toast-region");
    const calls = [];
    let isOpen = false;
    region.matches = (selector) => selector === ":popover-open" && isOpen;
    region.showPopover = () => {
      calls.push("show");
      isOpen = true;
    };
    region.hidePopover = () => {
      calls.push("hide");
      isOpen = false;
    };

    showToast({ kind: "ok", message: "Saved" });
    assert.deepEqual(calls, ["show"]);
    assert.equal(region.children.length, 1);

    ctx.mock.timers.tick(2300);
    assert.equal(region.children.length, 0);
    assert.deepEqual(calls, ["show", "hide"]);
  });

  test("handles environments without Popover API cleanly", () => {
    const region = dom.getById("toast-region");
    assert.doesNotThrow(() => {
      showToast({ kind: "error", message: "No popover API" });
      region.querySelector(".toast-close").click();
    });
    assert.equal(region.children.length, 0);
  });
});
