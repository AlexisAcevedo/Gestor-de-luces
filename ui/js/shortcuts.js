/*
 * Keyboard shortcuts, dialog light-dismiss fallbacks, and window auto-fit geometry.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import {
  appState,
  clampInt,
  getPrimaryBulb,
  t,
  updateSliderFill
} from "./store.js";
import { setStatusMessage } from "./toasts.js";

/*
 * Respaldo obligatorio de light-dismiss para navegadores que aun no implementan
 * nativamente el atributo declarativo `<dialog closedby="any">`.
 */
export function setupDialogLightDismissFallbacks() {
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    document.querySelectorAll("dialog").forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;

        if (isDialogContent) return;
        dialog.close();
      });
    });
  }

  document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dialogId = btn.getAttribute("data-close-dialog");
      const dialog = dialogId ? document.getElementById(dialogId) : null;
      if (dialog) dialog.close();
    });
  });
}

/* Atajos globales: se ignoran al escribir, con modificadores o con un dialogo abierto */
const SHORTCUT_BRIGHTNESS_STEP = 5;
let pendingBrightness = null;
let brightnessTimer = null;

function isTypingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function nudgeBrightness(delta) {
  const primary = getPrimaryBulb();
  if (!primary) return;
  const base = pendingBrightness !== null ? pendingBrightness : primary.state.brightness;
  const val = clampInt(base + delta, 10, 100);
  pendingBrightness = val;

  const slider = document.getElementById("brightness-slider");
  const output = document.getElementById("brightness-output");
  if (slider) {
    slider.value = String(val);
    updateSliderFill(slider);
  }
  if (output) output.textContent = `${val}%`;

  /* Se envia un solo comando al dejar de pulsar (mantener la tecla genera repeticiones) */
  clearTimeout(brightnessTimer);
  brightnessTimer = setTimeout(() => {
    const target = pendingBrightness;
    pendingBrightness = null;
    invokeApi(
      () => getBackendApi().set_brightness(target, null),
      () => t("status.brightnessSet", { brightness: target })
    );
  }, 250);
}

export function setupGlobalShortcuts({ activateTab }) {
  const tabs = Array.from(document.querySelectorAll(".mode-tab"));
  tabs.forEach((tab, idx) => tab.setAttribute("aria-keyshortcuts", String(idx + 1)));

  const helpBtn = document.getElementById("shortcuts-help-btn");
  const helpDialog = document.getElementById("shortcuts-dialog");
  const openHelp = () => {
    if (helpDialog && !helpDialog.open) helpDialog.showModal();
  };
  if (helpBtn) helpBtn.addEventListener("click", openHelp);

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey) return;
    if (document.querySelector("dialog[open]")) return;
    const target = event.target;
    if (isTypingTarget(target)) return;

    if (event.altKey) {
      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        const step = event.shiftKey ? SHORTCUT_BRIGHTNESS_STEP * 2 : SHORTCUT_BRIGHTNESS_STEP;
        event.preventDefault();
        nudgeBrightness(event.key === "ArrowUp" ? step : -step);
      }
      return;
    }

    if (event.key === "?") {
      event.preventDefault();
      openHelp();
      return;
    }

    if (/^[1-6]$/.test(event.key)) {
      const tab = tabs[Number(event.key) - 1];
      if (tab) {
        event.preventDefault();
        activateTab(tab.dataset.mode, false);
      }
      return;
    }

    /* Espacio sobre controles interactivos conserva su comportamiento nativo */
    if (event.key === " " || event.code === "Space") {
      if (target && target.closest && target.closest("button, a, summary, [role='tab'], label")) {
        return;
      }
      event.preventDefault();
      const masterPowerBtn = document.getElementById("master-power-btn");
      if (masterPowerBtn) masterPowerBtn.click();
    }
  });
}

/*
 * Window auto-fit ("widget" behavior): the native window height follows the natural content
 * height of the active section, so every tab shows its own content in full and no grid scrolls
 * inside. Heights are summed from the stage children (never scrollHeight, which reports the
 * stretched stage itself) while `.is-measuring` disables stretching, all in one task.
 */
const FIT_THRESHOLD_PX = 2;
const FIT_RETRY_MS = 180;
const FIT_OWN_RESIZE_WINDOW_MS = 800;
const FIT_BURST_LIMIT = 3;
const FIT_BURST_WINDOW_MS = 1000;
let fitFrame = 0;
let fitForced = false;
let fitLastSent = 0;
let fitLastSentAt = 0;
let fitSentAt = [];
let fitBudgetTripped = false;

