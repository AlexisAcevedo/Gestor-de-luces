/*
 * Controlador de interfaz de usuario para la Consola Fotometrica Arquitectonica WiZ.
 *
 * Punto de entrada modular ES (ui/js/app.js): coordina el ciclo de vida del DOM,
 * el cambio de tema e idioma, las pestanas WAI-ARIA y la sincronizacion con WebviewBridge.
 */

import { bindAmbilightEvents, renderAmbilightPanel, syncAmbilightPolling } from "./ambilight.js";
import {
  getBackendApi, invokeApi, resolveBackendApi, setBackendUpgradeHandler, setEnvelopeHandler
} from "./bridge-client.js";
import {
  bindFixtureEvents, renderFixtureList, renderSleepTimer, syncAutoSyncPolling, syncSleepTimerPolling
} from "./fixtures.js";
import { bindMusicEvents, renderMusicPanel, syncMusicPolling } from "./music.js";
import { bindSceneEvents, renderCustomScenesGrid, renderScenesGrid } from "./scenes.js";
import {
  bindGlobalHotkeyEvents, renderGlobalHotkeys, requestFit, setupDialogLightDismissFallbacks,
  setupGlobalShortcuts, setupResizeThrottle, setupWindowFit
} from "./shortcuts.js";
import {
  bindStageControlEvents, drawColorWheel, positionReticleFromRgb, renderStageHeaderAndControls
} from "./stage-controls.js";
import {
  ALLOWED_THEMES, DEFAULT_THEME, FAV_SCENES_STORAGE_KEY, appState, clampInt, getPrimaryBulb,
  loadFavoriteSceneIds, loadSceneCatalog, loadUiPrefs, normalizeTheme, saveFavoriteSceneIds,
  saveUiPref, t, updateAllSlidersFill
} from "./store.js";
import { setStatusMessage, showToast } from "./toasts.js";

const lastRendered = {
  language: null, persistedLanguage: null, theme: null, persistedTheme: null,
  bulbsKey: null, scenesKey: null, customKey: null, sleepKey: null, ambiKey: null, musicKey: null,
  legacyFavsMigrated: false
};

export function resetUiSyncCache() {
  Object.keys(lastRendered).forEach((k) => {
    lastRendered[k] = k === "legacyFavsMigrated" ? false : null;
  });
}

/* Sincroniza el selector visual de idioma (EN | ES) y traduce el arbol DOM estatico */
export function syncLanguageUi(lang) {
  const normalized = String(lang || "en").trim().toLowerCase() === "es" ? "es" : "en";
  if (lastRendered.persistedLanguage !== normalized) {
    saveUiPref("language", normalized);
    lastRendered.persistedLanguage = normalized;
  }
  if (lastRendered.language === normalized && appState.language === normalized) {
    return false;
  }
  const prevLang = appState.language;
  lastRendered.language = normalized;
  appState.language = normalized;
  if (document.documentElement && document.documentElement.dataset) {
    document.documentElement.dataset.lang = normalized;
  }
  if (window.I18N) {
    window.I18N.setLanguage(normalized);
    window.I18N.translateDom();
  }
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    const isMatch = btn.getAttribute("data-lang") === normalized;
    btn.setAttribute("aria-pressed", String(isMatch));
  });
  if (prevLang !== normalized) {
    // Las etiquetas cambian de largo y de alto: la ventana se reajusta al contenido nuevo.
    requestFit(true);
  }
  return true;
}

function readHashTheme() {
  try {
    const hash = String(window.location.hash || "");
    if (!hash || hash === "#") return null;
    const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
    const candidate = params.get("theme");
    if (typeof candidate !== "string") return null;
    const cleaned = candidate.trim().toLowerCase();
    return ALLOWED_THEMES.has(cleaned) ? cleaned : null;
  } catch (_err) {
    return null;
  }
}

