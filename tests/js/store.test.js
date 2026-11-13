/*
 * Behaviour tests for ui/js/store.js: the shared app state, the persisted
 * preferences/favourites, the theme/i18n helpers and the photometric utilities.
 *
 * These tests only use the module's public surface (its exports) and the browser
 * globals it is allowed to talk to (`window`, `window.localStorage`, `window.I18N`,
 * `document`, `fetch`), which the harness installs as in-memory fakes.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import * as store from "../../ui/js/store.js";

const { appState } = store;

/* ------------------------------------------------------------------ helpers */

function createMemoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    }
  };
}

/* Traductor falso: deja ver la clave y las variables pedidas en el texto final. */
function createFakeI18n() {
  const calls = [];
  return {
    calls,
    t(key, vars) {
      calls.push({ key, vars });
      if (!vars) return `T(${key})`;
      const rendered = Object.entries(vars)
        .map(([name, value]) => `${name}=${value}`)
        .join(",");
      return `T(${key}|${rendered})`;
    }
  };
}

function createRangeInput({ id, min, max, value }) {
  return {
    id,
    min,
    max,
    value,
    style: {
      props: {},
      setProperty(name, val) {
        this.props[name] = String(val);
      }
    },
    classList: { toggled: [] }
  };
}

const ORIGINAL_DATE_NOW = Date.now;

function resetAppState() {
  appState.language = "en";
  appState.theme = store.DEFAULT_THEME;
  appState.bulbs = [];
  appState.selectedIps = [];
  appState.scenes = [];
  appState.favoriteSceneIds = [];
  appState.customScenes = [];
  appState.sleepTimer = {
    active: false,
    remaining_seconds: 0,
    total_seconds: 0,
    target_ips: []
  };
  appState.activeTab = "temperature";
  appState.sceneCategory = "all";
  appState.autoSyncTimer = null;
  appState.sleepPollTimer = null;
  appState.ambilightPollTimer = null;
  appState.musicPollTimer = null;
  appState.isDraggingWheel = false;
  appState.lastWheelSendMs = 0;
  appState.wheelThrottleTimer = null;
}

function installGlobals({ i18n, storage } = {}) {
  globalThis.window = {
    localStorage: storage || createMemoryStorage(),
    I18N: i18n
  };
}

beforeEach(() => {
  installGlobals();
  resetAppState();
});

afterEach(() => {
  Date.now = ORIGINAL_DATE_NOW;
  delete globalThis.fetch;
  delete globalThis.document;
});

/* -------------------------------------------------------------- app state */

describe("appState", () => {
  test("exposes the documented initial values and never loses them on reset", () => {
    assert.equal(appState.language, "en");
    assert.equal(appState.theme, "architectural-stone");
    assert.deepEqual(appState.bulbs, []);
    assert.deepEqual(appState.selectedIps, []);
    assert.deepEqual(appState.customScenes, []);
    assert.equal(appState.activeTab, "temperature");
    assert.equal(appState.sceneCategory, "all");
    assert.equal(appState.sleepTimer.active, false);
    assert.equal(appState.sleepTimer.remaining_seconds, 0);
    assert.equal(appState.ambilight.color_mode, "vibrant");
    assert.equal(appState.musicSync.palette_mode, "spectrum");
    assert.deepEqual(appState.audioDevices.map((device) => device.index), [-1]);
  });

  test("the fallback monitor/audio device remain the documented single entries", () => {
    assert.equal(appState.monitors.length, 1);
    assert.equal(appState.monitors[0].index, 1);
    assert.equal(appState.audioDevices[0].is_default, true);
  });
});

/* ----------------------------------------------------------- favourites */

