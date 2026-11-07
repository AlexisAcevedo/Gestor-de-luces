# UI Redesign Specification — Dual Worktree Exploration

## 1. Context & Problem Statement

The current desktop UI (`ui/index.html`, `ui/styles.css`, `ui/app.js`) follows a dense "Photometric Console" aesthetic that suffers from several structural and visual problems identified during design review:

1. **Competing Visual Hierarchy ("Too much + Flat"):** Five heavy visual blocks (left fixture rail, telemetry header, dimming box with 5 percentage chips, 6-tab bar, and the 4-input RGB workbench) compete at the exact same visual weight with harsh structural borders (`#5A657A` / `#353E4F`).
2. **Inverted Workflow Priority:** The user's primary daily workflow is **fast power toggle (ON/OFF)**, **brightness adjustment (dimming)**, and **white color temperature (Kelvin warmth)** for a single primary fixture. However, the current UI dedicates ~30% of the viewport to a static multi-bulb network sidebar and opens by default on the complex Chromatic RGB wheel.
3. **Oversized Window Geometry:** `src/gestor_luces/main.py` currently forces the window to 90% of the primary monitor (`WINDOW_SCREEN_RATIO = 0.9`, up to `1440x920`), which is excessive for a fast desktop light controller.
4. **Generic AI-Dashboard Clichés:** Overuse of monospace technical badges (`UDP 38899`, `STANDBY`), tracked-out uppercase labels, and boxed cards.

---

## 2. Reference Design Skill (`benjitaylor/skills` — `stageshow`)

The `stageshow` skill from `https://github.com/benjitaylor/skills` is already installed locally at `.agents/skills/stageshow/` (`frontend-design` has been removed so it does not conflict). Read `.agents/skills/stageshow/SKILL.md`, `.agents/skills/stageshow/references/craft.md`, `.agents/skills/stageshow/references/looks.md`, `.agents/skills/stageshow/examples/dark-hero`, and `.agents/skills/stageshow/examples/looks/skeuomorphic.tsx` before designing or writing code.

> **Worktree Note:** Because `.agents/` is ignored in `.gitignore`, `git worktree add` will not copy `.agents/skills/stageshow/` into new worktrees automatically. Copy `.agents/` into each created worktree (or read from the main workspace root) so the skill remains active in every worktree.

> **Architectural Note:** Do **not** migrate the application to React or replace real PyWebView controls with `stageshow`'s faux-animation kit. Keep the existing Vanilla HTML/CSS/JS stack and Hexagonal Architecture intact. Extract and apply `stageshow`'s **visual craft, token discipline, surface hierarchy, and typography rules** to the real application UI, and execute `modern-web-guidance` first for all HTML/CSS/DOM patterns.

### Core `stageshow` Craft Rules to Enforce
- **One Clear Focal Point:** The eye must land immediately on the primary control (Master Power + Dimming + Warmth/Kelvin).
- **Hierarchy from Surface Steps, Not Box Borders:** Replace high-contrast wireframe borders with subtle surface steps, coherent top-edge highlights (`inset 0 1px 0`), and purposeful whitespace.
- **Typography Restraint:**
  - Single sans-serif stack (`--font-sans`), sentence case by default (no `UPPERCASE` tracked-out labels).
  - Reserve `--font-mono` (`font-variant-numeric: tabular-nums`) strictly for live numeric readouts (`2700 K`, `85%`, IP addresses), never for decorative labels.
  - Remove decorative telemetry noise (`UDP 38899` static text, redundant subtitles).
- **Spacing & Alignment:**
  - Minimum `12px` text inset from container edges; minimum `8px` gap between controls.
  - Group by whitespace rather than divider lines wherever possible.

---

## 3. Shared Spatial Architecture (Applies to Both Branches)

Both experimental branches must implement the same structural reorganization before applying their distinct visual look:

### 3.1. Single-Column Compact Controller + Slide-Over Fixture Drawer
- **Remove the permanent 30%-width left sidebar (`aside.fixture-rail`) from the main grid.**
- Replace it in the top bar with a clean **Fixture Pill / Drawer Trigger button** (hamburger / drawer trigger icon + active fixture name + online status dot) and a **Quick Language Switcher (`EN` / `ES`)**.
- Move `aside.fixture-rail` (containing `#fixture-list`, `#scan-network-btn`, `#open-add-dialog-btn`, `#select-all-fixtures`, `#fixture-count-badge`, `#sync-now-btn`, `#auto-sync-toggle`, `#shortcuts-help-btn`, and `#status-banner`) into a **slide-over drawer / sheet** (or native popover/dialog drawer) that stays hidden during normal daily use and opens smoothly when clicking the fixture trigger.

