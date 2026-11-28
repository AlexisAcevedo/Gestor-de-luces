# Product Roadmap & PR Strategy (`v0.5.0`–`v0.8.0`)

[English](roadmap.md) | [Español](roadmap.es.md)

This roadmap defines the internal rebrand to **WizConsole** (Set A) and the three feature tiers planned for **WiZ Architectural Lighting Console**, structured into reviewable PR slices (target `<=400` changed lines per PR, with tests and documentation in every slice).

## Canonical Set A Identifiers

| Concept | Legacy (`v0.4.x`) | Target (`v0.5.0+`) |
| --- | --- | --- |
| Display name | `WiZ Architectural Lighting Console` | `WiZ Architectural Lighting Console` |
| Python package (`src/`) | `gestor_luces` | `wiz_console` |
| Distribution & CLI | `gestor-luces` | `wiz-console` |
| Frontend package (`package.json`) | `gestor-de-luces-ui` | `wiz-console-ui` |
| Executable / AppData / Run value | `GestorDeLuces` | `WizConsole` (`%LOCALAPPDATA%\WizConsole`) |
| Non-Windows data dir | `~/.gestor_de_luces` | `~/.wiz_console` |
| `AppUserModelID` | `AlexisAcevedo.GestorDeLuces` | `AlexisAcevedo.WizConsole` |
| Win32 Mutex / Event | `Local\GestorDeLuces.*` | `Local\WizConsole.*` |
| Inno Setup `AppId` | `{{6B1E2C0A-3F1B-4D7E-9A55-5C0B7D1E8F42}` | **Preserved unchanged** (in-place upgrades) |

## Stage 0 — Internal Rebrand & Transparent Migration (Prerequisite for `v0.5.0`)

**PR strategy:** Stacked PRs targeting `main` (`0.0` independent; `0.1 -> 0.2 -> 0.3` stacked).

| PR | Branch | Work Unit | Risk |
| --- | --- | --- | --- |
| **0.0** | `docs/roadmap` | Bilingual roadmap (`docs/roadmap*.md`) and `README*.md` index links. | `none` |
| **0.1** | `feat/rebrand-data-autostart-migration` | Idempotent AppData migration (`GestorDeLuces` -> `WizConsole`) preserving legacy backups + HKCU `Run` autostart migration. | High (item 1) |
| **0.2** | `feat/rebrand-windows-identity-packaging` | `AppUserModelID`, mutex/event/threads, `wiz_console.log`, `packaging/wiz_console.spec`, `installer.iss` (keeping `AppId` + cleaning legacy `Run`), `build.ps1`, `release.yml`. | High (items 3, 5) |
| **0.3** | `refactor/rename-package-wiz-console` | Pure mechanical rename `src/gestor_luces` -> `src/wiz_console`, `pyproject.toml`, `package.json`, scripts, and CI (`size:exception`). | High (items 3, 5) |

## Stage 1 — Level 1: Quick Wins & Session Foundation (`v0.5.0`)

**PR strategy:** Stacked PRs to `main` (`PR 0.3 <- 1.1`, `1.2`, `1.3`; all merged before `1.4`).

| PR | Branch | Scope | Risk |
| --- | --- | --- | --- |
| **1.1** | `feat/bulb-delete-and-mac-reconcile` | End-to-end `remove_bulb` (with Undo) + MAC-based DHCP IP reconciliation in `discover_bulbs`. | High (item 1) |
| **1.2** | `feat/session-persistence-and-tray-streams` | Persist `selected_ips`, `auto_sync`, stream params, and unified favorites; add tray toggles for Ambilight/Music; fix `min_brightness` 10% drift. | High (item 1) |
| **1.3** | `feat/global-windows-hotkeys` | `GlobalHotkeyManager` port + Win32 `RegisterHotKey` adapter (power, brightness, favorites) + UI config. | High (item 4) |
| **1.4** | `chore/release-0.5.0` | Version bump, bilingual release notes, and simulated `v0.4.3` upgrade check. | High (item 5) |

## Stage 2A — Level 2A: Multi-Bulb Console & Reactive Engines (`v0.6.0`)

**PR strategy:** Feature Branch Chain with draft tracker PR (`feat/v0.6-multi-zone-engine` -> `main`).

| PR | Branch | Scope | Risk |
| --- | --- | --- | --- |
| **2A.1** | `feat/zones-and-multibulb-scenes-core` | Persisted `Zone` entity + backward-compatible per-bulb `CustomScene` schema and migration. | High (item 1) |
| **2A.2** | `feat/zones-and-multibulb-scenes-ui` | IPC bridge and UI for zones and multi-bulb scene authoring. | `none` |
| **2A.3** | `feat/ambilight-multizone` | Multi-region screen sampler (L/R/T/B/Center) + letterbox detection + per-bulb mapping. | High (item 4) |
| **2A.4** | `feat/music-sync-bands-and-beats` | Per-bulb frequency band assignment (Bass/Mid/Treble), beat/onset detector, custom palettes, `v0.6.0` prep. | High (item 4) |
| **2A.5** *(opt.)* | `feat/ambilight-dxgi-backend` | Optional DXGI/WGC capture backend for HDR/fullscreen games if `2A.3` benchmarks require it. | High (items 4, 5) |

## Stage 2B — Level 2B: Windows Context & Circadian Automation (`v0.7.0`)

**PR strategy:** Stacked PRs to `main` (independent, opt-in verticals).

| PR | Branch | Scope | Risk |
| --- | --- | --- | --- |
| **2B.1** | `feat/circadian-and-wakeup-ramp` | Time-of-day Kelvin/brightness circadian curve + sunrise wake-up ramp. | High (item 4) |
| **2B.2** | `feat/windows-session-triggers` | `WM_WTSSESSION_CHANGE` listener (auto-off on lock/sleep, restore on unlock). | High (item 4) |
| **2B.3** | `feat/context-profiles-on-air` | Opt-in foreground process profiles + local mic/camera "On-Air" indicator + `v0.7.0` prep. | High (items 2, 4) |

## Stage 3 — Level 3: Fluidity, Diagnostics & Open Ecosystem (`v0.8.0`)

**PR strategy:** Stacked PRs to `main` (independent verticals).

| PR | Branch | Scope | Risk |
| --- | --- | --- | --- |
| **3.1** | `feat/crossfade-transition-engine` | Configurable software crossfade engine (`0.5–5s` over `stream_pilot`) with clean preemption. | High (item 4) |
| **3.2** | `feat/bulb-diagnostics-and-capabilities` | Surface `rssi`, `fwVersion`, `moduleName` and adapt UI to device capabilities (RGBCCT / White / Plug). | High (item 3) |
| **3.3** | `feat/cli-complete-and-local-api` | Full CLI subcommands (`scene`, `preset`, `brightness`, `--name`) + opt-in loopback `127.0.0.1` HTTP/WS API with Bearer token. | High (items 2, 3) |
| **3.4** | `feat/multi-vendor-lan-foundation` | Move UDP `38899` validation from domain to WiZ adapter + protocol registry + first secondary LAN adapter (WLED or Govee LAN). | High (item 3) |

## PR & Quality Discipline

- Keep every PR within `<=400` authored changed lines (`size:exception` only for mechanical refactors like PR `0.3`).
- Ship tests and bilingual docs inside the same PR as the behavior they cover.
- Maintain green CI on every slice: `ruff`, `pytest` with per-package coverage floors (`domain >= 90%`, `application >= 75%`, `adapters >= 55%`), `bandit`, `pip-audit`, and `npm test`.
