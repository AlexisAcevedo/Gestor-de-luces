/*
 * Built-in WiZ scene grid, category filtering/counts, and custom presets management.
 */

import { getBackendApi, invokeApi } from "./bridge-client.js";
import {
  SCENE_CATEGORY_COLORS,
  SCENE_CHROMATIC_MAP,
  appState,
  bindSliderInteraction,
  captureFocusKey,
  clampInt,
  formatSceneDisplayName,
  getPrimaryBulb,
  kelvinToCssColor,
  restoreFocusKey,
  rgbToHex,
  saveFavoriteSceneIds,
  setFieldError,
  t,
  updateSliderFill,
  withButtonBusy
} from "./store.js";
import { setStatusMessage, showToast } from "./toasts.js";

let pendingPresetDelete = null;

export function resetPendingPresetDeleteForTests() {
  if (pendingPresetDelete) {
    clearTimeout(pendingPresetDelete.timerId);
    pendingPresetDelete = null;
  }
}

export function flushPendingPresetDelete() {
  if (!pendingPresetDelete) return;
  clearTimeout(pendingPresetDelete.timerId);
  const { commit } = pendingPresetDelete;
  pendingPresetDelete = null;
  commit();
}

if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("beforeunload", flushPendingPresetDelete);
}

const STAR_PATH_D =
  "M10 2.75l2.18 4.42 4.88.71-3.53 3.44.83 4.86L10 13.88l-4.36 2.3.83-4.86-3.53-3.44 4.88-.71L10 2.75Z";

function createStarIcon(filled) {
  const starSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  starSvg.setAttribute("class", "icon");
  starSvg.setAttribute("viewBox", "0 0 20 20");
  starSvg.setAttribute("fill", filled ? "currentColor" : "none");
  starSvg.setAttribute("aria-hidden", "true");
  const starPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  starPath.setAttribute("d", STAR_PATH_D);
  starPath.setAttribute("stroke", "currentColor");
  starPath.setAttribute("stroke-width", "1.5");
  starPath.setAttribute("stroke-linejoin", "round");
  starSvg.appendChild(starPath);
  return starSvg;
}

function createEl(tag, className, textContent) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (textContent !== undefined) el.textContent = textContent;
  return el;
}

/* Actualiza los contadores en cada pildora de filtro de categoria de escenas */
export function updateSceneCategoryCounts() {
  const countByCat = (cat) => appState.scenes.filter((s) => s.category === cat).length;
  const favLabel = document.getElementById("scene-cat-favorites-label");
  if (favLabel) {
    favLabel.textContent = t("scenes.catFavoritesCount", { count: appState.favoriteSceneIds.length });
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
    const entry = catKeyMap[btn.dataset.category];
    if (entry) btn.textContent = t(entry.key, { count: entry.count });
  });
}

