/*
 * Controlador de interfaz de usuario para la Consola Fotometrica Arquitectonica WiZ.
 *
 * Punto de entrada modular ES (ui/js/app.js): coordina el ciclo de vida del DOM,
 * el cambio de tema e idioma, las pestanas WAI-ARIA y la sincronizacion con WebviewBridge.
 */

import {
  bindAmbilightEvents,
  renderAmbilightPanel,
  syncAmbilightPolling
} from "./ambilight.js";
import {
  getBackendApi,
  invokeApi,
  resolveBackendApi,
  setEnvelopeHandler
} from "./bridge-client.js";
import {
  bindFixtureEvents,
  renderFixtureList,
  renderSleepTimer,
  syncSleepTimerPolling
} from "./fixtures.js";
import {
  bindMusicEvents,
  renderMusicPanel,
  syncMusicPolling
} from "./music.js";
import {
  bindSceneEvents,
  renderCustomScenesGrid,
  renderScenesGrid
} from "./scenes.js";
import {
  invalidateFitBaseline,
  requestFit,
  setupDialogLightDismissFallbacks,
  setupGlobalShortcuts,
  setupResizeThrottle,
  setupWindowFit
} from "./shortcuts.js";
import {
  bindStageControlEvents,
  drawColorWheel,
  positionReticleFromRgb,
  renderStageHeaderAndControls
} from "./stage-controls.js";
import {
  ALLOWED_THEMES,
  DEFAULT_THEME,
  appState,
  clampInt,
  loadSceneCatalog,
  loadUiPrefs,
  normalizeTheme,
  saveUiPref,
  t,
  updateAllSlidersFill
} from "./store.js";
import { setStatusMessage, showToast } from "./toasts.js";

/* Sincroniza el selector visual de idioma (EN | ES) y traduce el arbol DOM estatico */
function syncLanguageUi(lang) {
  const normalized = String(lang || "en").trim().toLowerCase() === "es" ? "es" : "en";
  const prevLang = appState.language;
  appState.language = normalized;
  if (window.I18N) {
    window.I18N.setLanguage(normalized);
    window.I18N.translateDom();
  }
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    const isMatch = btn.getAttribute("data-lang") === normalized;
    btn.setAttribute("aria-pressed", String(isMatch));
  });
  if (prevLang !== normalized) {
    invalidateFitBaseline();
  }
}

