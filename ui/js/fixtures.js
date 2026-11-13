/*
 * Fixture drawer rail, Sleep Timer rendering/polling, and related event bindings.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import { appState, clampInt, formatCountdown, t } from "./store.js";
import { setStatusMessage } from "./toasts.js";

function createSvgIcon(pathD, strokeWidth = "1.5") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("fill", "none");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pathD);
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", strokeWidth);
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}

export function openRenameDialog(bulb) {
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

/* Renderiza las tarjetas de focos en el riel izquierdo sin usar innerHTML con datos de usuario */
export function renderFixtureList() {
  const container = document.getElementById("fixture-list");
  const badge = document.getElementById("fixture-count-badge");
  const selectAllCheckbox = document.getElementById("select-all-fixtures");
  if (!container) return;

  const onlineCount = appState.bulbs.filter((b) => b.is_online).length;
  if (badge) {
    badge.textContent = t("rail.onlineCount", { online: onlineCount, total: appState.bulbs.length });
  }

  if (selectAllCheckbox) {
    selectAllCheckbox.checked =
      appState.bulbs.length > 0 && appState.bulbs.every((b) => appState.selectedIps.includes(b.ip));
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
      invokeApi(() => getBackendApi().select_targets(nextIps), () => t("status.selectionUpdated"));
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
    renameBtn.appendChild(
      createSvgIcon("M13.58 3.58a2 2 0 0 1 2.84 2.84l-8.5 8.5-3.67.83.83-3.67 8.5-8.5ZM12.17 5l2.83 2.83")
    );
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
    const powerLabel = t(isBulbOn ? "rail.powerToggleOnAria" : "rail.powerToggleOffAria", { name: bulb.name });
    powerBtn.title = powerLabel;
    powerBtn.setAttribute("aria-label", powerLabel);
    powerBtn.appendChild(createSvgIcon("M10 2.75v6.5M6.1 4.85a6.5 6.5 0 1 0 7.8 0", "1.75"));
    powerBtn.addEventListener("click", () => {
      const nextPower = !bulb.state.is_on;
      invokeApi(
        () => getBackendApi().set_power(nextPower, null, [bulb.ip]),
        () => t(nextPower ? "status.bulbTurnedOn" : "status.bulbTurnedOff", { name: bulb.name })
      );
    });

    actionsDiv.appendChild(powerBtn);
    bottomRow.append(statusSpan, actionsDiv);
    card.append(topRow, bottomRow);
    container.appendChild(card);
  });
}

/* Activa o detiene el sondeo cada 1s mientras el temporizador de apagado este corriendo */
export function syncSleepTimerPolling() {
  const isActive = Boolean(appState.sleepTimer && appState.sleepTimer.active);
  if (isActive && !appState.sleepPollTimer) {
    appState.sleepPollTimer = setInterval(() => {
      if (document.hidden) return;
      invokeApi(() => getBackendApi().get_sleep_timer_status(), null);
    }, 1000);
  } else if (!isActive && appState.sleepPollTimer) {
    clearInterval(appState.sleepPollTimer);
    appState.sleepPollTimer = null;
  }
}

