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

  /* Mapa cromatico curado para las 36 escenas nativas de WiZ (barra lateral y punto de color) */
  const SCENE_CHROMATIC_MAP = {
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

  const FAV_SCENES_STORAGE_KEY = "gestor_luces_fav_scenes";

  function loadFavoriteSceneIds() {
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

  function saveFavoriteSceneIds(ids) {
    try {
      window.localStorage.setItem(FAV_SCENES_STORAGE_KEY, JSON.stringify(ids));
    } catch (_err) {
      /* Ignora errores de cuota en entornos restringidos */
    }
  }

  /* Helper de traduccion que delega en window.I18N con respaldo directo */
  function t(key, vars) {
    if (window.I18N && typeof window.I18N.t === "function") {
      return window.I18N.t(key, vars);
    }
    return key;
  }

  /* Formatea el nombre visible de la escena #19 manteniendo compatibilidad con pywizlight */
  function formatSceneDisplayName(scene) {
    if (!scene) return "";
    if (scene.scene_id === 19 || scene.name === "Plantgrowth") {
      return t("scenes.plantGrowth");
    }
    return scene.name;
  }

  /* Estado reactivo local de la interfaz */
  const appState = {
    language: "en",
    bulbs: [],
    selectedIps: [],
    scenes: FALLBACK_SCENES.slice(),
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
    activeTab: "rgb",
    sceneCategory: "all",
    autoSyncTimer: null,
    sleepPollTimer: null,
    ambilightPollTimer: null,
    musicPollTimer: null,
    isDraggingWheel: false,
    lastWheelSendMs: 0,
    wheelThrottleTimer: null
  };

  /* Simulador en memoria cuando no existe el contenedor nativo de PyWebView */
  function createBrowserMockApi() {
    let mockLanguage = "en";
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
    let mockCustomScenes = [
      {
        id: "preset01",
        name: "Editorial Warmth",
        mode: "temperature",
        brightness: 70,
        color: null,
        temperature: 2700,
        built_in_scene_id: null,
        speed: 100,
        is_favorite: true
      },
      {
        id: "preset02",
        name: "Cyan Backlight",
        mode: "rgb",
        brightness: 85,
        color: { r: 0, g: 180, b: 255, hex: "#00b4ff" },
        temperature: null,
        built_in_scene_id: null,
        speed: 100,
        is_favorite: false
      }
    ];
    let mockSleepTimer = {
      active: false,
      remaining_seconds: 0,
      total_seconds: 0,
      target_ips: [],
      deadlineMs: 0
    };
    let mockAmbilight = {
      active: false,
      monitor_index: 1,
      color_mode: "vibrant",
      auto_brightness: true,
      brightness: 85,
      fixed_brightness: 85,
      smoothing_alpha: 0.38,
      last_color: { r: 56, g: 189, b: 248, hex: "#38bdf8" },
      target_ips: [],
      frames_sent: 0
    };
    const mockMonitors = [
      { index: 1, label: "Display 1 (2560x1440)", width: 2560, height: 1440 },
      { index: 2, label: "Display 2 (1920x1080)", width: 1920, height: 1080 },
      { index: 0, label: "All displays (4480x1440)", width: 4480, height: 1440 }
    ];
    let mockMusicSync = {
      active: false,
      device_index: -1,
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
      last_color: { r: 235, g: 45, b: 95, hex: "#eb2d5f" },
      target_ips: [],
      frames_sent: 0
    };
    const mockAudioDevices = [
      {
        index: -1,
        name: "Speakers (Realtek High Definition Audio) [Loopback]",
        label: "Default · Speakers (Realtek High Definition Audio) [Loopback] (48000 Hz)",
        sample_rate: 48000,
        channels: 2,
        is_default: true
      }
    ];

    function syncMockTimer() {
      if (!mockSleepTimer.active) return;
      const rem = Math.max(0, Math.ceil((mockSleepTimer.deadlineMs - Date.now()) / 1000));
      if (rem <= 0) {
        mockSleepTimer.active = false;
        mockSleepTimer.remaining_seconds = 0;
        mockSleepTimer.total_seconds = 0;
        mockBulbs.forEach((b) => {
          if (mockSleepTimer.target_ips.includes(b.ip)) {
            b.state.is_on = false;
          }
        });
        mockSleepTimer.target_ips = [];
      } else {
        mockSleepTimer.remaining_seconds = rem;
      }
    }

    function buildMockEnvelope() {
      syncMockTimer();
      return Promise.resolve({
        ok: true,
        language: mockLanguage,
        bulbs: JSON.parse(JSON.stringify(mockBulbs)),
        selected_ips: mockSelected.slice(),
        scenes: FALLBACK_SCENES.slice(),
        custom_scenes: JSON.parse(JSON.stringify(mockCustomScenes)),
        sleep_timer: {
          active: mockSleepTimer.active,
          remaining_seconds: mockSleepTimer.remaining_seconds,
          total_seconds: mockSleepTimer.total_seconds,
          target_ips: mockSleepTimer.target_ips.slice()
        },
        ambilight: JSON.parse(JSON.stringify(mockAmbilight)),
        monitors: mockMonitors.slice(),
        music_sync: JSON.parse(JSON.stringify(mockMusicSync)),
        audio_devices: mockAudioDevices.slice(),
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
      set_language: (lang) => {
        const cleaned = String(lang || "en").trim().toLowerCase();
        mockLanguage = cleaned === "es" ? "es" : "en";
        return buildMockEnvelope();
      },
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
      },
      save_custom_scene: (name) => {
        const refBulb = mockBulbs.find((b) => mockSelected.includes(b.ip)) || mockBulbs[0];
        const st = refBulb ? refBulb.state : { mode: "temperature", brightness: 100, color: null, temperature: 4200, scene_id: null, speed: 100 };
        mockCustomScenes.push({
          id: Math.random().toString(16).slice(2, 10),
          name: String(name || "Preset").trim(),
          mode: st.mode,
          brightness: st.brightness,
          color: st.color ? Object.assign({}, st.color) : null,
          temperature: st.temperature,
          built_in_scene_id: st.scene_id,
          speed: st.speed || 100
        });
        return buildMockEnvelope();
      },
      update_custom_scene: (sceneId, name, captureCurrent) => {
        const target = mockCustomScenes.find((s) => s.id === sceneId);
        if (target) {
          target.name = String(name || target.name).trim();
          if (captureCurrent) {
            const refBulb = mockBulbs.find((b) => mockSelected.includes(b.ip)) || mockBulbs[0];
            if (refBulb) {
              target.mode = refBulb.state.mode;
              target.brightness = refBulb.state.brightness;
              target.color = refBulb.state.color ? Object.assign({}, refBulb.state.color) : null;
              target.temperature = refBulb.state.temperature;
              target.built_in_scene_id = refBulb.state.scene_id;
              target.speed = refBulb.state.speed || 100;
            }
          }
        }
        return buildMockEnvelope();
      },
      delete_custom_scene: (sceneId) => {
        mockCustomScenes = mockCustomScenes.filter((s) => s.id !== sceneId);
        return buildMockEnvelope();
      },
      set_custom_scene_favorite: (sceneId, isFavorite) => {
        const target = mockCustomScenes.find((s) => s.id === sceneId);
        if (target) {
          target.is_favorite = Boolean(isFavorite);
        }
        return buildMockEnvelope();
      },
      apply_custom_scene: (sceneId, ips) => {
        const preset = mockCustomScenes.find((s) => s.id === sceneId);
        if (!preset) return buildMockEnvelope();
        const targets = resolveTargets(ips);
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = preset.mode;
            bulb.state.brightness = preset.brightness;
            bulb.state.color = preset.color ? Object.assign({}, preset.color) : null;
            bulb.state.temperature = preset.temperature;
            bulb.state.scene_id = preset.built_in_scene_id;
            const bScene = FALLBACK_SCENES.find((s) => s.scene_id === preset.built_in_scene_id);
            bulb.state.scene_name = bScene ? bScene.name : null;
            bulb.state.speed = preset.speed || 100;
          }
        });
        return buildMockEnvelope();
      },
      start_sleep_timer: (minutes, ips) => {
        const totalSec = Math.max(1, Math.round(Number(minutes) * 60));
        mockSleepTimer = {
          active: true,
          remaining_seconds: totalSec,
          total_seconds: totalSec,
          target_ips: resolveTargets(ips),
          deadlineMs: Date.now() + totalSec * 1000
        };
        return buildMockEnvelope();
      },
      cancel_sleep_timer: () => {
        mockSleepTimer = {
          active: false,
          remaining_seconds: 0,
          total_seconds: 0,
          target_ips: [],
          deadlineMs: 0
        };
        return buildMockEnvelope();
      },
      get_sleep_timer_status: () => buildMockEnvelope(),
      start_ambilight: (monitorIndex, colorMode, autoBrightness, brightness, smoothingAlpha, ips, minBrightness) => {
        const targets = resolveTargets(ips);
        const sampled = { r: 56, g: 189, b: 248, hex: "#38bdf8" };
        mockMusicSync.active = false;
        mockMusicSync.target_ips = [];
        mockAmbilight = {
          active: true,
          monitor_index: Number(monitorIndex || 1),
          color_mode: String(colorMode || "vibrant"),
          auto_brightness: Boolean(autoBrightness),
          min_brightness: clampInt(minBrightness != null ? minBrightness : 10, 5, 20),
          brightness: Number(brightness || 85),
          fixed_brightness: Number(brightness || 85),
          smoothing_alpha: Number(smoothingAlpha || 0.38),
          last_color: sampled,
          target_ips: targets,
          frames_sent: mockAmbilight.frames_sent + 1
        };
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = "rgb";
            bulb.state.color = Object.assign({}, sampled);
            bulb.state.temperature = null;
          }
        });
        return buildMockEnvelope();
      },
      stop_ambilight: () => {
        mockAmbilight.active = false;
        mockAmbilight.target_ips = [];
        return buildMockEnvelope();
      },
      get_ambilight_status: () => {
        if (mockAmbilight.active) {
          mockAmbilight.frames_sent += 4;
        }
        return buildMockEnvelope();
      },
      start_music_sync: (paletteMode, sensitivity, smoothingAlpha, audioBrightness, brightness, deviceIndex, ips) => {
        const targets = resolveTargets(ips);
        const sampled = { r: 240, g: 52, b: 112, hex: "#f03470" };
        mockAmbilight.active = false;
        mockAmbilight.target_ips = [];
        mockMusicSync = {
          active: true,
          device_index: deviceIndex != null ? Number(deviceIndex) : -1,
          palette_mode: String(paletteMode || "spectrum"),
          sensitivity: Number(sensitivity || 1.0),
          smoothing_alpha: Number(smoothingAlpha || 0.50),
          audio_brightness: Boolean(audioBrightness),
          brightness: Number(brightness || 85),
          fixed_brightness: Number(brightness || 85),
          rms: 0.68,
          bass: 0.82,
          mid: 0.54,
          treble: 0.36,
          last_color: sampled,
          target_ips: targets,
          frames_sent: mockMusicSync.frames_sent + 1
        };
        mockBulbs.forEach((bulb) => {
          if (targets.includes(bulb.ip)) {
            bulb.state.is_on = true;
            bulb.state.mode = "rgb";
            bulb.state.color = Object.assign({}, sampled);
            bulb.state.temperature = null;
          }
        });
        return buildMockEnvelope();
      },
      stop_music_sync: () => {
        mockMusicSync.active = false;
        mockMusicSync.target_ips = [];
        mockMusicSync.rms = 0.0;
        mockMusicSync.bass = 0.0;
        mockMusicSync.mid = 0.0;
        mockMusicSync.treble = 0.0;
        return buildMockEnvelope();
      },
      get_music_sync_status: () => {
        if (mockMusicSync.active) {
          mockMusicSync.frames_sent += 3;
        }
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

  /* Toasts: los exitosos se cierran solos y se reemplazan entre si (evita ruido al arrastrar
     sliders); los de error permanecen hasta cerrarse e incluyen un boton para reintentar. */
  const TOAST_OK_MS = 2200;
  let okToastEl = null;
  let okToastTimer = null;

  function dismissToast(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
    if (el === okToastEl) okToastEl = null;
  }

  function showToast({ kind, message, retry }) {
    const region = document.getElementById("toast-region");
    if (!region || !message) return;

    if (kind === "ok") {
      clearTimeout(okToastTimer);
      if (okToastEl) {
        okToastEl.querySelector(".toast-message").textContent = message;
      } else {
        okToastEl = buildToast("ok", message, null);
        region.appendChild(okToastEl);
      }
      okToastTimer = setTimeout(() => dismissToast(okToastEl), TOAST_OK_MS);
      return;
    }

    /* Un error identico ya visible no se duplica */
    const duplicate = Array.from(region.querySelectorAll(".toast-error .toast-message")).find(
      (node) => node.textContent === message
    );
    if (duplicate) return;
    region.appendChild(buildToast("error", message, retry));
  }

  function buildToast(kind, message, retry) {
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    if (kind === "error") el.setAttribute("role", "alert");

    const text = document.createElement("span");
    text.className = "toast-message";
    text.textContent = message;
    el.appendChild(text);

    if (kind === "error") {
      if (typeof retry === "function") {
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "toast-action";
        retryBtn.textContent = t("toast.retry");
        retryBtn.addEventListener("click", () => {
          dismissToast(el);
          retry();
        });
        el.appendChild(retryBtn);
      }
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "toast-close";
      closeBtn.setAttribute("aria-label", t("toast.dismiss"));
      closeBtn.textContent = "\u00d7";
      closeBtn.addEventListener("click", () => dismissToast(el));
      el.appendChild(closeBtn);
    }
    return el;
  }

  /* Sincroniza el progreso visual de un deslizador (<input type="range">) y sus botones de escala */
  function updateSliderFill(inputEl) {
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

  function updateAllSlidersFill() {
    document.querySelectorAll('input[type="range"]').forEach((slider) => {
      updateSliderFill(slider);
    });
  }

  /* Calcula la tasa instantanea o promedio de FPS a partir del contador acumulado de fotogramas */
  function computeLiveFps(telemetrySlot, isActive, currentFrames, nominalFps) {
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

  /* Sincroniza el selector visual de idioma (EN | ES) y traduce el arbol DOM estatico */
  function syncLanguageUi(lang) {
    const normalized = String(lang || "en").trim().toLowerCase() === "es" ? "es" : "en";
    appState.language = normalized;
    if (window.I18N) {
      window.I18N.setLanguage(normalized);
      window.I18N.translateDom();
    }
    document.querySelectorAll(".lang-btn").forEach((btn) => {
      const isMatch = btn.getAttribute("data-lang") === normalized;
      btn.setAttribute("aria-pressed", String(isMatch));
    });
  }

  /* Actualiza la variable CSS `--beam-color` y toda la interfaz a partir del sobre del backend */
  function applyBackendEnvelope(envelope, statusText, retry, silent) {
    if (!envelope) return;
    if (typeof envelope.language === "string") {
      syncLanguageUi(envelope.language);
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
    renderFixtureList();
    renderStageHeaderAndControls();
    renderSleepTimer();
    renderScenesGrid();
    renderCustomScenesGrid();
    renderAmbilightPanel();
    renderMusicPanel();
  }

  /* Renderiza las tarjetas de focos en el riel izquierdo sin usar innerHTML con datos de usuario */
  function renderFixtureList() {
    const container = document.getElementById("fixture-list");
    const badge = document.getElementById("fixture-count-badge");
    const selectAllCheckbox = document.getElementById("select-all-fixtures");
    if (!container) return;

    const onlineCount = appState.bulbs.filter((b) => b.is_online).length;
    if (badge) {
      badge.textContent = t("rail.onlineCount", {
        online: onlineCount,
        total: appState.bulbs.length
      });
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
      p1.textContent = t("rail.emptyTitle");
      const p2 = document.createElement("p");
      p2.textContent = t("rail.emptySubtitle");
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
      checkbox.setAttribute("aria-label", t("rail.selectFixtureAria", { name: bulb.name }));
      checkbox.addEventListener("change", () => {
        let nextIps = appState.selectedIps.slice();
        if (checkbox.checked) {
          if (!nextIps.includes(bulb.ip)) nextIps.push(bulb.ip);
        } else {
          nextIps = nextIps.filter((ip) => ip !== bulb.ip);
        }
        invokeApi(() => backendApi.select_targets(nextIps), () => t("status.selectionUpdated"));
      });

      const metaDiv = document.createElement("div");
      metaDiv.className = "fixture-meta";

      const titleRow = document.createElement("div");
      titleRow.className = "fixture-title-row";

      const nameHeading = document.createElement("h3");
      nameHeading.className = "fixture-name";
      nameHeading.textContent = bulb.name;

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "btn-icon-rename";
      const renameTooltip = t("rail.renameAria", { name: bulb.name });
      renameBtn.title = renameTooltip;
      renameBtn.setAttribute("aria-label", renameTooltip);

      const pencilSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      pencilSvg.setAttribute("class", "icon");
      pencilSvg.setAttribute("viewBox", "0 0 20 20");
      pencilSvg.setAttribute("fill", "none");
      pencilSvg.setAttribute("aria-hidden", "true");
      const pencilPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      pencilPath.setAttribute(
        "d",
        "M13.58 3.58a2 2 0 0 1 2.84 2.84l-8.5 8.5-3.67.83.83-3.67 8.5-8.5ZM12.17 5l2.83 2.83"
      );
      pencilPath.setAttribute("stroke", "currentColor");
      pencilPath.setAttribute("stroke-width", "1.5");
      pencilPath.setAttribute("stroke-linecap", "round");
      pencilPath.setAttribute("stroke-linejoin", "round");
      pencilSvg.appendChild(pencilPath);
      renameBtn.appendChild(pencilSvg);

      renameBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openRenameDialog(bulb);
      });

      titleRow.append(nameHeading, renameBtn);

      const addressLine = document.createElement("p");
      addressLine.className = "fixture-address";
      addressLine.textContent = `${bulb.ip} · ${bulb.mac}`;

      metaDiv.append(titleRow, addressLine);
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
      statusText.textContent = bulb.is_online ? t("rail.statusOnline") : t("rail.statusOffline");
      statusSpan.append(dot, statusText);

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "fixture-card-actions";

      const isBulbOn = Boolean(bulb.state.is_on);
      const powerBtn = document.createElement("button");
      powerBtn.type = "button";
      powerBtn.className = "btn-fixture-power";
      powerBtn.setAttribute("aria-pressed", String(isBulbOn));
      const powerLabel = t(
        isBulbOn ? "rail.powerToggleOnAria" : "rail.powerToggleOffAria",
        { name: bulb.name }
      );
      powerBtn.title = powerLabel;
      powerBtn.setAttribute("aria-label", powerLabel);

      const powerSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      powerSvg.setAttribute("class", "icon");
      powerSvg.setAttribute("viewBox", "0 0 20 20");
      powerSvg.setAttribute("fill", "none");
      powerSvg.setAttribute("aria-hidden", "true");
      const powerPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      powerPath.setAttribute("d", "M10 2.75v6.5M6.1 4.85a6.5 6.5 0 1 0 7.8 0");
      powerPath.setAttribute("stroke", "currentColor");
      powerPath.setAttribute("stroke-width", "1.75");
      powerPath.setAttribute("stroke-linecap", "round");
      powerSvg.appendChild(powerPath);
      powerBtn.appendChild(powerSvg);

      powerBtn.addEventListener("click", () => {
        const nextPower = !bulb.state.is_on;
        invokeApi(
          () => backendApi.set_power(nextPower, null, [bulb.ip]),
          () =>
            t(nextPower ? "status.bulbTurnedOn" : "status.bulbTurnedOff", {
              name: bulb.name
            })
        );
      });

      actionsDiv.appendChild(powerBtn);
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
    const aperture = document.getElementById("photometric-aperture");
    if (!primary) {
      if (shell) shell.setAttribute("data-power", "off");
      document.documentElement.style.setProperty("--beam-color", "#2A303C");
      if (aperture) {
        aperture.style.backgroundColor = "#232832";
        aperture.style.boxShadow = "none";
      }
      if (targetSummary) targetSummary.textContent = t("stage.noFixture");
      if (statePill) statePill.textContent = t("stage.stateOffline");
      updateAllSlidersFill();
      return;
    }

    const selectedCount = appState.selectedIps.length || appState.bulbs.length;
    if (targetSummary) {
      /* Destinos reales de los comandos: los seleccionados (o todos si no hay seleccion) */
      const targets = appState.selectedIps.length
        ? appState.bulbs.filter((b) => appState.selectedIps.includes(b.ip))
        : appState.bulbs;
      const names = targets.map((b) => b.name);
      let summary;
      if (selectedCount === 1) {
        summary = t("stage.controllingOne", { name: primary.name });
      } else if (selectedCount <= 3 && names.length === selectedCount) {
        summary = t("stage.controllingList", { count: selectedCount, names: names.join(", ") });
      } else {
        summary = t("stage.controllingMany", { count: selectedCount, name: primary.name });
      }
      targetSummary.textContent = summary;
      /* El tooltip siempre lista todos los destinos */
      targetSummary.title = names.join("\n");
    }

    const st = primary.state;
    const isOn = Boolean(st.is_on);
    if (shell) {
      shell.setAttribute("data-power", isOn ? "on" : "off");
    }

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

    /* Calculo del color fotometrico (`--beam-color`) segun el modo activo */
    let beamCss = "#2A303C";
    let modeReadout = t("stage.stateOff");

    if (isOn) {
      if (st.mode === "rgb" && st.color) {
        beamCss = `rgb(${st.color.r}, ${st.color.g}, ${st.color.b})`;
        modeReadout = t("stage.stateOnRgb", {
          r: st.color.r,
          g: st.color.g,
          b: st.color.b,
          brightness: st.brightness
        });
      } else if (st.mode === "scene" && st.scene_id) {
        const sceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
        const sceneTheme = SCENE_CHROMATIC_MAP[st.scene_id];
        const category = sceneObj ? sceneObj.category : "dynamic";
        beamCss = (sceneTheme && sceneTheme.accent) || SCENE_CATEGORY_COLORS[category] || "#C084FC";
        const sceneTitle = sceneObj
          ? formatSceneDisplayName(sceneObj)
          : (st.scene_name || `#${st.scene_id}`);
        modeReadout = t("stage.stateOnScene", {
          scene: sceneTitle,
          brightness: st.brightness
        });
      } else {
        const kelvin = st.temperature || 4200;
        beamCss = kelvinToCssColor(kelvin);
        modeReadout = t("stage.stateOnKelvin", {
          kelvin,
          brightness: st.brightness
        });
      }
    } else {
      modeReadout = t("stage.stateOffStandby", { brightness: st.brightness });
    }

    document.documentElement.style.setProperty("--beam-color", beamCss);
    if (aperture) {
      if (isOn) {
        const briNorm = Math.max(0, Math.min(1, ((Number(st.brightness) || 100) - 10) / 90));
        const glowRadius = Math.round(12 + briNorm * 24);
        const glowAlpha = Math.round(28 + briNorm * 52);
        aperture.style.backgroundColor = beamCss;
        aperture.style.boxShadow = `0 0 ${glowRadius}px color-mix(in oklab, ${beamCss} ${glowAlpha}%, transparent)`;
      } else {
        aperture.style.backgroundColor = "#232832";
        aperture.style.boxShadow = "none";
      }
    }
    if (statePill) {
      statePill.textContent = modeReadout;
      statePill.title = modeReadout;
    }
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
      updateSliderFill(kelvinSlider);
    }
    document.querySelectorAll(".kelvin-card").forEach((card) => {
      card.classList.toggle(
        "active",
        st.mode === "temperature" && Number(card.dataset.kelvin) === activeKelvin
      );
    });

    /* Sincronizacion contextual del deslizador de velocidad de escena */
    const speedContainer = document.getElementById("scene-speed-container");
    const speedSlider = document.getElementById("scene-speed-slider");
    const speedOutput = document.getElementById("scene-speed-output");
    const activeSceneObj = appState.scenes.find((s) => s.scene_id === st.scene_id);
    const isDynamicSpeedSupported = Boolean(
      st.mode === "scene" &&
      activeSceneObj &&
      activeSceneObj.supports_speed &&
      appState.sceneCategory !== "white"
    );
    if (speedContainer) {
      speedContainer.classList.toggle("is-disabled", !isDynamicSpeedSupported);
    }
    if (speedSlider && speedOutput) {
      speedSlider.value = String(st.speed || 100);
      speedOutput.textContent = String(st.speed || 100);
      speedSlider.disabled = !isDynamicSpeedSupported;
      updateSliderFill(speedSlider);
    }
  }

  /* Actualiza los contadores en cada pildora de filtro de categoria de escenas */
  function updateSceneCategoryCounts() {
    const countByCat = (cat) => appState.scenes.filter((s) => s.category === cat).length;
    const favCount = appState.favoriteSceneIds.length;

    const favLabel = document.getElementById("scene-cat-favorites-label");
    if (favLabel) {
      favLabel.textContent = t("scenes.catFavoritesCount", { count: favCount });
    }

    const catKeyMap = {
      all: { key: "scenes.catAllCount", count: appState.scenes.length },
      white: { key: "scenes.catWhiteCount", count: countByCat("white") },
      ambient: { key: "scenes.catAmbientCount", count: countByCat("ambient") },
      nature: { key: "scenes.catNatureCount", count: countByCat("nature") },
      dynamic: { key: "scenes.catDynamicCount", count: countByCat("dynamic") },
      holiday: { key: "scenes.catHolidayCount", count: countByCat("holiday") }
    };

    document.querySelectorAll("#scene-category-bar .scene-filter").forEach((btn) => {
      const cat = btn.dataset.category;
      if (cat && catKeyMap[cat]) {
        btn.textContent = t(catKeyMap[cat].key, { count: catKeyMap[cat].count });
      }
    });
  }

  /* Renderiza la cuadricula de las 36 escenas nativas de WiZ con indicadores cromaticos y favoritos */
  function renderScenesGrid() {
    const grid = document.getElementById("scenes-grid");
    updateSceneCategoryCounts();
    if (!grid) return;

    const primary = getPrimaryBulb();
    const activeSceneId =
      primary && primary.state.mode === "scene" ? primary.state.scene_id : null;

    /* Sincroniza tambien el estado contextual del contenedor de velocidad al cambiar de filtro */
    const speedContainer = document.getElementById("scene-speed-container");
    const speedSlider = document.getElementById("scene-speed-slider");
    const activeSceneObj = appState.scenes.find((s) => s.scene_id === activeSceneId);
    const isDynamicSpeedSupported = Boolean(
      activeSceneObj &&
      activeSceneObj.supports_speed &&
      appState.sceneCategory !== "white"
    );
    if (speedContainer) {
      speedContainer.classList.toggle("is-disabled", !isDynamicSpeedSupported);
    }
    if (speedSlider) {
      speedSlider.disabled = !isDynamicSpeedSupported;
    }

    let filtered = [];
    if (appState.sceneCategory === "favorites") {
      filtered = appState.scenes.filter((scene) =>
        appState.favoriteSceneIds.includes(scene.scene_id)
      );
    } else if (appState.sceneCategory === "all") {
      /* En la vista Todas (36), las escenas favoritas fijadas aparecen primero */
      filtered = appState.scenes.slice().sort((a, b) => {
        const aFav = appState.favoriteSceneIds.includes(a.scene_id) ? 0 : 1;
        const bFav = appState.favoriteSceneIds.includes(b.scene_id) ? 0 : 1;
        if (aFav !== bFav) return aFav - bFav;
        return a.scene_id - b.scene_id;
      });
    } else {
      filtered = appState.scenes.filter((scene) => scene.category === appState.sceneCategory);
    }

    grid.replaceChildren();

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-fixtures-state";
      const p = document.createElement("p");
      p.textContent = t("scenes.emptyFavorites");
      empty.appendChild(p);
      grid.appendChild(empty);
      return;
    }

    filtered.forEach((scene) => {
      const isSceneActive = activeSceneId === scene.scene_id;
      const isFav = appState.favoriteSceneIds.includes(scene.scene_id);
      const displayName = formatSceneDisplayName(scene);
      const chroma = SCENE_CHROMATIC_MAP[scene.scene_id] || {
        accent: SCENE_CATEGORY_COLORS[scene.category] || "#38bdf8",
        gradient: SCENE_CATEGORY_COLORS[scene.category] || "#38bdf8"
      };

      const card = document.createElement("article");
      card.className = `scene-card${isSceneActive ? " active" : ""}`;
      card.setAttribute("role", "button");
      card.tabIndex = 0;
      card.style.setProperty("--scene-accent", chroma.accent);
      card.style.setProperty("--scene-gradient", chroma.gradient);

      const top = document.createElement("div");
      top.className = "scene-card-top";

      const idGroup = document.createElement("div");
      idGroup.className = "scene-card-id-group";

      const colorDot = document.createElement("span");
      colorDot.className = "scene-color-dot";
      colorDot.setAttribute("aria-hidden", "true");

      const idBadge = document.createElement("span");
      idBadge.className = "scene-id-badge";
      idBadge.textContent = `#${String(scene.scene_id).padStart(2, "0")}`;

      idGroup.append(colorDot, idBadge);

      const badgesGroup = document.createElement("div");
      badgesGroup.className = "scene-card-badges";

      if (isSceneActive) {
        const activeBadge = document.createElement("span");
        activeBadge.className = "scene-active-badge";
        activeBadge.textContent = t("scenes.badgeActive");
        badgesGroup.appendChild(activeBadge);
      }

      const tag = document.createElement("span");
      tag.className = "scene-tag";
      tag.textContent = scene.supports_speed ? t("scenes.tagDynamic") : t("scenes.tagStatic");
      badgesGroup.appendChild(tag);

      top.append(idGroup, badgesGroup);

      const bottom = document.createElement("div");
      bottom.className = "scene-card-bottom";

      const title = document.createElement("p");
      title.className = "scene-name";
      title.textContent = displayName;

      const favBtn = document.createElement("button");
      favBtn.type = "button";
      favBtn.className = `scene-fav-btn${isFav ? " is-fav" : ""}`;
      favBtn.setAttribute("aria-pressed", String(isFav));
      const favLabel = t(isFav ? "scenes.favRemoveAria" : "scenes.favAddAria", {
        name: displayName
      });
      favBtn.title = favLabel;
      favBtn.setAttribute("aria-label", favLabel);

      const starSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      starSvg.setAttribute("class", "icon");
      starSvg.setAttribute("viewBox", "0 0 20 20");
      starSvg.setAttribute("fill", isFav ? "currentColor" : "none");
      starSvg.setAttribute("aria-hidden", "true");
      const starPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      starPath.setAttribute(
        "d",
        "M10 2.75l2.18 4.42 4.88.71-3.53 3.44.83 4.86L10 13.88l-4.36 2.3.83-4.86-3.53-3.44 4.88-.71L10 2.75Z"
      );
      starPath.setAttribute("stroke", "currentColor");
      starPath.setAttribute("stroke-width", "1.5");
      starPath.setAttribute("stroke-linejoin", "round");
      starSvg.appendChild(starPath);
      favBtn.appendChild(starSvg);

      favBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const exists = appState.favoriteSceneIds.includes(scene.scene_id);
        if (exists) {
          appState.favoriteSceneIds = appState.favoriteSceneIds.filter(
            (id) => id !== scene.scene_id
          );
        } else {
          appState.favoriteSceneIds.push(scene.scene_id);
        }
        saveFavoriteSceneIds(appState.favoriteSceneIds);
        renderScenesGrid();
        setStatusMessage(
          t(exists ? "status.sceneFavRemoved" : "status.sceneFavAdded", { name: displayName })
        );
      });

      bottom.append(title, favBtn);
      card.append(top, bottom);

      const activateScene = () => {
        const speedInput = document.getElementById("scene-speed-slider");
        const speedVal = scene.supports_speed && speedInput ? Number(speedInput.value) : null;
        invokeApi(
          () => backendApi.set_builtin_scene(scene.scene_id, speedVal, null, null),
          () => t("status.sceneActivated", { id: scene.scene_id, name: displayName })
        );
      };

      card.addEventListener("click", activateScene);
      card.addEventListener("keydown", (event) => {
        if (event.target !== card) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activateScene();
        }
      });

      grid.appendChild(card);
    });
  }

  /* Formatea segundos totales en MM:SS para el indicador del temporizador */
  function formatCountdown(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  /* Activa o detiene el sondeo cada 1s mientras el temporizador de apagado este corriendo */
  function syncSleepTimerPolling() {
    const isActive = Boolean(appState.sleepTimer && appState.sleepTimer.active);
    if (isActive && !appState.sleepPollTimer) {
      appState.sleepPollTimer = setInterval(() => {
        invokeApi(() => backendApi.get_sleep_timer_status(), null);
      }, 1000);
    } else if (!isActive && appState.sleepPollTimer) {
      clearInterval(appState.sleepPollTimer);
      appState.sleepPollTimer = null;
    }
  }

  /* Actualiza la barra visual colapsable del Sleep Timer y el estado contextual del boton Cancelar */
  function renderSleepTimer() {
    const detailsEl = document.getElementById("sleep-timer-details");
    const badge = document.getElementById("sleep-timer-badge");
    const cancelBtn = document.getElementById("cancel-sleep-timer-btn");
    const timer = appState.sleepTimer || { active: false, remaining_seconds: 0, total_seconds: 0 };

    if (detailsEl && timer.active) {
      detailsEl.open = true;
    }

    if (badge) {
      badge.setAttribute("data-active", String(Boolean(timer.active)));
      badge.setAttribute("data-live", String(Boolean(timer.active)));
      if (timer.active) {
        const fadeThreshold = Math.ceil((timer.total_seconds || 0) * 0.3);
        const inFadePhase = timer.remaining_seconds <= fadeThreshold;
        const phaseLabel = inFadePhase ? t("sleep.phaseFade") : t("sleep.phaseSteady");
        badge.textContent = t("sleep.badgeActive", {
          countdown: formatCountdown(timer.remaining_seconds),
          phase: phaseLabel
        });
      } else {
        badge.textContent = t("sleep.badgeInactive");
      }
    }

    if (cancelBtn) {
      cancelBtn.disabled = !timer.active;
      cancelBtn.classList.toggle("is-active-alert", Boolean(timer.active));
      cancelBtn.textContent = timer.active
        ? t("sleep.cancelBtnActive", { countdown: formatCountdown(timer.remaining_seconds) })
        : t("sleep.cancelBtn");
    }
  }

  /* Sondea cada 400ms el color muestreado mientras Ambilight este activo */
  function syncAmbilightPolling() {
    const isActive = Boolean(appState.ambilight && appState.ambilight.active);
    if (isActive && !appState.ambilightPollTimer) {
      appState.ambilightPollTimer = setInterval(() => {
        invokeApi(() => backendApi.get_ambilight_status(), null);
      }, 400);
    } else if (!isActive && appState.ambilightPollTimer) {
      clearInterval(appState.ambilightPollTimer);
      appState.ambilightPollTimer = null;
    }
  }

  /* Sincroniza el panel de Ambilight, la lista de pantallas y la muestra de color en vivo */
  function renderAmbilightPanel() {
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

  /* Sondea cada 250ms la telemetria acustica (Bass/Mid/Treble/RMS) mientras Music Sync este activo */
  function syncMusicPolling() {
    const isActive = Boolean(appState.musicSync && appState.musicSync.active);
    if (isActive && !appState.musicPollTimer) {
      appState.musicPollTimer = setInterval(() => {
        invokeApi(() => backendApi.get_music_sync_status(), null);
      }, 250);
    } else if (!isActive && appState.musicPollTimer) {
      clearInterval(appState.musicPollTimer);
      appState.musicPollTimer = null;
    }
  }

  /* Actualiza las barras espectrales FFT, la muestra cromatica y la configuracion de WASAPI */
  function renderMusicPanel() {
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

  /* Renderiza la galeria de presets personalizados guardados en JSON */
  function renderCustomScenesGrid() {
    const grid = document.getElementById("custom-scenes-grid");
    const tabLabel = document.getElementById("custom-tab-label");
    if (tabLabel) {
      tabLabel.textContent = t("tabs.customWithCount", { count: appState.customScenes.length });
    }
    if (!grid) return;

    grid.replaceChildren();

    if (appState.customScenes.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-fixtures-state";
      const p1 = document.createElement("p");
      p1.textContent = t("custom.emptyTitle");
      const p2 = document.createElement("p");
      p2.textContent = t("custom.emptySubtitle");
      empty.append(p1, p2);
      grid.appendChild(empty);
      return;
    }

    appState.customScenes.forEach((preset) => {
      const card = document.createElement("article");
      card.className = "custom-scene-card";

      let swatchCss = "#FFF1E0";
      let summaryText = `${preset.brightness}%`;

      if (preset.mode === "rgb" && preset.color) {
        const hex = (preset.color.hex || rgbToHex(preset.color.r, preset.color.g, preset.color.b)).toUpperCase();
        swatchCss = `rgb(${preset.color.r}, ${preset.color.g}, ${preset.color.b})`;
        summaryText = `RGB ${hex} · ${preset.brightness}%`;
      } else if (preset.mode === "scene" && preset.built_in_scene_id) {
        const bScene = appState.scenes.find((s) => s.scene_id === preset.built_in_scene_id);
        const cat = bScene ? bScene.category : "dynamic";
        swatchCss = SCENE_CATEGORY_COLORS[cat] || "#C084FC";
        const sName = bScene ? bScene.name : `#${preset.built_in_scene_id}`;
        summaryText = t("custom.summaryScene", {
          scene: sName,
          brightness: preset.brightness
        });
      } else {
        const k = preset.temperature || 4200;
        swatchCss = kelvinToCssColor(k);
        summaryText = `${k} K · ${preset.brightness}%`;
      }

      const topArea = document.createElement("div");
      topArea.className = "custom-scene-top";
      topArea.setAttribute("role", "button");
      topArea.tabIndex = 0;
      topArea.setAttribute("aria-label", t("custom.applyAria", { name: preset.name }));

      const swatch = document.createElement("span");
      swatch.className = "custom-scene-swatch";
      swatch.style.setProperty("--preset-swatch", swatchCss);
      swatch.setAttribute("aria-hidden", "true");

      const meta = document.createElement("div");
      meta.className = "custom-scene-meta";

      const title = document.createElement("h4");
      title.className = "custom-scene-title";
      title.textContent = preset.name;

      const summary = document.createElement("p");
      summary.className = "custom-scene-summary";
      summary.textContent = summaryText;

      meta.append(title, summary);
      topArea.append(swatch, meta);

      const triggerApply = () => {
        invokeApi(
          () => backendApi.apply_custom_scene(preset.id, null),
          () => t("status.presetApplied", { name: preset.name })
        );
      };

      topArea.addEventListener("click", triggerApply);
      topArea.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          triggerApply();
        }
      });

      const actions = document.createElement("div");
      actions.className = "custom-scene-actions";

      const isFavorite = Boolean(preset.is_favorite);
      const favoriteBtn = document.createElement("button");
      favoriteBtn.type = "button";
      favoriteBtn.className = `btn btn-compact btn-favorite${isFavorite ? " is-favorite" : ""}`;
      favoriteBtn.setAttribute("aria-pressed", String(isFavorite));
      favoriteBtn.title = isFavorite
        ? t("custom.favoriteRemoveTitle")
        : t("custom.favoriteAddTitle");

      const starSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      starSvg.setAttribute("class", "icon");
      starSvg.setAttribute("viewBox", "0 0 20 20");
      starSvg.setAttribute("fill", isFavorite ? "currentColor" : "none");
      starSvg.setAttribute("aria-hidden", "true");
      const starPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      starPath.setAttribute(
        "d",
        "M10 2.75l2.18 4.42 4.88.71-3.53 3.44.83 4.86L10 13.88l-4.36 2.3.83-4.86-3.53-3.44 4.88-.71L10 2.75Z"
      );
      starPath.setAttribute("stroke", "currentColor");
      starPath.setAttribute("stroke-width", "1.5");
      starPath.setAttribute("stroke-linejoin", "round");
      starSvg.appendChild(starPath);

      const favoriteLabel = document.createElement("span");
      favoriteLabel.textContent = isFavorite ? t("custom.favoritedBtn") : t("custom.favoriteBtn");
      favoriteBtn.append(starSvg, favoriteLabel);
      favoriteBtn.addEventListener("click", () => {
        const nextFavorite = !isFavorite;
        invokeApi(
          () => backendApi.set_custom_scene_favorite(preset.id, nextFavorite),
          () =>
            t(nextFavorite ? "status.favoriteAdded" : "status.favoriteRemoved", {
              name: preset.name
            })
        );
      });

      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "btn btn-compact btn-primary";
      applyBtn.textContent = t("custom.applyBtn");
      applyBtn.addEventListener("click", triggerApply);

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn-compact btn-secondary";
      editBtn.textContent = t("custom.editBtn");
      editBtn.addEventListener("click", () => openCustomSceneDialog(preset));

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "btn btn-compact btn-ghost";
      deleteBtn.textContent = t("custom.deleteBtn");
      deleteBtn.addEventListener("click", () => {
        invokeApi(
          () => backendApi.delete_custom_scene(preset.id),
          () => t("status.presetDeleted", { name: preset.name })
        );
      });

      actions.append(favoriteBtn, applyBtn, editBtn, deleteBtn);
      card.append(topArea, actions);
      grid.appendChild(card);
    });
  }

  /* Abre el dialogo modal para crear un nuevo preset o editar uno existente */
  function openCustomSceneDialog(existingPreset) {
    const dialog = document.getElementById("custom-scene-dialog");
    const titleEl = document.getElementById("custom-scene-dialog-title");
    const subtitleEl = document.getElementById("custom-scene-dialog-subtitle");
    const idInput = document.getElementById("custom-scene-id-input");
    const nameInput = document.getElementById("custom-scene-name-input");
    const overwriteRow = document.getElementById("custom-scene-overwrite-row");
    const overwriteCheckbox = document.getElementById("custom-scene-overwrite-checkbox");
    const submitBtn = document.getElementById("custom-scene-submit-btn");

    if (!dialog || !idInput || !nameInput) return;

    if (existingPreset) {
      idInput.value = existingPreset.id;
      nameInput.value = existingPreset.name;
      if (titleEl) titleEl.textContent = t("dialog.presetEditTitle");
      if (subtitleEl) subtitleEl.textContent = t("dialog.presetEditSubtitle");
      if (overwriteRow) overwriteRow.hidden = false;
      if (overwriteCheckbox) overwriteCheckbox.checked = false;
      if (submitBtn) submitBtn.textContent = t("dialog.presetUpdateSubmit");
    } else {
      idInput.value = "";
      nameInput.value = "";
      if (titleEl) titleEl.textContent = t("dialog.presetSaveTitle");
      if (subtitleEl) subtitleEl.textContent = t("dialog.presetSaveSubtitle");
      if (overwriteRow) overwriteRow.hidden = true;
      if (overwriteCheckbox) overwriteCheckbox.checked = false;
      if (submitBtn) submitBtn.textContent = t("dialog.presetSaveSubmit");
    }

    dialog.showModal();
    nameInput.focus();
    if (existingPreset) nameInput.select();
  }

  /* Ejecuta llamadas hacia WebviewBridge de forma uniforme */
  async function invokeApi(callFn, successMessage, options) {
    if (!backendApi) return;
    const retry = () => invokeApi(callFn, successMessage, options);
    const silent = Boolean(options && options.silent);
    try {
      const response = await callFn();
      applyBackendEnvelope(response, successMessage, retry, silent);
    } catch (err) {
      const message = t("status.commError", {
        error: err && err.message ? err.message : String(err),
      });
      setStatusMessage(message);
      showToast({ kind: "error", message, retry });
    }
  }

  /* Refresca el estado completo de la consola cuando se solicita manual o externamente */
  function refreshStates(statusMessage) {
    return invokeApi(
      () => backendApi.refresh_states(),
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
    if (ipDisplay) {
      ipDisplay.textContent = t("dialog.renameIpDisplay", { ip: bulb.ip, mac: bulb.mac });
    }
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

  /* Vincula eventos de la rueda de color, deslizadores, selector de idioma y formularios */
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
        () => backendApi.set_brightness(target, null),
        () => t("status.brightnessSet", { brightness: target })
      );
    }, 250);
  }

  function setupGlobalShortcuts() {
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

  function bindEvents() {
    setupDialogLightDismissFallbacks();
    setupGlobalShortcuts();

    /* Selector segmentado de idioma (EN | ES) */
    document.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetLang = btn.getAttribute("data-lang") || "en";
        if (backendApi && typeof backendApi.set_language === "function") {
          invokeApi(
            () => backendApi.set_language(targetLang),
            () => t("status.languageChanged")
          );
        } else {
          syncLanguageUi(targetLang);
          renderFixtureList();
          renderStageHeaderAndControls();
          renderSleepTimer();
          renderScenesGrid();
          renderCustomScenesGrid();
          renderAmbilightPanel();
          renderMusicPanel();
          setStatusMessage(t("status.languageChanged"));
        }
      });
    });

    /* Escaneo de red y dialogo de alta por IP */
    const scanBtn = document.getElementById("scan-network-btn");
    const scanLabel = document.getElementById("scan-btn-label");
    if (scanBtn) {
      scanBtn.addEventListener("click", async () => {
        if (scanLabel) scanLabel.textContent = t("rail.scanningBtn");
        scanBtn.disabled = true;
        try {
          await invokeApi(() => backendApi.discover_bulbs(), () => t("status.scanDone"));
        } finally {
          if (scanLabel) scanLabel.textContent = t("rail.scanBtn");
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
        invokeApi(
          () => backendApi.add_manual_bulb(ip, name),
          () => t("status.registeredIp", { ip })
        );
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
        invokeApi(
          () => backendApi.rename_bulb(ip, newName),
          () => t("status.renamedBulb", { ip, name: newName })
        );
      });
    }

    /* Seleccionar todos los focos */
    const selectAll = document.getElementById("select-all-fixtures");
    if (selectAll) {
      selectAll.addEventListener("change", () => {
        const nextIps = selectAll.checked ? appState.bulbs.map((b) => b.ip) : [];
        invokeApi(
          () => backendApi.select_targets(nextIps),
          () => t("status.multiSelectionUpdated")
        );
      });
    }

    /* Sincronizacion en vivo con getPilot */
    const syncNowBtn = document.getElementById("sync-now-btn");
    if (syncNowBtn) {
      syncNowBtn.addEventListener("click", () => {
        invokeApi(() => backendApi.refresh_states(), () => t("status.syncedLive"));
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
            invokeApi(() => backendApi.refresh_states(), () => t("status.autoSyncStep"));
          }, 3000);
          setStatusMessage(t("status.autoSyncEnabled"));
        } else {
          setStatusMessage(t("status.autoSyncPaused"));
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
          () => t(nextPower ? "status.masterTurnedOn" : "status.masterTurnedOff")
        );
      });
    }

    /* Control de brillo maestro */
    const brightnessSlider = document.getElementById("brightness-slider");
    const brightnessOutput = document.getElementById("brightness-output");
    if (brightnessSlider && brightnessOutput) {
      brightnessSlider.addEventListener("input", () => {
        brightnessOutput.textContent = `${brightnessSlider.value}%`;
        updateSliderFill(brightnessSlider);
      });
      brightnessSlider.addEventListener("change", () => {
        const val = clampInt(brightnessSlider.value, 10, 100);
        updateSliderFill(brightnessSlider);
        invokeApi(
          () => backendApi.set_brightness(val, null),
          () => t("status.brightnessSet", { brightness: val })
        );
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
        invokeApi(
          () => backendApi.set_brightness(val, null),
          () => t("status.brightnessSet", { brightness: val })
        );
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

    /* Interaccion con la rueda de color HSV con envio en tiempo real (~70ms throttle) */
    const WHEEL_THROTTLE_MS = 70;
    const canvas = document.getElementById("color-wheel-canvas");
    if (canvas) {
      const dispatchWheelRgb = (rgb, isFinalCommit) => {
        if (!backendApi) return;
        invokeApi(
          () => backendApi.set_color(rgb.r, rgb.g, rgb.b, null, null),
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
        const beamCss = `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
        document.documentElement.style.setProperty("--beam-color", beamCss);
        const aperture = document.getElementById("photometric-aperture");
        if (aperture) {
          aperture.style.backgroundColor = beamCss;
        }

        if (commitImmediate) {
          if (appState.wheelThrottleTimer) {
            clearTimeout(appState.wheelThrottleTimer);
            appState.wheelThrottleTimer = null;
          }
          appState.lastWheelSendMs = Date.now();
          dispatchWheelRgb(rgb, true);
          return;
        }

        const now = Date.now();
        const elapsed = now - appState.lastWheelSendMs;
        if (elapsed >= WHEEL_THROTTLE_MS) {
          if (appState.wheelThrottleTimer) {
            clearTimeout(appState.wheelThrottleTimer);
            appState.wheelThrottleTimer = null;
          }
          appState.lastWheelSendMs = now;
          dispatchWheelRgb(rgb, false);
        } else {
          if (appState.wheelThrottleTimer) {
            clearTimeout(appState.wheelThrottleTimer);
          }
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
        () => t("status.rgbApplied", { r, g, b })
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
          () => t("status.swatchApplied", { r, g, b })
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
        updateSliderFill(kelvinSlider);
        document.documentElement.style.setProperty("--beam-color", kelvinToCssColor(k));
      });
      kelvinSlider.addEventListener("change", () => {
        const k = clampInt(kelvinSlider.value, 2200, 6500);
        updateSliderFill(kelvinSlider);
        invokeApi(
          () => backendApi.set_temperature(k, null, null),
          () => t("status.kelvinSet", { kelvin: k })
        );
      });
    }

    document.querySelectorAll(".kelvin-card").forEach((card) => {
      card.addEventListener("click", () => {
        const k = clampInt(card.dataset.kelvin, 2200, 6500);
        invokeApi(
          () => backendApi.set_temperature(k, null, null),
          () => t("status.kelvinSet", { kelvin: k })
        );
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
        updateSliderFill(speedSlider);
      });
      speedSlider.addEventListener("change", () => {
        updateSliderFill(speedSlider);
        const primary = getPrimaryBulb();
        if (!primary || primary.state.mode !== "scene" || !primary.state.scene_id) return;
        const speed = clampInt(speedSlider.value, 10, 200);
        invokeApi(
          () => backendApi.set_builtin_scene(primary.state.scene_id, speed, null, null),
          () => t("status.sceneSpeedUpdated", { id: primary.state.scene_id, speed })
        );
      });
    }

    /* Eventos del Temporizador de Apagado (Sleep Timer) */
    const sleepMinutesInput = document.getElementById("sleep-minutes-input");
    document.querySelectorAll(".sleep-preset-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mins = clampInt(btn.dataset.minutes, 1, 240);
        if (sleepMinutesInput) sleepMinutesInput.value = String(mins);
        document.querySelectorAll(".sleep-preset-btn").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        invokeApi(
          () => backendApi.start_sleep_timer(mins, null),
          () => t("status.sleepStarted", { minutes: mins })
        );
      });
    });

    const startTimerBtn = document.getElementById("start-sleep-timer-btn");
    if (startTimerBtn) {
      startTimerBtn.addEventListener("click", () => {
        const mins = clampInt(sleepMinutesInput ? sleepMinutesInput.value : 30, 1, 240);
        if (sleepMinutesInput) sleepMinutesInput.value = String(mins);
        invokeApi(
          () => backendApi.start_sleep_timer(mins, null),
          () => t("status.sleepStarted", { minutes: mins })
        );
      });
    }

    const cancelTimerBtn = document.getElementById("cancel-sleep-timer-btn");
    if (cancelTimerBtn) {
      cancelTimerBtn.addEventListener("click", () => {
        document.querySelectorAll(".sleep-preset-btn").forEach((b) => b.classList.remove("active"));
        invokeApi(() => backendApi.cancel_sleep_timer(), () => t("status.sleepCancelled"));
      });
    }

    /* Eventos de creacion y edicion de escenas personalizadas (Custom Presets) */
    const quickSavePresetBtn = document.getElementById("quick-save-preset-btn");
    if (quickSavePresetBtn) {
      quickSavePresetBtn.addEventListener("click", () => openCustomSceneDialog(null));
    }

    const openSaveSceneBtn = document.getElementById("open-save-scene-dialog-btn");
    if (openSaveSceneBtn) {
      openSaveSceneBtn.addEventListener("click", () => openCustomSceneDialog(null));
    }

    const customSceneForm = document.getElementById("custom-scene-form");
    const customSceneDialog = document.getElementById("custom-scene-dialog");
    if (customSceneForm && customSceneDialog) {
      customSceneForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const idInput = document.getElementById("custom-scene-id-input");
        const nameInput = document.getElementById("custom-scene-name-input");
        const overwriteCheckbox = document.getElementById("custom-scene-overwrite-checkbox");

        const sceneId = idInput ? idInput.value.trim() : "";
        const name = nameInput ? nameInput.value.trim() : "";
        const captureCurrent = Boolean(overwriteCheckbox && overwriteCheckbox.checked);
        if (!name) return;

        customSceneDialog.close();
        if (sceneId) {
          invokeApi(
            () => backendApi.update_custom_scene(sceneId, name, captureCurrent),
            () => t("status.presetUpdated", { name })
          );
        } else {
          const primary = getPrimaryBulb();
          invokeApi(
            () => backendApi.save_custom_scene(name, primary ? primary.ip : null),
            () => t("status.presetSaved", { name })
          );
          activateTab("custom", false);
        }
      });
    }

    /* Eventos del modo Ambilight (sincronizacion de pantalla en tiempo real) */
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
          backendApi.start_ambilight(
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
          invokeApi(() => backendApi.stop_ambilight(), () => t("status.ambiStopped"));
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

    /* Eventos del modo Music Sync (WASAPI Loopback y espectro FFT en tiempo real) */
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
          backendApi.start_music_sync(
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
          invokeApi(() => backendApi.stop_music_sync(), () => t("status.musicStopped"));
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
        const targetId = btn.dataset.sliderTarget;
        const presetValue = btn.dataset.presetValue;
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

  /* Inicializacion principal al cargar el DOM */
  document.addEventListener("DOMContentLoaded", async () => {
    syncLanguageUi("en");
    drawColorWheel();
    updateAllSlidersFill();
    bindEvents();
    backendApi = await resolveBackendApi();
    await invokeApi(
      () => backendApi.get_initial_state(),
      () => t("status.connected")
    );
  });
})();


/* Suspende transiciones CSS mientras se redimensiona la ventana (se restauran 150 ms despues). */
(function setupResizeThrottle() {
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    document.documentElement.classList.add('is-resizing');
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      document.documentElement.classList.remove('is-resizing');
    }, 150);
  }, { passive: true });
})();