export function syncThemeUi(theme, { persist = true } = {}) {
  const normalized = normalizeTheme(theme);
  const prevTheme = appState.theme;
  const prevDomTheme = document.documentElement.dataset.theme;
  const domAlreadyMatches = prevDomTheme === normalized;
  if (lastRendered.theme !== normalized || prevTheme !== normalized || !domAlreadyMatches) {
    document.documentElement.dataset.theme = normalized;
    const colorSchemeMeta = document.querySelector('meta[name="color-scheme"]');
    if (colorSchemeMeta) {
      colorSchemeMeta.setAttribute("content", normalized === "atmospheric-dark" ? "dark" : "light");
    }
    const consoleShell = document.getElementById("console-shell");
    if (consoleShell) consoleShell.dataset.look = normalized;
    const stoneBtn = document.getElementById("theme-btn-stone");
    if (stoneBtn) {
      const isStone = normalized === "architectural-stone";
      stoneBtn.classList.toggle("active", isStone);
      stoneBtn.setAttribute("aria-pressed", isStone ? "true" : "false");
    }
    const darkBtn = document.getElementById("theme-btn-dark");
    if (darkBtn) {
      const isDark = normalized === "atmospheric-dark";
      darkBtn.classList.toggle("active", isDark);
      darkBtn.setAttribute("aria-pressed", isDark ? "true" : "false");
    }
  }
  if (persist && lastRendered.persistedTheme !== normalized) {
    saveUiPref("theme", normalized);
    lastRendered.persistedTheme = normalized;
  }
  lastRendered.theme = normalized;
  appState.theme = normalized;
  if (prevTheme !== normalized || prevDomTheme !== normalized) {
    requestFit(true);
  }
}

function renderAllPanels() {
  renderFixtureList();
  renderStageHeaderAndControls();
  renderSleepTimer();
  renderScenesGrid();
  renderCustomScenesGrid();
  renderAmbilightPanel();
  renderMusicPanel();
}

