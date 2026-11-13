/*
 * Music Sync (WASAPI Loopback + FFT spectrum) panel rendering, polling, and event bindings.
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

/* Sondea cada 250ms la telemetria acustica (Bass/Mid/Treble/RMS) mientras Music Sync este activo */
export function syncMusicPolling() {
  const isActive = Boolean(appState.musicSync && appState.musicSync.active);
  if (isActive && !appState.musicPollTimer) {
    appState.musicPollTimer = setInterval(() => {
      if (document.hidden) return;
      invokeApi(() => getBackendApi().get_music_sync_status(), null);
    }, 250);
  } else if (!isActive && appState.musicPollTimer) {
    clearInterval(appState.musicPollTimer);
    appState.musicPollTimer = null;
  }
}

/* Actualiza las barras espectrales FFT, la muestra cromatica y la configuracion de WASAPI */
export function renderMusicPanel() {
  const music = appState.musicSync || {
    active: false,
    device_index: null,
    palette_mode: "spectrum",
    sensitivity: 1.0,
    smoothing_alpha: 0.50,
    audio_brightness: true,
    brightness: 85,
    rms: 0.0,
    bass: 0.0,
    mid: 0.0,
    treble: 0.0,
    last_color: null,
    frames_sent: 0
  };

  const tabDot = document.getElementById("tab-music-dot");
  if (tabDot) {
    tabDot.hidden = !music.active;
  }

  const devSelect = document.getElementById("music-device-select");
  if (devSelect && Array.isArray(appState.audioDevices) && appState.audioDevices.length > 0) {
    const currentOpts = Array.from(devSelect.options)
      .map((o) => `${o.value}:${o.textContent}`)
      .join("|");
    const nextOpts = appState.audioDevices.map((d) => `${d.index}:${d.label}`).join("|");
    if (currentOpts !== nextOpts) {
      devSelect.replaceChildren();
      appState.audioDevices.forEach((dev) => {
        const opt = document.createElement("option");
        opt.value = String(dev.index);
        opt.textContent = dev.label;
        devSelect.appendChild(opt);
      });
    }
    if (music.device_index !== null && music.device_index !== undefined) {
      devSelect.value = String(music.device_index);
    }
  }

  const badge = document.getElementById("music-status-badge");
  if (badge) {
    badge.setAttribute("data-active", String(Boolean(music.active)));
    badge.setAttribute("data-live", String(Boolean(music.active)));
    badge.textContent = music.active ? t("music.statusLive") : t("music.statusStandby");
  }

  const framesEl = document.getElementById("music-frames-readout");
  if (framesEl) {
    const fps = computeLiveFps(appState.musicTelemetry, Boolean(music.active), music.frames_sent, 11);
    framesEl.textContent = t("music.telemetryFpsFrames", {
      fps,
      count: music.frames_sent || 0
    });
  }

  const swatch = document.getElementById("music-preview-swatch");
  const colorReadout = document.getElementById("music-color-readout");
  const lastColor = music.last_color;
  if (lastColor && typeof lastColor.r === "number") {
    const cssRgb = `rgb(${lastColor.r}, ${lastColor.g}, ${lastColor.b})`;
    const hex = (lastColor.hex || rgbToHex(lastColor.r, lastColor.g, lastColor.b)).toUpperCase();
    if (swatch) {
      swatch.style.setProperty("--music-swatch-color", cssRgb);
    }
    if (colorReadout) {
      colorReadout.textContent = `RGB (${lastColor.r}, ${lastColor.g}, ${lastColor.b}) · ${hex}`;
    }
    if (music.active) {
      document.documentElement.style.setProperty("--beam-color", cssRgb);
    }
  }

  if (swatch) {
    const peak = Math.max(Number(music.bass) || 0, Number(music.mid) || 0, Number(music.rms) || 0);
    const sens = Math.max(0.4, Number(music.sensitivity) || 1.0);
    const beatThreshold = Math.max(0.22, Math.min(0.85, 0.62 / sens));
    swatch.classList.toggle("is-beat-peak", Boolean(music.active && peak >= beatThreshold));
  }

  const setMeter = (bandName, ratio) => {
    const pct = clampInt(Math.round((Number(ratio) || 0) * 100), 0, 100);
    const fill = document.getElementById(`music-meter-${bandName}-fill`);
    const val = document.getElementById(`music-meter-${bandName}-val`);
    if (fill) fill.style.width = `${pct}%`;
    if (val) val.textContent = `${pct}%`;
  };

  setMeter("bass", music.bass);
  setMeter("mid", music.mid);
  setMeter("treble", music.treble);
  setMeter("rms", music.rms);

  const toggleBtn = document.getElementById("toggle-music-btn");
  const toggleLabel = document.getElementById("toggle-music-label");
  if (toggleBtn && toggleLabel) {
    toggleBtn.setAttribute("aria-pressed", String(Boolean(music.active)));
    toggleLabel.textContent = music.active ? t("music.stopBtn") : t("music.startBtn");
  }

  document.querySelectorAll(".music-palette-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.paletteMode === (music.palette_mode || "spectrum"));
  });

  const sensSlider = document.getElementById("music-sensitivity-slider");
  const sensOutput = document.getElementById("music-sensitivity-output");
  if (sensSlider && sensOutput && typeof music.sensitivity === "number") {
    sensSlider.value = String(music.sensitivity);
    sensOutput.textContent = `${Number(music.sensitivity).toFixed(1)}x`;
    updateSliderFill(sensSlider);
  }

  const alphaSlider = document.getElementById("music-smoothing-slider");
  const alphaOutput = document.getElementById("music-smoothing-output");
  if (alphaSlider && alphaOutput && typeof music.smoothing_alpha === "number") {
    alphaSlider.value = String(music.smoothing_alpha);
    alphaOutput.textContent = Number(music.smoothing_alpha).toFixed(2);
    updateSliderFill(alphaSlider);
  }

  const audioBriCheckbox = document.getElementById("music-audio-brightness");
  if (audioBriCheckbox && typeof music.audio_brightness === "boolean") {
    audioBriCheckbox.checked = music.audio_brightness;
  }
}

