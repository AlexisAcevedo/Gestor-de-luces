/*
 * Shared state, scene catalog, persistent preferences, and pure photometric helpers.
 */

export let SCENE_CATALOG = [];

export async function loadSceneCatalog() {
  try {
    const response = await fetch("scenes.json", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (Array.isArray(data) && data.length > 0) {
      SCENE_CATALOG = data;
      if (!appState.scenes.length) appState.scenes = SCENE_CATALOG.slice();
    }
  } catch (_err) {
    /* Sin fetch (p. ej. file://): el handshake del backend provee el catalogo. */
  }
}

export const SCENE_CATEGORY_COLORS = {
  white: "#FFF1E0",
  ambient: "#FF9254",
  nature: "#38BDF8",
  dynamic: "#C084FC",
  holiday: "#F43F5E"
};

/* Mapa cromatico curado para las 36 escenas nativas de WiZ (barra lateral y punto de color) */
export const SCENE_CHROMATIC_MAP = {
  1: { accent: "#00b4d8", gradient: "linear-gradient(135deg, #00b4d8, #0077b6)" },
  2: { accent: "#ff4d6d", gradient: "linear-gradient(135deg, #ff4d6d, #c9184a)" },
  3: { accent: "#ff7b00", gradient: "linear-gradient(135deg, #ff9e00, #e85d04)" },
  4: { accent: "#f72585", gradient: "linear-gradient(135deg, #f72585, #7209b7, #4cc9f0)" },
  5: { accent: "#ff5400", gradient: "linear-gradient(135deg, #ff5400, #d00000)" },
  6: { accent: "#ffb703", gradient: "linear-gradient(135deg, #ffb703, #fb8500)" },
  7: { accent: "#2dc653", gradient: "linear-gradient(135deg, #2d6a4f, #52b788)" },
  8: { accent: "#b8c0ff", gradient: "linear-gradient(135deg, #ffcad4, #b8c0ff, #bde0fe)" },
  9: { accent: "#ffbf69", gradient: "linear-gradient(135deg, #ff9f1c, #ffbf69, #cbf3f0)" },
  10: { accent: "#e07a5f", gradient: "linear-gradient(135deg, #e07a5f, #81b29a)" },
  11: { accent: "#ffd6aa", gradient: "#ffd6aa" },
  12: { accent: "#fff4e6", gradient: "#fff4e6" },
  13: { accent: "#cce6ff", gradient: "#cce6ff" },
  14: { accent: "#ff9e44", gradient: "#ff9e44" },
  15: { accent: "#e2f1ff", gradient: "#e2f1ff" },
  16: { accent: "#ffc899", gradient: "#ffc899" },
  17: { accent: "#fff9f2", gradient: "#fff9f2" },
  18: { accent: "#a3bffa", gradient: "#a3bffa" },
  19: { accent: "#d65db1", gradient: "linear-gradient(135deg, #ff6bcb, #845ec2)" },
  20: { accent: "#80ed99", gradient: "linear-gradient(135deg, #80ed99, #f9c74f)" },
  21: { accent: "#f9c74f", gradient: "linear-gradient(135deg, #f9c74f, #4cc9f0)" },
  22: { accent: "#f3722c", gradient: "linear-gradient(135deg, #f3722c, #f8961e)" },
  23: { accent: "#0096c7", gradient: "linear-gradient(135deg, #03045e, #0077b6, #00b4d8)" },
  24: { accent: "#10b981", gradient: "linear-gradient(135deg, #1b4332, #2dc653)" },
  25: { accent: "#80b918", gradient: "linear-gradient(135deg, #55a630, #aacc00)" },
  26: { accent: "#b5179e", gradient: "linear-gradient(135deg, #7209b7, #3a0ca3, #f72585)" },
  27: { accent: "#ef233c", gradient: "linear-gradient(135deg, #d90429, #2b9348)" },
  28: { accent: "#ff6d00", gradient: "linear-gradient(135deg, #ff6d00, #7b2cbf)" },
  29: { accent: "#ff9f1c", gradient: "linear-gradient(135deg, #ff9f1c, #e76f51)" },
  30: { accent: "#ffe1a8", gradient: "#ffe1a8" },
  31: { accent: "#4cc9f0", gradient: "linear-gradient(135deg, #4361ee, #f72585)" },
  32: { accent: "#ee9b00", gradient: "linear-gradient(135deg, #ca6702, #bb3e03)" },
  33: { accent: "#ffbe0b", gradient: "linear-gradient(135deg, #ffbe0b, #fb5607, #ff006e)" },
  34: { accent: "#ffffff", gradient: "#ffffff" },
  35: { accent: "#ef233c", gradient: "linear-gradient(135deg, #ef233c, #ffb703)" },
  36: { accent: "#90e0ef", gradient: "linear-gradient(135deg, #90e0ef, #caf0f8)" }
};

export const FAV_SCENES_STORAGE_KEY = "gestor_luces_fav_scenes";

export function loadFavoriteSceneIds() {
  try {
    const raw = window.localStorage.getItem(FAV_SCENES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((id) => Number(id)).filter((id) => Number.isInteger(id) && id >= 1 && id <= 36);
  } catch (_err) {
    return [];
  }
}

export function saveFavoriteSceneIds(ids) {
  try {
    window.localStorage.setItem(FAV_SCENES_STORAGE_KEY, JSON.stringify(ids));
  } catch (_err) {
    /* Ignora errores de cuota en entornos restringidos */
  }
}

/* Helper de traduccion que delega en window.I18N con respaldo directo */
export function t(key, vars) {
  if (window.I18N && typeof window.I18N.t === "function") {
    return window.I18N.t(key, vars);
  }
  return key;
}

/* Formatea el nombre visible de la escena #19 manteniendo compatibilidad con pywizlight */
export function formatSceneDisplayName(scene) {
  if (!scene) return "";
  if (scene.scene_id === 19 || scene.name === "Plantgrowth") {
    return t("scenes.plantGrowth");
  }
  return scene.name;
}

export const ALLOWED_THEMES = new Set(["architectural-stone", "atmospheric-dark"]);
export const DEFAULT_THEME = "architectural-stone";

export function normalizeTheme(theme) {
  if (typeof theme === "string") {
    const candidate = theme.trim().toLowerCase();
    if (ALLOWED_THEMES.has(candidate)) {
      return candidate;
    }
  }
  return DEFAULT_THEME;
}

/* Preferencias de interfaz persistentes (pestana activa y secciones plegables) */
export const UI_PREFS_STORAGE_KEY = "gestor_luces_ui_prefs";

export function loadUiPrefs() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(UI_PREFS_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_err) {
    return {};
  }
}

export function saveUiPref(key, value) {
  try {
    const prefs = loadUiPrefs();
    prefs[key] = value;
    window.localStorage.setItem(UI_PREFS_STORAGE_KEY, JSON.stringify(prefs));
  } catch (_err) {
    /* localStorage no disponible: la preferencia solo vive en la sesion actual */
  }
}

/* Estado reactivo local de la interfaz */
export const appState = {
  language: "en",
  theme: DEFAULT_THEME,
  bulbs: [],
  selectedIps: [],
  scenes: SCENE_CATALOG.slice(),
  favoriteSceneIds: loadFavoriteSceneIds(),
  customScenes: [],
  sleepTimer: {
    active: false,
    remaining_seconds: 0,
    total_seconds: 0,
    target_ips: []
  },
  ambilight: {
    active: false,
    monitor_index: 1,
    color_mode: "vibrant",
    auto_brightness: true,
    min_brightness: 10,
    brightness: 85,
    fixed_brightness: 85,
    smoothing_alpha: 0.38,
    last_color: null,
    target_ips: [],
    frames_sent: 0
  },
  ambiTelemetry: {
    lastFrames: 0,
    lastTs: 0,
    fps: 0
  },
  monitors: [
    { index: 1, label: "Display 1 (1920x1080)", width: 1920, height: 1080 }
  ],
  musicSync: {
    active: false,
    device_index: null,
    palette_mode: "spectrum",
    sensitivity: 1.0,
    smoothing_alpha: 0.50,
    audio_brightness: true,
    brightness: 85,
    fixed_brightness: 85,
    rms: 0.0,
    bass: 0.0,
    mid: 0.0,
    treble: 0.0,
    last_color: null,
    target_ips: [],
    frames_sent: 0
  },
  musicTelemetry: {
    lastFrames: 0,
    lastTs: 0,
    fps: 0
  },
  audioDevices: [
    {
      index: -1,
      name: "System Audio Loopback",
      label: "Default System Output (WASAPI Loopback)",
      sample_rate: 48000,
      channels: 2,
      is_default: true
    }
  ],
  activeTab: "temperature",
  sceneCategory: "all",
  autoSyncTimer: null,
  sleepPollTimer: null,
  ambilightPollTimer: null,
  musicPollTimer: null,
  isDraggingWheel: false,
  lastWheelSendMs: 0,
  wheelThrottleTimer: null
};

/* Obtiene el foco de referencia principal entre los seleccionados */
export function getPrimaryBulb() {
  if (appState.selectedIps.length > 0) {
    const found = appState.bulbs.find((b) => appState.selectedIps.includes(b.ip));
    if (found) return found;
  }
  return appState.bulbs[0] || null;
}

/* Utilidades de conversion cromatica */
export function clampInt(val, min, max) {
  const n = Math.round(Number(val));
  if (Number.isNaN(n)) return min;
  return Math.max(min, Math.min(max, n));
}

export function rgbToHex(r, g, b) {
  const toHex = (n) => clampInt(n, 0, 255).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

export function parseHexToRgb(hexStr) {
  const cleaned = String(hexStr || "").trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(cleaned)) return null;
  return {
    r: parseInt(cleaned.slice(0, 2), 16),
    g: parseInt(cleaned.slice(2, 4), 16),
    b: parseInt(cleaned.slice(4, 6), 16)
  };
}

export function hsvToRgb(h, s, v) {
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

export function rgbToHsv(r, g, b) {
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
export function kelvinToCssColor(kelvin) {
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

/* Formatea segundos totales en MM:SS para el indicador del temporizador */
export function formatCountdown(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

/* Calcula la tasa instantanea o promedio de FPS a partir del contador acumulado de fotogramas */
export function computeLiveFps(telemetrySlot, isActive, currentFrames, nominalFps) {
  const now = Date.now();
  const frames = Number(currentFrames) || 0;
  if (!isActive) {
    telemetrySlot.lastFrames = frames;
    telemetrySlot.lastTs = now;
    telemetrySlot.fps = 0;
    return 0;
  }
  if (telemetrySlot.lastTs > 0 && frames > telemetrySlot.lastFrames) {
    const elapsedSec = (now - telemetrySlot.lastTs) / 1000;
    if (elapsedSec >= 0.15) {
      const measured = (frames - telemetrySlot.lastFrames) / elapsedSec;
      telemetrySlot.fps = Math.min(30, Math.max(1, Math.round(measured)));
      telemetrySlot.lastFrames = frames;
      telemetrySlot.lastTs = now;
    }
  } else if (telemetrySlot.lastTs === 0) {
    telemetrySlot.lastFrames = frames;
    telemetrySlot.lastTs = now;
    telemetrySlot.fps = nominalFps;
  }
  return telemetrySlot.fps || nominalFps;
}

/* Sincroniza el progreso visual de un deslizador (<input type="range">) y sus botones de escala */
export function updateSliderFill(inputEl) {
  if (!inputEl) return;
  const min = parseFloat(inputEl.min);
  const max = parseFloat(inputEl.max);
  const val = parseFloat(inputEl.value);
  const safeMin = Number.isNaN(min) ? 0 : min;
  const safeMax = Number.isNaN(max) ? 100 : max;
  const safeVal = Number.isNaN(val) ? safeMin : Math.max(safeMin, Math.min(safeMax, val));
  const pct = safeMax > safeMin ? ((safeVal - safeMin) / (safeMax - safeMin)) * 100 : 0;

  inputEl.style.setProperty("--attr-min", String(safeMin));
  inputEl.style.setProperty("--attr-max", String(safeMax));
  inputEl.style.setProperty("--control-value", String(safeVal));
  inputEl.style.setProperty("--slider-progress", `${pct.toFixed(2)}%`);

  if (inputEl.id) {
    document
      .querySelectorAll(`.scale-preset-btn[data-target-slider="${inputEl.id}"]`)
      .forEach((btn) => {
        const targetVal = parseFloat(btn.getAttribute("data-value") || "");
        const isMatch = !Number.isNaN(targetVal) && Math.abs(targetVal - safeVal) < 0.009;
        btn.classList.toggle("active", isMatch);
      });
  }
}

export function updateAllSlidersFill() {
  document.querySelectorAll('input[type="range"]').forEach((slider) => {
    updateSliderFill(slider);
  });
}
