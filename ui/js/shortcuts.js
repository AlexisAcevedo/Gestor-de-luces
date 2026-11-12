/*
 * Keyboard shortcuts, dialog light-dismiss fallbacks, and window auto-fit geometry.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import {
  clampInt,
  getPrimaryBulb,
  t,
  updateSliderFill
} from "./store.js";

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
    if (event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey) return;
    if (document.querySelector("dialog[open]")) return;
    const target = event.target;
    if (isTypingTarget(target)) return;

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

    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      const step = event.shiftKey ? SHORTCUT_BRIGHTNESS_STEP * 2 : SHORTCUT_BRIGHTNESS_STEP;
      event.preventDefault();
      nudgeBrightness(event.key === "ArrowUp" ? step : -step);
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
 * Window auto-fit ("widget" behavior): the native window height is
 * max(baseline, natural content height). The baseline is the natural height of the
 * White tab with every collapsible closed, so the window never shrinks below it.
 * Heights are summed from the stage children (never scrollHeight, which reports the
 * stretched stage itself) while `.is-measuring` disables stretching, all in one task.
 */
const FIT_THRESHOLD_PX = 2;
const FIT_RETRY_MS = 180;
const FIT_OWN_RESIZE_WINDOW_MS = 800;
let fitFrame = 0;
let fitForced = false;
let fitLastSent = 0;
let fitLastSentAt = 0;
let fitBaseline = { width: -1, value: 0 };
let invalidateWindowFitBaseline = null;

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

function measureBaseline(stage) {
  const width = Math.round(stage.getBoundingClientRect().width);
  if (fitBaseline && fitBaseline.width === width && fitBaseline.value > 0) return fitBaseline.value;
  const panels = Array.from(stage.querySelectorAll(":scope > .mode-panel"));
  const previousHidden = panels.map((panel) => panel.hidden);
  panels.forEach((panel) => {
    panel.hidden = panel.id !== "panel-temperature";
  });
  stage.classList.add("is-measuring-baseline");
  let value = 0;
  try {
    value = measureNaturalHeight(stage);
  } finally {
    stage.classList.remove("is-measuring-baseline");
    panels.forEach((panel, index) => {
      panel.hidden = previousHidden[index];
    });
  }
  fitBaseline = { width, value };
  return value;
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
  const target = Math.max(measureBaseline(stage), measureNaturalHeight(stage));
  if (target < 200 || Math.abs(target - fitLastSent) < FIT_THRESHOLD_PX) return;
  fitLastSent = target;
  fitLastSentAt = performance.now();
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
  if (force) fitForced = true;
  scheduleFit();
}

export function invalidateFitBaseline() {
  if (typeof invalidateWindowFitBaseline === "function") {
    invalidateWindowFitBaseline();
  }
}

export function setupWindowFit() {
  const stage = document.querySelector(".photometric-stage");
  if (!stage) return;
  invalidateWindowFitBaseline = () => {
    fitBaseline = null;
  };
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
  window.addEventListener("resize", () => {
    if (fitBaseline && Math.abs(stage.clientWidth - fitBaseline.width) > 1) {
      fitBaseline = null;
    }
  }, { passive: true });
  requestFit(true);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
      fitBaseline = null;
      requestFit(true);
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
