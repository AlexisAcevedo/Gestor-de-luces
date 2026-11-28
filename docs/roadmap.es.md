# Hoja de Ruta y Estrategia de PRs (`v0.5.0`–`v0.8.0`)

[English](roadmap.md) | [Español](roadmap.es.md)

Esta hoja de ruta define el rebrand interno hacia **WizConsole** (Set A) y los tres niveles de funcionalidades previstos para **WiZ Architectural Lighting Console**, organizados en PRs revisables (`<=400` líneas cambiadas por PR, con pruebas y documentación en cada entrega).

## Identificadores Canónicos (Set A)

| Concepto | Legacy (`v0.4.x`) | Objetivo (`v0.5.0+`) |
| --- | --- | --- |
| Nombre visible | `WiZ Architectural Lighting Console` | `WiZ Architectural Lighting Console` |
| Paquete Python (`src/`) | `gestor_luces` | `wiz_console` |
| Distribución y CLI | `gestor-luces` | `wiz-console` |
| Paquete frontend (`package.json`) | `gestor-de-luces-ui` | `wiz-console-ui` |
| Ejecutable / AppData / Clave `Run` | `GestorDeLuces` | `WizConsole` (`%LOCALAPPDATA%\WizConsole`) |
| Carpeta de datos fuera de Windows | `~/.gestor_de_luces` | `~/.wiz_console` |
| `AppUserModelID` | `AlexisAcevedo.GestorDeLuces` | `AlexisAcevedo.WizConsole` |
| Mutex / Evento Win32 | `Local\GestorDeLuces.*` | `Local\WizConsole.*` |
| `AppId` de Inno Setup | `{{6B1E2C0A-3F1B-4D7E-9A55-5C0B7D1E8F42}` | **Se preserva intacto** (actualización in-place) |

## Etapa 0 — Rebrand Interno y Migración Transparente (Prerrequisito `v0.5.0`)

**Estrategia de PRs:** PRs apilados hacia `main` (`0.0` independiente; `0.1 -> 0.2 -> 0.3` encadenados).

| PR | Rama | Unidad de trabajo | Riesgo |
| --- | --- | --- | --- |
| **0.0** | `docs/roadmap` | Hoja de ruta bilingüe (`docs/roadmap*.md`) y enlaces en `README*.md`. | `none` |
| **0.1** | `feat/rebrand-data-autostart-migration` | Migración idempotente de AppData (`GestorDeLuces` -> `WizConsole`) conservando respaldo legacy + migración de autoinicio en `HKCU\...\Run`. | Alto (ítem 1) |
| **0.2** | `feat/rebrand-windows-identity-packaging` | `AppUserModelID`, mutex/evento/hilos, `wiz_console.log`, `packaging/wiz_console.spec`, `installer.iss` (conservando `AppId` y limpiando `Run` legacy), `build.ps1`, `release.yml`. | Alto (ítems 3, 5) |
| **0.3** | `refactor/rename-package-wiz-console` | Renombrado mecánico puro `src/gestor_luces` -> `src/wiz_console`, `pyproject.toml`, `package.json`, scripts y CI (`size:exception`). | Alto (ítems 3, 5) |

## Etapa 1 — Nivel 1: Mejoras Rápidas y Base de Sesión (`v0.5.0`)

**Estrategia de PRs:** PRs apilados hacia `main` (`PR 0.3 <- 1.1`, `1.2`, `1.3`; integrados antes de `1.4`).

| PR | Rama | Alcance | Riesgo |
| --- | --- | --- | --- |
| **1.1** | `feat/bulb-delete-and-mac-reconcile` | `remove_bulb` completo (con Deshacer) + reconciliación por MAC ante cambios de IP por DHCP en `discover_bulbs`. | Alto (ítem 1) |
| **1.2** | `feat/session-persistence-and-tray-streams` | Persistir `selected_ips`, `auto_sync`, parámetros de streams y favoritos unificados; toggles de Ambilight/Música en bandeja; ajuste de piso 10% en `min_brightness`. | Alto (ítem 1) |
| **1.3** | `feat/global-windows-hotkeys` | Puerto `GlobalHotkeyManager` + adaptador Win32 `RegisterHotKey` (encendido, brillo, favoritos) + configuración en UI. | Alto (ítem 4) |
| **1.4** | `chore/release-0.5.0` | Subida de versión, notas bilingües y verificación de actualización desde datos `v0.4.3`. | Alto (ítem 5) |