/* Renderiza la cuadricula de las 36 escenas nativas de WiZ con indicadores cromaticos y favoritos */
export function renderScenesGrid() {
  const grid = document.getElementById("scenes-grid");
  updateSceneCategoryCounts();
  if (!grid) return;
  const focusKey = captureFocusKey(grid);

  const primary = getPrimaryBulb();
  const activeSceneId = primary && primary.state.mode === "scene" ? primary.state.scene_id : null;

  const speedContainer = document.getElementById("scene-speed-container");
  const speedSlider = document.getElementById("scene-speed-slider");
  const activeSceneObj = appState.scenes.find((s) => s.scene_id === activeSceneId);
  const isDynamicSpeedSupported = Boolean(
    activeSceneObj && activeSceneObj.supports_speed && appState.sceneCategory !== "white"
  );
  if (speedContainer) speedContainer.classList.toggle("is-disabled", !isDynamicSpeedSupported);
  if (speedSlider) speedSlider.disabled = !isDynamicSpeedSupported;

  let filtered = [];
  if (appState.sceneCategory === "favorites") {
    filtered = appState.scenes.filter((scene) => appState.favoriteSceneIds.includes(scene.scene_id));
  } else if (appState.sceneCategory === "all") {
    filtered = appState.scenes.slice().sort((a, b) => {
      const aFav = appState.favoriteSceneIds.includes(a.scene_id) ? 0 : 1;
      const bFav = appState.favoriteSceneIds.includes(b.scene_id) ? 0 : 1;
      return aFav !== bFav ? aFav - bFav : a.scene_id - b.scene_id;
    });
  } else {
    filtered = appState.scenes.filter((scene) => scene.category === appState.sceneCategory);
  }

  if (filtered.length === 0) {
    const empty = createEl("div", "empty-fixtures-state");
    empty.appendChild(createEl("p", null, t("scenes.emptyFavorites")));
    grid.replaceChildren(empty);
    return;
  }

  const cards = filtered.map((scene) => {
    const isSceneActive = activeSceneId === scene.scene_id;
    const isFav = appState.favoriteSceneIds.includes(scene.scene_id);
    const displayName = formatSceneDisplayName(scene);
    const chroma = SCENE_CHROMATIC_MAP[scene.scene_id] || {
      accent: SCENE_CATEGORY_COLORS[scene.category] || "#38bdf8",
      gradient: SCENE_CATEGORY_COLORS[scene.category] || "#38bdf8"
    };

    const card = createEl("article", `scene-card${isSceneActive ? " active" : ""}`);
    card.style.setProperty("--scene-accent", chroma.accent);
    card.style.setProperty("--scene-gradient", chroma.gradient);

    const trigger = createEl("button", "scene-card-trigger");
    trigger.type = "button";
    trigger.setAttribute("data-focus-key", `scene-trigger:${scene.scene_id}`);
    trigger.setAttribute("aria-pressed", String(isSceneActive));

    const top = createEl("span", "scene-card-top");
    const idGroup = createEl("span", "scene-card-id-group");
    const colorDot = createEl("span", "scene-color-dot");
    colorDot.setAttribute("aria-hidden", "true");
    idGroup.append(colorDot, createEl("span", "scene-id-badge", `#${String(scene.scene_id).padStart(2, "0")}`));

    const badgesGroup = createEl("span", "scene-card-badges");
    if (isSceneActive) {
      badgesGroup.appendChild(createEl("span", "scene-active-badge", t("scenes.badgeActive")));
    }
    badgesGroup.appendChild(
      createEl("span", "scene-tag", scene.supports_speed ? t("scenes.tagDynamic") : t("scenes.tagStatic"))
    );
    top.append(idGroup, badgesGroup);

    const title = createEl("span", "scene-name", displayName);

    const favBtn = createEl("button", `scene-fav-btn${isFav ? " is-fav" : ""}`);
    favBtn.type = "button";
    favBtn.setAttribute("data-focus-key", `scene-fav:${scene.scene_id}`);
    favBtn.setAttribute("aria-pressed", String(isFav));
    const favLabel = t(isFav ? "scenes.favRemoveAria" : "scenes.favAddAria", { name: displayName });
    favBtn.title = favLabel;
    favBtn.setAttribute("aria-label", favLabel);
    favBtn.appendChild(createStarIcon(isFav));

    favBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const exists = appState.favoriteSceneIds.includes(scene.scene_id);
      if (exists) {
        appState.favoriteSceneIds = appState.favoriteSceneIds.filter((id) => id !== scene.scene_id);
      } else {
        appState.favoriteSceneIds.push(scene.scene_id);
      }
      saveFavoriteSceneIds(appState.favoriteSceneIds);
      renderScenesGrid();
      setStatusMessage(t(exists ? "status.sceneFavRemoved" : "status.sceneFavAdded", { name: displayName }));
      const api = getBackendApi();
      if (api && typeof api.set_favorite_builtin_scenes === "function") {
        invokeApi(() => api.set_favorite_builtin_scenes(appState.favoriteSceneIds.slice()), null, {
          silent: true
        });
      }
    });

    const activateScene = () => {
      const speedInput = document.getElementById("scene-speed-slider");
      const speedVal = scene.supports_speed && speedInput ? Number(speedInput.value) : null;
      invokeApi(
        () => getBackendApi().set_builtin_scene(scene.scene_id, speedVal, null, null),
        () => t("status.sceneActivated", { id: scene.scene_id, name: displayName })
      );
    };

    trigger.addEventListener("click", activateScene);
    trigger.append(top, title);
    card.append(trigger, favBtn);
    return card;
  });
  grid.replaceChildren(...cards);
  restoreFocusKey(grid, focusKey);
}