export function bindMusicEvents() {
  const readMusicParamsFromDom = () => {
    const devSelect = document.getElementById("music-device-select");
    const activePaletteBtn = document.querySelector(".music-palette-btn.active");
    const sensSlider = document.getElementById("music-sensitivity-slider");
    const alphaSlider = document.getElementById("music-smoothing-slider");
    const audioBriCheckbox = document.getElementById("music-audio-brightness");
    const briSlider = document.getElementById("brightness-slider");

    const rawDev = devSelect ? Number(devSelect.value) : -1;
    return {
      deviceIndex: rawDev >= 0 ? rawDev : null,
      paletteMode: activePaletteBtn ? activePaletteBtn.dataset.paletteMode : "spectrum",
      sensitivity: Number(sensSlider ? sensSlider.value : 1.0),
      smoothingAlpha: Number(alphaSlider ? alphaSlider.value : 0.50),
      audioBrightness: Boolean(audioBriCheckbox ? audioBriCheckbox.checked : true),
      brightness: clampInt(briSlider ? briSlider.value : 85, 10, 100)
    };
  };

  const startOrUpdateMusicSync = (statusMsg) => {
    const p = readMusicParamsFromDom();
    invokeApi(
      () =>
        getBackendApi().start_music_sync(
          p.paletteMode,
          p.sensitivity,
          p.smoothingAlpha,
          p.audioBrightness,
          p.brightness,
          p.deviceIndex,
          null
        ),
      statusMsg
    );
  };

  const toggleMusicBtn = document.getElementById("toggle-music-btn");
  if (toggleMusicBtn) {
    toggleMusicBtn.addEventListener("click", () => {
      if (appState.musicSync && appState.musicSync.active) {
        invokeApi(() => getBackendApi().stop_music_sync(), () => t("status.musicStopped"));
      } else {
        startOrUpdateMusicSync(() => t("status.musicStarted"));
      }
    });
  }

  const musicDevSelect = document.getElementById("music-device-select");
  if (musicDevSelect) {
    musicDevSelect.addEventListener("change", () => {
      const val = Number(musicDevSelect.value);
      appState.musicSync.device_index = val >= 0 ? val : null;
      if (appState.musicSync.active) {
        startOrUpdateMusicSync(() => t("status.musicDeviceSwitched"));
      }
    });
  }

  document.querySelectorAll(".music-palette-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".music-palette-btn").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      appState.musicSync.palette_mode = btn.dataset.paletteMode || "spectrum";
      if (appState.musicSync.active) {
        startOrUpdateMusicSync(() =>
          t("status.musicPaletteChanged", { palette: appState.musicSync.palette_mode })
        );
      }
    });
  });

  const musicSensSlider = document.getElementById("music-sensitivity-slider");
  const musicSensOutput = document.getElementById("music-sensitivity-output");
  if (musicSensSlider && musicSensOutput) {
    musicSensSlider.addEventListener("input", () => {
      musicSensOutput.textContent = `${Number(musicSensSlider.value).toFixed(1)}x`;
      updateSliderFill(musicSensSlider);
    });
    musicSensSlider.addEventListener("change", () => {
      updateSliderFill(musicSensSlider);
      appState.musicSync.sensitivity = Number(musicSensSlider.value);
      if (appState.musicSync.active) {
        startOrUpdateMusicSync(() =>
          t("status.musicSensitivityChanged", {
            sensitivity: Number(musicSensSlider.value).toFixed(1)
          })
        );
      }
    });
  }

  const musicAlphaSlider = document.getElementById("music-smoothing-slider");
  const musicAlphaOutput = document.getElementById("music-smoothing-output");
  if (musicAlphaSlider && musicAlphaOutput) {
    musicAlphaSlider.addEventListener("input", () => {
      musicAlphaOutput.textContent = Number(musicAlphaSlider.value).toFixed(2);
      updateSliderFill(musicAlphaSlider);
    });
    musicAlphaSlider.addEventListener("change", () => {
      updateSliderFill(musicAlphaSlider);
      appState.musicSync.smoothing_alpha = Number(musicAlphaSlider.value);
      if (appState.musicSync.active) {
        startOrUpdateMusicSync(() =>
          t("status.musicSmoothingChanged", {
            alpha: Number(musicAlphaSlider.value).toFixed(2)
          })
        );
      }
    });
  }

  /* Botones de preajuste alineados matematicamente bajo los sliders de Ambilight y Music Sync */
  document.querySelectorAll(".scale-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.targetSlider || btn.dataset.sliderTarget;
      const presetValue = btn.dataset.value !== undefined ? btn.dataset.value : btn.dataset.presetValue;
      const slider = targetId ? document.getElementById(targetId) : null;
      if (!slider || presetValue === undefined) return;
      slider.value = presetValue;
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      slider.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  const musicAudioBriCheckbox = document.getElementById("music-audio-brightness");
  if (musicAudioBriCheckbox) {
    musicAudioBriCheckbox.addEventListener("change", () => {
      appState.musicSync.audio_brightness = musicAudioBriCheckbox.checked;
      if (appState.musicSync.active) {
        startOrUpdateMusicSync(() =>
          t(musicAudioBriCheckbox.checked ? "status.musicAudioBriOn" : "status.musicAudioBriOff")
        );
      }
    });
  }
}
