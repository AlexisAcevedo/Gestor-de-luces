/*
 * PyWebView bridge resolution, invocation wrapper, and in-memory browser mock API.
 */

import { ALLOWED_THEMES, DEFAULT_THEME, SCENE_CATALOG, clampInt, rgbToHex, t } from "./store.js";
import { setStatusMessage, showToast } from "./toasts.js";

/* Simulador en memoria cuando no existe el contenedor nativo de PyWebView */
export function createBrowserMockApi() {
  let mockLanguage = "en";
  let mockTheme = DEFAULT_THEME;
  let mockBulbs = [{
    ip: "192.168.0.34", mac: "a8bb50df9029", name: "Studio Key Light", module_name: "ESP01_SHRGB1C_31", is_online: true,
    state: { is_on: true, brightness: 85, mode: "temperature", color: null, temperature: 4200, scene_id: null, scene_name: null, speed: 100 }
  }];
  let mockSelected = ["192.168.0.34"];
  let mockZones = [];
  let mockCustomScenes = [
    { id: "preset01", name: "Editorial Warmth", mode: "temperature", brightness: 70, color: null, temperature: 2700, built_in_scene_id: null, speed: 100, is_favorite: true },
    { id: "preset02", name: "Cyan Backlight", mode: "rgb", brightness: 85, color: { r: 0, g: 180, b: 255, hex: "#00b4ff" }, temperature: null, built_in_scene_id: null, speed: 100, is_favorite: false }
  ];
  let mockSleepTimer = { active: false, remaining_seconds: 0, total_seconds: 0, target_ips: [], deadlineMs: 0 };
  let mockAutoSync = false;
  let mockFavoriteBuiltinScenes = [];
  let mockAmbilightPrefs = {
    monitor_index: 1, color_mode: "vibrant", auto_brightness: true,
    min_brightness: 10, brightness: 85, smoothing_alpha: 0.38
  };
  let mockMusicPrefs = {
    device_index: -1, palette_mode: "spectrum", sensitivity: 1.0,
    smoothing_alpha: 0.50, audio_brightness: true, brightness: 85
  };
  let mockGlobalHotkeys = {
    enabled: false,
    bindings: {
      toggle_power: "Ctrl+Alt+P",
      brightness_up: "Ctrl+Alt+Up",
      brightness_down: "Ctrl+Alt+Down",
      toggle_ambilight: "Ctrl+Alt+A",
      toggle_music_sync: "Ctrl+Alt+M",
      toggle_window: "Ctrl+Alt+W"
    }
  };
  let mockCircadian = { enabled: false, sunrise_hour: 7.0, sunset_hour: 20.0, day_kelvin: 5600, night_kelvin: 2700, day_brightness: 95, night_brightness: 40, interval_seconds: 60 };
  let mockTransitionSeconds = 0;
  let mockWakeupRamp = { enabled: false, target_hour: 7, target_minute: 0, duration_minutes: 20, start_kelvin: 2200, end_kelvin: 5000, start_brightness: 10, end_brightness: 100, target_ips: [] };
  let mockWakeupStatus = { active: false, progress: 0.0 };
  let mockSessionTriggers = { off_on_lock: false, restore_on_unlock: false, off_on_sleep: false };
  let mockContextAutomation = {
    enabled: false,
    poll_seconds: 5,
    on_air: { enabled: false, watch_mic: true, watch_camera: true, color_hex: "#ff2a55", brightness: 90, target_ips: [] },
    rules: []
  };
  let mockLocalApi = { enabled: false, port: 18899, token: "" };
  let mockAmbilight = {
    active: false, monitor_index: 1, color_mode: "vibrant", auto_brightness: true,
    min_brightness: 10, brightness: 85, fixed_brightness: 85, smoothing_alpha: 0.38,
    last_color: { r: 56, g: 189, b: 248, hex: "#38bdf8" }, target_ips: [], frames_sent: 0
  };
  const mockMonitors = [
    { index: 1, label: "Display 1 (2560x1440)", width: 2560, height: 1440 },
    { index: 2, label: "Display 2 (1920x1080)", width: 1920, height: 1080 },
    { index: 0, label: "All displays (4480x1440)", width: 4480, height: 1440 }
  ];
  let mockMusicSync = {
    active: false, device_index: -1, palette_mode: "spectrum", sensitivity: 1.0,
    smoothing_alpha: 0.50, audio_brightness: true, brightness: 85, fixed_brightness: 85,
    rms: 0.0, bass: 0.0, mid: 0.0, treble: 0.0,
    last_color: { r: 235, g: 45, b: 95, hex: "#eb2d5f" }, target_ips: [], frames_sent: 0
  };
  const mockAudioDevices = [{
    index: -1,
    name: "Speakers (Realtek High Definition Audio) [Loopback]",
    label: "Default · Speakers (Realtek High Definition Audio) [Loopback] (48000 Hz)",
    sample_rate: 48000, channels: 2, is_default: true
  }];

  function syncMockTimer() {
    if (!mockSleepTimer.active) return;
    const rem = Math.max(0, Math.ceil((mockSleepTimer.deadlineMs - Date.now()) / 1000));
    if (rem <= 0) {
      mockSleepTimer.active = false;
      mockSleepTimer.remaining_seconds = 0;
      mockSleepTimer.total_seconds = 0;
      mockBulbs.forEach((b) => {
        if (mockSleepTimer.target_ips.includes(b.ip)) b.state.is_on = false;
      });
      mockSleepTimer.target_ips = [];
    } else {
      mockSleepTimer.remaining_seconds = rem;
    }
  }

  function buildMockEnvelope() {
    syncMockTimer();
    return Promise.resolve({
      ok: true, language: mockLanguage, theme: mockTheme,
      auto_sync: mockAutoSync,
      favorite_builtin_scenes: mockFavoriteBuiltinScenes.slice(),
      ambilight_prefs: Object.assign({}, mockAmbilightPrefs),
      music_prefs: Object.assign({}, mockMusicPrefs),
      global_hotkeys: {
        enabled: mockGlobalHotkeys.enabled,
        bindings: Object.assign({}, mockGlobalHotkeys.bindings)
      },
      global_hotkeys_supported: false,
      global_hotkey_errors: {},
      bulbs: JSON.parse(JSON.stringify(mockBulbs)), selected_ips: mockSelected.slice(),
      scenes: SCENE_CATALOG.slice(), custom_scenes: JSON.parse(JSON.stringify(mockCustomScenes)),
      zones: JSON.parse(JSON.stringify(mockZones)),
      sleep_timer: {
        active: mockSleepTimer.active, remaining_seconds: mockSleepTimer.remaining_seconds,
        total_seconds: mockSleepTimer.total_seconds, target_ips: mockSleepTimer.target_ips.slice()
      },
      ambilight: JSON.parse(JSON.stringify(mockAmbilight)), monitors: mockMonitors.slice(),
      music_sync: JSON.parse(JSON.stringify(mockMusicSync)), audio_devices: mockAudioDevices.slice(),
      circadian: Object.assign({}, mockCircadian),
      wakeup_ramp: Object.assign({}, mockWakeupRamp),
      wakeup_ramp_status: Object.assign({}, mockWakeupStatus),
      session_triggers: Object.assign({}, mockSessionTriggers),
      context_automation: JSON.parse(JSON.stringify(mockContextAutomation)),
      context_status: { supported: false, active_reason: null, on_air_active: false, foreground_process: null },
      transition_seconds: mockTransitionSeconds,
      local_api: Object.assign({}, mockLocalApi),
      error: null
    });
  }

  function resolveTargets(ips) {
    if (Array.isArray(ips) && ips.length > 0) return ips;
    if (mockSelected.length > 0) return mockSelected;
    return mockBulbs.map((b) => b.ip);
  }

  function mutateTargetBulbs(ips, mutator) {
    const targets = resolveTargets(ips);
    mockBulbs.forEach((bulb) => {
      if (targets.includes(bulb.ip)) mutator(bulb.state, bulb);
    });
  }

  return {
    get_initial_state: () => buildMockEnvelope(),
    set_language: (lang) => {
      const cleaned = String(lang || "en").trim().toLowerCase();
      mockLanguage = cleaned === "es" ? "es" : "en";
      return buildMockEnvelope();
    },
    set_theme: (theme) => {
      if (typeof theme === "string" && ALLOWED_THEMES.has(theme.trim().toLowerCase())) {
        mockTheme = theme.trim().toLowerCase();
      }
      return buildMockEnvelope();
    },
    discover_bulbs: () => buildMockEnvelope(),
    refresh_states: () => buildMockEnvelope(),
    select_targets: (ips) => {
      mockSelected = Array.isArray(ips) ? ips.slice() : [];
      return buildMockEnvelope();
    },
    set_auto_sync: (enabled) => {
      mockAutoSync = Boolean(enabled);
      return buildMockEnvelope();
    },
    set_favorite_builtin_scenes: (sceneIds) => {
      const seen = new Set();
      mockFavoriteBuiltinScenes = [];
      if (Array.isArray(sceneIds)) {
        sceneIds.forEach((id) => {
          const parsed = Number.parseInt(id, 10);
          if (Number.isInteger(parsed) && parsed > 0 && !seen.has(parsed)) {
            seen.add(parsed);
            mockFavoriteBuiltinScenes.push(parsed);
          }
        });
      }
      return buildMockEnvelope();
    },
    set_global_hotkeys: (enabled, bindings) => {
      mockGlobalHotkeys = {
        enabled: Boolean(enabled),
        bindings: bindings && typeof bindings === "object"
          ? Object.assign({}, mockGlobalHotkeys.bindings, bindings)
          : Object.assign({}, mockGlobalHotkeys.bindings)
      };
      return buildMockEnvelope();
    },
    add_manual_bulb: (ip, name, protocol = "wiz") => {
      const cleaned = String(ip || "").trim();
      if (!cleaned) {
        return Promise.resolve({ ok: false, bulbs: mockBulbs, selected_ips: mockSelected, scenes: SCENE_CATALOG.slice(), error: "IP cannot be empty." });
      }
      const proto = String(protocol || "wiz").trim().toLowerCase() === "govee" ? "govee" : "wiz";
      const label = String(name || "").trim() || `${proto === "govee" ? "Govee Bulb" : "WiZ Bulb"} (${cleaned})`;
      const existing = mockBulbs.find((b) => b.ip === cleaned);
      if (existing) {
        existing.name = label;
        existing.protocol = proto;
      } else {
        mockBulbs.push({
          ip: cleaned, mac: "a8bb50001122", name: label, module_name: proto === "govee" ? "GOVEE_LAN_RGB" : "ESP01_SHRGB1C_31", protocol: proto, is_online: true,
          state: { is_on: true, brightness: 100, mode: "temperature", color: null, temperature: 4200, scene_id: null, scene_name: null, speed: 100 }
        });
        if (!mockSelected.includes(cleaned)) mockSelected.push(cleaned);
      }
      return buildMockEnvelope();
    },
    rename_bulb: (ip, newName) => {
      const target = mockBulbs.find((b) => b.ip === ip);
      if (target && String(newName || "").trim()) target.name = String(newName).trim();
      return buildMockEnvelope();
    },
    remove_bulb: (ip) => {
      const cleaned = String(ip || "").trim();
      mockBulbs = mockBulbs.filter((b) => b.ip !== cleaned);
      mockSelected = mockSelected.filter((item) => item !== cleaned);
      return buildMockEnvelope();
    },
    set_power: (isOn, brightness, ips) => {
      mutateTargetBulbs(ips, (st) => {
        st.is_on = Boolean(isOn);
        if (typeof brightness === "number") st.brightness = brightness;
      });
      return buildMockEnvelope();
    },
    set_brightness: (brightness, ips) => {
      mutateTargetBulbs(ips, (st) => {
        st.is_on = true;
        st.brightness = Number(brightness);
      });
      return buildMockEnvelope();
    },
    set_color: (r, g, b, brightness, ips) => {
      const hex = rgbToHex(r, g, b);
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, { is_on: true, mode: "rgb", color: { r: Number(r), g: Number(g), b: Number(b), hex }, temperature: null, scene_id: null, scene_name: null });
        if (typeof brightness === "number") st.brightness = brightness;
      });
      return buildMockEnvelope();
    },
    set_temperature: (kelvin, brightness, ips) => {
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, { is_on: true, mode: "temperature", temperature: Number(kelvin), color: null, scene_id: null, scene_name: null });
        if (typeof brightness === "number") st.brightness = brightness;
      });
      return buildMockEnvelope();
    },
    set_builtin_scene: (sceneId, speed, brightness, ips) => {
      const scene = SCENE_CATALOG.find((s) => s.scene_id === Number(sceneId));
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, { is_on: true, mode: "scene", scene_id: Number(sceneId), scene_name: scene ? scene.name : `Scene ${sceneId}`, color: null, temperature: null });
        if (typeof speed === "number") st.speed = speed;
        if (typeof brightness === "number") st.brightness = brightness;
      });
      return buildMockEnvelope();
    },
    save_custom_scene: (name, sourceIp, captureAllTargets = false) => {
      const refBulb = mockBulbs.find((b) => (sourceIp ? b.ip === sourceIp : mockSelected.includes(b.ip))) || mockBulbs[0];
      const st = refBulb ? refBulb.state : { mode: "temperature", brightness: 100, color: null, temperature: 4200, scene_id: null, speed: 100 };
      const targets = resolveTargets(null);
      let bulbStates = null;
      if (captureAllTargets && targets.length >= 2) {
        bulbStates = {};
        targets.forEach((ip) => {
          const b = mockBulbs.find((entry) => entry.ip === ip);
          if (b) {
            bulbStates[ip] = {
              is_on: Boolean(b.state.is_on),
              mode: b.state.mode,
              brightness: b.state.brightness,
              color: b.state.color ? Object.assign({}, b.state.color) : null,
              temperature: b.state.temperature,
              built_in_scene_id: b.state.scene_id,
              speed: b.state.speed || 100
            };
          }
        });
      }
      const created = {
        id: Math.random().toString(16).slice(2, 10), name: String(name || "Preset").trim(),
        mode: st.mode, brightness: st.brightness, color: st.color ? Object.assign({}, st.color) : null,
        temperature: st.temperature, built_in_scene_id: st.scene_id, speed: st.speed || 100
      };
      if (bulbStates && Object.keys(bulbStates).length >= 2) created.bulb_states = bulbStates;
      mockCustomScenes.push(created);
      return buildMockEnvelope();
    },
    update_custom_scene: (sceneId, name, captureCurrent, captureAllTargets = false) => {
      const target = mockCustomScenes.find((s) => s.id === sceneId);
      if (target) {
        target.name = String(name || target.name).trim();
        if (captureCurrent) {
          const refBulb = mockBulbs.find((b) => mockSelected.includes(b.ip)) || mockBulbs[0];
          if (refBulb) {
            Object.assign(target, {
              mode: refBulb.state.mode, brightness: refBulb.state.brightness,
              color: refBulb.state.color ? Object.assign({}, refBulb.state.color) : null,
              temperature: refBulb.state.temperature, built_in_scene_id: refBulb.state.scene_id,
              speed: refBulb.state.speed || 100
            });
          }
          const targets = resolveTargets(null);
          if (captureAllTargets && targets.length >= 2) {
            target.bulb_states = {};
            targets.forEach((ip) => {
              const b = mockBulbs.find((entry) => entry.ip === ip);
              if (b) target.bulb_states[ip] = Object.assign({}, b.state);
            });
          } else {
            delete target.bulb_states;
          }
        }
      }
      return buildMockEnvelope();
    },
    save_zone: (name, bulbIps, zoneId, icon) => {
      const id = zoneId || Math.random().toString(16).slice(2, 10);
      const next = {
        id,
        name: String(name || "Zone").trim(),
        bulb_ips: Array.isArray(bulbIps) ? bulbIps.slice() : [],
        icon: String(icon || "room")
      };
      const idx = mockZones.findIndex((z) => z.id === id);
      if (idx >= 0) mockZones[idx] = next;
      else mockZones.push(next);
      return buildMockEnvelope();
    },
    delete_zone: (zoneId) => {
      mockZones = mockZones.filter((z) => z.id !== zoneId);
      return buildMockEnvelope();
    },
    select_zone: (zoneId) => {
      const z = mockZones.find((entry) => entry.id === zoneId);
      if (z) mockSelected = z.bulb_ips.slice();
      return buildMockEnvelope();
    },
    delete_custom_scene: (sceneId) => {
      mockCustomScenes = mockCustomScenes.filter((s) => s.id !== sceneId);
      return buildMockEnvelope();
    },
    set_custom_scene_favorite: (sceneId, isFavorite) => {
      const target = mockCustomScenes.find((s) => s.id === sceneId);
      if (target) target.is_favorite = Boolean(isFavorite);
      return buildMockEnvelope();
    },
    apply_custom_scene: (sceneId, ips) => {
      const preset = mockCustomScenes.find((s) => s.id === sceneId);
      if (!preset) return buildMockEnvelope();
      const bScene = SCENE_CATALOG.find((s) => s.scene_id === preset.built_in_scene_id);
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, {
          is_on: true, mode: preset.mode, brightness: preset.brightness,
          color: preset.color ? Object.assign({}, preset.color) : null,
          temperature: preset.temperature, scene_id: preset.built_in_scene_id,
          scene_name: bScene ? bScene.name : null, speed: preset.speed || 100
        });
      });
      return buildMockEnvelope();
    },
    start_sleep_timer: (minutes, ips) => {
      const totalSec = Math.max(1, Math.round(Number(minutes) * 60));
      mockSleepTimer = { active: true, remaining_seconds: totalSec, total_seconds: totalSec, target_ips: resolveTargets(ips), deadlineMs: Date.now() + totalSec * 1000 };
      return buildMockEnvelope();
    },
    cancel_sleep_timer: () => {
      mockSleepTimer = { active: false, remaining_seconds: 0, total_seconds: 0, target_ips: [], deadlineMs: 0 };
      return buildMockEnvelope();
    },
    get_sleep_timer_status: () => buildMockEnvelope(),
    start_ambilight: (monitorIndex, colorMode, autoBrightness, brightness, smoothingAlpha, ips, minBrightness, regionMap, letterboxCrop) => {
      const targets = resolveTargets(ips);
      const sampled = { r: 56, g: 189, b: 248, hex: "#38bdf8" };
      mockMusicSync.active = false;
      mockMusicSync.target_ips = [];
      const minBri = clampInt(minBrightness != null ? minBrightness : 10, 10, 20);
      const cleanedRegions = (regionMap && typeof regionMap === "object") ? Object.assign({}, regionMap) : {};
      const crop = letterboxCrop == null ? true : Boolean(letterboxCrop);
      mockAmbilightPrefs = {
        monitor_index: Number(monitorIndex || 1), color_mode: String(colorMode || "vibrant"),
        auto_brightness: Boolean(autoBrightness), min_brightness: minBri,
        brightness: Number(brightness || 85), smoothing_alpha: Number(smoothingAlpha || 0.38),
        region_map: cleanedRegions, letterbox_crop: crop
      };
      mockAmbilight = {
        active: true, monitor_index: mockAmbilightPrefs.monitor_index, color_mode: mockAmbilightPrefs.color_mode,
        auto_brightness: mockAmbilightPrefs.auto_brightness, min_brightness: minBri,
        brightness: mockAmbilightPrefs.brightness, fixed_brightness: mockAmbilightPrefs.brightness,
        smoothing_alpha: mockAmbilightPrefs.smoothing_alpha, last_color: sampled,
        region_map: cleanedRegions, letterbox_crop: crop, last_region_colors: { full: sampled },
        target_ips: targets, frames_sent: mockAmbilight.frames_sent + 1
      };
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, { is_on: true, mode: "rgb", color: Object.assign({}, sampled), temperature: null });
      });
      return buildMockEnvelope();
    },
    stop_ambilight: () => {
      mockAmbilight.active = false;
      mockAmbilight.target_ips = [];
      return buildMockEnvelope();
    },
    get_ambilight_status: () => {
      if (mockAmbilight.active) mockAmbilight.frames_sent += 4;
      return Promise.resolve({ ok: true, ambilight: JSON.parse(JSON.stringify(mockAmbilight)), error: null });
    },
    start_music_sync: (paletteMode, sensitivity, smoothingAlpha, audioBrightness, brightness, deviceIndex, ips, bandMap, beatBoost, customPalette) => {
      const targets = resolveTargets(ips);
      const sampled = { r: 240, g: 52, b: 112, hex: "#f03470" };
      mockAmbilight.active = false;
      mockAmbilight.target_ips = [];
      const cleanedBands = (bandMap && typeof bandMap === "object") ? Object.assign({}, bandMap) : {};
      const boost = beatBoost == null ? true : Boolean(beatBoost);
      const custom = (customPalette && typeof customPalette === "object")
        ? Object.assign({ bass: "#ff2a55", mid: "#22e58b", treble: "#389bff" }, customPalette)
        : { bass: "#ff2a55", mid: "#22e58b", treble: "#389bff" };
      mockMusicPrefs = {
        device_index: deviceIndex != null ? Number(deviceIndex) : -1,
        palette_mode: String(paletteMode || "spectrum"), sensitivity: Number(sensitivity || 1.0),
        smoothing_alpha: Number(smoothingAlpha || 0.50), audio_brightness: Boolean(audioBrightness),
        brightness: Number(brightness || 85), band_map: cleanedBands, beat_boost: boost, custom_palette: custom
      };
      mockMusicSync = {
        active: true, device_index: mockMusicPrefs.device_index,
        palette_mode: mockMusicPrefs.palette_mode, sensitivity: mockMusicPrefs.sensitivity,
        smoothing_alpha: mockMusicPrefs.smoothing_alpha, audio_brightness: mockMusicPrefs.audio_brightness,
        brightness: mockMusicPrefs.brightness, fixed_brightness: mockMusicPrefs.brightness,
        rms: 0.68, bass: 0.82, mid: 0.54, treble: 0.36, beat: true, beat_intensity: 0.82,
        band_map: cleanedBands, beat_boost: boost, custom_palette: custom, last_color: sampled,
        target_ips: targets, frames_sent: mockMusicSync.frames_sent + 1
      };
      mutateTargetBulbs(ips, (st) => {
        Object.assign(st, { is_on: true, mode: "rgb", color: Object.assign({}, sampled), temperature: null });
      });
      return buildMockEnvelope();
    },
    stop_music_sync: () => {
      Object.assign(mockMusicSync, { active: false, target_ips: [], rms: 0.0, bass: 0.0, mid: 0.0, treble: 0.0 });
      return buildMockEnvelope();
    },
    get_music_sync_status: () => {
      if (mockMusicSync.active) mockMusicSync.frames_sent += 3;
      return Promise.resolve({ ok: true, music_sync: JSON.parse(JSON.stringify(mockMusicSync)), error: null });
    },
    set_circadian_config: (config) => {
      mockCircadian = Object.assign({}, mockCircadian, config || {});
      return buildMockEnvelope();
    },
    set_wakeup_ramp_config: (config) => {
      mockWakeupRamp = Object.assign({}, mockWakeupRamp, config || {});
      return buildMockEnvelope();
    },
    trigger_wakeup_ramp: () => {
      mockWakeupStatus = { active: true, progress: 0.0 };
      return buildMockEnvelope();
    },
    cancel_wakeup_ramp: () => {
      mockWakeupStatus = { active: false, progress: 0.0 };
      return buildMockEnvelope();
    },
    set_session_triggers: (config) => {
      mockSessionTriggers = Object.assign({}, mockSessionTriggers, config || {});
      return buildMockEnvelope();
    },
    set_context_automation: (config) => {
      mockContextAutomation = Object.assign({}, mockContextAutomation, config || {});
      return buildMockEnvelope();
    },
    set_transition_seconds: (seconds) => {
      mockTransitionSeconds = Math.max(0, Math.min(5, Number(seconds) || 0));
      return buildMockEnvelope();
    },
    set_local_api_config: (config) => {
      mockLocalApi = Object.assign({}, mockLocalApi, config || {});
      if (mockLocalApi.enabled && !mockLocalApi.token) mockLocalApi.token = "mock-bearer-token";
      return buildMockEnvelope();
    },
    rotate_local_api_token: () => {
      mockLocalApi.token = `mock-token-${Date.now()}`;
      return buildMockEnvelope();
    }
  };
}