/* Renderiza la galeria de presets personalizados guardados en JSON */
export function renderCustomScenesGrid() {
  const grid = document.getElementById("custom-scenes-grid");
  const tabLabel = document.getElementById("custom-tab-label");
  const visiblePresets = pendingPresetDelete
    ? appState.customScenes.filter((p) => p.id !== pendingPresetDelete.preset.id)
    : appState.customScenes;
  if (tabLabel) {
    tabLabel.textContent = t("tabs.customWithCount", { count: visiblePresets.length });
  }
  if (!grid) return;
  const focusKey = captureFocusKey(grid);

  if (visiblePresets.length === 0) {
    const empty = createEl("div", "empty-fixtures-state");
    empty.append(createEl("p", null, t("custom.emptyTitle")), createEl("p", null, t("custom.emptySubtitle")));
    grid.replaceChildren(empty);
    return;
  }

  const cards = visiblePresets.map((preset) => {
    const card = createEl("article", "custom-scene-card");
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
      const sName = bScene ? formatSceneDisplayName(bScene) : `#${preset.built_in_scene_id}`;
      summaryText = t("custom.summaryScene", { scene: sName, brightness: preset.brightness });
    } else {
      const k = preset.temperature || 4200;
      swatchCss = kelvinToCssColor(k);
      summaryText = `${k} K · ${preset.brightness}%`;
    }

    const topArea = createEl("button", "custom-scene-top");
    topArea.type = "button";
    topArea.setAttribute("data-focus-key", `preset-top:${preset.id}`);
    topArea.setAttribute("aria-label", t("custom.applyAria", { name: preset.name }));

    const swatch = createEl("span", "custom-scene-swatch");
    swatch.style.setProperty("--preset-swatch", swatchCss);
    swatch.setAttribute("aria-hidden", "true");

    const meta = createEl("span", "custom-scene-meta");
    meta.append(
      createEl("span", "custom-scene-title", preset.name),
      createEl("span", "custom-scene-summary", summaryText)
    );
    topArea.append(swatch, meta);

    const triggerApply = () => {
      invokeApi(
        () => getBackendApi().apply_custom_scene(preset.id, null),
        () => t("status.presetApplied", { name: preset.name })
      );
    };

    topArea.addEventListener("click", triggerApply);

    const actions = createEl("div", "custom-scene-actions");
    const isFavorite = Boolean(preset.is_favorite);
    const favoriteBtn = createEl("button", `btn btn-compact btn-favorite${isFavorite ? " is-favorite" : ""}`);
    favoriteBtn.type = "button";
    favoriteBtn.setAttribute("data-focus-key", `preset-fav:${preset.id}`);
    favoriteBtn.setAttribute("aria-pressed", String(isFavorite));
    favoriteBtn.title = isFavorite ? t("custom.favoriteRemoveTitle") : t("custom.favoriteAddTitle");
    favoriteBtn.append(
      createStarIcon(isFavorite),
      createEl("span", null, isFavorite ? t("custom.favoritedBtn") : t("custom.favoriteBtn"))
    );
    favoriteBtn.addEventListener("click", () => {
      const nextFavorite = !isFavorite;
      invokeApi(
        () => getBackendApi().set_custom_scene_favorite(preset.id, nextFavorite),
        () => t(nextFavorite ? "status.favoriteAdded" : "status.favoriteRemoved", { name: preset.name })
      );
    });

    const applyBtn = createEl("button", "btn btn-compact btn-primary", t("custom.applyBtn"));
    applyBtn.type = "button";
    applyBtn.setAttribute("data-focus-key", `preset-apply:${preset.id}`);
    applyBtn.addEventListener("click", triggerApply);

    const editBtn = createEl("button", "btn btn-compact btn-secondary", t("custom.editBtn"));
    editBtn.type = "button";
    editBtn.setAttribute("data-focus-key", `preset-edit:${preset.id}`);
    editBtn.addEventListener("click", () => openCustomSceneDialog(preset));

    const deleteBtn = createEl("button", "btn btn-compact btn-ghost", t("custom.deleteBtn"));
    deleteBtn.type = "button";
    deleteBtn.setAttribute("data-focus-key", `preset-delete:${preset.id}`);
    deleteBtn.addEventListener("click", () => {
      flushPendingPresetDelete();
      const commit = () =>
        invokeApi(() => getBackendApi().delete_custom_scene(preset.id), null, { silent: true });
      const timerId = setTimeout(() => {
        if (!pendingPresetDelete || pendingPresetDelete.preset.id !== preset.id) return;
        pendingPresetDelete = null;
        commit();
      }, 5000);
      pendingPresetDelete = { preset, timerId, commit };
      renderCustomScenesGrid();
      const deletedMsg = t("status.presetDeleted", { name: preset.name });
      setStatusMessage(deletedMsg);
      showToast({
        kind: "ok",
        message: deletedMsg,
        actionLabel: t("toast.undo"),
        durationMs: 5000,
        onAction: () => {
          if (!pendingPresetDelete || pendingPresetDelete.preset.id !== preset.id) return;
          clearTimeout(pendingPresetDelete.timerId);
          pendingPresetDelete = null;
          renderCustomScenesGrid();
          setStatusMessage(t("status.presetRestored", { name: preset.name }));
        },
        onDismiss: () => {
          if (!pendingPresetDelete || pendingPresetDelete.preset.id !== preset.id) return;
          clearTimeout(pendingPresetDelete.timerId);
          const fn = pendingPresetDelete.commit;
          pendingPresetDelete = null;
          fn();
        }
      });
    });

    actions.append(favoriteBtn, applyBtn, editBtn, deleteBtn);
    card.append(topArea, actions);
    return card;
  });
  grid.replaceChildren(...cards);
  restoreFocusKey(grid, focusKey);
}