describe("favourite scenes persistence", () => {
  test("saves the ids as JSON under the documented storage key", () => {
    store.saveFavoriteSceneIds([34, 12]);
    assert.equal(
      window.localStorage.getItem(store.FAV_SCENES_STORAGE_KEY),
      JSON.stringify([34, 12])
    );
  });

  test("round-trips saved ids", () => {
    store.saveFavoriteSceneIds([34, 12, 1]);
    assert.deepEqual(store.loadFavoriteSceneIds(), [34, 12, 1]);
  });

  test("returns an empty list when nothing was ever stored", () => {
    assert.deepEqual(store.loadFavoriteSceneIds(), []);
  });

  test("rejects unparsable, non-array and out-of-range entries", () => {
    window.localStorage.setItem(store.FAV_SCENES_STORAGE_KEY, "{not json");
    assert.deepEqual(store.loadFavoriteSceneIds(), []);

    window.localStorage.setItem(store.FAV_SCENES_STORAGE_KEY, '{"1":true}');
    assert.deepEqual(store.loadFavoriteSceneIds(), []);

    window.localStorage.setItem(store.FAV_SCENES_STORAGE_KEY, '[1,"2",37,0,-3,3.5,36]');
    assert.deepEqual(store.loadFavoriteSceneIds(), [1, 2, 36]);
  });

  test("a storage that throws degrades to an empty list instead of breaking the module", () => {
    installGlobals({
      storage: {
        getItem() {
          throw new Error("SecurityError");
        },
        setItem() {
          throw new Error("QuotaExceededError");
        }
      }
    });
    assert.deepEqual(store.loadFavoriteSceneIds(), []);
    assert.doesNotThrow(() => store.saveFavoriteSceneIds([1]));
  });
});

/* -------------------------------------------------------------- ui prefs */

describe("ui preferences persistence", () => {
  test("saveUiPref keeps the previously stored keys", () => {
    store.saveUiPref("activityTab", "scenes");
    store.saveUiPref("collapsed", true);
    assert.deepEqual(store.loadUiPrefs(), { activityTab: "scenes", collapsed: true });
  });

  test("loadUiPrefs falls back to an empty object for missing or malformed data", () => {
    assert.deepEqual(store.loadUiPrefs(), {});

    window.localStorage.setItem(store.UI_PREFS_STORAGE_KEY, "{oops");
    assert.deepEqual(store.loadUiPrefs(), {});

    window.localStorage.setItem(store.UI_PREFS_STORAGE_KEY, "null");
    assert.deepEqual(store.loadUiPrefs(), {});

    window.localStorage.setItem(store.UI_PREFS_STORAGE_KEY, "7");
    assert.deepEqual(store.loadUiPrefs(), {});
  });

  test("saveUiPref never throws when the storage is unavailable", () => {
    installGlobals({
      storage: {
        getItem() {
          throw new Error("denied");
        },
        setItem() {
          throw new Error("denied");
        }
      }
    });
    assert.doesNotThrow(() => store.saveUiPref("activityTab", "scenes"));
  });
});

/* --------------------------------------------------------------- themes */

describe("theme validation", () => {
  test("accepts exactly the two shipped themes", () => {
    assert.deepEqual([...store.ALLOWED_THEMES].sort(), [
      "architectural-stone",
      "atmospheric-dark"
    ]);
    assert.equal(store.normalizeTheme("atmospheric-dark"), "atmospheric-dark");
    assert.equal(store.normalizeTheme("architectural-stone"), "architectural-stone");
  });

  test("normalizes surrounding whitespace and casing", () => {
    assert.equal(store.normalizeTheme("  Atmospheric-Dark \n"), "atmospheric-dark");
  });

  test("falls back to the default theme for unknown or malformed values", () => {
    assert.equal(store.normalizeTheme("neon"), store.DEFAULT_THEME);
    assert.equal(store.normalizeTheme(""), store.DEFAULT_THEME);
    assert.equal(store.normalizeTheme(null), store.DEFAULT_THEME);
    assert.equal(store.normalizeTheme(undefined), store.DEFAULT_THEME);
    assert.equal(store.normalizeTheme(3), store.DEFAULT_THEME);
    assert.equal(store.normalizeTheme({ theme: "atmospheric-dark" }), store.DEFAULT_THEME);
  });

  test("never mutates the live app state", () => {
    store.normalizeTheme("atmospheric-dark");
    assert.equal(appState.theme, "architectural-stone");
  });
});