### 3.2. Primary Hero Stage: Fast Power + Brightness + Warmth (Kelvin)
- **Master Power Hero (`#master-power-btn`):** Prominent, tactile central/top control for instant ON/OFF toggling (also bound to `Space`), paired with `#photometric-aperture` and `#live-state-pill`.
- **Primary Dimming Control (`#brightness-slider` + `#brightness-output`):** Wide, tactile brightness track directly integrated into the main stage. Keep `.brightness-preset` chips subtle or compact so they do not visually compete with the slider.
- **Default Mode (`White / Kelvin` first):**
  - Set **White (Kelvin)** (`#tab-btn-temperature` / `#panel-temperature`) as the initial active view or integrate warmth (`#kelvin-slider`, `#kelvin-output`, `.kelvin-card` presets `2200 K`–`6500 K`) directly into the primary daily workflow so the user can toggle power, brightness, and warmth immediately upon opening the app.
  - Keep `#quick-save-preset-btn` accessible without crowding the power button.

### 3.3. Quiet Bottom / Segmented Mode Dock & Progressive Disclosure
- Restyle `.mode-tabs` as a quiet, compact segmented dock for switching between:
  1. **White / Warmth (`temperature`)** — Default active tab
  2. **Color (`rgb`)** — With `#color-wheel-canvas` as the focal element and raw numeric inputs (`#input-r`, `#input-g`, `#input-b`, `#input-hex`, `#apply-rgb-btn`) tucked into a clean secondary collapsible/popover group alongside `#swatch-grid`
  3. **Scenes (`scene`)** — 36 WiZ scenes with category pills and speed slider
  4. **Presets (`custom`)** — Saved user presets
  5. **Ambilight (`ambilight`)** — Screen sync controls
  6. **Music (`music`)** — WASAPI audio sync controls
- **Live Background Stream / Timer Status Pill:** Keep `#tab-ambilight-dot`, `#tab-music-dot`, and the collapsible `#sleep-timer-details` bar clean and unobtrusive at the bottom of the stage, surfacing a clear active indicator whenever Ambilight, Music Sync, or Sleep Timer is running.

### 3.4. Compact Desktop Window Geometry (`src/gestor_luces/main.py`)
- Update the initial window sizing in `src/gestor_luces/main.py` so the app launches as a focused, well-proportioned desktop controller (e.g., default width `~520–620px`, height `~720–800px`, minimum size `~460x600`) instead of `WINDOW_SCREEN_RATIO = 0.9` (`1440x920`), while remaining responsive if the user resizes or maximizes the window.

---

## 4. Parallel Branch / Worktree & Subagent Strategy

Create two isolated Git branches and worktrees from `main` so both designs can be launched, tested, and compared side by side:

1. **Branch A:** `ui/atmospheric-dark` (Worktree path: `../gestor-luces-atmospheric-dark` or `.worktrees/atmospheric-dark`)
2. **Branch B:** `ui/architectural-stone` (Worktree path: `../gestor-luces-architectural-stone` or `.worktrees/architectural-stone`)

### Dedicated Subagents Available in `.agents/agents/`
- **`ui-craft-specialist`** (`.agents/agents/ui-craft-specialist.md`): Write-enabled UI specialist pre-configured with `stageshow` rules, `modern-web-guidance`, CSP constraints, and DOM/i18n test contracts. Invoke one instance per worktree to build each variant cleanly.
- **`hexagonal-auditor`** (`.agents/agents/hexagonal-auditor.md`): Read-only architecture and test auditor. Invoke after implementation to verify hexagonal boundaries and run `.venv\Scripts\pytest.exe -q`.

---

## 5. Aesthetic Specifications per Branch

### 5.1. Branch A: `ui/atmospheric-dark` (Option 2 — *Atmospheric Glass & Light*)
*Visual direction inspired by `stageshow/examples/dark-hero`, Apple Home, and atmospheric light projection.*

- **Palette & Surfaces:**
  - Deep matte carbon canvas (`#08090C`) when fixtures are off (`data-power="off"`).
  - Elevated translucent glass surfaces (`rgba(22, 25, 32, 0.72)` with `backdrop-filter: blur(24px)`) and subtle top-edge specular border (`1px solid rgba(255, 255, 255, 0.08)`).
- **Atmospheric Photometric Halo:**
  - When `data-power="on"`, project a wide, soft radial ambient glow behind the stage header/hero using `color-mix(in oklab, var(--beam-color) 35%, transparent)` so the real Kelvin warmth (`2200 K` amber to `6500 K` cool white) or RGB color bathes the background organically without harsh colored borders.
- **Controls:**
  - Pill-shaped tactile slider tracks (`height: 36px–44px`, `border-radius: 14px`) filled with a smooth luminance gradient driven by `--beam-color`.
  - Sculptural, glowing power orb/button that responds smoothly to hover, press, and active light emission.

