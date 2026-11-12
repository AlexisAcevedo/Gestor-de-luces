/*
 * Primary photometric stage rendering, HSV color wheel, and Kelvin warmth controls.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import {
  SCENE_CATEGORY_COLORS,
  SCENE_CHROMATIC_MAP,
  appState,
  clampInt,
  formatSceneDisplayName,
  getPrimaryBulb,
  hsvToRgb,
  kelvinToCssColor,
  parseHexToRgb,
  rgbToHex,
  rgbToHsv,
  t,
  updateAllSlidersFill,
  updateSliderFill
} from "./store.js";

/* Renderiza la rueda cromatica HSV en el elemento <canvas> */
export function drawColorWheel() {
  const canvas = document.getElementById("color-wheel-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  const radius = width / 2;
  const imageData = ctx.createImageData(width, height);
  const data = imageData.data;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const dx = x - radius;
      const dy = y - radius;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const idx = (y * width + x) * 4;
      if (dist <= radius) {
        let angle = Math.atan2(dy, dx) * (180 / Math.PI);
        if (angle < 0) angle += 360;
        const rgb = hsvToRgb(angle, Math.min(1, dist / radius), 1);
        data[idx] = rgb.r;
        data[idx + 1] = rgb.g;
        data[idx + 2] = rgb.b;
        data[idx + 3] = 255;
      } else {
        data[idx + 3] = 0;
      }
    }
  }
  ctx.putImageData(imageData, 0, 0);
}

export function positionReticleFromRgb(r, g, b) {
  const canvas = document.getElementById("color-wheel-canvas");
  const reticle = document.getElementById("wheel-reticle");
  if (!canvas || !reticle) return;
  const radius = canvas.clientWidth / 2;
  const hsv = rgbToHsv(r, g, b);
  const rad = (hsv.h * Math.PI) / 180;
  const dist = hsv.s * radius;
  reticle.style.left = `${radius + Math.cos(rad) * dist}px`;
  reticle.style.top = `${radius + Math.sin(rad) * dist}px`;
}

function updateApertureGlow(aperture, isOn, brightness) {
  if (!aperture) return;
  aperture.style.removeProperty("background-color");
  aperture.style.removeProperty("box-shadow");
  if (isOn) {
    const briNorm = Math.max(0, Math.min(1, ((Number(brightness) || 100) - 10) / 90));
    aperture.style.setProperty("--aperture-glow-radius", `${Math.round(16 + briNorm * 28)}px`);
    aperture.style.setProperty("--aperture-glow-alpha", `${Math.round(36 + briNorm * 52)}%`);
  } else {
    aperture.style.setProperty("--aperture-glow-radius", "0px");
    aperture.style.setProperty("--aperture-glow-alpha", "0%");
  }
}