/* Actualiza la variable CSS `--beam-color` y toda la interfaz a partir del sobre del backend */
export function applyBackendEnvelope(envelope, statusText, retry, silent) {
  if (!envelope) return;
  const wasAmbiActive = Boolean(appState.ambilight && appState.ambilight.active);
  const wasMusicActive = Boolean(appState.musicSync && appState.musicSync.active);
  const hasBulbs = Array.isArray(envelope.bulbs);
  const hasSelected = Array.isArray(envelope.selected_ips);
  const hasScenes = Array.isArray(envelope.scenes) && envelope.scenes.length > 0;
  const hasCustom = Array.isArray(envelope.custom_scenes);
  const hasSleep = Boolean(envelope.sleep_timer && typeof envelope.sleep_timer === "object");
  const hasAmbi = Boolean(envelope.ambilight && typeof envelope.ambilight === "object");
  const hasMonitors = Array.isArray(envelope.monitors) && envelope.monitors.length > 0;
  const hasMusic = Boolean(envelope.music_sync && typeof envelope.music_sync === "object");
  const hasAudio = Array.isArray(envelope.audio_devices) && envelope.audio_devices.length > 0;
  const hasFavScenes = Array.isArray(envelope.favorite_builtin_scenes);
  const hasAmbiPrefs = Boolean(envelope.ambilight_prefs && typeof envelope.ambilight_prefs === "object");
  const hasMusicPrefs = Boolean(envelope.music_prefs && typeof envelope.music_prefs === "object");
  const hasGlobalHotkeys = Boolean(envelope.global_hotkeys && typeof envelope.global_hotkeys === "object");

  const langChanged = typeof envelope.language === "string" ? syncLanguageUi(envelope.language) : false;
  if (typeof envelope.theme === "string") syncThemeUi(envelope.theme);
  if (typeof envelope.auto_sync === "boolean" && appState.autoSync !== envelope.auto_sync) {
    syncAutoSyncPolling(envelope.auto_sync);
  }
  if (hasFavScenes) {
    if (envelope.favorite_builtin_scenes.length === 0 && !lastRendered.legacyFavsMigrated) {
      lastRendered.legacyFavsMigrated = true;
      const legacyFavs = loadFavoriteSceneIds();
      if (legacyFavs.length > 0) {
        appState.favoriteSceneIds = legacyFavs;
        const api = getBackendApi();
        if (api && typeof api.set_favorite_builtin_scenes === "function") {
          invokeApi(() => api.set_favorite_builtin_scenes(legacyFavs), null, { silent: true });
        }
        try {
          if (typeof window !== "undefined" && window.localStorage) {
            window.localStorage.removeItem(FAV_SCENES_STORAGE_KEY);
          }
        } catch (_err) {
          /* Ignore storage restrictions */
        }
      } else {
        appState.favoriteSceneIds = [];
      }
    } else {
      lastRendered.legacyFavsMigrated = true;
      appState.favoriteSceneIds = envelope.favorite_builtin_scenes.slice();
      saveFavoriteSceneIds(appState.favoriteSceneIds);
    }
  }
  if (hasAmbiPrefs) appState.ambilightPrefs = envelope.ambilight_prefs;
  if (hasMusicPrefs) appState.musicPrefs = envelope.music_prefs;
  if (hasGlobalHotkeys || typeof envelope.global_hotkeys_supported === "boolean") {
    const prev = appState.globalHotkeys || {};
    appState.globalHotkeys = {
      enabled: hasGlobalHotkeys ? Boolean(envelope.global_hotkeys.enabled) : Boolean(prev.enabled),
      supported: typeof envelope.global_hotkeys_supported === "boolean"
        ? envelope.global_hotkeys_supported
        : Boolean(prev.supported),
      bindings: hasGlobalHotkeys && envelope.global_hotkeys.bindings
        ? Object.assign({}, envelope.global_hotkeys.bindings)
        : Object.assign({}, prev.bindings || {}),
      errors: envelope.global_hotkey_errors && typeof envelope.global_hotkey_errors === "object"
        ? Object.assign({}, envelope.global_hotkey_errors)
        : Object.assign({}, prev.errors || {})
    };
    renderGlobalHotkeys();
  }
  if (hasBulbs) appState.bulbs = envelope.bulbs;
  if (hasSelected) appState.selectedIps = envelope.selected_ips;
  if (hasScenes) appState.scenes = envelope.scenes;
  if (hasCustom) appState.customScenes = envelope.custom_scenes;
  if (hasSleep) appState.sleepTimer = envelope.sleep_timer;
  if (hasAmbi) appState.ambilight = envelope.ambilight;
  if (hasMonitors) appState.monitors = envelope.monitors;
  if (hasMusic) appState.musicSync = envelope.music_sync;
  if (hasAudio) appState.audioDevices = envelope.audio_devices;

  if (!envelope.ok && envelope.error) {
    const warning = t("status.warning", { error: envelope.error });
    setStatusMessage(warning);
    showToast({ kind: "error", message: warning, retry });
  } else {
    const text = typeof statusText === "function" ? statusText() : statusText;
    if (text) {
      setStatusMessage(text);
      if (!silent) showToast({ kind: "ok", message: text });
    }
  }

  if (langChanged) {
    lastRendered.bulbsKey = lastRendered.scenesKey = lastRendered.customKey = null;
    lastRendered.sleepKey = lastRendered.ambiKey = lastRendered.musicKey = null;
  }

  let bulbsChanged = false;
  if (hasBulbs || hasSelected || langChanged) {
    const nextKey = JSON.stringify([appState.bulbs, appState.selectedIps]);
    if (nextKey !== lastRendered.bulbsKey) {
      lastRendered.bulbsKey = nextKey;
      bulbsChanged = true;
      renderFixtureList();
      renderStageHeaderAndControls();
    }
  }
  if (hasScenes || hasFavScenes || bulbsChanged || langChanged) {
    const primary = getPrimaryBulb();
    const activeSig = primary ? [primary.state?.mode, primary.state?.scene_id, primary.state?.speed] : null;
    const nextKey = JSON.stringify([appState.scenes, appState.favoriteSceneIds, activeSig]);
    if (nextKey !== lastRendered.scenesKey) {
      lastRendered.scenesKey = nextKey;
      renderScenesGrid();
    }
  }
  if (hasCustom || hasScenes || langChanged) {
    const nextKey = JSON.stringify([appState.customScenes, appState.scenes.length]);
    if (nextKey !== lastRendered.customKey) {
      lastRendered.customKey = nextKey;
      renderCustomScenesGrid();
    }
  }
  if (hasSleep || langChanged) {
    const nextKey = JSON.stringify(appState.sleepTimer);
    if (nextKey !== lastRendered.sleepKey) {
      lastRendered.sleepKey = nextKey;
      renderSleepTimer();
    }
    if (hasSleep) syncSleepTimerPolling();
  }
  if (hasAmbi || hasAmbiPrefs || hasMonitors || langChanged) {
    const nextKey = JSON.stringify([appState.ambilight, appState.ambilightPrefs, appState.monitors]);
    if (nextKey !== lastRendered.ambiKey) {
      lastRendered.ambiKey = nextKey;
      renderAmbilightPanel();
    }
    if (hasAmbi) syncAmbilightPolling();
  }
  if (hasMusic || hasMusicPrefs || hasAudio || langChanged) {
    const nextKey = JSON.stringify([appState.musicSync, appState.musicPrefs, appState.audioDevices]);
    if (nextKey !== lastRendered.musicKey) {
      lastRendered.musicKey = nextKey;
      renderMusicPanel();
    }
    if (hasMusic) syncMusicPolling();
  }
  const streamToggled =
    (hasAmbi && wasAmbiActive !== Boolean(appState.ambilight && appState.ambilight.active)) ||
    (hasMusic && wasMusicActive !== Boolean(appState.musicSync && appState.musicSync.active));
  if (streamToggled && !bulbsChanged) {
    renderStageHeaderAndControls();
  }
  if (
    !hasBulbs &&
    ((hasAmbi && wasAmbiActive && !appState.ambilight.active) ||
      (hasMusic && wasMusicActive && !appState.musicSync.active))
  ) {
    refreshStates();
  }
}