/* ------------------------------------------------------------------ i18n */

describe("t()", () => {
  test("delegates to the UI translator and forwards the variables", () => {
    const i18n = createFakeI18n();
    installGlobals({ i18n });

    assert.equal(store.t("scenes.count", { count: 4 }), "T(scenes.count|count=4)");
    assert.deepEqual(i18n.calls, [{ key: "scenes.count", vars: { count: 4 } }]);
  });

  test("returns the key itself when no translator is installed", () => {
    assert.equal(store.t("rail.scanBtn"), "rail.scanBtn");
  });

  test("returns the key when the translator is missing the t() method", () => {
    installGlobals({ i18n: { language: "es" } });
    assert.equal(store.t("rail.scanBtn"), "rail.scanBtn");
  });
});

describe("formatSceneDisplayName()", () => {
  test("renames the Plantgrowth preset through the translator", () => {
    installGlobals({ i18n: createFakeI18n() });
    assert.equal(store.formatSceneDisplayName({ scene_id: 19, name: "Plantgrowth" }), "T(scenes.plantGrowth)");
    assert.equal(store.formatSceneDisplayName({ scene_id: 19, name: "Otro" }), "T(scenes.plantGrowth)");
    assert.equal(store.formatSceneDisplayName({ scene_id: 4, name: "Plantgrowth" }), "T(scenes.plantGrowth)");
  });

  test("keeps every other name untouched", () => {
    installGlobals({ i18n: createFakeI18n() });
    assert.equal(store.formatSceneDisplayName({ scene_id: 1, name: "Ocean" }), "Ocean");
    assert.equal(store.formatSceneDisplayName(null), "");
    assert.equal(store.formatSceneDisplayName(undefined), "");
  });
});

/* -------------------------------------------------------- primary fixture */

describe("getPrimaryBulb()", () => {
  const bulbA = { ip: "10.0.0.1", name: "A" };
  const bulbB = { ip: "10.0.0.2", name: "B" };

  test("prefers the first selected bulb", () => {
    appState.bulbs = [bulbA, bulbB];
    appState.selectedIps = ["10.0.0.2"];
    assert.equal(store.getPrimaryBulb(), bulbB);
  });

  test("falls back to the first bulb when nothing (or nobody) is selected", () => {
    appState.bulbs = [bulbA, bulbB];
    assert.equal(store.getPrimaryBulb(), bulbA);
    appState.selectedIps = ["192.168.9.9"];
    assert.equal(store.getPrimaryBulb(), bulbA);
  });

  test("returns null without bulbs and leaves the state untouched", () => {
    const snapshot = structuredClone(appState);
    assert.equal(store.getPrimaryBulb(), null);
    assert.deepEqual(appState, snapshot);
  });
});

/* --------------------------------------------------------------- scene catalog */