/* Sincroniza la cabecera fotometrica, el deslizador de brillo y los paneles de modo */
export function renderStageHeaderAndControls() {
  const shell = document.getElementById("console-shell");
  const targetSummary = document.getElementById("target-summary");
  const statePill = document.getElementById("live-state-pill");
  const telemetryMeta = document.getElementById("telemetry-meta");
  const masterPowerBtn = document.getElementById("master-power-btn");
  const masterPowerLabel = document.getElementById("master-power-label");
  const brightnessSlider = document.getElementById("brightness-slider");
  const brightnessOutput = document.getElementById("brightness-output");

  const primary = getPrimaryBulb();
  const aperture = document.getElementById("photometric-aperture");
  const drawerPillLabel = document.getElementById("drawer-pill-label");
  const drawerPillDot = document.getElementById("drawer-pill-dot");
  if (!primary) {
    if (shell) shell.setAttribute("data-power", "off");
    document.documentElement.style.setProperty("--beam-color", "var(--beam-standby)");
    updateApertureGlow(aperture, false, 0);
    if (targetSummary) targetSummary.textContent = t("stage.noFixture");
    if (drawerPillLabel) drawerPillLabel.textContent = t("stage.noFixture");
    if (drawerPillDot) drawerPillDot.classList.add("is-offline");
    if (statePill) statePill.textContent = t("stage.stateOffline");
    updateAllSlidersFill();
    return;
  }

  const selectedCount = appState.selectedIps.length || appState.bulbs.length;
  if (drawerPillDot) drawerPillDot.classList.toggle("is-offline", !primary.is_online);
  if (drawerPillLabel) {
    drawerPillLabel.textContent = selectedCount > 1 ? `${primary.name} (+${selectedCount - 1})` : primary.name;
  }
  if (targetSummary) {
    const targets = appState.selectedIps.length
      ? appState.bulbs.filter((b) => appState.selectedIps.includes(b.ip))
      : appState.bulbs;
    const names = targets.map((b) => b.name);
    if (selectedCount === 1) {
      targetSummary.textContent = primary.name;
    } else if (selectedCount <= 3 && names.length === selectedCount) {
      targetSummary.textContent = t("stage.controllingList", { count: selectedCount, names: names.join(", ") });
    } else {
      targetSummary.textContent = t("stage.controllingMany", { count: selectedCount, name: primary.name });
    }
    targetSummary.title = names.join("\n");
  }

  const st = primary.state;
  const isOn = Boolean(st.is_on);
  if (shell) shell.setAttribute("data-power", isOn ? "on" : "off");
  if (masterPowerBtn && masterPowerLabel) {
    masterPowerBtn.setAttribute("aria-pressed", String(isOn));
    masterPowerLabel.textContent = isOn ? t("stage.turnOff") : t("stage.turnOn");
  }
  if (brightnessSlider && brightnessOutput) {
    brightnessSlider.value = String(st.brightness);
    brightnessOutput.textContent = `${st.brightness}%`;
    updateSliderFill(brightnessSlider);
  }
  document.querySelectorAll(".brightness-preset").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.brightness) === st.brightness);
  });

  let beamCss = "var(--beam-standby)";
  let modeReadout = t("stage.stateOff");
  if (isOn) {
    if (st.mode === "rgb" && st.color) {
      beamCss = `rgb(${st.color.r}, ${st.color.g}, ${st.color.b})`;
      modeReadout = t("stage.stateOnRgb", { r: st.color.r, g: st.color.g, b: st.color.b, brightness: st.brightness });
    } else if (st.mode === "scene" && st.scene_id) {
      const sceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
      const sceneTheme = SCENE_CHROMATIC_MAP[st.scene_id];
      const category = sceneObj ? sceneObj.category : "dynamic";
      beamCss = (sceneTheme && sceneTheme.accent) || SCENE_CATEGORY_COLORS[category] || "#C084FC";
      const sceneTitle = sceneObj ? formatSceneDisplayName(sceneObj) : (st.scene_name || `#${st.scene_id}`);
      modeReadout = t("stage.stateOnScene", { scene: sceneTitle, brightness: st.brightness });
    } else {
      const kelvin = st.temperature || 4200;
      beamCss = kelvinToCssColor(kelvin);
      modeReadout = t("stage.stateOnKelvin", { kelvin, brightness: st.brightness });
    }
  } else {
    modeReadout = t("stage.stateOffStandby", { brightness: st.brightness });
  }

  document.documentElement.style.setProperty("--beam-color", beamCss);
  updateApertureGlow(aperture, isOn, st.brightness);
  if (statePill) {
    statePill.textContent = modeReadout;
    statePill.title = modeReadout;
  }
  if (telemetryMeta) telemetryMeta.textContent = `${primary.ip} · ${primary.module_name}`;

  if (st.color && !appState.isDraggingWheel) {
    const rIn = document.getElementById("input-r");
    const gIn = document.getElementById("input-g");
    const bIn = document.getElementById("input-b");
    const hexIn = document.getElementById("input-hex");
    if (rIn) rIn.value = String(st.color.r);
    if (gIn) gIn.value = String(st.color.g);
    if (bIn) bIn.value = String(st.color.b);
    if (hexIn) hexIn.value = st.color.hex || rgbToHex(st.color.r, st.color.g, st.color.b);
    positionReticleFromRgb(st.color.r, st.color.g, st.color.b);
  }

  const activeKelvin = st.temperature || 4200;
  const kelvinSlider = document.getElementById("kelvin-slider");
  const kelvinOutput = document.getElementById("kelvin-output");
  if (kelvinSlider && kelvinOutput) {
    kelvinSlider.value = String(activeKelvin);
    kelvinOutput.textContent = `${activeKelvin} K`;
    updateSliderFill(kelvinSlider);
  }
  document.querySelectorAll(".kelvin-card").forEach((card) => {
    card.classList.toggle("active", st.mode === "temperature" && Number(card.dataset.kelvin) === activeKelvin);
  });

  const speedContainer = document.getElementById("scene-speed-container");
  const speedSlider = document.getElementById("scene-speed-slider");
  const speedOutput = document.getElementById("scene-speed-output");
  const activeSceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
  const isDynamicSpeedSupported = Boolean(
    st.mode === "scene" && activeSceneObj && activeSceneObj.supports_speed && appState.sceneCategory !== "white"
  );
  if (speedContainer) speedContainer.classList.toggle("is-disabled", !isDynamicSpeedSupported);
  if (speedSlider && speedOutput) {
    speedSlider.value = String(st.speed || 100);
    speedOutput.textContent = String(st.speed || 100);
    speedSlider.disabled = !isDynamicSpeedSupported;
    updateSliderFill(speedSlider);
  }
}

