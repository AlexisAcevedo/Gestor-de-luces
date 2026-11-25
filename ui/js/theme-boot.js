/*
 * Synchronous pre-CSS theme bootstrap (FOUC prevention under strict CSP).
 *
 * Runs before stylesheets load so the first paint uses the persisted theme
 * passed via URL hash (`#theme=...` from DesktopApplication) or localStorage.
 */
(function bootstrapInitialTheme() {
  var ALLOWED = {
    "architectural-stone": true,
    "atmospheric-dark": true
  };
  var DEFAULT_THEME = "architectural-stone";
  var UI_PREFS_STORAGE_KEY = "gestor_luces_ui_prefs";

  function normalize(value) {
    if (typeof value !== "string") return null;
    var cleaned = value.trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(ALLOWED, cleaned) ? cleaned : null;
  }

  function readThemeFromHash() {
    try {
      var hash = String((window.location && window.location.hash) || "");
      if (!hash || hash === "#") return null;
      var query = hash.charAt(0) === "#" ? hash.slice(1) : hash;
      var params = new URLSearchParams(query);
      return normalize(params.get("theme"));
    } catch (_err) {
      return null;
    }
  }

  function readThemeFromStorage() {
    try {
      if (!window.localStorage) return null;
      var raw = window.localStorage.getItem(UI_PREFS_STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? normalize(parsed.theme) : null;
    } catch (_err) {
      return null;
    }
  }

  var resolved = readThemeFromHash() || readThemeFromStorage() || DEFAULT_THEME;
  var root = document.documentElement;
  if (root && root.dataset) {
    root.dataset.theme = resolved;
  } else if (root && typeof root.setAttribute === "function") {
    root.setAttribute("data-theme", resolved);
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