describe("loadSceneCatalog()", () => {
  const catalog = [
    { scene_id: 1, name: "Ocean", category: "nature", supports_speed: true },
    { scene_id: 34, name: "Candlelight", category: "white", supports_speed: false }
  ];

  test("publishes the fetched catalog and seeds an empty scene list", async () => {
    let requested = null;
    globalThis.fetch = async (url) => {
      requested = url;
      return { ok: true, json: async () => catalog };
    };

    await store.loadSceneCatalog();

    assert.equal(requested, "scenes.json");
    assert.deepEqual(store.SCENE_CATALOG, catalog);
    assert.deepEqual(appState.scenes, catalog);
  });

  test("does not replace scenes the backend handshake already delivered", async () => {
    appState.scenes = [{ scene_id: 99, name: "Backend", category: "dynamic", supports_speed: true }];
    globalThis.fetch = async () => ({ ok: true, json: async () => catalog });

    await store.loadSceneCatalog();

    assert.deepEqual(store.SCENE_CATALOG, catalog);
    assert.deepEqual(appState.scenes, [{ scene_id: 99, name: "Backend", category: "dynamic", supports_speed: true }]);
  });

  test("ignores failed, empty and malformed responses", async () => {
    globalThis.fetch = async () => ({ ok: false, json: async () => catalog });
    await store.loadSceneCatalog();
    assert.deepEqual(appState.scenes, []);

    globalThis.fetch = async () => ({ ok: true, json: async () => [] });
    await store.loadSceneCatalog();
    assert.deepEqual(appState.scenes, []);

    globalThis.fetch = async () => ({ ok: true, json: async () => ({ scenes: catalog }) });
    await store.loadSceneCatalog();
    assert.deepEqual(appState.scenes, []);
  });

  test("a missing fetch (file:// origin) leaves the state untouched", async () => {
    await assert.doesNotReject(store.loadSceneCatalog());
    assert.deepEqual(appState.scenes, []);
  });
});

/* ---------------------------------------------------------- numeric helpers */

describe("clampInt()", () => {
  test("rounds and clamps inside the range", () => {
    assert.equal(store.clampInt(12.6, 0, 100), 13);
    assert.equal(store.clampInt(-5, 0, 100), 0);
    assert.equal(store.clampInt(190, 0, 100), 100);
    assert.equal(store.clampInt("42", 0, 100), 42);
  });

  test("returns the lower bound for values that are not numbers", () => {
    assert.equal(store.clampInt("abc", 7, 100), 7);
    assert.equal(store.clampInt(NaN, 7, 100), 7);
  });
});

describe("hex conversion", () => {
  test("rgbToHex pads and clamps every channel", () => {
    assert.equal(store.rgbToHex(255, 0, 16), "#ff0010");
    assert.equal(store.rgbToHex(300, -20, 255), "#ff00ff");
    assert.equal(store.rgbToHex(0, 0, 0), "#000000");
  });

  test("parseHexToRgb accepts with and without the leading hash", () => {
    assert.deepEqual(store.parseHexToRgb("#FF9254"), { r: 255, g: 146, b: 84 });
    assert.deepEqual(store.parseHexToRgb(" 00b4d8 "), { r: 0, g: 180, b: 216 });
  });

  test("parseHexToRgb rejects everything that is not a 6-digit hex color", () => {
    assert.equal(store.parseHexToRgb("#FFF"), null);
    assert.equal(store.parseHexToRgb("#GGGGGG"), null);
    assert.equal(store.parseHexToRgb(""), null);
    assert.equal(store.parseHexToRgb(null), null);
    assert.equal(store.parseHexToRgb(undefined), null);
  });
});

describe("HSV conversion", () => {
  test("hsvToRgb maps the six hue sectors", () => {
    assert.deepEqual(store.hsvToRgb(0, 1, 1), { r: 255, g: 0, b: 0 });
    assert.deepEqual(store.hsvToRgb(60, 1, 1), { r: 255, g: 255, b: 0 });
    assert.deepEqual(store.hsvToRgb(120, 1, 1), { r: 0, g: 255, b: 0 });
    assert.deepEqual(store.hsvToRgb(180, 1, 1), { r: 0, g: 255, b: 255 });
    assert.deepEqual(store.hsvToRgb(240, 1, 1), { r: 0, g: 0, b: 255 });
    assert.deepEqual(store.hsvToRgb(300, 1, 1), { r: 255, g: 0, b: 255 });
  });

  test("hsvToRgb keeps zero saturation on the gray axis", () => {
    assert.deepEqual(store.hsvToRgb(210, 0, 0.5), { r: 128, g: 128, b: 128 });
  });

  test("rgbToHsv recovers the hue of the primary colors", () => {
    assert.deepEqual(store.rgbToHsv(255, 0, 0), { h: 0, s: 1, v: 1 });
    assert.deepEqual(store.rgbToHsv(0, 255, 0), { h: 120, s: 1, v: 1 });
    assert.deepEqual(store.rgbToHsv(0, 0, 255), { h: 240, s: 1, v: 1 });
    assert.deepEqual(store.rgbToHsv(0, 0, 0), { h: 0, s: 0, v: 0 });
  });

  test("rgbToHsv stays in [0, 360) for hues below the red sector", () => {
    const { h } = store.rgbToHsv(255, 0, 128);
    assert.ok(h >= 0 && h < 360, `hue out of range: ${h}`);
  });
});