/* Actualiza la barra visual colapsable del Sleep Timer y el estado contextual del boton Cancelar */
export function renderSleepTimer() {
  const detailsEl = document.getElementById("sleep-timer-details");
  const badge = document.getElementById("sleep-timer-badge");
  const cancelBtn = document.getElementById("cancel-sleep-timer-btn");
  const timer = appState.sleepTimer || { active: false, remaining_seconds: 0, total_seconds: 0 };

  if (detailsEl && timer.active) detailsEl.open = true;
  if (badge) {
    badge.setAttribute("data-active", String(Boolean(timer.active)));
    badge.setAttribute("data-live", String(Boolean(timer.active)));
    if (timer.active) {
      const fadeThreshold = Math.ceil((timer.total_seconds || 0) * 0.3);
      const inFadePhase = timer.remaining_seconds <= fadeThreshold;
      const phaseLabel = inFadePhase ? t("sleep.phaseFade") : t("sleep.phaseSteady");
      badge.textContent = t("sleep.badgeActive", { countdown: formatCountdown(timer.remaining_seconds), phase: phaseLabel });
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

export function bindFixtureEvents() {
  const drawerBtn = document.getElementById("fixture-drawer-btn");
  const fixtureDrawer = document.getElementById("fixture-drawer");
  if (drawerBtn && fixtureDrawer) {
    drawerBtn.addEventListener("click", () => {
      if (!fixtureDrawer.open) {
        fixtureDrawer.showModal();
        drawerBtn.setAttribute("aria-expanded", "true");
      }
    });
    fixtureDrawer.addEventListener("close", () => {
      drawerBtn.setAttribute("aria-expanded", "false");
    });
  }

  const scanBtn = document.getElementById("scan-network-btn");
  const scanLabel = document.getElementById("scan-btn-label");
  if (scanBtn) {
    scanBtn.addEventListener("click", async () => {
      if (scanLabel) scanLabel.textContent = t("rail.scanningBtn");
      scanBtn.disabled = true;
      try {
        await invokeApi(() => getBackendApi().discover_bulbs(), () => t("status.scanDone"));
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
      invokeApi(() => getBackendApi().add_manual_bulb(ip, name), () => t("status.registeredIp", { ip }));
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
      invokeApi(() => getBackendApi().rename_bulb(ip, newName), () => t("status.renamedBulb", { ip, name: newName }));
    });
  }

  const selectAll = document.getElementById("select-all-fixtures");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      const nextIps = selectAll.checked ? appState.bulbs.map((b) => b.ip) : [];
      invokeApi(() => getBackendApi().select_targets(nextIps), () => t("status.multiSelectionUpdated"));
    });
  }

  const syncNowBtn = document.getElementById("sync-now-btn");
  if (syncNowBtn) {
    syncNowBtn.addEventListener("click", () => {
      invokeApi(() => getBackendApi().refresh_states(), () => t("status.syncedLive"));
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
          if (document.hidden) return;
          invokeApi(() => getBackendApi().refresh_states(), () => t("status.autoSyncStep"));
        }, 3000);
        setStatusMessage(t("status.autoSyncEnabled"));
      } else {
        setStatusMessage(t("status.autoSyncPaused"));
      }
    });
  }

  const sleepMinutesInput = document.getElementById("sleep-minutes-input");
  document.querySelectorAll(".sleep-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mins = clampInt(btn.dataset.minutes, 1, 240);
      if (sleepMinutesInput) sleepMinutesInput.value = String(mins);
      document.querySelectorAll(".sleep-preset-btn").forEach((b) => b.classList.toggle("active", b === btn));
      invokeApi(() => getBackendApi().start_sleep_timer(mins, null), () => t("status.sleepStarted", { minutes: mins }));
    });
  });

  const startTimerBtn = document.getElementById("start-sleep-timer-btn");
  if (startTimerBtn) {
    startTimerBtn.addEventListener("click", () => {
      const mins = clampInt(sleepMinutesInput ? sleepMinutesInput.value : 30, 1, 240);
      if (sleepMinutesInput) sleepMinutesInput.value = String(mins);
      invokeApi(() => getBackendApi().start_sleep_timer(mins, null), () => t("status.sleepStarted", { minutes: mins }));
    });
  }

  const cancelTimerBtn = document.getElementById("cancel-sleep-timer-btn");
  if (cancelTimerBtn) {
    cancelTimerBtn.addEventListener("click", () => {
      document.querySelectorAll(".sleep-preset-btn").forEach((b) => b.classList.remove("active"));
      invokeApi(() => getBackendApi().cancel_sleep_timer(), () => t("status.sleepCancelled"));
    });
  }
}