function readNaturalHeight(stage) {
  const topbar = document.querySelector(".compact-topbar");
  const style = window.getComputedStyle(stage);
  const gap = parseFloat(style.rowGap) || 0;
  const children = Array.from(stage.children).filter((el) => el.getClientRects().length > 0);
  const childrenHeight = children.reduce((sum, el) => sum + el.getBoundingClientRect().height, 0);
  const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  const gaps = Math.max(children.length - 1, 0) * gap;
  const topbarHeight = topbar ? topbar.getBoundingClientRect().height : 0;
  return Math.ceil(topbarHeight + padding + gaps + childrenHeight);
}

function measureNaturalHeight(stage) {
  stage.classList.add("is-measuring");
  try {
    return readNaturalHeight(stage);
  } finally {
    stage.classList.remove("is-measuring");
  }
}

/*
 * Cortafuegos: si la medicion oscilara (por ejemplo porque el ancho util cambia al aparecer
 * una barra de scroll), cada ciclo pediria un resize nativo nuevo y la ventana quedaria
 * saturada de WM_SIZE, con la UI sin responder a los clics. El presupuesto es un pestillo:
 * al agotarse se cortan todos los pedidos automaticos hasta el proximo `requestFit(true)`
 * (cambio de seccion, idioma o tema), que lo reinicia.
 */
function fitBudgetAllows() {
  if (fitBudgetTripped) return false;
  const now = performance.now();
  fitSentAt = fitSentAt.filter((sentAt) => now - sentAt < FIT_BURST_WINDOW_MS);
  if (fitSentAt.length >= FIT_BURST_LIMIT) {
    fitBudgetTripped = true;
    return false;
  }
  return true;
}

function runFit() {
  fitFrame = 0;
  const forced = fitForced;
  const root = document.documentElement;
  if (root.classList.contains("is-resizing")) {
    const own = performance.now() - fitLastSentAt < FIT_OWN_RESIZE_WINDOW_MS;
    if (forced || own) {
      fitForced = forced;
      window.setTimeout(scheduleFit, FIT_RETRY_MS);
    }
    return;
  }
  fitForced = false;
  const api = getBackendApi();
  const stage = document.querySelector(".photometric-stage");
  if (!stage || !api || typeof api.fit_window_height !== "function") return;
  const target = measureNaturalHeight(stage);
  if (target < 200 || Math.abs(target - fitLastSent) < FIT_THRESHOLD_PX) return;
  if (!fitBudgetAllows()) return;
  fitLastSent = target;
  fitLastSentAt = performance.now();
  fitSentAt.push(fitLastSentAt);
  try {
    Promise.resolve(api.fit_window_height(target)).catch(() => {});
  } catch (_err) {
    /* the feature degrades to a regular fixed-size window */
  }
}

function scheduleFit() {
  if (!fitFrame) fitFrame = requestAnimationFrame(runFit);
}

export function requestFit(force) {
  if (force) {
    fitForced = true;
    // Un pedido explicito siempre puede reajustar: reinicia el presupuesto anti-oscilacion.
    fitSentAt = [];
    fitBudgetTripped = false;
  }
  scheduleFit();
}

export function setupWindowFit() {
  const stage = document.querySelector(".photometric-stage");
  if (!stage) return;
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => requestFit(false));
    Array.from(stage.children).forEach((el) => observer.observe(el));
  }
  if (typeof MutationObserver === "function") {
    const mutations = new MutationObserver(() => requestFit(false));
    ["scenes-grid", "custom-scenes-grid"].forEach((id) => {
      const grid = document.getElementById(id);
      if (grid) mutations.observe(grid, { childList: true });
    });
  }
  requestFit(true);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => requestFit(true));
  }
}

export const DEFAULT_GLOBAL_HOTKEY_BINDINGS = Object.freeze({
  toggle_power: "Ctrl+Alt+P",
  brightness_up: "Ctrl+Alt+Up",
  brightness_down: "Ctrl+Alt+Down",
  toggle_ambilight: "Ctrl+Alt+A",
  toggle_music_sync: "Ctrl+Alt+M",
  toggle_window: "Ctrl+Alt+W"
});

const HOTKEY_ACTION_KEYS = Object.keys(DEFAULT_GLOBAL_HOTKEY_BINDINGS);
const MODIFIER_ALIASES = {
  ctrl: "Ctrl",
  control: "Ctrl",
  alt: "Alt",
  shift: "Shift",
  win: "Win",
  windows: "Win",
  super: "Win",
  meta: "Win"
};
const SPECIAL_KEYS = {
  up: "Up",
  arrowup: "Up",
  down: "Down",
  arrowdown: "Down",
  left: "Left",
  arrowleft: "Left",
  right: "Right",
  arrowright: "Right",
  space: "Space",
  " ": "Space",
  home: "Home",
  end: "End",
  pageup: "PageUp",
  pgup: "PageUp",
  pagedown: "PageDown",
  pgdn: "PageDown"
};

