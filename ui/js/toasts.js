/*
 * Status banner and toast notification helpers.
 */

import { t } from "./store.js";

export function setStatusMessage(message) {
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

function syncToastPopover(region, { promote = false } = {}) {
  if (!region) return;
  const hasToasts = Boolean(region.children && region.children.length > 0);
  if (hasToasts) {
    if (typeof region.showPopover !== "function") return;
    try {
      if (typeof region.matches === "function" && region.matches(":popover-open")) {
        if (!promote) return;
        if (typeof region.hidePopover === "function") {
          region.hidePopover();
        }
      }
      region.showPopover();
    } catch {
      /* Ignore browsers or test environments without full Popover API support */
    }
    return;
  }
  if (typeof region.hidePopover === "function") {
    try {
      region.hidePopover();
    } catch {
      /* Ignore when popover is already closed */
    }
  }
}

function dismissToast(el) {
  const region = el ? el.parentNode : null;
  if (el && region) region.removeChild(el);
  if (el === okToastEl) okToastEl = null;
  syncToastPopover(region);
}

export function showToast({ kind, message, retry }) {
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
    syncToastPopover(region, { promote: true });
    okToastTimer = setTimeout(() => dismissToast(okToastEl), TOAST_OK_MS);
    return;
  }

  /* Un error identico ya visible no se duplica */
  const duplicate = Array.from(region.querySelectorAll(".toast-error .toast-message")).find(
    (node) => node.textContent === message
  );
  if (duplicate) {
    syncToastPopover(region, { promote: true });
    return;
  }
  region.appendChild(buildToast("error", message, retry));
  syncToastPopover(region, { promote: true });
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
