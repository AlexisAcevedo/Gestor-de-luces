/*
 * Tests for ui/js/theme-boot.js (synchronous pre-CSS theme bootstrap).
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BOOT_SCRIPT_PATH = path.resolve(__dirname, "../../ui/js/theme-boot.js");
const BOOT_SCRIPT_SOURCE = fs.readFileSync(BOOT_SCRIPT_PATH, "utf8");

function runBootScript({ hash = "", storage = undefined, includeColorSchemeMeta = true } = {}) {
  const metaAttrs = { name: "color-scheme", content: "light dark" };
  const colorSchemeMeta = includeColorSchemeMeta
    ? {
        setAttribute(name, value) {
          metaAttrs[name] = String(value);
        },
        getAttribute(name) {
          return metaAttrs[name] ?? null;
        }
      }
    : null;

  const documentElement = {
    dataset: { theme: "architectural-stone" },
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }
  };

  const windowObj = {
    location: { hash },
    localStorage: storage
  };

  const documentObj = {
    documentElement,
    querySelector(selector) {
      if (selector === 'meta[name="color-scheme"]') {
        return colorSchemeMeta;
      }
      return null;
    }
  };

  const context = vm.createContext({
    window: windowObj,
    document: documentObj,
    URLSearchParams
  });

  vm.runInContext(BOOT_SCRIPT_SOURCE, context, { filename: "theme-boot.js" });
  return {
    theme: documentElement.dataset.theme,
    colorScheme: colorSchemeMeta ? colorSchemeMeta.getAttribute("content") : null
  };
}

function createStorage(prefsObj) {
  const data = new Map();
  if (prefsObj !== undefined) {
    data.set("gestor_luces_ui_prefs", typeof prefsObj === "string" ? prefsObj : JSON.stringify(prefsObj));
  }
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    }
  };
}

describe("theme-boot.js", () => {
  test("applies atmospheric-dark from URL hash before paint even when storage is empty or light", () => {
    const emptyStorageResult = runBootScript({
      hash: "#theme=atmospheric-dark",
      storage: createStorage()
    });
    assert.equal(emptyStorageResult.theme, "atmospheric-dark");
    assert.equal(emptyStorageResult.colorScheme, "dark");

    const overridingLightStorage = runBootScript({
      hash: "#theme=%20Atmospheric-Dark%20",
      storage: createStorage({ theme: "architectural-stone" })
    });
    assert.equal(overridingLightStorage.theme, "atmospheric-dark");
    assert.equal(overridingLightStorage.colorScheme, "dark");
  });

  test("applies architectural-stone from URL hash and sets light color-scheme", () => {
    const res = runBootScript({
      hash: "#theme=architectural-stone",
      storage: createStorage({ theme: "atmospheric-dark" })
    });
    assert.equal(res.theme, "architectural-stone");
    assert.equal(res.colorScheme, "light");
  });

  test("falls back to localStorage when URL hash has no theme", () => {
    const res = runBootScript({
      hash: "",
      storage: createStorage({ theme: "atmospheric-dark" })
    });
    assert.equal(res.theme, "atmospheric-dark");
    assert.equal(res.colorScheme, "dark");
  });

  test("falls back from invalid hash to localStorage, then to default theme", () => {
    const fromStorage = runBootScript({
      hash: "#theme=neon-pink",
      storage: createStorage({ theme: "atmospheric-dark" })
    });
    assert.equal(fromStorage.theme, "atmospheric-dark");
    assert.equal(fromStorage.colorScheme, "dark");

    const fromDefault = runBootScript({
      hash: "#theme=neon-pink",
      storage: createStorage("{bad json")
    });
    assert.equal(fromDefault.theme, "architectural-stone");
    assert.equal(fromDefault.colorScheme, "light");
  });

  test("degrades gracefully when localStorage throws or color-scheme meta is missing", () => {
    const throwingStorage = {
      getItem() {
        throw new Error("SecurityError");
      }
    };

    const withHash = runBootScript({
      hash: "#theme=atmospheric-dark",
      storage: throwingStorage,
      includeColorSchemeMeta: false
    });
    assert.equal(withHash.theme, "atmospheric-dark");
    assert.equal(withHash.colorScheme, null);

    const withoutHash = runBootScript({
      hash: "",
      storage: throwingStorage
    });
    assert.equal(withoutHash.theme, "architectural-stone");
    assert.equal(withoutHash.colorScheme, "light");
  });
});