setEnvelopeHandler(applyBackendEnvelope);
setBackendUpgradeHandler(() =>
  invokeApi(() => getBackendApi().get_initial_state(), () => t("status.connected"))
);

/* Refresca el estado completo de la consola cuando se solicita manual o externamente */
function refreshStates(statusMessage) {
  return invokeApi(
    () => getBackendApi().refresh_states(),
    statusMessage || (() => t("status.syncedTray")),
    { silent: true }
  );
}

/* Callback global invocado desde Python cuando el usuario opera el menu de la bandeja */
if (typeof window !== "undefined") {
  window.onTrayStateChanged = () => {
    refreshStates();
  };
}

/* Gestion de pestanas accesibles (WAI-ARIA Tabs con navegacion por flechas) */
export function activateTab(modeName, focusTab) {
  appState.activeTab = modeName;
  saveUiPref("activeTab", modeName);
  const tabs = Array.from(document.querySelectorAll(".mode-tab"));
  tabs.forEach((tab) => {
    const isMatch = tab.dataset.mode === modeName;
    tab.setAttribute("aria-selected", String(isMatch));
    tab.tabIndex = isMatch ? 0 : -1;
    if (isMatch && focusTab) {
      tab.focus();
    }
    const panelId = tab.getAttribute("aria-controls");
    const panel = panelId ? document.getElementById(panelId) : null;
    if (panel) {
      panel.hidden = !isMatch;
    }
  });
  if (modeName === "rgb") {
    requestAnimationFrame(() => {
      const r = clampInt(document.getElementById("input-r")?.value ?? 255, 0, 255);
      const g = clampInt(document.getElementById("input-g")?.value ?? 140, 0, 255);
      const b = clampInt(document.getElementById("input-b")?.value ?? 66, 0, 255);
      positionReticleFromRgb(r, g, b);
    });
  }
  requestFit(true);
}

function restoreUiPrefs() {
  const prefs = loadUiPrefs();
  const openState = prefs.openSections && typeof prefs.openSections === "object" ? prefs.openSections : {};

  document.querySelectorAll("details[data-persist-open]").forEach((el) => {
    const key = el.getAttribute("data-persist-open");
    if (typeof openState[key] === "boolean") el.open = openState[key];
    el.addEventListener("toggle", () => {
      const current = loadUiPrefs();
      const sections = current.openSections && typeof current.openSections === "object" ? current.openSections : {};
      sections[key] = el.open;
      saveUiPref("openSections", sections);
      requestFit(true);
    });
  });

  const savedTab = prefs.activeTab;
  const known = Array.from(document.querySelectorAll(".mode-tab")).some(
    (tab) => tab.dataset.mode === savedTab
  );
  if (known) activateTab(savedTab, false);

  const prefTheme =
    typeof prefs.theme === "string" && ALLOWED_THEMES.has(prefs.theme.trim().toLowerCase())
      ? prefs.theme.trim().toLowerCase()
      : null;
  const domTheme = ALLOWED_THEMES.has(document.documentElement.dataset.theme)
    ? document.documentElement.dataset.theme
    : null;
  const initialTheme = readHashTheme() || prefTheme || domTheme || DEFAULT_THEME;
  syncThemeUi(initialTheme, { persist: false });
}