describe("kelvinToCssColor()", () => {
  test("clamps the range to 2200K-6500K", () => {
    assert.equal(store.kelvinToCssColor(1000), store.kelvinToCssColor(2200));
    assert.equal(store.kelvinToCssColor(12000), store.kelvinToCssColor(6500));
  });

  test("renders the documented ends of the two segments", () => {
    assert.equal(store.kelvinToCssColor(2200), "rgb(255, 180, 107)");
    assert.equal(store.kelvinToCssColor(4200), "rgb(255, 241, 224)");
    assert.equal(store.kelvinToCssColor(6500), "rgb(214, 232, 255)");
  });

  test("gets cooler (more blue, less red) as the temperature rises", () => {
    const read = (css) => css.match(/\d+/g).map(Number);
    const warm = read(store.kelvinToCssColor(2700));
    const cool = read(store.kelvinToCssColor(6000));
    assert.ok(cool[2] > warm[2], "blue channel must grow with temperature");
    assert.ok(cool[1] > warm[1], "green channel must grow with temperature");
  });
});

describe("formatCountdown()", () => {
  test("formats whole minutes and seconds as MM:SS", () => {
    assert.equal(store.formatCountdown(0), "00:00");
    assert.equal(store.formatCountdown(59), "00:59");
    assert.equal(store.formatCountdown(60), "01:00");
    assert.equal(store.formatCountdown(3599), "59:59");
    assert.equal(store.formatCountdown(3661), "61:01");
  });

  test("truncates fractions and never goes negative", () => {
    assert.equal(store.formatCountdown(45.9), "00:45");
    assert.equal(store.formatCountdown(-30), "00:00");
    assert.equal(store.formatCountdown("90"), "01:30");
  });

  test("treats missing or non-numeric input as zero", () => {
    assert.equal(store.formatCountdown(null), "00:00");
    assert.equal(store.formatCountdown(undefined), "00:00");
    assert.equal(store.formatCountdown("abc"), "00:00");
  });
});

/* ------------------------------------------------------------ fps telemetry */

describe("computeLiveFps()", () => {
  test("an inactive stream reports 0 and records its frame counter", () => {
    let now = 1000;
    Date.now = () => now;
    const slot = { lastFrames: 0, lastTs: 0, fps: 12 };

    assert.equal(store.computeLiveFps(slot, false, 40, 10), 0);
    assert.deepEqual(slot, { lastFrames: 40, lastTs: 1000, fps: 0 });
  });

  test("the first active sample reports the nominal rate", () => {
    Date.now = () => 500;
    const slot = { lastFrames: 0, lastTs: 0, fps: 0 };

    assert.equal(store.computeLiveFps(slot, true, 0, 24), 24);
    assert.equal(slot.lastTs, 500);
  });

  test("a later sample is measured from the elapsed time", () => {
    let now = 1000;
    Date.now = () => now;
    const slot = { lastFrames: 0, lastTs: 0, fps: 0 };
    store.computeLiveFps(slot, true, 0, 12);

    now = 2000;
    assert.equal(store.computeLiveFps(slot, true, 30, 12), 30);
    assert.equal(slot.lastFrames, 30);
  });

  test("the measured rate is clamped to 1..30", () => {
    let now = 1000;
    Date.now = () => now;
    const fast = { lastFrames: 0, lastTs: 0, fps: 0 };
    store.computeLiveFps(fast, true, 0, 12);

    now = 1200;
    assert.equal(store.computeLiveFps(fast, true, 60, 12), 30);

    now = 1000;
    const slow = { lastFrames: 0, lastTs: 0, fps: 0 };
    store.computeLiveFps(slow, true, 0, 12);
    now = 5000;
    assert.equal(store.computeLiveFps(slow, true, 1, 12), 1);
  });

  test("samples closer than 150 ms keep the previous rate", () => {
    let now = 1000;
    Date.now = () => now;
    const slot = { lastFrames: 0, lastTs: 0, fps: 0 };
    store.computeLiveFps(slot, true, 0, 12);

    now = 1100;
    assert.equal(store.computeLiveFps(slot, true, 50, 12), 12);
    assert.equal(slot.lastFrames, 0);
  });
});