### 5.2. Branch B: `ui/architectural-stone` (Option 3 — *Minimal Precision / Braun & Lutron*)
*Visual direction inspired by `stageshow/examples/looks/skeuomorphic.tsx`, Dieter Rams (Braun), and Lutron Palladiom architectural keypads.*

- **Palette & Surfaces:**
  - Warm architectural limestone/mineral paper chassis (`#F4F1EA` / `#EFECE6`), recessed control wells (`#E5E0D8` with subtle inner shadow), and crisp matte-white physical keys/cards (`#FFFFFF` with `0 1px 2px rgba(20, 18, 15, 0.08), 0 0 0 1px rgba(20, 18, 15, 0.06)`).
  - High-contrast ink typography (`#181715` primary, `#6E6A63` secondary).
  - Optional subtle theme toggle (Daylight Stone vs. Evening Graphite) if desired, defaulting to Warm Architectural Stone.
- **Physical Light Representation on Light Surfaces:**
  - Instead of a full-screen background wash, represent `--beam-color` through a **recessed optical aperture/ring** and warm backlit slider tracks that glow with physical depth against the matte stone surface.
- **Controls:**
  - Precision hardware key proportions (`border-radius: 8px`), crisp mechanical press states (`transform: translateY(1px)`), and clean engraved-style scale markings on the Kelvin and Dimming tracks.

---

## 6. Non-Negotiable Technical & Test Contracts (Zero-Loss Checklist)

To ensure zero regressions across `ui/app.js`, `ui/i18n.js`, `WebviewBridge`, and the `pytest` suite (`tests/test_i18n.py`, `tests/test_app_shell.py`, `tests/test_security_hardening.py`, `tests/test_ui_bridge.py`), both branches **MUST** preserve:

1. **Content Security Policy (CSP):**
   Keep the strict `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' file:; style-src 'self' file:; img-src 'self' file: data:; font-src 'self' file:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">` in `ui/index.html`. No external CDN fonts or inline `<script>`/`style=""` violations (note: existing `style="--swatch-rgb: ..."` / `style="--pos: ..."` attributes in `index.html` or JS custom properties should be checked against CSP if modified).
2. **Mandatory DOM IDs & Hooks Referenced by `ui/app.js` and `tests/test_i18n.py`:**
   - Shell & Toast: `#toast-region`, `#console-shell` (with `data-power`)
   - Language & Drawer/Rail: `#lang-btn-en`, `#lang-btn-es`, `#scan-network-btn`, `#scan-btn-label`, `#open-add-dialog-btn`, `#select-all-fixtures`, `#fixture-count-badge`, `#fixture-list`, `#sync-now-btn`, `#auto-sync-toggle`, `#shortcuts-help-btn`, `#status-banner`
   - Stage Header & Master Power: `#photometric-aperture`, `#target-summary`, `#live-state-pill`, `#telemetry-meta`, `#quick-save-preset-btn`, `#master-power-btn`, `#master-power-label`
   - Dimming: `#brightness-slider`, `#brightness-output`, `.brightness-preset[data-brightness]`
   - Mode Tabs & Panels: `#tab-btn-rgb` (`#panel-rgb`), `#tab-btn-temperature` (`#panel-temperature`), `#tab-btn-scene` (`#panel-scene`), `#tab-btn-custom` (`#panel-custom`, `#custom-tab-label`), `#tab-btn-ambilight` (`#panel-ambilight`, `#tab-ambilight-dot`), `#tab-music` (`#panel-music`, `#tab-music-dot`), `.mode-tab[data-mode]`
   - RGB Controls: `#color-wheel-canvas`, `#wheel-reticle`, `#input-r`, `#input-g`, `#input-b`, `#input-hex`, `#apply-rgb-btn`, `#swatch-grid`, `.color-swatch`
   - Kelvin Controls: `#kelvin-slider`, `#kelvin-output`, `.kelvin-card[data-kelvin]`
   - Scenes & Custom Presets: `#scene-category-bar`, `#scene-filter-favorites`, `#scene-cat-favorites-label`, `.scene-filter[data-category]`, `#scene-speed-container`, `#scene-speed-slider`, `#scene-speed-output`, `#scenes-grid`, `#open-save-scene-dialog-btn`, `#custom-scenes-grid`
   - Ambilight Controls: `#ambilight-status-badge`, `#ambilight-frames-readout`, `#ambilight-preview-swatch`, `#ambilight-color-readout`, `#toggle-ambilight-btn`, `#toggle-ambilight-label`, `#ambilight-monitor-select`, `.ambilight-mode-btn[data-color-mode]`, `#ambilight-smoothing-slider`, `#ambilight-smoothing-output`, `#ambilight-auto-brightness`, `#ambilight-min-brightness-row`, `#ambilight-min-brightness-slider`, `#ambilight-min-brightness-output`
   - Music Sync Controls: `#music-status-badge`, `#music-frames-readout`, `#music-preview-swatch`, `#music-color-readout`, `#music-meter-bass-val`, `#music-meter-bass-fill`, `#music-meter-mid-val`, `#music-meter-mid-fill`, `#music-meter-treble-val`, `#music-meter-treble-fill`, `#music-meter-rms-val`, `#music-meter-rms-fill`, `#toggle-music-btn`, `#toggle-music-label`, `#music-device-select`, `.music-palette-btn[data-palette-mode]`, `#music-sensitivity-slider`, `#music-sensitivity-output`, `#music-smoothing-slider`, `#music-smoothing-output`, `#music-audio-brightness`
   - Sleep Timer: `#sleep-timer-details`, `#sleep-timer-badge`, `.sleep-preset-btn[data-minutes]`, `#sleep-minutes-input`, `#start-sleep-timer-btn`, `#cancel-sleep-timer-btn`
   - Modals (`<dialog>`): `#add-bulb-dialog` (`#add-bulb-form`, `#manual-ip-input`, `#manual-name-input`, `#submit-add-bulb-btn`), `#rename-bulb-dialog` (`#rename-bulb-form`, `#rename-bulb-ip-display`, `#rename-bulb-ip-input`, `#rename-bulb-name-input`), `#shortcuts-dialog`, `#custom-scene-dialog` (`#custom-scene-form`, `#custom-scene-dialog-title`, `#custom-scene-dialog-subtitle`, `#custom-scene-id-input`, `#custom-scene-name-input`, `#custom-scene-overwrite-row`, `#custom-scene-overwrite-checkbox`, `#custom-scene-submit-btn`)
