/*
 * Circadian lighting curve, Wake-Up ramp, Windows session triggers, and Context/On-Air panel.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import { appState, clampInt, t, withButtonBusy } from "./store.js";

function pad2(val) {
  return String(Math.max(0, Math.floor(Number(val) || 0))).padStart(2, "0");
}

function formatHourInput(hourFloat) {
  const totalMinutes = Math.round(Math.max(0, Math.min(23.98, Number(hourFloat) || 0)) * 60);
  const hh = Math.floor(totalMinutes / 60) % 24;
  const mm = totalMinutes % 60;
  return `${pad2(hh)}:${pad2(mm)}`;
}

function parseHourInput(hhmm, fallback) {
  if (typeof hhmm !== "string" || !hhmm.includes(":")) return fallback;
  const [rawH, rawM] = hhmm.split(":");
  const h = Number(rawH);
  const m = Number(rawM);
  if (!Number.isFinite(h) || !Number.isFinite(m) || h < 0 || h > 23 || m < 0 || m > 59) {
    return fallback;
  }
  return Number((h + m / 60).toFixed(2));
}

function saveContextAutomation(nextCfg) {
  return invokeApi(
    () => getBackendApi().set_context_automation(nextCfg),
    () => t("status.contextAutomationSaved")
  );
}

function renderContextRulesList(ctxCfg) {
  const listEl = document.getElementById("context-rules-list");
  if (!listEl) return;
  const rules = Array.isArray(ctxCfg.rules) ? ctxCfg.rules : [];
  const rows = rules.map((rule) => {
    const row = document.createElement("div");
    row.className = "context-rule-row";
    const label = document.createElement("span");
    label.className = "context-rule-label";
    label.textContent = `${rule.process_name} -> ${rule.action_type}:${rule.value}`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-ghost btn-compact";
    removeBtn.textContent = t("auto.removeRule");
    removeBtn.addEventListener("click", () => {
      const updated = Object.assign({}, ctxCfg, {
        rules: rules.filter((r) => r.process_name !== rule.process_name)
      });
      saveContextAutomation(updated);
    });
    row.appendChild(label);
    row.appendChild(removeBtn);
    return row;
  });
  listEl.replaceChildren(...rows);
}

export function renderAutomationPanel() {
  const circ = appState.circadian || {};
  const wake = appState.wakeupRamp || {};
  const wakeStatus = appState.wakeupRampStatus || {};
  const session = appState.sessionTriggers || {};
  const ctx = appState.contextAutomation || {};
  const onAir = ctx.on_air || {};
  const ctxStatus = appState.contextStatus || {};

  const badge = document.getElementById("automation-badge");
  if (badge) {
    const anyActive = Boolean(
      circ.enabled ||
        wake.enabled ||
        wakeStatus.active ||
        session.off_on_lock ||
        session.restore_on_unlock ||
        session.off_on_sleep ||
        ctx.enabled ||
        onAir.enabled
    );
    badge.setAttribute("data-active", String(anyActive));
    badge.textContent = anyActive ? t("auto.badgeActive") : t("auto.badgeIdle");
  }

  const circEnabled = document.getElementById("circadian-enabled");
  if (circEnabled) circEnabled.checked = Boolean(circ.enabled);

  const sunriseInp = document.getElementById("circadian-sunrise");
  if (sunriseInp && document.activeElement !== sunriseInp) {
    sunriseInp.value = formatHourInput(circ.sunrise_hour ?? 7.0);
  }
  const sunsetInp = document.getElementById("circadian-sunset");
  if (sunsetInp && document.activeElement !== sunsetInp) {
    sunsetInp.value = formatHourInput(circ.sunset_hour ?? 20.0);
  }

  const wakeEnabled = document.getElementById("wakeup-enabled");
  if (wakeEnabled) wakeEnabled.checked = Boolean(wake.enabled);

  const wakeTime = document.getElementById("wakeup-time");
  if (wakeTime && document.activeElement !== wakeTime) {
    wakeTime.value = `${pad2(wake.target_hour ?? 7)}:${pad2(wake.target_minute ?? 0)}`;
  }

  const wakeDuration = document.getElementById("wakeup-duration");
  if (wakeDuration && document.activeElement !== wakeDuration) {
    wakeDuration.value = String(clampInt(wake.duration_minutes ?? 20, 1, 60));
  }

  const cancelWakeBtn = document.getElementById("cancel-wakeup-btn");
  if (cancelWakeBtn) {
    cancelWakeBtn.disabled = !Boolean(wakeStatus.active);
  }

  const offOnLock = document.getElementById("session-off-on-lock");
  if (offOnLock) offOnLock.checked = Boolean(session.off_on_lock);
  const restoreUnlock = document.getElementById("session-restore-on-unlock");
  if (restoreUnlock) restoreUnlock.checked = Boolean(session.restore_on_unlock);
  const offOnSleep = document.getElementById("session-off-on-sleep");
  if (offOnSleep) offOnSleep.checked = Boolean(session.off_on_sleep);

  const ctxEnabled = document.getElementById("context-enabled");
  if (ctxEnabled) ctxEnabled.checked = Boolean(ctx.enabled);
  const onAirEnabled = document.getElementById("on-air-enabled");
  if (onAirEnabled) onAirEnabled.checked = Boolean(onAir.enabled);
  const onAirColor = document.getElementById("on-air-color");
  if (onAirColor && document.activeElement !== onAirColor) {
    onAirColor.value = onAir.color_hex || "#ff2a55";
  }
  const statusPill = document.getElementById("context-status-pill");
  if (statusPill) {
    statusPill.textContent = ctxStatus.on_air_active
      ? t("auto.onAirLive")
      : ctxStatus.active_reason || "";
  }
  renderContextRulesList(ctx);
}

export function bindAutomationEvents() {
  const saveCircadian = () => {
    const enabled = Boolean(document.getElementById("circadian-enabled")?.checked);
    const sunriseStr = document.getElementById("circadian-sunrise")?.value || "07:00";
    const sunsetStr = document.getElementById("circadian-sunset")?.value || "20:00";
    const prev = appState.circadian || {};
    const nextCfg = Object.assign({}, prev, {
      enabled,
      sunrise_hour: parseHourInput(sunriseStr, 7.0),
      sunset_hour: parseHourInput(sunsetStr, 20.0)
    });
    return invokeApi(
      () => getBackendApi().set_circadian_config(nextCfg),
      () => t(enabled ? "status.circadianEnabled" : "status.circadianDisabled")
    );
  };

  const saveWakeup = () => {
    const enabled = Boolean(document.getElementById("wakeup-enabled")?.checked);
    const timeStr = document.getElementById("wakeup-time")?.value || "07:00";
    const [rawH, rawM] = timeStr.split(":");
    const target_hour = clampInt(rawH ?? 7, 0, 23);
    const target_minute = clampInt(rawM ?? 0, 0, 59);
    const duration_minutes = clampInt(document.getElementById("wakeup-duration")?.value ?? 20, 1, 60);
    const prev = appState.wakeupRamp || {};
    const nextCfg = Object.assign({}, prev, {
      enabled,
      target_hour,
      target_minute,
      duration_minutes
    });
    return invokeApi(
      () => getBackendApi().set_wakeup_ramp_config(nextCfg),
      () => t(enabled ? "status.wakeupSaved" : "status.wakeupDisabled")
    );
  };

  const circEnabled = document.getElementById("circadian-enabled");
  if (circEnabled) circEnabled.addEventListener("change", saveCircadian);
  const saveCircBtn = document.getElementById("save-circadian-btn");
  if (saveCircBtn) {
    saveCircBtn.addEventListener("click", () => withButtonBusy(saveCircBtn, saveCircadian));
  }

  const wakeEnabled = document.getElementById("wakeup-enabled");
  if (wakeEnabled) wakeEnabled.addEventListener("change", saveWakeup);
  const saveWakeBtn = document.getElementById("save-wakeup-btn");
  if (saveWakeBtn) {
    saveWakeBtn.addEventListener("click", () => withButtonBusy(saveWakeBtn, saveWakeup));
  }

  const triggerWakeBtn = document.getElementById("trigger-wakeup-btn");
  if (triggerWakeBtn) {
    triggerWakeBtn.addEventListener("click", () =>
      withButtonBusy(triggerWakeBtn, () =>
        invokeApi(() => getBackendApi().trigger_wakeup_ramp(null), () => t("status.wakeupTriggered"))
      )
    );
  }

  const cancelWakeBtn = document.getElementById("cancel-wakeup-btn");
  if (cancelWakeBtn) {
    cancelWakeBtn.addEventListener("click", () =>
      invokeApi(() => getBackendApi().cancel_wakeup_ramp(), () => t("status.wakeupCancelled"))
    );
  }

  const saveSessionTriggers = () => {
    const nextCfg = {
      off_on_lock: Boolean(document.getElementById("session-off-on-lock")?.checked),
      restore_on_unlock: Boolean(document.getElementById("session-restore-on-unlock")?.checked),
      off_on_sleep: Boolean(document.getElementById("session-off-on-sleep")?.checked)
    };
    return invokeApi(
      () => getBackendApi().set_session_triggers(nextCfg),
      () => t("status.sessionTriggersSaved")
    );
  };
  for (const id of ["session-off-on-lock", "session-restore-on-unlock", "session-off-on-sleep"]) {
    const inp = document.getElementById(id);
    if (inp) inp.addEventListener("change", saveSessionTriggers);
  }

  const pushContextConfig = () => {
    const prev = appState.contextAutomation || {};
    const prevOnAir = prev.on_air || {};
    const nextCfg = {
      enabled: Boolean(document.getElementById("context-enabled")?.checked),
      poll_seconds: prev.poll_seconds ?? 5,
      on_air: Object.assign({}, prevOnAir, {
        enabled: Boolean(document.getElementById("on-air-enabled")?.checked),
        color_hex: document.getElementById("on-air-color")?.value || prevOnAir.color_hex || "#ff2a55"
      }),
      rules: Array.isArray(prev.rules) ? prev.rules.slice() : []
    };
    return saveContextAutomation(nextCfg);
  };
  for (const id of ["context-enabled", "on-air-enabled", "on-air-color"]) {
    const inp = document.getElementById(id);
    if (inp) inp.addEventListener("change", pushContextConfig);
  }

  const addRuleBtn = document.getElementById("add-context-rule-btn");
  if (addRuleBtn) {
    addRuleBtn.addEventListener("click", () => {
      const procInput = document.getElementById("context-rule-process");
      const sceneInput = document.getElementById("context-rule-scene");
      const proc = String(procInput?.value || "").trim().toLowerCase();
      if (!proc) return;
      const sceneId = clampInt(sceneInput?.value ?? 12, 1, 36);
      const prev = appState.contextAutomation || {};
      const existing = Array.isArray(prev.rules) ? prev.rules.filter((r) => r.process_name !== proc) : [];
      existing.push({
        process_name: proc,
        action_type: "scene",
        value: String(sceneId),
        brightness: 85,
        target_ips: []
      });
      if (procInput) procInput.value = "";
      saveContextAutomation(Object.assign({}, prev, { rules: existing }));
    });
  }
}