/* ------------------------------------------------------------- slider fill */

describe("updateSliderFill()", () => {
  test("publishes the range and the progress as CSS custom properties", () => {
    globalThis.document = { querySelectorAll: () => [] };
    const input = createRangeInput({ id: "brightness", min: "0", max: "100", value: "50" });

    store.updateSliderFill(input);

    assert.deepEqual(input.style.props, {
      "--attr-min": "0",
      "--attr-max": "100",
      "--control-value": "50",
      "--slider-progress": "50.00%"
    });
  });

  test("clamps the published value into the slider range", () => {
    globalThis.document = { querySelectorAll: () => [] };
    const input = createRangeInput({ id: "brightness", min: "10", max: "100", value: "140" });

    store.updateSliderFill(input);

    assert.equal(input.style.props["--control-value"], "100");
    assert.equal(input.style.props["--slider-progress"], "100.00%");
  });

  test("falls back to 0..100 when the input declares no range", () => {
    globalThis.document = { querySelectorAll: () => [] };
    const input = createRangeInput({ id: "brightness", min: "", max: "", value: "25" });

    store.updateSliderFill(input);

    assert.equal(input.style.props["--attr-min"], "0");
    assert.equal(input.style.props["--attr-max"], "100");
    assert.equal(input.style.props["--slider-progress"], "25.00%");
  });

  test("does nothing for a missing element", () => {
    assert.doesNotThrow(() => store.updateSliderFill(null));
    assert.doesNotThrow(() => store.updateSliderFill(undefined));
  });

  test("marks only the scale preset that matches the current value", () => {
    const matching = {
      attrs: { "data-value": "50" },
      getAttribute(name) {
        return this.attrs[name] ?? null;
      },
      classList: {
        active: false,
        toggle(name, on) {
          if (name === "active") this.active = on;
        }
      }
    };
    const other = {
      attrs: { "data-value": "100" },
      getAttribute(name) {
        return this.attrs[name] ?? null;
      },
      classList: {
        active: true,
        toggle(name, on) {
          if (name === "active") this.active = on;
        }
      }
    };
    let requested = null;
    globalThis.document = {
      querySelectorAll(selector) {
        requested = selector;
        return [matching, other];
      }
    };

    store.updateSliderFill(createRangeInput({ id: "brightness", min: "0", max: "100", value: "50" }));

    assert.equal(requested, '.scale-preset-btn[data-target-slider="brightness"]');
    assert.equal(matching.classList.active, true);
    assert.equal(other.classList.active, false);
  });

  test("updateAllSlidersFill() fills every range input on the page", () => {
    const sliders = [
      createRangeInput({ id: "brightness", min: "0", max: "100", value: "10" }),
      createRangeInput({ id: "speed", min: "10", max: "200", value: "100" })
    ];
    globalThis.document = {
      querySelectorAll(selector) {
        return selector === 'input[type="range"]' ? sliders : [];
      }
    };

    store.updateAllSlidersFill();

    assert.equal(sliders[0].style.props["--slider-progress"], "10.00%");
    assert.equal(sliders[1].style.props["--slider-progress"], "47.37%");
  });
});