3. **Bilingual i18n Integrity (`tests/test_i18n.py`):**
   - Preserve `<script src="i18n.js"></script>` and `<script src="app.js"></script>`.
   - Preserve all existing keys in `ui/i18n.js` asserted by `test_ui_i18n_assets_and_builtin_scene_names_preserved` (any new UI strings must be added to both `en` and `es` dictionaries without deleting tested keys).
4. **Verification Gate:**
   - Run `pytest` in each worktree to verify 100% test pass rate before concluding.

---

## 7. Implementation Status & Multi-Theme Unification on `main`

The dual-worktree UI redesign exploration has been completed and **unified into `main`** as a single runtime multi-theme architecture:

1. **Unified Multi-Theme Token Architecture (`ui/themes.css` + `ui/styles.css`):**
   - Consolidates the single-column compact controller layout, slide-over fixture drawer (`aside#fixture-drawer`), Kelvin-first default active tab (`#tab-btn-temperature` / `#panel-temperature`), and strict Content Security Policy (CSP) compliance without inline `style=""` attributes.
   - Implements a 3-tier CSS design token system in `ui/themes.css` supporting instant runtime switching between **Architectural Stone** (`architectural-stone`, default Light theme) and **Atmospheric Dark** (`atmospheric-dark`, selectable Dark theme).
   - Theme selection is validated in the domain layer (`SUPPORTED_THEMES`, `DEFAULT_THEME = "architectural-stone"`), persisted in `settings.json` (`SettingsRepository.get_theme` / `set_theme`), exposed in the top bar (`#theme-btn-stone` / `#theme-btn-dark`), and synchronized with the Windows DWM titlebar (`DwmSetWindowAttribute` 20) and WebView2 background color (`THEME_WINDOW_CHROME`).
2. **Window Geometry & Dynamic Widget Auto-Fit:**
   - Configured with `WINDOW_DEFAULT_SIZE = (620, 760)` and `WINDOW_MIN_SIZE = (480, 640)`, calibrated for zero vertical scroll across all 6 mode tabs.
   - Includes dynamic content-driven height auto-fit (`resize_window_to_content` in `WebviewBridge` and `_fit_native_window_height` in `main.py`), using the White (Kelvin) tab with collapsibles closed as the baseline window height.
3. **Package Entrypoint, Multi-Instance Diagnostics & Automated Test Suite:**
   - Added package entrypoint `src/gestor_luces/__main__.py` (`python -m gestor_luces`) alongside `python -m gestor_luces.main`.
   - Added the `--multi-instance` CLI flag to bypass the single-instance mutex when running side-by-side diagnostic comparisons.
   - Verified by **99 automated tests** across domain invariants, persistence, UI bridge theme/language contracts, window geometry, dynamic height fitting, and security hardening.