let backendApi = null;
let usingMockBackend = false;
let envelopeHandler = null;
let backendUpgradeHandler = null;
let lateReadyListener = null;
let requestSeq = 0;
let latestMutationSeq = 0;
let lastAppliedMutationSeq = 0;
const inFlightKeys = new Set();

export function getBackendApi() { return backendApi; }
export function isMockBackend() { return usingMockBackend; }
export function setEnvelopeHandler(fn) { envelopeHandler = fn; }
export function setBackendUpgradeHandler(fn) { backendUpgradeHandler = fn; }

export function resetBridgeStateForTests() {
  if (lateReadyListener && typeof window !== "undefined" && typeof window.removeEventListener === "function") {
    window.removeEventListener("pywebviewready", lateReadyListener);
  }
  backendApi = null;
  usingMockBackend = false;
  envelopeHandler = null;
  backendUpgradeHandler = null;
  lateReadyListener = null;
  requestSeq = 0;
  latestMutationSeq = 0;
  lastAppliedMutationSeq = 0;
  inFlightKeys.clear();
}

/* Resuelve el puente nativo de PyWebView o activa el simulador de desarrollo */
export async function resolveBackendApi(options = {}) {
  if (lateReadyListener && typeof window !== "undefined" && typeof window.removeEventListener === "function") {
    window.removeEventListener("pywebviewready", lateReadyListener);
    lateReadyListener = null;
  }
  if (window.pywebview && window.pywebview.api) {
    backendApi = window.pywebview.api;
    usingMockBackend = false;
    return backendApi;
  }
  const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : 2000;
  return new Promise((resolve) => {
    let settled = false;
    let timerId = null;
    const onReady = () => {
      if (!settled && window.pywebview && window.pywebview.api) {
        settled = true;
        if (timerId !== null) clearTimeout(timerId);
        backendApi = window.pywebview.api;
        usingMockBackend = false;
        resolve(backendApi);
      }
    };
    window.addEventListener("pywebviewready", onReady, { once: true });
    timerId = setTimeout(() => {
      if (settled) return;
      settled = true;
      if (typeof window.removeEventListener === "function") {
        window.removeEventListener("pywebviewready", onReady);
      }
      backendApi = createBrowserMockApi();
      usingMockBackend = true;
      lateReadyListener = () => {
        if (!window.pywebview || !window.pywebview.api) return;
        lateReadyListener = null;
        backendApi = window.pywebview.api;
        usingMockBackend = false;
        requestSeq = 0;
        latestMutationSeq = 0;
        lastAppliedMutationSeq = 0;
        inFlightKeys.clear();
        if (typeof backendUpgradeHandler === "function") backendUpgradeHandler(backendApi);
      };
      window.addEventListener("pywebviewready", lateReadyListener, { once: true });
      resolve(backendApi);
    }, timeoutMs);
  });
}

