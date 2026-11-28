/*
 * Synchronous pre-CSS theme and language bootstrap (FOUC/FOUL prevention under strict CSP).
 *
 * Runs before stylesheets load so the first paint uses the persisted theme and language
 * passed via URL hash (`#theme=...&lang=...` from DesktopApplication) or localStorage.
 */
(function bootstrapInitialThemeAndLanguage() {
  var ALLOWED = {
    "architectural-stone": true,
    "atmospheric-dark": true
  };
  var DEFAULT_THEME = "architectural-stone";
  var ALLOWED_LANGS = {
    en: true,
    es: true
  };
  var DEFAULT_LANG = "en";
  var UI_PREFS_STORAGE_KEY = "wiz_console_ui_prefs";
  var LEGACY_UI_PREFS_STORAGE_KEY = "gestor_luces_ui_prefs";

  function normalize(value) {
    if (typeof value !== "string") return null;
    var cleaned = value.trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(ALLOWED, cleaned) ? cleaned : null;
  }

  function normalizeLang(value) {
    if (typeof value !== "string") return null;
    var cleaned = value.trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(ALLOWED_LANGS, cleaned) ? cleaned : null;
  }

  function readParamsFromHash() {
    try {
      var hash = String((window.location && window.location.hash) || "");
      if (!hash || hash === "#") return null;
      var query = hash.charAt(0) === "#" ? hash.slice(1) : hash;
      return new URLSearchParams(query);
    } catch (_err) {
      return null;
    }
  }

  function readPrefsFromStorage() {
    try {
      if (!window.localStorage) return null;
      var raw =
        window.localStorage.getItem(UI_PREFS_STORAGE_KEY) ||
        window.localStorage.getItem(LEGACY_UI_PREFS_STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (_err) {
      return null;
    }
  }

  var hashParams = readParamsFromHash();
  var storedPrefs = readPrefsFromStorage();

  var resolved =
    (hashParams ? normalize(hashParams.get("theme")) : null) ||
    (storedPrefs ? normalize(storedPrefs.theme) : null) ||
    DEFAULT_THEME;

  var resolvedLang =
    (hashParams ? normalizeLang(hashParams.get("lang")) : null) ||
    (storedPrefs ? normalizeLang(storedPrefs.language) : null) ||
    DEFAULT_LANG;

  var root = document.documentElement;
  if (root) {
    root.lang = resolvedLang;
    if (root.dataset) {
      root.dataset.theme = resolved;
      root.dataset.lang = resolvedLang;
    }
    if (typeof root.setAttribute === "function") {
      root.setAttribute("lang", resolvedLang);
      root.setAttribute("data-theme", resolved);
      root.setAttribute("data-lang", resolvedLang);
    }
  }

  var colorSchemeMeta =
    typeof document.querySelector === "function"
      ? document.querySelector('meta[name="color-scheme"]')
      : null;
  if (colorSchemeMeta && typeof colorSchemeMeta.setAttribute === "function") {
    colorSchemeMeta.setAttribute(
      "content",
      resolved === "atmospheric-dark" ? "dark" : "light"
    );
  }
})();