async function handleSetTheme(theme) {
  const normalized = normalizeTheme(theme);
  syncThemeUi(normalized);
  const api = getBackendApi();
  if (api && typeof api.set_theme === "function") {
    await invokeApi(() => api.set_theme(normalized), null, { silent: true });
  }
}

export function bindEvents() {
  if (typeof window !== "undefined") {
    window.onTrayStateChanged = () => { refreshStates(); };
  }
  setupDialogLightDismissFallbacks();
  setupGlobalShortcuts({ activateTab });

  const themeBtnStone = document.getElementById("theme-btn-stone");
  if (themeBtnStone) themeBtnStone.addEventListener("click", () => handleSetTheme("architectural-stone"));
  const themeBtnDark = document.getElementById("theme-btn-dark");
  if (themeBtnDark) themeBtnDark.addEventListener("click", () => handleSetTheme("atmospheric-dark"));

  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetLang = btn.getAttribute("data-lang") || "en";
      const api = getBackendApi();
      if (api && typeof api.set_language === "function") {
        invokeApi(() => api.set_language(targetLang), () => t("status.languageChanged"));
      } else {
        syncLanguageUi(targetLang);
        renderAllPanels();
        setStatusMessage(t("status.languageChanged"));
      }
    });
  });

  /* Pestanas de modo con soporte de teclado Left/Right/Home/End */
  const tabList = Array.from(document.querySelectorAll(".mode-tab"));
  tabList.forEach((tab, idx) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.mode, false));
    tab.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const dir = event.key === "ArrowRight" ? 1 : -1;
        const nextIdx = (idx + dir + tabList.length) % tabList.length;
        activateTab(tabList[nextIdx].dataset.mode, true);
      } else if (event.key === "Home") {
        event.preventDefault();
        if (tabList.length > 0) activateTab(tabList[0].dataset.mode, true);
      } else if (event.key === "End") {
        event.preventDefault();
        if (tabList.length > 0) activateTab(tabList[tabList.length - 1].dataset.mode, true);
      }
    });
  });

  bindFixtureEvents();
  bindStageControlEvents();
  bindSceneEvents({ activateTab });
  bindAmbilightEvents();
  bindMusicEvents();
  bindGlobalHotkeyEvents();

  document.addEventListener("visibilitychange", () => {
    const api = getBackendApi();
    if (!document.hidden && api) {
      if (appState.ambilight && appState.ambilight.active) {
        invokeApi(() => api.get_ambilight_status(), null, {
          silent: true, poll: true, dedupeKey: "poll:ambilight"
        });
      } else if (appState.musicSync && appState.musicSync.active) {
        invokeApi(() => api.get_music_sync_status(), null, {
          silent: true, poll: true, dedupeKey: "poll:music"
        });
      } else if (appState.sleepTimer && appState.sleepTimer.active) {
        invokeApi(() => api.get_sleep_timer_status(), null, {
          silent: true, poll: true, dedupeKey: "poll:sleep"
        });
      }
    }
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined" && typeof document.addEventListener === "function") {
  setupResizeThrottle();
  document.addEventListener("DOMContentLoaded", async () => {
    syncThemeUi(normalizeTheme(document.documentElement.dataset.theme), { persist: false });
    loadSceneCatalog();
    const bootLang =
      (document.documentElement &&
        ((document.documentElement.dataset && document.documentElement.dataset.lang) ||
          document.documentElement.lang)) ||
      "en";
    const normalizedBootLang = String(bootLang).trim().toLowerCase() === "es" ? "es" : "en";
    lastRendered.persistedLanguage = normalizedBootLang;
    syncLanguageUi(normalizedBootLang);
    drawColorWheel();
    updateAllSlidersFill();
    bindEvents();
    restoreUiPrefs();
    await resolveBackendApi();
    setupWindowFit();
    await invokeApi(() => getBackendApi().get_initial_state(), () => t("status.connected"));
  });
}