function syncThemeUi(theme, { persist = true } = {}) {
  const normalized = normalizeTheme(theme);
  const prevTheme = appState.theme;
  const prevDomTheme = document.documentElement.dataset.theme;
  appState.theme = normalized;
  document.documentElement.dataset.theme = normalized;
  const consoleShell = document.getElementById("console-shell");
  if (consoleShell) {
    consoleShell.dataset.look = normalized;
  }
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
  if (persist) {
    saveUiPref("theme", normalized);
  }
  if (prevTheme !== normalized || prevDomTheme !== normalized) {
    invalidateFitBaseline();
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
function applyBackendEnvelope(envelope, statusText, retry, silent) {
  if (!envelope) return;
  if (typeof envelope.language === "string") {
    syncLanguageUi(envelope.language);
  }
  if (typeof envelope.theme === "string") {
    syncThemeUi(envelope.theme);
  }
  if (Array.isArray(envelope.bulbs)) {
    appState.bulbs = envelope.bulbs;
  }
  if (Array.isArray(envelope.selected_ips)) {
    appState.selectedIps = envelope.selected_ips;
  }
  if (Array.isArray(envelope.scenes) && envelope.scenes.length > 0) {
    appState.scenes = envelope.scenes;
  }
  if (Array.isArray(envelope.custom_scenes)) {
    appState.customScenes = envelope.custom_scenes;
  }
  if (envelope.sleep_timer && typeof envelope.sleep_timer === "object") {
    appState.sleepTimer = envelope.sleep_timer;
  }
  if (envelope.ambilight && typeof envelope.ambilight === "object") {
    appState.ambilight = envelope.ambilight;
  }
  if (Array.isArray(envelope.monitors) && envelope.monitors.length > 0) {
    appState.monitors = envelope.monitors;
  }
  if (envelope.music_sync && typeof envelope.music_sync === "object") {
    appState.musicSync = envelope.music_sync;
  }
  if (Array.isArray(envelope.audio_devices) && envelope.audio_devices.length > 0) {
    appState.audioDevices = envelope.audio_devices;
  }

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

  syncSleepTimerPolling();
  syncAmbilightPolling();
  syncMusicPolling();
  renderAllPanels();
}

setEnvelopeHandler(applyBackendEnvelope);

/* Refresca el estado completo de la consola cuando se solicita manual o externamente */
function refreshStates(statusMessage) {
  return invokeApi(
    () => getBackendApi().refresh_states(),
    statusMessage || (() => t("status.syncedTray")),
    { silent: true }
  );
}

/* Callback global invocado desde Python cuando el usuario opera el menu de la bandeja */
window.onTrayStateChanged = () => {
  refreshStates();
};

/* Gestion de pestanas accesibles (WAI-ARIA Tabs con navegacion por flechas) */
function activateTab(modeName, focusTab) {
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

  if (typeof prefs.theme === "string" && ALLOWED_THEMES.has(prefs.theme)) {
    syncThemeUi(prefs.theme, { persist: false });
  } else {
    syncThemeUi(DEFAULT_THEME, { persist: false });
  }
}

async function handleSetTheme(theme) {
  const normalized = normalizeTheme(theme);
  syncThemeUi(normalized);
  const api = getBackendApi();
  if (api && typeof api.set_theme === "function") {
    await invokeApi(
      () => api.set_theme(normalized),
      null,
      { silent: true }
    );
  }
}

function bindEvents() {
  setupDialogLightDismissFallbacks();
  setupGlobalShortcuts({ activateTab });

  /* Selector segmentado de tema (Architectural Stone | Atmospheric Dark) */
  const themeBtnStone = document.getElementById("theme-btn-stone");
  if (themeBtnStone) {
    themeBtnStone.addEventListener("click", () => handleSetTheme("architectural-stone"));
  }
  const themeBtnDark = document.getElementById("theme-btn-dark");
  if (themeBtnDark) {
    themeBtnDark.addEventListener("click", () => handleSetTheme("atmospheric-dark"));
  }

  /* Selector segmentado de idioma (EN | ES) */
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetLang = btn.getAttribute("data-lang") || "en";
      const api = getBackendApi();
      if (api && typeof api.set_language === "function") {
        invokeApi(
          () => api.set_language(targetLang),
          () => t("status.languageChanged")
        );
      } else {
        syncLanguageUi(targetLang);
        renderAllPanels();
        setStatusMessage(t("status.languageChanged"));
      }
    });
  });

  /* Pestanas de modo con soporte de teclado Left/Right */
  const tabList = Array.from(document.querySelectorAll(".mode-tab"));
  tabList.forEach((tab, idx) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.mode, false));
    tab.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const dir = event.key === "ArrowRight" ? 1 : -1;
        const nextIdx = (idx + dir + tabList.length) % tabList.length;
        activateTab(tabList[nextIdx].dataset.mode, true);
      }
    });
  });

  bindFixtureEvents();
  bindStageControlEvents();
  bindSceneEvents({ activateTab });
  bindAmbilightEvents();
  bindMusicEvents();

  document.addEventListener("visibilitychange", () => {
    const api = getBackendApi();
    if (!document.hidden && api) {
      if (appState.ambilight && appState.ambilight.active) {
        invokeApi(() => api.get_ambilight_status(), null);
      } else if (appState.musicSync && appState.musicSync.active) {
        invokeApi(() => api.get_music_sync_status(), null);
      } else if (appState.sleepTimer && appState.sleepTimer.active) {
        invokeApi(() => api.get_sleep_timer_status(), null);
      }
    }
  });
}

setupResizeThrottle();

/* Inicializacion principal al cargar el DOM */
document.addEventListener("DOMContentLoaded", async () => {
  loadSceneCatalog();
  syncLanguageUi("en");
  drawColorWheel();
  updateAllSlidersFill();
  bindEvents();
  restoreUiPrefs();
  await resolveBackendApi();
  setupWindowFit();
  await invokeApi(
    () => getBackendApi().get_initial_state(),
    () => t("status.connected")
  );
});