export function normalizeHotkeyComboInput(raw) {
  const cleaned = String(raw || "").trim();
  if (!cleaned) return "";
  const parts = cleaned.split("+").map((p) => p.trim());
  if (parts.some((p) => !p)) return null;
  const mods = new Set();
  let primaryKey = null;
  for (const part of parts) {
    const mod = MODIFIER_ALIASES[part.toLowerCase()];
    if (mod) {
      if (primaryKey !== null) return null;
      mods.add(mod);
    } else if (primaryKey !== null) {
      return null;
    } else {
      primaryKey = part;
    }
  }
  if (mods.size === 0 || !primaryKey) return null;

  let canonicalKey = null;
  const lower = primaryKey.toLowerCase();
  if (/^[a-z0-9]$/i.test(primaryKey)) {
    canonicalKey = primaryKey.toUpperCase();
  } else if (/^f([1-9]|1[0-2])$/.test(lower)) {
    canonicalKey = primaryKey.toUpperCase();
  } else if (Object.hasOwn(SPECIAL_KEYS, lower)) {
    canonicalKey = SPECIAL_KEYS[lower];
  }
  if (!canonicalKey) return null;

  const orderedMods = ["Ctrl", "Alt", "Shift", "Win"].filter((m) => mods.has(m));
  return [...orderedMods, canonicalKey].join("+");
}

function captureHotkeyFromEvent(event) {
  if (!event || event.isComposing) return null;
  const key = event.key || "";
  if (["Control", "Alt", "Shift", "Meta", "OS"].includes(key)) return null;
  const mods = [];
  if (event.ctrlKey) mods.push("Ctrl");
  if (event.altKey) mods.push("Alt");
  if (event.shiftKey) mods.push("Shift");
  if (event.metaKey) mods.push("Win");
  if (mods.length === 0) return null;

  let canonicalKey = null;
  const lower = key.toLowerCase();
  if (/^[a-z0-9]$/i.test(key)) {
    canonicalKey = key.toUpperCase();
  } else if (/^f([1-9]|1[0-2])$/.test(lower)) {
    canonicalKey = key.toUpperCase();
  } else if (Object.hasOwn(SPECIAL_KEYS, lower)) {
    canonicalKey = SPECIAL_KEYS[lower];
  } else if (event.code === "Space") {
    canonicalKey = "Space";
  }
  if (!canonicalKey) return null;
  return [...mods, canonicalKey].join("+");
}

function formatHotkeyErrorMessage(code) {
  if (code === "in_use") return t("hotkeys.errInUse");
  if (code === "register_failed") return t("hotkeys.errRegisterFailed");
  return code ? String(code) : "";
}

export function renderGlobalHotkeys() {
  const hk = appState.globalHotkeys || { enabled: false, supported: false, bindings: {}, errors: {} };
  const enabledCheckbox = document.getElementById("global-hotkeys-enabled");
  if (enabledCheckbox) {
    enabledCheckbox.checked = Boolean(hk.enabled);
    enabledCheckbox.disabled = !hk.supported;
  }

  const unsupportedNotice = document.getElementById("global-hotkeys-unsupported");
  if (unsupportedNotice) unsupportedNotice.hidden = Boolean(hk.supported);

  const errorSummary = document.getElementById("global-hotkeys-error");
  if (errorSummary) {
    errorSummary.textContent = "";
    errorSummary.hidden = true;
  }

  const activeEl = typeof document !== "undefined" ? document.activeElement : null;
  HOTKEY_ACTION_KEYS.forEach((action) => {
    const input = document.getElementById(`hotkey-input-${action}`);
    if (input) {
      if (input !== activeEl) {
        input.value = (hk.bindings && Object.hasOwn(hk.bindings, action))
          ? hk.bindings[action]
          : DEFAULT_GLOBAL_HOTKEY_BINDINGS[action];
      }
      input.disabled = !hk.supported;
      const errCode = hk.errors && hk.errors[action];
      if (errCode) {
        input.setAttribute("aria-invalid", "true");
      } else {
        input.removeAttribute("aria-invalid");
      }
    }
    const clearBtn = document.querySelector(`[data-hotkey-clear="${action}"]`);
    if (clearBtn) clearBtn.disabled = !hk.supported;

    const rowErr = document.getElementById(`hotkey-error-${action}`);
    if (rowErr) {
      const msg = formatHotkeyErrorMessage(hk.errors && hk.errors[action]);
      rowErr.textContent = msg;
      rowErr.hidden = !msg;
    }
  });

  const saveBtn = document.getElementById("save-global-hotkeys-btn");
  const resetBtn = document.getElementById("reset-global-hotkeys-btn");
  if (saveBtn) saveBtn.disabled = !hk.supported;
  if (resetBtn) resetBtn.disabled = !hk.supported;
}

