/*
 * Stage 5 regression tests: zero-flash initial language boot in i18n.js and
 * localStorage language persistence from syncLanguageUi().
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

import { createDomEnvironment } from "./dom-harness.js";
import { resetUiSyncCache, syncLanguageUi } from "../../ui/js/app.js";
import { appState } from "../../ui/js/store.js";

const I18N_SOURCE = readFileSync(new URL("../../ui/i18n.js", import.meta.url), "utf8");

describe("Stage 5 zero-flash i18n bootstrap & language persistence", () => {
  test("i18n.js translates DOM synchronously when documentElement.dataset.lang is es", () => {
    const heading = {
      attrs: { "data-i18n": "kelvin.title" },
      textContent: "Color Temperature",
      getAttribute(name) {
        return this.attrs[name] ?? null;
      },
      setAttribute(name, val) {
        this.attrs[name] = String(val);
      }
    };

    const sandboxDoc = {
      title: "",
      documentElement: { lang: "es", dataset: { lang: "es" } },
      querySelectorAll(selector) {
        return selector === "[data-i18n]" ? [heading] : [];
      }
    };
    const sandboxWindow = {};
    vm.runInNewContext(I18N_SOURCE, { window: sandboxWindow, document: sandboxDoc });

    assert.equal(sandboxWindow.I18N.getLanguage(), "es");
    assert.equal(heading.textContent, "Temperatura de Color");
    assert.equal(sandboxDoc.title, "Consola de Iluminación Arquitectónica WiZ");
  });

  test("syncLanguageUi updates dataset.lang and persists language preference once", () => {
    resetUiSyncCache();
    appState.language = "en";
    const dom = createDomEnvironment({
      elementsById: {
        "lang-btn-en": { tag: "button", className: "lang-btn", attrs: { "data-lang": "en" } },
        "lang-btn-es": { tag: "button", className: "lang-btn", attrs: { "data-lang": "es" } }
      }
    });
    dom.install();

    try {
      const changed = syncLanguageUi("es");
      assert.equal(changed, true);
      assert.equal(dom.document.documentElement.dataset.lang, "es");
      const savedPrefs = JSON.parse(dom.storage.getItem("wiz_console_ui_prefs"));
      assert.equal(savedPrefs.language, "es");

      const callsBeforeRepeat = dom.storage.setCalls.length;
      assert.equal(syncLanguageUi("es"), false);
      assert.equal(dom.storage.setCalls.length, callsBeforeRepeat);
    } finally {
      resetUiSyncCache();
      appState.language = "en";
    }
  });
});