export function bindStageControlEvents() {
  const masterPowerBtn = document.getElementById("master-power-btn");
  if (masterPowerBtn) {
    masterPowerBtn.addEventListener("click", () => {
      const primary = getPrimaryBulb();
      const nextPower = primary ? !primary.state.is_on : true;
      invokeApi(
        () => getBackendApi().set_power(nextPower, null, null),
        () => t(nextPower ? "status.masterTurnedOn" : "status.masterTurnedOff")
      );
    });
  }

  const brightnessSlider = document.getElementById("brightness-slider");
  const brightnessOutput = document.getElementById("brightness-output");
  if (brightnessSlider && brightnessOutput) {
    brightnessSlider.addEventListener("input", () => {
      brightnessOutput.textContent = `${brightnessSlider.value}%`;
      updateSliderFill(brightnessSlider);
      updateApertureGlow(document.getElementById("photometric-aperture"), true, brightnessSlider.value);
    });
    brightnessSlider.addEventListener("change", () => {
      const val = clampInt(brightnessSlider.value, 10, 100);
      updateSliderFill(brightnessSlider);
      invokeApi(() => getBackendApi().set_brightness(val, null), () => t("status.brightnessSet", { brightness: val }));
    });
  }

  document.querySelectorAll(".brightness-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = clampInt(btn.dataset.brightness, 10, 100);
      if (brightnessSlider) {
        brightnessSlider.value = String(val);
        updateSliderFill(brightnessSlider);
      }
      if (brightnessOutput) brightnessOutput.textContent = `${val}%`;
      invokeApi(() => getBackendApi().set_brightness(val, null), () => t("status.brightnessSet", { brightness: val }));
    });
  });

  const WHEEL_THROTTLE_MS = 70;
  const canvas = document.getElementById("color-wheel-canvas");
  if (canvas) {
    const dispatchWheelRgb = (rgb, isFinalCommit) => {
      const api = getBackendApi();
      if (!api) return;
      invokeApi(
        () => api.set_color(rgb.r, rgb.g, rgb.b, null, null),
        isFinalCommit ? () => t("status.rgbApplied", { r: rgb.r, g: rgb.g, b: rgb.b }) : null
      );
    };

    const pickColorFromPointer = (clientX, clientY, commitImmediate) => {
      const rect = canvas.getBoundingClientRect();
      const radius = rect.width / 2;
      const dx = clientX - (rect.left + radius);
      const dy = clientY - (rect.top + radius);
      const dist = Math.min(radius, Math.sqrt(dx * dx + dy * dy));
      let angle = Math.atan2(dy, dx) * (180 / Math.PI);
      if (angle < 0) angle += 360;
      const rgb = hsvToRgb(angle, dist / radius, 1);

      const rIn = document.getElementById("input-r");
      const gIn = document.getElementById("input-g");
      const bIn = document.getElementById("input-b");
      const hexIn = document.getElementById("input-hex");
      if (rIn) rIn.value = String(rgb.r);
      if (gIn) gIn.value = String(rgb.g);
      if (bIn) bIn.value = String(rgb.b);
      if (hexIn) hexIn.value = rgbToHex(rgb.r, rgb.g, rgb.b);
      positionReticleFromRgb(rgb.r, rgb.g, rgb.b);
      document.documentElement.style.setProperty("--beam-color", `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`);

      if (appState.wheelThrottleTimer) {
        clearTimeout(appState.wheelThrottleTimer);
        appState.wheelThrottleTimer = null;
      }
      if (commitImmediate) {
        appState.lastWheelSendMs = Date.now();
        dispatchWheelRgb(rgb, true);
        return;
      }

      const now = Date.now();
      const elapsed = now - appState.lastWheelSendMs;
      if (elapsed >= WHEEL_THROTTLE_MS) {
        appState.lastWheelSendMs = now;
        dispatchWheelRgb(rgb, false);
      } else {
        appState.wheelThrottleTimer = setTimeout(() => {
          appState.wheelThrottleTimer = null;
          appState.lastWheelSendMs = Date.now();
          dispatchWheelRgb(rgb, false);
        }, WHEEL_THROTTLE_MS - elapsed);
      }
    };

    canvas.addEventListener("pointerdown", (event) => {
      appState.isDraggingWheel = true;
      canvas.setPointerCapture(event.pointerId);
      pickColorFromPointer(event.clientX, event.clientY, false);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!appState.isDraggingWheel) return;
      pickColorFromPointer(event.clientX, event.clientY, false);
    });
    canvas.addEventListener("pointerup", (event) => {
      if (!appState.isDraggingWheel) return;
      appState.isDraggingWheel = false;
      pickColorFromPointer(event.clientX, event.clientY, true);
    });
    canvas.addEventListener("pointercancel", () => {
      if (appState.wheelThrottleTimer) {
        clearTimeout(appState.wheelThrottleTimer);
        appState.wheelThrottleTimer = null;
      }
      appState.isDraggingWheel = false;
    });
  }

  const applyRgbInputs = () => {
    const r = clampInt(document.getElementById("input-r")?.value, 0, 255);
    const g = clampInt(document.getElementById("input-g")?.value, 0, 255);
    const b = clampInt(document.getElementById("input-b")?.value, 0, 255);
    const hexIn = document.getElementById("input-hex");
    if (hexIn) hexIn.value = rgbToHex(r, g, b);
    positionReticleFromRgb(r, g, b);
    invokeApi(() => getBackendApi().set_color(r, g, b, null, null), () => t("status.rgbApplied", { r, g, b }));
  };

  ["input-r", "input-g", "input-b"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", applyRgbInputs);
  });

  const applyRgbBtn = document.getElementById("apply-rgb-btn");
  if (applyRgbBtn) {
    applyRgbBtn.addEventListener("click", () => {
      const hexIn = document.getElementById("input-hex");
      const parsed = hexIn ? parseHexToRgb(hexIn.value) : null;
      if (parsed) {
        document.getElementById("input-r").value = String(parsed.r);
        document.getElementById("input-g").value = String(parsed.g);
        document.getElementById("input-b").value = String(parsed.b);
      }
      applyRgbInputs();
    });
  }

  document.querySelectorAll(".color-swatch").forEach((swatch) => {
    const r = clampInt(swatch.dataset.r, 0, 255);
    const g = clampInt(swatch.dataset.g, 0, 255);
    const b = clampInt(swatch.dataset.b, 0, 255);
    swatch.style.setProperty("--swatch-rgb", `rgb(${r}, ${g}, ${b})`);
    swatch.addEventListener("click", () => {
      invokeApi(() => getBackendApi().set_color(r, g, b, null, null), () => t("status.swatchApplied", { r, g, b }));
    });
  });

  const kelvinSlider = document.getElementById("kelvin-slider");
  const kelvinOutput = document.getElementById("kelvin-output");
  if (kelvinSlider && kelvinOutput) {
    kelvinSlider.addEventListener("input", () => {
      const k = clampInt(kelvinSlider.value, 2200, 6500);
      kelvinOutput.textContent = `${k} K`;
      updateSliderFill(kelvinSlider);
      document.documentElement.style.setProperty("--beam-color", kelvinToCssColor(k));
    });
    kelvinSlider.addEventListener("change", () => {
      const k = clampInt(kelvinSlider.value, 2200, 6500);
      updateSliderFill(kelvinSlider);
      invokeApi(() => getBackendApi().set_temperature(k, null, null), () => t("status.kelvinSet", { kelvin: k }));
    });
  }

  document.querySelectorAll(".kelvin-card").forEach((card) => {
    card.addEventListener("click", () => {
      const k = clampInt(card.dataset.kelvin, 2200, 6500);
      invokeApi(() => getBackendApi().set_temperature(k, null, null), () => t("status.kelvinSet", { kelvin: k }));
    });
  });
}