export function bindGlobalHotkeyEvents() {
  const errorSummary = document.getElementById("global-hotkeys-error");
  const showSummaryError = (msg) => {
    if (!errorSummary) return;
    errorSummary.textContent = msg;
    errorSummary.hidden = !msg;
  };

  HOTKEY_ACTION_KEYS.forEach((action) => {
    const input = document.getElementById(`hotkey-input-${action}`);
    if (input) {
      input.addEventListener("input", () => {
        input.removeAttribute("aria-invalid");
        const rowErr = document.getElementById(`hotkey-error-${action}`);
        if (rowErr) {
          rowErr.textContent = "";
          rowErr.hidden = true;
        }
        showSummaryError("");
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Tab" || event.key === "Escape") return;
        if (
          (event.key === "Backspace" || event.key === "Delete") &&
          !event.ctrlKey && !event.altKey && !event.shiftKey && !event.metaKey
        ) {
          event.preventDefault();
          input.value = "";
          input.removeAttribute("aria-invalid");
          return;
        }
        const captured = captureHotkeyFromEvent(event);
        if (captured) {
          event.preventDefault();
          input.value = captured;
          input.removeAttribute("aria-invalid");
          showSummaryError("");
        }
      });
    }

    const clearBtn = document.querySelector(`[data-hotkey-clear="${action}"]`);
    if (clearBtn && input) {
      clearBtn.addEventListener("click", () => {
        input.value = "";
        input.removeAttribute("aria-invalid");
        const rowErr = document.getElementById(`hotkey-error-${action}`);
        if (rowErr) {
          rowErr.textContent = "";
          rowErr.hidden = true;
        }
        showSummaryError("");
      });
    }
  });

  const resetBtn = document.getElementById("reset-global-hotkeys-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      HOTKEY_ACTION_KEYS.forEach((action) => {
        const input = document.getElementById(`hotkey-input-${action}`);
        if (input) {
          input.value = DEFAULT_GLOBAL_HOTKEY_BINDINGS[action];
          input.removeAttribute("aria-invalid");
        }
        const rowErr = document.getElementById(`hotkey-error-${action}`);
        if (rowErr) {
          rowErr.textContent = "";
          rowErr.hidden = true;
        }
      });
      showSummaryError("");
      setStatusMessage(t("hotkeys.resetDone"));
    });
  }

  const saveBtn = document.getElementById("save-global-hotkeys-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const enabledCheckbox = document.getElementById("global-hotkeys-enabled");
      const enabled = Boolean(enabledCheckbox && enabledCheckbox.checked);
      const nextBindings = {};
      const seen = new Map();

      for (const action of HOTKEY_ACTION_KEYS) {
        const input = document.getElementById(`hotkey-input-${action}`);
        const rowErr = document.getElementById(`hotkey-error-${action}`);
        if (rowErr) {
          rowErr.textContent = "";
          rowErr.hidden = true;
        }
        const normalized = normalizeHotkeyComboInput(input ? input.value : "");
        if (normalized === null) {
          if (input) {
            input.setAttribute("aria-invalid", "true");
            if (typeof input.focus === "function") input.focus();
          }
          if (rowErr) {
            rowErr.textContent = t("hotkeys.errInvalid");
            rowErr.hidden = false;
          }
          showSummaryError(t("hotkeys.errInvalid"));
          return;
        }
        if (normalized && seen.has(normalized)) {
          if (input) {
            input.setAttribute("aria-invalid", "true");
            if (typeof input.focus === "function") input.focus();
          }
          if (rowErr) {
            rowErr.textContent = t("hotkeys.errDuplicate");
            rowErr.hidden = false;
          }
          showSummaryError(t("hotkeys.errDuplicate"));
          return;
        }
        if (normalized) seen.set(normalized, action);
        nextBindings[action] = normalized;
      }

      const api = getBackendApi();
      if (!api || typeof api.set_global_hotkeys !== "function") return;
      saveBtn.disabled = true;
      try {
        await invokeApi(
          () => api.set_global_hotkeys(enabled, nextBindings),
          () => t("hotkeys.saved")
        );
      } finally {
        saveBtn.disabled = !appState.globalHotkeys.supported;
      }
    });
  }
}

/* Suspende transiciones CSS mientras se redimensiona la ventana (se restauran 150 ms despues). */
export function setupResizeThrottle() {
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    document.documentElement.classList.add("is-resizing");
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      document.documentElement.classList.remove("is-resizing");
    }, 150);
  }, { passive: true });
}