## Etapa 2A — Nivel 2A: Consola Multi-Foco y Motores Reactivos (`v0.6.0`)

**Estrategia de PRs:** Cadena sobre rama de funcionalidad con PR tracker en borrador (`feat/v0.6-multi-zone-engine` -> `main`).

| PR | Rama | Alcance | Riesgo |
| --- | --- | --- | --- |
| **2A.1** | `feat/zones-and-multibulb-scenes-core` | Entidad `Zone` persistida + esquema retrocompatible de `CustomScene` por foco y migración. | Alto (ítem 1) |
| **2A.2** | `feat/zones-and-multibulb-scenes-ui` | Puente IPC e interfaz para zonas y creación de escenas multi-foco. | `none` |
| **2A.3** | `feat/ambilight-multizone` | Muestreador multizona (Izq/Der/Arr/Aba/Centro) + detección de barras negras + mapeo por foco. | Alto (ítem 4) |
| **2A.4** | `feat/music-sync-bands-and-beats` | Asignación de bandas por foco (Bajos/Medios/Agudos), detector de ritmo/onset, paletas personalizadas y cierre `v0.6.0`. | Alto (ítem 4) |
| **2A.5** *(opc.)* | `feat/ambilight-dxgi-backend` | Backend opcional DXGI/WGC para juegos en pantalla completa/HDR si los benchmarks de `2A.3` lo requieren. | Alto (ítems 4, 5) |

## Etapa 2B — Nivel 2B: Automatización y Contexto de Windows (`v0.7.0`)

**Estrategia de PRs:** PRs apilados hacia `main` (verticales independientes y opcionales).

| PR | Rama | Alcance | Riesgo |
| --- | --- | --- | --- |
| **2B.1** | `feat/circadian-and-wakeup-ramp` | Curva circadiana automática (Kelvin/brillo por horario) + rampa progresiva de despertar. | Alto (ítem 4) |
| **2B.2** | `feat/windows-session-triggers` | Escucha de `WM_WTSSESSION_CHANGE` (apagado al bloquear/suspender y restauración al desbloquear). | Alto (ítem 4) |
| **2B.3** | `feat/context-profiles-on-air` | Perfiles opcionales por aplicación en primer plano + indicador local de micrófono/cámara ("En reunión") + cierre `v0.7.0`. | Alto (ítems 2, 4) |

## Etapa 3 — Nivel 3: Fluidez, Diagnóstico y Ecosistema Abierto (`v0.8.0`)

**Estrategia de PRs:** PRs apilados hacia `main` (verticales independientes).

| PR | Rama | Alcance | Riesgo |
| --- | --- | --- | --- |
| **3.1** | `feat/crossfade-transition-engine` | Motor de transiciones suaves por software (`0.5–5s` sobre `stream_pilot`) con cancelación limpia. | Alto (ítem 4) |
| **3.2** | `feat/bulb-diagnostics-and-capabilities` | Exposición de `rssi`, `fwVersion`, `moduleName` y UI adaptada a las capacidades reales del dispositivo (RGBCCT / Blanco / Enchufe). | Alto (ítem 3) |
| **3.3** | `feat/cli-complete-and-local-api` | Subcomandos CLI (`scene`, `preset`, `brightness`, `--name`) + API HTTP/WS opcional en `127.0.0.1` con token Bearer. | Alto (ítems 2, 3) |
| **3.4** | `feat/multi-vendor-lan-foundation` | Mover validación UDP `38899` del dominio al adaptador WiZ + registro de protocolos + primer adaptador LAN secundario (WLED o Govee LAN). | Alto (ítem 3) |

## Disciplina de PRs y Calidad

- Mantener cada PR dentro de `<=400` líneas modificadas (`size:exception` solo para refactors mecánicos como el PR `0.3`).
- Incluir pruebas y documentación bilingüe en el mismo PR del comportamiento correspondiente.
- Mantener el CI en verde en cada corte: `ruff`, `pytest` con umbrales por paquete (`domain >= 90%`, `application >= 75%`, `adapters >= 55%`), `bandit`, `pip-audit` y `npm test`.