/* Ejecuta llamadas hacia WebviewBridge de forma uniforme */
export async function invokeApi(callFn, successMessage, options) {
  if (!backendApi) return false;
  const retry = () => invokeApi(callFn, successMessage, options);
  const silent = Boolean(options && options.silent);
  const isPoll = Boolean(options && options.poll);
  const dedupeKey = options && typeof options.dedupeKey === "string" ? options.dedupeKey : null;
  if (dedupeKey && inFlightKeys.has(dedupeKey)) return false;
  if (dedupeKey) inFlightKeys.add(dedupeKey);
  const seq = ++requestSeq;
  if (!isPoll) latestMutationSeq = seq;
  try {
    const response = await callFn();
    if (isPoll && seq < latestMutationSeq) return false;
    if (!isPoll && seq < lastAppliedMutationSeq) return false;
    if (!isPoll) lastAppliedMutationSeq = seq;
    if (typeof envelopeHandler === "function") {
      envelopeHandler(response, successMessage, retry, silent, options);
    }
    return Boolean(response && response.ok !== false);
  } catch (err) {
    if (isPoll && seq < latestMutationSeq) return false;
    const message = t("status.commError", { error: err && err.message ? err.message : String(err) });
    setStatusMessage(message);
    showToast({ kind: "error", message, retry });
    return false;
  } finally {
    if (dedupeKey) inFlightKeys.delete(dedupeKey);
  }
}
