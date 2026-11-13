/*
 * Ambilight screen-sampling panel rendering, polling, and event bindings.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import {
  appState,
  clampInt,
  computeLiveFps,
  rgbToHex,
  t,
  updateSliderFill
} from "./store.js";
import { setStatusMessage } from "./toasts.js";

/* Sondea cada 400ms el color muestreado mientras Ambilight este activo */
export function syncAmbilightPolling() {
  const isActive = Boolean(appState.ambilight && appState.ambilight.active);
  if (isActive && !appState.ambilightPollTimer) {
    appState.ambilightPollTimer = setInterval(() => {
      if (document.hidden) return;
      invokeApi(() => getBackendApi().get_ambilight_status(), null);
    }, 400);
  } else if (!isActive && appState.ambilightPollTimer) {
    clearInterval(appState.ambilightPollTimer);
    appState.ambilightPollTimer = null;
  }
}

/* Sincroniza el panel de Ambilight, la lista de pantallas y la muestra de color en vivo */
export function renderAmbilightPanel() {
  const ambi = appState.ambilight || {
    active: false,
    monitor_index: 1,
    color_mode: "vibrant",
    auto_brightness: true,
    min_brightness: 10,
    brightness: 85,
    smoothing_alpha: 0.38,
    last_color: null,
    frames_sent: 0
  };

  const tabDot = document.getElementById("tab-ambilight-dot");
  if (tabDot) {
    tabDot.hidden = !ambi.active;
  }

  const monitorSelect = document.getElementById("ambilight-monitor-select");
  if (monitorSelect && Array.isArray(appState.monitors) && appState.monitors.length > 0) {
    const currentOptions = Array.from(monitorSelect.options).map((o) => `${o.value}:${o.textContent}`).join("|");
    const nextOptions = appState.monitors.map((m) => `${m.index}:${m.label}`).join("|");
    if (currentOptions !== nextOptions) {
      monitorSelect.replaceChildren();
      appState.monitors.forEach((mon) => {
        const opt = document.createElement("option");
        opt.value = String(mon.index);
        opt.textContent = mon.label;
        monitorSelect.appendChild(opt);
      });
    }
    monitorSelect.value = String(ambi.monitor_index ?? 1);
  }

  const badge = document.getElementById("ambilight-status-badge");
  if (badge) {
    badge.setAttribute("data-active", String(Boolean(ambi.active)));
    badge.setAttribute("data-live", String(Boolean(ambi.active)));
    badge.textContent = ambi.active ? t("ambi.statusLive") : t("ambi.statusStandby");
  }

  const framesEl = document.getElementById("ambilight-frames-readout");
  if (framesEl) {
    const fps = computeLiveFps(appState.ambiTelemetry, Boolean(ambi.active), ambi.frames_sent, 10);
    framesEl.textContent = t("ambi.telemetryFpsFrames", {
      fps,
      count: ambi.frames_sent || 0
    });
  }

  const swatch = document.getElementById("ambilight-preview-swatch");
  const colorReadout = document.getElementById("ambilight-color-readout");
  const lastColor = ambi.last_color;
  if (lastColor && typeof lastColor.r === "number") {
    const cssRgb = `rgb(${lastColor.r}, ${lastColor.g}, ${lastColor.b})`;
    const hex = (lastColor.hex || rgbToHex(lastColor.r, lastColor.g, lastColor.b)).toUpperCase();
    if (swatch) {
      swatch.style.setProperty("--ambilight-swatch-color", cssRgb);
    }
    if (colorReadout) {
      colorReadout.textContent = `RGB (${lastColor.r}, ${lastColor.g}, ${lastColor.b}) · ${hex}`;
    }
    if (ambi.active) {
      document.documentElement.style.setProperty("--beam-color", cssRgb);
    }
  }

  const toggleBtn = document.getElementById("toggle-ambilight-btn");
  const toggleLabel = document.getElementById("toggle-ambilight-label");
  if (toggleBtn && toggleLabel) {
    toggleBtn.setAttribute("aria-pressed", String(Boolean(ambi.active)));
    toggleLabel.textContent = ambi.active ? t("ambi.stopBtn") : t("ambi.startBtn");
  }

  document.querySelectorAll(".ambilight-mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.colorMode === (ambi.color_mode || "vibrant"));
  });

  const alphaSlider = document.getElementById("ambilight-smoothing-slider");
  const alphaOutput = document.getElementById("ambilight-smoothing-output");
  if (alphaSlider && alphaOutput && typeof ambi.smoothing_alpha === "number") {
    alphaSlider.value = String(ambi.smoothing_alpha);
    alphaOutput.textContent = Number(ambi.smoothing_alpha).toFixed(2);
    updateSliderFill(alphaSlider);
  }

  const autoBrightnessCheckbox = document.getElementById("ambilight-auto-brightness");
  if (autoBrightnessCheckbox && typeof ambi.auto_brightness === "boolean") {
    autoBrightnessCheckbox.checked = ambi.auto_brightness;
  }

  const minBriRow = document.getElementById("ambilight-min-brightness-row");
  const minBriSlider = document.getElementById("ambilight-min-brightness-slider");
  const minBriOutput = document.getElementById("ambilight-min-brightness-output");
  const isAutoBri = Boolean(ambi.auto_brightness ?? true);
  const floorVal = clampInt(ambi.min_brightness != null ? ambi.min_brightness : 10, 5, 20);
  if (minBriRow) {
    minBriRow.classList.toggle("is-disabled", !isAutoBri);
  }
  if (minBriSlider && minBriOutput) {
    minBriSlider.value = String(floorVal);
    minBriSlider.disabled = !isAutoBri;
    minBriOutput.textContent = `${floorVal}%`;
    updateSliderFill(minBriSlider);
  }
}