/* Abre el dialogo modal para crear un nuevo preset o editar uno existente */
export function openCustomSceneDialog(existingPreset) {
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

  setFieldError(nameInput, document.getElementById("custom-scene-error"), "");
  dialog.showModal();
  nameInput.focus();
  if (existingPreset) nameInput.select();
}

export function bindSceneEvents({ activateTab }) {
  document.querySelectorAll(".scene-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      appState.sceneCategory = btn.dataset.category || "all";
      document.querySelectorAll(".scene-filter").forEach((b) => {
        const active = b === btn;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
      renderScenesGrid();
    });
  });

  const speedSlider = document.getElementById("scene-speed-slider");
  const speedOutput = document.getElementById("scene-speed-output");
  if (speedSlider && speedOutput) {
    bindSliderInteraction(speedSlider);
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
        () => getBackendApi().set_builtin_scene(primary.state.scene_id, speed, null, null),
        () => t("status.sceneSpeedUpdated", { id: primary.state.scene_id, speed })
      );
    });
  }

  const quickSavePresetBtn = document.getElementById("quick-save-preset-btn");
  if (quickSavePresetBtn) quickSavePresetBtn.addEventListener("click", () => openCustomSceneDialog(null));

  const openSaveSceneBtn = document.getElementById("open-save-scene-dialog-btn");
  if (openSaveSceneBtn) openSaveSceneBtn.addEventListener("click", () => openCustomSceneDialog(null));

  const customSceneNameInput = document.getElementById("custom-scene-name-input");
  const customSceneError = document.getElementById("custom-scene-error");
  if (customSceneNameInput) {
    customSceneNameInput.addEventListener("input", () => setFieldError(customSceneNameInput, customSceneError, ""));
  }

  const customSceneForm = document.getElementById("custom-scene-form");
  const customSceneDialog = document.getElementById("custom-scene-dialog");
  const customSceneSubmitBtn = document.getElementById("custom-scene-submit-btn");
  if (customSceneForm && customSceneDialog) {
    customSceneForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const idInput = document.getElementById("custom-scene-id-input");
      const nameInput = document.getElementById("custom-scene-name-input");
      const overwriteCheckbox = document.getElementById("custom-scene-overwrite-checkbox");
      const sceneId = idInput ? idInput.value.trim() : "";
      const name = nameInput ? nameInput.value.trim() : "";
      const captureCurrent = Boolean(overwriteCheckbox && overwriteCheckbox.checked);
      if (!name) return;

      setFieldError(nameInput, customSceneError, "");
      const ok = await withButtonBusy(customSceneSubmitBtn, () => {
        if (sceneId) {
          return invokeApi(
            () => getBackendApi().update_custom_scene(sceneId, name, captureCurrent),
            () => t("status.presetUpdated", { name })
          );
        }
        const primary = getPrimaryBulb();
        return invokeApi(
          () => getBackendApi().save_custom_scene(name, primary ? primary.ip : null),
          () => t("status.presetSaved", { name })
        );
      });
      if (ok) {
        customSceneDialog.close();
        if (!sceneId) activateTab("custom", false);
      } else {
        setFieldError(nameInput, customSceneError, t("dialog.presetSaveFailed"));
        if (nameInput) nameInput.focus();
      }
    });
  }
}
