/*
 * Controlador de interfaz de usuario para la Consola Fotometrica Arquitectonica WiZ.
 *
 * Se comunica con Python a traves de `window.pywebview.api` y mantiene una copia
 * reactiva del estado de los focos, la seleccion multiple y el catalogo de 36 escenas.
 * Incluye un adaptador de respaldo en memoria cuando se abre fuera de PyWebView para
 * permitir pruebas de diseno e inspeccion directa en navegadores convencionales.
 */

(function () {
  "use strict";

  /* Catalogo de respaldo de las 36 escenas oficiales para modo previsualizacion en navegador */
  const FALLBACK_SCENES = [
    { scene_id: 1, name: "Ocean", category: "nature", supports_speed: true },
    { scene_id: 2, name: "Romance", category: "ambient", supports_speed: true },
    { scene_id: 3, name: "Sunset", category: "nature", supports_speed: true },
    { scene_id: 4, name: "Party", category: "dynamic", supports_speed: true },
    { scene_id: 5, name: "Fireplace", category: "ambient", supports_speed: true },
    { scene_id: 6, name: "Cozy", category: "ambient", supports_speed: true },
    { scene_id: 7, name: "Forest", category: "nature", supports_speed: true },
    { scene_id: 8, name: "Pastel colors", category: "dynamic", supports_speed: true },
    { scene_id: 9, name: "Wake-up", category: "ambient", supports_speed: true },
    { scene_id: 10, name: "Bedtime", category: "ambient", supports_speed: true },
    { scene_id: 11, name: "Warm white", category: "white", supports_speed: false },
    { scene_id: 12, name: "Daylight", category: "white", supports_speed: false },
    { scene_id: 13, name: "Cool white", category: "white", supports_speed: false },
    { scene_id: 14, name: "Night light", category: "white", supports_speed: false },
    { scene_id: 15, name: "Focus", category: "white", supports_speed: false },
    { scene_id: 16, name: "Relax", category: "white", supports_speed: false },
    { scene_id: 17, name: "True colors", category: "white", supports_speed: false },
    { scene_id: 18, name: "TV time", category: "white", supports_speed: false },
    { scene_id: 19, name: "Plantgrowth", category: "nature", supports_speed: false },
    { scene_id: 20, name: "Spring", category: "nature", supports_speed: true },
    { scene_id: 21, name: "Summer", category: "nature", supports_speed: true },
    { scene_id: 22, name: "Fall", category: "nature", supports_speed: true },
    { scene_id: 23, name: "Deep dive", category: "nature", supports_speed: true },
    { scene_id: 24, name: "Jungle", category: "nature", supports_speed: true },
    { scene_id: 25, name: "Mojito", category: "dynamic", supports_speed: true },
    { scene_id: 26, name: "Club", category: "dynamic", supports_speed: true },
    { scene_id: 27, name: "Christmas", category: "holiday", supports_speed: true },
    { scene_id: 28, name: "Halloween", category: "holiday", supports_speed: true },
    { scene_id: 29, name: "Candlelight", category: "ambient", supports_speed: true },
    { scene_id: 30, name: "Golden white", category: "white", supports_speed: false },
    { scene_id: 31, name: "Pulse", category: "dynamic", supports_speed: true },
    { scene_id: 32, name: "Steampunk", category: "dynamic", supports_speed: true },
    { scene_id: 33, name: "Diwali", category: "holiday", supports_speed: true },
    { scene_id: 34, name: "White", category: "white", supports_speed: false },
    { scene_id: 35, name: "Alarm", category: "dynamic", supports_speed: true },
    { scene_id: 36, name: "Snowy sky", category: "nature", supports_speed: true }
  ];

  const SCENE_CATEGORY_COLORS = {
    white: "#FFF1E0",
    ambient: "#FF9254",
    nature: "#38BDF8",
    dynamic: "#C084FC",
    holiday: "#F43F5E"
  };

  /* Estado reactivo local de la interfaz */
  const appState = {
    bulbs: [],
    selectedIps: [],
    scenes: FALLBACK_SCENES.slice(),
    activeTab: "rgb",
    sceneCategory: "all",
    autoSyncTimer: null,
    isDraggingWheel: false
  };

  /* Simulador en memoria cuando no existe el contenedor nativo de PyWebView */
  function createBrowserMockApi() {
    let mockBulbs = [
      {
        ip: "192.168.0.34",
        mac: "a8bb50df9029",
        name: "Studio Key Light",
        module_name: "ESP01_SHRGB1C_31",
        is_online: true,
        state: {
          is_on: true,
          brightness: 85,
          mode: "temperature",
          color: null,
          temperature: 4200,
          scene_id: null,
          scene_name: null,
          speed: 100
        }
      }
    ];
    let mockSelected = ["192.168.0.34"];

    function buildMockEnvelope() {
      return Promise.resolve({
        ok: true,
        bulbs: JSON.parse(JSON.stringify(mockBulbs)),
        selected_ips: mockSelected.slice(),
        scenes: FALLBACK_SCENES.slice(),
        error: null
      });
    }

    function resolveTargets(ips) {
      if (Array.isArray(ips) && ips.length > 0) return ips;
      if (mockSelected.length > 0) return mockSelected;
      return mockBulbs.map((b) => b.ip);
    }

    return {
      get_initial_state: () => buildMockEnvelope(),
      discover_bulbs: () => buildMockEnvelope(),
      refresh_states: () => buildMockEnvelope(),
      select_targets: (ips) => {
        mockSelected = Array.isArray(ips) ? ips.slice() : [];
        return buildMockEnvelope();
      },
      add_manual_bulb: (ip, name) => {
        const cleaned = String(ip || "").trim();
        if (!cleaned) {
          return Promise.resolve({ ok: false, bulbs: mockBulbs, selected_ips: mockSelected, scenes: FALLBACK_SCENES, error: "IP cannot be empty." });
        }
        const label = String(name || "").trim() || `WiZ Bulb (${cleaned})`;
        const existing = mockBulbs.find((b) => b.ip === cleaned);
        if (existing) {
          existing.name = label;
        } else {
          mockBulbs.push({
            ip: cleaned,
            mac: "a8bb50001122",
            name: label,
            module_name: "ESP01_SHRGB1C_31",
            is_online: true,
            state: {
              is_on: true,
              brightness: 100,
              mode: "temperature",
              color: null,
              temperature: 4200,
              scene_id: null,
              scene_name: null,
              speed: 100
            }
          });
          if (!mockSelected.includes(cleaned)) mockSelected.push(cleaned);
        }
        return buildMockEnvelope();
      },
      rename_bulb: (ip, newName) => {
        const target = mockBulbs.find((b) => b.ip === ip);
        if (target && String(newName || "").trim()) {
          target.name = String(newName).trim();
        }
        return buildMockEnvelope();
      },
      set_power: (isOn, brightness, ips) => {
        const targets = resolveTargets(ips);
        mockBulbs.forEach((b) => {
          if (targets.includes(b.ip)) {
            b.state.is_on = Boolean(isOn);
            if (typeof brightness === "number") b.state.brightness = brightness;
          }
        });
        return buildMockEnvelope();
      },
      set_brightness: (brightness, ips) => {
        const targets = resolveTargets(ips);
        mockBulbs.forEach((b) => {
          if (targets.includes(b.ip)) {
            b.state.is_on = true;
            b.state.brightness = Number(brightness);
          }
        });
        return buildMockEnvelope();
      },
      set_color: (r, g, b, brightness, ips) => {
        const targets = resolveTargets(ips);
        const hex = rgbToHex(r, g, b);
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = "rgb";
            bulb.state.color = { r: Number(r), g: Number(g), b: Number(b), hex };
            bulb.state.temperature = null;
            bulb.state.scene_id = null;
            bulb.state.scene_name = null;
            if (typeof brightness === "number") bulb.state.brightness = brightness;
          }
        });
        return buildMockEnvelope();
      },
      set_temperature: (kelvin, brightness, ips) => {
        const targets = resolveTargets(ips);
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = "temperature";
            bulb.state.temperature = Number(kelvin);
            bulb.state.color = null;
            bulb.state.scene_id = null;
            bulb.state.scene_name = null;
            if (typeof brightness === "number") bulb.state.brightness = brightness;
          }
        });
        return buildMockEnvelope();
      },
      set_builtin_scene: (sceneId, speed, brightness, ips) => {
        const targets = resolveTargets(ips);
        const scene = FALLBACK_SCENES.find((s) => s.scene_id === Number(sceneId));
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = "scene";
            bulb.state.scene_id = Number(sceneId);
            bulb.state.scene_name = scene ? scene.name : `Scene ${sceneId}`;
            bulb.state.color = null;
            bulb.state.temperature = null;
            if (typeof speed === "number") bulb.state.speed = speed;
            if (typeof brightness === "number") bulb.state.brightness = brightness;
          }
        });
        return buildMockEnvelope();
      }
    };
  }

  let backendApi = null;

  /* Resuelve el puente nativo de PyWebView o activa el simulador de desarrollo */
  async function resolveBackendApi() {
    if (window.pywebview && window.pywebview.api) {
      return window.pywebview.api;
    }
    return new Promise((resolve) => {
      let settled = false;
      const onReady = () => {
        if (!settled && window.pywebview && window.pywebview.api) {
          settled = true;
          resolve(window.pywebview.api);
        }
      };
      window.addEventListener("pywebviewready", onReady, { once: true });
      setTimeout(() => {
        if (!settled) {
          settled = true;
          resolve(createBrowserMockApi());
        }
      }, 350);
    });
  }

  /* Utilidades de conversion cromatica */
  function clampInt(val, min, max) {
    const n = Math.round(Number(val));
    if (Number.isNaN(n)) return min;
    return Math.max(min, Math.min(max, n));
  }

  function rgbToHex(r, g, b) {
    const toHex = (n) => clampInt(n, 0, 255).toString(16).padStart(2, "0");
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
  }

  function parseHexToRgb(hexStr) {
    const cleaned = String(hexStr || "").trim().replace(/^#/, "");
    if (!/^[0-9a-fA-F]{6}$/.test(cleaned)) return null;
    return {
      r: parseInt(cleaned.slice(0, 2), 16),
      g: parseInt(cleaned.slice(2, 4), 16),
      b: parseInt(cleaned.slice(4, 6), 16)
    };
  }

  function hsvToRgb(h, s, v) {
    const c = v * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = v - c;
    let rPrime = 0;
    let gPrime = 0;
    let bPrime = 0;

    if (h >= 0 && h < 60) {
      rPrime = c; gPrime = x; bPrime = 0;
    } else if (h >= 60 && h < 120) {
      rPrime = x; gPrime = c; bPrime = 0;
    } else if (h >= 120 && h < 180) {
      rPrime = 0; gPrime = c; bPrime = x;
    } else if (h >= 180 && h < 240) {
      rPrime = 0; gPrime = x; bPrime = c;
    } else if (h >= 240 && h < 300) {
      rPrime = x; gPrime = 0; bPrime = c;
    } else {
      rPrime = c; gPrime = 0; bPrime = x;
    }

    return {
      r: Math.round((rPrime + m) * 255),
      g: Math.round((gPrime + m) * 255),
      b: Math.round((bPrime + m) * 255)
    };
  }

  function rgbToHsv(r, g, b) {
    const rNorm = r / 255;
    const gNorm = g / 255;
    const bNorm = b / 255;
    const max = Math.max(rNorm, gNorm, bNorm);
    const min = Math.min(rNorm, gNorm, bNorm);
    const delta = max - min;

    let h = 0;
    if (delta !== 0) {
      if (max === rNorm) {
        h = 60 * (((gNorm - bNorm) / delta) % 6);
      } else if (max === gNorm) {
        h = 60 * ((bNorm - rNorm) / delta + 2);
      } else {
        h = 60 * ((rNorm - gNorm) / delta + 4);
      }
    }
    if (h < 0) h += 360;
    const s = max === 0 ? 0 : delta / max;
    return { h, s, v: max };
  }

  /* Aproxima una temperatura Kelvin (2200K-6500K) a un color CSS representativo */
  function kelvinToCssColor(kelvin) {
    const k = clampInt(kelvin, 2200, 6500);
    if (k <= 4200) {
      const t = (k - 2200) / (4200 - 2200);
      const r = Math.round(255 + (255 - 255) * t);
      const g = Math.round(180 + (241 - 180) * t);
      const b = Math.round(107 + (224 - 107) * t);
      return `rgb(${r}, ${g}, ${b})`;
    }
    const t = (k - 4200) / (6500 - 4200);
    const r = Math.round(255 + (214 - 255) * t);
    const g = Math.round(241 + (232 - 241) * t);
    const b = Math.round(224 + (255 - 224) * t);
    return `rgb(${r}, ${g}, ${b})`;
  }

  /* Renderiza la rueda cromatica HSV en el elemento <canvas> */
  function drawColorWheel() {
    const canvas = document.getElementById("color-wheel-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
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
          const sat = Math.min(1, dist / radius);
          const rgb = hsvToRgb(angle, sat, 1);
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

  function positionReticleFromRgb(r, g, b) {
    const canvas = document.getElementById("color-wheel-canvas");
    const reticle = document.getElementById("wheel-reticle");
    if (!canvas || !reticle) return;
    const radius = canvas.clientWidth / 2;
    const hsv = rgbToHsv(r, g, b);
    const rad = (hsv.h * Math.PI) / 180;
    const dist = hsv.s * radius;
    const x = radius + Math.cos(rad) * dist;
    const y = radius + Math.sin(rad) * dist;
    reticle.style.left = `${x}px`;
    reticle.style.top = `${y}px`;
  }

  /* Obtiene el foco de referencia principal entre los seleccionados */
  function getPrimaryBulb() {
    if (appState.selectedIps.length > 0) {
      const found = appState.bulbs.find((b) => appState.selectedIps.includes(b.ip));
      if (found) return found;
    }
    return appState.bulbs[0] || null;
  }

  function setStatusMessage(message) {
    const banner = document.getElementById("status-banner");
    if (banner) {
      banner.textContent = message;
    }
  }

  /* Actualiza la variable CSS `--beam-color` y toda la interfaz a partir del sobre del backend */
  function applyBackendEnvelope(envelope, statusText) {
    if (!envelope) return;
    if (Array.isArray(envelope.bulbs)) {
      appState.bulbs = envelope.bulbs;
    }
    if (Array.isArray(envelope.selected_ips)) {
      appState.selectedIps = envelope.selected_ips;
    }
    if (Array.isArray(envelope.scenes) && envelope.scenes.length > 0) {
      appState.scenes = envelope.scenes;
    }

    if (!envelope.ok && envelope.error) {
      setStatusMessage(`Warning: ${envelope.error}`);
    } else if (statusText) {
      setStatusMessage(statusText);
    }

    renderFixtureList();
    renderStageHeaderAndControls();
    renderScenesGrid();
  }

  /* Renderiza las tarjetas de focos en el riel izquierdo sin usar innerHTML con datos de usuario */
  function renderFixtureList() {
    const container = document.getElementById("fixture-list");
    const badge = document.getElementById("fixture-count-badge");
    const selectAllCheckbox = document.getElementById("select-all-fixtures");
    if (!container) return;

    const onlineCount = appState.bulbs.filter((b) => b.is_online).length;
    if (badge) {
      badge.textContent = `${onlineCount} / ${appState.bulbs.length} online`;
    }

    if (selectAllCheckbox) {
      selectAllCheckbox.checked =
        appState.bulbs.length > 0 &&
        appState.bulbs.every((b) => appState.selectedIps.includes(b.ip));
    }

    container.replaceChildren();

    if (appState.bulbs.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-fixtures-state";
      const p1 = document.createElement("p");
      p1.textContent = "No WiZ fixtures registered yet.";
      const p2 = document.createElement("p");
      p2.textContent = "Use Scan network or Add by IP to connect.";
      empty.append(p1, p2);
      container.appendChild(empty);
      return;
    }

    appState.bulbs.forEach((bulb) => {
      const isSelected = appState.selectedIps.includes(bulb.ip);
      const card = document.createElement("article");
      card.className = `fixture-card${isSelected ? " is-selected" : ""}`;

      const topRow = document.createElement("div");
      topRow.className = "fixture-card-top";

      const selectLabel = document.createElement("label");
      selectLabel.className = "fixture-select-label";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = isSelected;
      checkbox.setAttribute("aria-label", `Select ${bulb.name}`);
      checkbox.addEventListener("change", () => {
        let nextIps = appState.selectedIps.slice();
        if (checkbox.checked) {
          if (!nextIps.includes(bulb.ip)) nextIps.push(bulb.ip);
        } else {
          nextIps = nextIps.filter((ip) => ip !== bulb.ip);
        }
        invokeApi(() => backendApi.select_targets(nextIps), "Updated target selection.");
      });

      const metaDiv = document.createElement("div");
      metaDiv.className = "fixture-meta";

      const nameHeading = document.createElement("h3");
      nameHeading.className = "fixture-name";
      nameHeading.textContent = bulb.name;

      const addressLine = document.createElement("p");
      addressLine.className = "fixture-address";
      addressLine.textContent = `${bulb.ip} · ${bulb.mac}`;

      metaDiv.append(nameHeading, addressLine);
      selectLabel.append(checkbox, metaDiv);
      topRow.appendChild(selectLabel);

      const bottomRow = document.createElement("div");
      bottomRow.className = "fixture-card-bottom";

      const statusSpan = document.createElement("span");
      statusSpan.className = `status-indicator${bulb.is_online ? "" : " is-offline"}`;
      const dot = document.createElement("span");
      dot.className = "status-dot";
      dot.setAttribute("aria-hidden", "true");
      const statusText = document.createElement("span");
      statusText.textContent = bulb.is_online ? "Online" : "Offline";
      statusSpan.append(dot, statusText);

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "fixture-card-actions";

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "btn btn-compact btn-ghost";
      renameBtn.textContent = "Rename";
      renameBtn.addEventListener("click", () => openRenameDialog(bulb));

      const powerBtn = document.createElement("button");
      powerBtn.type = "button";
      powerBtn.className = `btn btn-compact ${bulb.state.is_on ? "btn-primary" : "btn-secondary"}`;
      powerBtn.setAttribute("aria-pressed", String(Boolean(bulb.state.is_on)));
      powerBtn.textContent = bulb.state.is_on ? "ON" : "OFF";
      powerBtn.addEventListener("click", () => {
        const nextPower = !bulb.state.is_on;
        invokeApi(
          () => backendApi.set_power(nextPower, null, [bulb.ip]),
          `${bulb.name} turned ${nextPower ? "ON" : "OFF"}.`
        );
      });

      actionsDiv.append(renameBtn, powerBtn);
      bottomRow.append(statusSpan, actionsDiv);

      card.append(topRow, bottomRow);
      container.appendChild(card);
    });
  }

  /* Sincroniza la cabecera fotometrica, el deslizador de brillo y los paneles de modo */
  function renderStageHeaderAndControls() {
    const shell = document.getElementById("console-shell");
    const targetSummary = document.getElementById("target-summary");
    const statePill = document.getElementById("live-state-pill");
    const telemetryMeta = document.getElementById("telemetry-meta");
    const masterPowerBtn = document.getElementById("master-power-btn");
    const masterPowerLabel = document.getElementById("master-power-label");
    const brightnessSlider = document.getElementById("brightness-slider");
    const brightnessOutput = document.getElementById("brightness-output");

    const primary = getPrimaryBulb();
    if (!primary) {
      if (shell) shell.setAttribute("data-power", "off");
      document.documentElement.style.setProperty("--beam-color", "#2A303C");
      if (targetSummary) targetSummary.textContent = "No fixture selected";
      if (statePill) statePill.textContent = "OFFLINE";
      return;
    }

    const selectedCount = appState.selectedIps.length || appState.bulbs.length;
    if (targetSummary) {
      targetSummary.textContent =
        selectedCount === 1
          ? `Controlling 1 fixture: ${primary.name}`
          : `Controlling ${selectedCount} fixtures (${primary.name} primary)`;
    }

    const st = primary.state;
    const isOn = Boolean(st.is_on);
    if (shell) {
      shell.setAttribute("data-power", isOn ? "on" : "off");
    }

    if (masterPowerBtn && masterPowerLabel) {
      masterPowerBtn.setAttribute("aria-pressed", String(isOn));
      masterPowerLabel.textContent = isOn ? "Turn OFF" : "Turn ON";
    }

    if (brightnessSlider && brightnessOutput) {
      brightnessSlider.value = String(st.brightness);
      brightnessOutput.textContent = `${st.brightness}%`;
    }

    document.querySelectorAll(".brightness-preset").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.brightness) === st.brightness);
    });

    /* Calculo del color fotometrico (`--beam-color`) segun el modo activo */
    let beamCss = "#2A303C";
    let modeReadout = "OFF";

    if (isOn) {
      if (st.mode === "rgb" && st.color) {
        beamCss = `rgb(${st.color.r}, ${st.color.g}, ${st.color.b})`;
        modeReadout = `ON · RGB (${st.color.r}, ${st.color.g}, ${st.color.b}) · ${st.brightness}%`;
      } else if (st.mode === "scene" && st.scene_id) {
        const sceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
        const category = sceneObj ? sceneObj.category : "dynamic";
        beamCss = SCENE_CATEGORY_COLORS[category] || "#C084FC";
        const sceneTitle = st.scene_name || (sceneObj ? sceneObj.name : `Scene ${st.scene_id}`);
        modeReadout = `ON · Scene: ${sceneTitle} · ${st.brightness}%`;
      } else {
        const kelvin = st.temperature || 4200;
        beamCss = kelvinToCssColor(kelvin);
        modeReadout = `ON · ${kelvin} K · ${st.brightness}%`;
      }
    } else {
      modeReadout = `OFF · Standby (${st.brightness}%)`;
    }

    document.documentElement.style.setProperty("--beam-color", beamCss);
    if (statePill) statePill.textContent = modeReadout;
    if (telemetryMeta) telemetryMeta.textContent = `${primary.ip} · ${primary.module_name}`;

    /* Sincronizacion de controles RGB */
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

    /* Sincronizacion de controles Kelvin */
    const activeKelvin = st.temperature || 4200;
    const kelvinSlider = document.getElementById("kelvin-slider");
    const kelvinOutput = document.getElementById("kelvin-output");
    if (kelvinSlider && kelvinOutput) {
      kelvinSlider.value = String(activeKelvin);
      kelvinOutput.textContent = `${activeKelvin} K`;
    }
    document.querySelectorAll(".kelvin-card").forEach((card) => {
      card.classList.toggle(
        "active",
        st.mode === "temperature" && Number(card.dataset.kelvin) === activeKelvin
      );
    });

    /* Sincronizacion del deslizador de velocidad de escena */
    const speedSlider = document.getElementById("scene-speed-slider");
    const speedOutput = document.getElementById("scene-speed-output");
    const activeSceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
    if (speedSlider && speedOutput) {
      speedSlider.value = String(st.speed || 100);
      speedOutput.textContent = String(st.speed || 100);
      speedSlider.disabled = !(st.mode === "scene" && activeSceneObj && activeSceneObj.supports_speed);
    }
  }

  /* Renderiza la cuadricula de las 36 escenas nativas de WiZ */
  function renderScenesGrid() {
    const grid = document.getElementById("scenes-grid");
    if (!grid) return;

    const primary = getPrimaryBulb();
    const activeSceneId =
      primary && primary.state.mode === "scene" ? primary.state.scene_id : null;

    const filtered = appState.scenes.filter((scene) =>
      appState.sceneCategory === "all" ? true : scene.category === appState.sceneCategory
    );

    grid.replaceChildren();

    filtered.forEach((scene) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `scene-card${activeSceneId === scene.scene_id ? " active" : ""}`;

      const top = document.createElement("div");
      top.className = "scene-card-top";

      const idBadge = document.createElement("span");
      idBadge.className = "scene-id-badge";
      idBadge.textContent = `#${String(scene.scene_id).padStart(2, "0")}`;

      const tag = document.createElement("span");
      tag.className = "scene-tag";
      tag.textContent = scene.supports_speed ? "Dynamic" : "Static";

      top.append(idBadge, tag);

      const title = document.createElement("p");
      title.className = "scene-name";
      title.textContent = scene.name;

      btn.append(top, title);
      btn.addEventListener("click", () => {
        const speedSlider = document.getElementById("scene-speed-slider");
        const speedVal = scene.supports_speed && speedSlider ? Number(speedSlider.value) : null;
        invokeApi(
          () => backendApi.set_builtin_scene(scene.scene_id, speedVal, null, null),
          `Activated scene #${scene.scene_id}: ${scene.name}.`
        );
      });

      grid.appendChild(btn);
    });
  }

  /* Ejecuta llamadas hacia WebviewBridge de forma uniforme */
  async function invokeApi(callFn, successMessage) {
    if (!backendApi) return;
    try {
      const response = await callFn();
      applyBackendEnvelope(response, successMessage);
    } catch (err) {
      setStatusMessage(`Communication error: ${err && err.message ? err.message : String(err)}`);
    }
  }

  /* Gestion de pestanas accesibles (WAI-ARIA Tabs con navegacion por flechas) */
  function activateTab(modeName, focusTab) {
    appState.activeTab = modeName;
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
  }

  function openRenameDialog(bulb) {
    const dialog = document.getElementById("rename-bulb-dialog");
    const ipDisplay = document.getElementById("rename-bulb-ip-display");
    const ipInput = document.getElementById("rename-bulb-ip-input");
    const nameInput = document.getElementById("rename-bulb-name-input");
    if (!dialog || !ipInput || !nameInput) return;

    ipInput.value = bulb.ip;
    nameInput.value = bulb.name;
    if (ipDisplay) ipDisplay.textContent = `Fixture IP: ${bulb.ip} (${bulb.mac})`;
    dialog.showModal();
    nameInput.focus();
    nameInput.select();
  }

  /*
   * Respaldo obligatorio de light-dismiss para navegadores que aun no implementan
   * nativamente el atributo declarativo `<dialog closedby="any">`.
   */
  function setupDialogLightDismissFallbacks() {
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

  /* Vincula eventos de la rueda de color, deslizadores y formularios */
  function bindEvents() {
    setupDialogLightDismissFallbacks();

    /* Escaneo de red y dialogo de alta por IP */
    const scanBtn = document.getElementById("scan-network-btn");
    const scanLabel = document.getElementById("scan-btn-label");
    if (scanBtn) {
      scanBtn.addEventListener("click", async () => {
        if (scanLabel) scanLabel.textContent = "Scanning...";
        scanBtn.disabled = true;
        try {
          await invokeApi(() => backendApi.discover_bulbs(), "Network scan completed.");
        } finally {
          if (scanLabel) scanLabel.textContent = "Scan network";
          scanBtn.disabled = false;
        }
      });
    }

    const openAddBtn = document.getElementById("open-add-dialog-btn");
    const addDialog = document.getElementById("add-bulb-dialog");
    if (openAddBtn && addDialog) {
      openAddBtn.addEventListener("click", () => {
        addDialog.showModal();
        const ipInput = document.getElementById("manual-ip-input");
        if (ipInput) ipInput.focus();
      });
    }

    const addForm = document.getElementById("add-bulb-form");
    if (addForm && addDialog) {
      addForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const ipInput = document.getElementById("manual-ip-input");
        const nameInput = document.getElementById("manual-name-input");
        const ip = ipInput ? ipInput.value.trim() : "";
        const name = nameInput ? nameInput.value.trim() : "";
        if (!ip) return;
        addDialog.close();
        if (ipInput) ipInput.value = "";
        if (nameInput) nameInput.value = "";
        invokeApi(() => backendApi.add_manual_bulb(ip, name), `Registered fixture at ${ip}.`);
      });
    }

    const renameForm = document.getElementById("rename-bulb-form");
    const renameDialog = document.getElementById("rename-bulb-dialog");
    if (renameForm && renameDialog) {
      renameForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const ipInput = document.getElementById("rename-bulb-ip-input");
        const nameInput = document.getElementById("rename-bulb-name-input");
        const ip = ipInput ? ipInput.value : "";
        const newName = nameInput ? nameInput.value.trim() : "";
        if (!ip || !newName) return;
        renameDialog.close();
        invokeApi(() => backendApi.rename_bulb(ip, newName), `Renamed ${ip} to "${newName}".`);
      });
    }

    /* Seleccionar todos los focos */
    const selectAll = document.getElementById("select-all-fixtures");
    if (selectAll) {
      selectAll.addEventListener("change", () => {
        const nextIps = selectAll.checked ? appState.bulbs.map((b) => b.ip) : [];
        invokeApi(() => backendApi.select_targets(nextIps), "Updated multi-fixture selection.");
      });
    }

    /* Sincronizacion en vivo con getPilot */
    const syncNowBtn = document.getElementById("sync-now-btn");
    if (syncNowBtn) {
      syncNowBtn.addEventListener("click", () => {
        invokeApi(() => backendApi.refresh_states(), "Synchronized live state from UDP getPilot.");
      });
    }

    const autoSyncToggle = document.getElementById("auto-sync-toggle");
    if (autoSyncToggle) {
      autoSyncToggle.addEventListener("change", () => {
        if (appState.autoSyncTimer) {
          clearInterval(appState.autoSyncTimer);
          appState.autoSyncTimer = null;
        }
        if (autoSyncToggle.checked) {
          appState.autoSyncTimer = setInterval(() => {
            invokeApi(() => backendApi.refresh_states(), "Auto-synced live bulb telemetry.");
          }, 3000);
          setStatusMessage("Auto-sync enabled (polling UDP getPilot every 3s).");
        } else {
          setStatusMessage("Auto-sync paused.");
        }
      });
    }

    /* Boton maestro de encendido/apagado */
    const masterPowerBtn = document.getElementById("master-power-btn");
    if (masterPowerBtn) {
      masterPowerBtn.addEventListener("click", () => {
        const primary = getPrimaryBulb();
        const nextPower = primary ? !primary.state.is_on : true;
        invokeApi(
          () => backendApi.set_power(nextPower, null, null),
          `Master power turned ${nextPower ? "ON" : "OFF"}.`
        );
      });
    }

    /* Control de brillo maestro */
    const brightnessSlider = document.getElementById("brightness-slider");
    const brightnessOutput = document.getElementById("brightness-output");
    if (brightnessSlider && brightnessOutput) {
      brightnessSlider.addEventListener("input", () => {
        brightnessOutput.textContent = `${brightnessSlider.value}%`;
      });
      brightnessSlider.addEventListener("change", () => {
        const val = clampInt(brightnessSlider.value, 10, 100);
        invokeApi(() => backendApi.set_brightness(val, null), `Set brightness to ${val}%.`);
      });
    }

    document.querySelectorAll(".brightness-preset").forEach((btn) => {
      btn.addEventListener("click", () => {
        const val = clampInt(btn.dataset.brightness, 10, 100);
        if (brightnessSlider) brightnessSlider.value = String(val);
        if (brightnessOutput) brightnessOutput.textContent = `${val}%`;
        invokeApi(() => backendApi.set_brightness(val, null), `Set brightness to ${val}%.`);
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

    /* Interaccion con la rueda de color HSV */
    const canvas = document.getElementById("color-wheel-canvas");
    if (canvas) {
      const pickColorFromPointer = (clientX, clientY, commitToBulb) => {
        const rect = canvas.getBoundingClientRect();
        const radius = rect.width / 2;
        const dx = clientX - (rect.left + radius);
        const dy = clientY - (rect.top + radius);
        const dist = Math.min(radius, Math.sqrt(dx * dx + dy * dy));
        let angle = Math.atan2(dy, dx) * (180 / Math.PI);
        if (angle < 0) angle += 360;
        const sat = dist / radius;
        const rgb = hsvToRgb(angle, sat, 1);

        const rIn = document.getElementById("input-r");
        const gIn = document.getElementById("input-g");
        const bIn = document.getElementById("input-b");
        const hexIn = document.getElementById("input-hex");
        if (rIn) rIn.value = String(rgb.r);
        if (gIn) gIn.value = String(rgb.g);
        if (bIn) bIn.value = String(rgb.b);
        if (hexIn) hexIn.value = rgbToHex(rgb.r, rgb.g, rgb.b);

        positionReticleFromRgb(rgb.r, rgb.g, rgb.b);
        document.documentElement.style.setProperty(
          "--beam-color",
          `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`
        );

        if (commitToBulb) {
          invokeApi(
            () => backendApi.set_color(rgb.r, rgb.g, rgb.b, null, null),
            `Applied RGB (${rgb.r}, ${rgb.g}, ${rgb.b}).`
          );
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
    }

    /* Entradas numericas RGB y codigo Hex */
    const applyRgbInputs = () => {
      const r = clampInt(document.getElementById("input-r")?.value, 0, 255);
      const g = clampInt(document.getElementById("input-g")?.value, 0, 255);
      const b = clampInt(document.getElementById("input-b")?.value, 0, 255);
      const hexIn = document.getElementById("input-hex");
      if (hexIn) hexIn.value = rgbToHex(r, g, b);
      positionReticleFromRgb(r, g, b);
      invokeApi(
        () => backendApi.set_color(r, g, b, null, null),
        `Applied RGB (${r}, ${g}, ${b}).`
      );
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
      swatch.addEventListener("click", () => {
        const r = clampInt(swatch.dataset.r, 0, 255);
        const g = clampInt(swatch.dataset.g, 0, 255);
        const b = clampInt(swatch.dataset.b, 0, 255);
        invokeApi(
          () => backendApi.set_color(r, g, b, null, null),
          `Applied swatch RGB (${r}, ${g}, ${b}).`
        );
      });
    });

    /* Controles de temperatura de blanco (Kelvin) */
    const kelvinSlider = document.getElementById("kelvin-slider");
    const kelvinOutput = document.getElementById("kelvin-output");
    if (kelvinSlider && kelvinOutput) {
      kelvinSlider.addEventListener("input", () => {
        const k = clampInt(kelvinSlider.value, 2200, 6500);
        kelvinOutput.textContent = `${k} K`;
        document.documentElement.style.setProperty("--beam-color", kelvinToCssColor(k));
      });
      kelvinSlider.addEventListener("change", () => {
        const k = clampInt(kelvinSlider.value, 2200, 6500);
        invokeApi(() => backendApi.set_temperature(k, null, null), `Set white balance to ${k} K.`);
      });
    }

    document.querySelectorAll(".kelvin-card").forEach((card) => {
      card.addEventListener("click", () => {
        const k = clampInt(card.dataset.kelvin, 2200, 6500);
        invokeApi(() => backendApi.set_temperature(k, null, null), `Set white balance to ${k} K.`);
      });
    });

    /* Filtros de categoria de escenas y velocidad dinamica */
    document.querySelectorAll(".scene-filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        appState.sceneCategory = btn.dataset.category || "all";
        document.querySelectorAll(".scene-filter").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        renderScenesGrid();
      });
    });

    const speedSlider = document.getElementById("scene-speed-slider");
    const speedOutput = document.getElementById("scene-speed-output");
    if (speedSlider && speedOutput) {
      speedSlider.addEventListener("input", () => {
        speedOutput.textContent = speedSlider.value;
      });
      speedSlider.addEventListener("change", () => {
        const primary = getPrimaryBulb();
        if (!primary || primary.state.mode !== "scene" || !primary.state.scene_id) return;
        const speed = clampInt(speedSlider.value, 10, 200);
        invokeApi(
          () => backendApi.set_builtin_scene(primary.state.scene_id, speed, null, null),
          `Updated scene #${primary.state.scene_id} speed to ${speed}.`
        );
      });
    }
  }

  /* Inicializacion principal al cargar el DOM */
  document.addEventListener("DOMContentLoaded", async () => {
    drawColorWheel();
    bindEvents();
    backendApi = await resolveBackendApi();
    await invokeApi(
      () => backendApi.get_initial_state(),
      "Connected to local UDP lighting service."
    );
  });
})();