export function bindAmbilightEvents() {
  const readAmbilightParamsFromDom = () => {
    const monSelect = document.getElementById("ambilight-monitor-select");
    const activeModeBtn = document.querySelector(".ambilight-mode-btn.active");
    const alphaSlider = document.getElementById("ambilight-smoothing-slider");
    const autoBriCheckbox = document.getElementById("ambilight-auto-brightness");
    const minBriSlider = document.getElementById("ambilight-min-brightness-slider");
    const briSlider = document.getElementById("brightness-slider");

    return {
      monitorIndex: Number(monSelect ? monSelect.value : 1),
      colorMode: activeModeBtn ? activeModeBtn.dataset.colorMode : "vibrant",
      smoothingAlpha: Number(alphaSlider ? alphaSlider.value : 0.38),
      autoBrightness: Boolean(autoBriCheckbox ? autoBriCheckbox.checked : true),
      minBrightness: clampInt(minBriSlider ? minBriSlider.value : 10, 5, 20),
      brightness: clampInt(briSlider ? briSlider.value : 85, 10, 100)
    };
  };

  const startOrUpdateAmbilight = (statusMsg) => {
    const p = readAmbilightParamsFromDom();
    invokeApi(
      () =>
        getBackendApi().start_ambilight(
          p.monitorIndex,
          p.colorMode,
          p.autoBrightness,
          p.brightness,
          p.smoothingAlpha,
          null,
          p.minBrightness
        ),
      statusMsg
    );
  };

  const toggleAmbilightBtn = document.getElementById("toggle-ambilight-btn");
  if (toggleAmbilightBtn) {
    toggleAmbilightBtn.addEventListener("click", () => {
      if (appState.ambilight && appState.ambilight.active) {
        invokeApi(() => getBackendApi().stop_ambilight(), () => t("status.ambiStopped"));
      } else {
        startOrUpdateAmbilight(() => t("status.ambiStarted"));
      }
    });
  }

  const monitorSelect = document.getElementById("ambilight-monitor-select");
  if (monitorSelect) {
    monitorSelect.addEventListener("change", () => {
      appState.ambilight.monitor_index = Number(monitorSelect.value);
      if (appState.ambilight.active) {
        startOrUpdateAmbilight(() =>
          t("status.ambiDisplaySwitched", { display: monitorSelect.value })
        );
      }
    });
  }

  document.querySelectorAll(".ambilight-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ambilight-mode-btn").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      appState.ambilight.color_mode = btn.dataset.colorMode || "vibrant";
      if (appState.ambilight.active) {
        startOrUpdateAmbilight(() =>
          t("status.ambiModeChanged", { mode: appState.ambilight.color_mode })
        );
      }
    });
  });

  const alphaSlider = document.getElementById("ambilight-smoothing-slider");
  const alphaOutput = document.getElementById("ambilight-smoothing-output");
  if (alphaSlider && alphaOutput) {
    alphaSlider.addEventListener("input", () => {
      alphaOutput.textContent = Number(alphaSlider.value).toFixed(2);
      updateSliderFill(alphaSlider);
    });
    alphaSlider.addEventListener("change", () => {
      updateSliderFill(alphaSlider);
      appState.ambilight.smoothing_alpha = Number(alphaSlider.value);
      if (appState.ambilight.active) {
        startOrUpdateAmbilight(() =>
          t("status.ambiSmoothingChanged", {
            alpha: Number(alphaSlider.value).toFixed(2)
          })
        );
      }
    });
  }

  const autoBrightnessCheckbox = document.getElementById("ambilight-auto-brightness");
  const minBriRow = document.getElementById("ambilight-min-brightness-row");
  const minBriSlider = document.getElementById("ambilight-min-brightness-slider");
  const minBriOutput = document.getElementById("ambilight-min-brightness-output");
  if (autoBrightnessCheckbox) {
    autoBrightnessCheckbox.addEventListener("change", () => {
      const isChecked = autoBrightnessCheckbox.checked;
      appState.ambilight.auto_brightness = isChecked;
      if (minBriRow) minBriRow.classList.toggle("is-disabled", !isChecked);
      if (minBriSlider) minBriSlider.disabled = !isChecked;
      if (appState.ambilight.active) {
        startOrUpdateAmbilight(() =>
          t(isChecked ? "status.ambiAutoBriOn" : "status.ambiAutoBriOff")
        );
      }
    });
  }

  if (minBriSlider && minBriOutput) {
    minBriSlider.addEventListener("input", () => {
      const val = clampInt(minBriSlider.value, 5, 20);
      minBriOutput.textContent = `${val}%`;
      updateSliderFill(minBriSlider);
    });
    minBriSlider.addEventListener("change", () => {
      const val = clampInt(minBriSlider.value, 5, 20);
      updateSliderFill(minBriSlider);
      appState.ambilight.min_brightness = val;
      if (appState.ambilight.active) {
        startOrUpdateAmbilight(() => t("status.ambiMinBriChanged", { floor: val }));
      } else {
        setStatusMessage(t("status.ambiMinBriChanged", { floor: val }));
      }
    });
  }
}
