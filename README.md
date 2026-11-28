# Gestor de Luces

[English](README.md) | [Español](README.es.md)

[![CI](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/AlexisAcevedo/wiz-architectural-lighting-console/badges/coverage.json)](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/blob/main/.github/workflows/coverage-badge.yml)

Desktop control center for Philips WiZ smart lighting systems over local area networks (LAN). Engineered with Python, Hexagonal Architecture (Ports and Adapters), and Microsoft WebView2 (PyWebView), operating exclusively through local UDP packets without cloud dependencies, external bridges, or internet access requirements.

---

## Architectural Highlights

- Zero Cloud Dependency: Direct local communication with WiZ bulbs over UDP port 38899.
- Hexagonal Architecture: Domain, ports, and application layers never import adapters (verified by `test_inner_hexagonal_layers_never_import_adapters`).
- Multi-Threaded Concurrency: Independent event loop for asynchronous network I/O, isolated background streaming threads, and non-blocking desktop tray integration.
- Hardware Rate Limiting: Leaky-bucket pacing enforced at 10 Hz (100 ms) to avoid saturating bulb ESP microcontrollers during continuous streaming.
- Fully Offline Testable: Automated test suite runs fully offline against an in-memory UDP simulator fixture reproducing WiZ JSON RPC behavior.

---

## Key Features

1. Complete Photometric Control:
   - Real-time power toggle, dimming curve adjustment (10% to 100%), and status polling.
   - Correlated Color Temperature (CCT) tuning from 2,200K (Warm Incandescent) to 6,500K (Cool Daylight).
   - RGB color selection with live palette preview and hexadecimal input.

2. Firmware Scene Catalog & Custom Presets:
   - Full catalog of all 36 native WiZ firmware scenes with dynamic speed regulation (10% to 200%).
   - User-defined custom presets saved to local storage with one-click recall, editing, and deletion protected by a 5-second **Undo** toast in top-layer (`popover="manual"`).

3. Ambient Screen Sync (Ambilight):
   - Real-time display screen sampling using pure-Python Win32 GDI screen capture (`mss`).
   - Multiple sampling algorithms: screen average color, dominant edge color, or high-luminance centroid.
   - Continuous 10 Hz fire-and-forget UDP streaming with Exponential Moving Average (EMA) color smoothing.

4. WASAPI Loopback Reactive Music Sync:
   - Real-time system audio capture via Windows Audio Session API (WASAPI) loopback (`PyAudioWPatch`).
   - Fast Fourier Transform (FFT) spectral decomposition into Bass, Mid, and Treble energy bands using `numpy`.
   - Frequency-to-color mapping with configurable gain sensitivity and smoothing decay.

5. System Tray & Background Residency:
   - Runs silently in the Windows Notification Area through a native WinForms `NotifyIcon`
     menu painted with the active theme (with a `pystray` fallback when WinForms cannot load).
   - Unified menu actions (`Show window` / `Hide window`, `Favorite presets`, `Exit`), master power toggle, and graceful minimize-to-tray on window close or minimize with a one-time notice (`tray_hint_seen` persisted in `settings.json`).
   - The on/off item acts on the bulb's real state: it re-reads the target bulbs before flipping, and the label, tooltip and icon colour are refreshed from the bulbs on every poll, so a light switched from the wall or the phone app does not invert the next click.
   - Hiding to the tray leaves nothing behind in alt+tab (the tray message-pump window is a tool window) and exiting from the menu shuts down cleanly.
   - Deadlock-free WinForms and PyWebView synchronization.

6. Progressive Sleep Timer:
   - Configurable countdown timer (1 to 240 minutes) with progressive brightness dimming down to zero before powering off.

7. Bilingual & Multi-Theme Desktop Console:
   - Native bilingual interface in English (`en`) and Spanish (`es`) with dynamic instant switching across UI, localized native window title, System Tray, and window menu bar, plus zero-flash startup for both theme and language (`#theme=<theme>&lang=<lang>`).
   - Runtime theme switching between **Architectural Stone** (default Light theme inspired by Braun/Lutron hardware keypads) and **Atmospheric Dark** (frosted glass and dynamic `oklab` photometric halo), persisted in `settings.json` with automatic Windows DWM titlebar and WinForms `MenuStrip` palette synchronization.

8. Windows Desktop Integration:
   - Compact widget geometry (opens at `620x760`, then resizes to the content of the active section) and custom light-bulb icon for the window, taskbar, tray and executable. The app also carries its own taskbar identity (`AppUserModelID`), so the button shows that icon and pins as an application instead of as the Python interpreter, even when it runs from source.
   - Theme-aware native menu bar: **File** (Show/Hide window, Start with Windows, Exit) and **Help** (Keyboard shortcuts, About), painted to match Light/Dark mode. About reports the localized display name, the version, the licence (MIT), the author and the repository.
   - Accessible keyboard ergonomics: `Space` for power, `Alt+Up/Down` for brightness (leaving bare arrow keys free for scrolling), `1`–`6` and `Home`/`End` across mode tabs, and `?` shortcuts help from the top bar.
   - Optional "Start with Windows" toggle (File menu) that registers the app under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`WizConsole`, automatically migrating legacy `GestorDeLuces` entries) and launches it minimized to the tray.
   - Single-instance guard: launching a second copy brings the running window to the front instead of opening another one (with `--multi-instance` override for side-by-side diagnostics).
   - Distributed as a per-user installer or a portable ZIP (see [Packaging & Distribution](#packaging--distribution)).

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Desktop UI (WebView2 / HTML5)   |
                      |       System Tray (WinForms NotifyIcon)|
                      |       CLI Diagnostic Utility          |
                      +-------------------+-------------------+
                                          |
                              (Primary / Driving Ports)
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| APPLICATION LAYER                                                                 |
|   LightControlService  - Orchestrates use cases and multi-bulb targeting          |
|   StreamRateLimiter    - Enforces 10 Hz pacing for continuous UDP streams         |
|   AmbilightStream      - Manages 10 Hz screen capture and color smoothing         |
|   MusicSyncStream      - Coordinates WASAPI loopback FFT and frequency mapping     |
|   SleepTimerManager    - Drives progressive brightness fade countdowns            |
+-----------------------------------------+-----------------------------------------+
                                          |
                              (Secondary / Driven Ports)
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| DOMAIN LAYER                                                                      |
|   Entities: Bulb, LightState, CustomScene, BuiltInScene                           |
|   Value Objects: Color, Brightness, ColorTemperature, LightMode, SceneSpeed       |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| ADAPTERS & INFRASTRUCTURE                                                         |
|   WizUdpController   - Socket communication over UDP 38899 via pywizlight         |
|   JsonRepositories   - Persistence in %LOCALAPPDATA%/WizConsole                    |
|   MssScreenSampler   - Windows desktop frame grabber                              |
|   WasapiAudioSampler - Windows WASAPI loopback audio stream sampler               |
+-----------------------------------------------------------------------------------+
```

Detailed technical breakdown, concurrency models, and thread lifecycle documentation are available in [docs/architecture.md](docs/architecture.md).

---

## Technology Stack

| Layer | Component | Version | Description |
|---|---|---|---|
| Runtime | Python | >= 3.12 (tested on 3.14) | Base language platform |
| Networking | `pywizlight` | 0.6.6 | Local UDP 38899 socket transport |
| Desktop Container | `pywebview` | 6.2.1 | Native window wrapping Microsoft Edge WebView2 |
| System Tray | `Pillow` / `pystray` | 13.0.0 / 0.19.5 | `Pillow` renders the bulb icon; the tray menu is a WinForms `NotifyIcon`, with `pystray` as the fallback view |
| Screen Capture | `mss` | 10.2.0 | High-performance Win32 GDI screen buffer grabber |
| Audio Capture | `PyAudioWPatch` | 0.2.12.9 | WASAPI loopback system output capture |
| DSP / FFT | `numpy` | 2.5.4 | Real-time Discrete Fourier Transform and spectral analysis |
| Testing | `pytest` / `pytest-asyncio` | 9.0.3 / 1.3.0 | Unit and integration test harness |

---

## Project Structure

```
.
├── .gitignore
├── assets/
│   └── icon/                    # make_icon.py plus generated app.ico / app.png
├── packaging/
│   ├── gestor_luces.spec        # PyInstaller one-folder build definition
│   └── installer.iss            # Inno Setup per-user installer script
├── scripts/
│   └── build.ps1                # Icon + PyInstaller + portable ZIP + installer
├── pyproject.toml               # Dependencies, project metadata, and pytest configuration
├── README.md                    # Primary English documentation
├── README.es.md                 # Spanish translation of project documentation
├── docs/
│   ├── architecture.md          # Architectural deep-dive and concurrency design (EN)
│   ├── architecture.es.md       # Architectural deep-dive and concurrency design (ES)
│   ├── wiz_protocol.md          # WiZ UDP protocol specifications and RPC schema (EN)
│   ├── wiz_protocol.es.md       # WiZ UDP protocol specifications and RPC schema (ES)
│   └── design/
│       ├── ui_redesign_spec.md     # UI redesign specification (EN)
│       └── ui_redesign_spec.es.md  # UI redesign specification (ES)
├── src/
│   └── gestor_luces/
│       ├── __init__.py
│       ├── __main__.py              # Package entrypoint (python -m gestor_luces)
│       ├── main.py              # Composition root and application entrypoint
│       ├── cli.py               # Low-level network probe and CLI diagnostics
│       ├── resources.py         # Asset/version resolution (dev and PyInstaller-frozen)
│       ├── desktop/             # Desktop shell lifecycle & window orchestration
│       │   └── app.py           # DesktopApplication, menu sync & window events
│       ├── domain/              # Pure domain logic and entities
│       │   ├── models.py        # Bulb and LightState entities
│       │   ├── scenes.py        # Built-in WiZ catalog and custom scene models
│       │   └── value_objects.py # Color, Brightness, Kelvin, endpoint & mode validation
│       ├── ports/               # Driven & service contracts (typing.Protocol)
│       │   ├── light_control.py # LightControlServicePort desktop contract
│       │   ├── repositories.py  # Controller, Repository, and Sampler protocols
│       │   └── autostart.py     # AutostartManager protocol
│       ├── application/         # Use cases, focused services, and streaming managers
│       │   ├── service.py       # Facade orchestrating application workflows
│       │   ├── service_context.py # Shared state, repositories, and resource teardown
│       │   ├── bulb_control_service.py    # Power, color, CCT, and brightness commands
│       │   ├── bulb_inventory_service.py  # Discovery, probing, and alias management
│       │   ├── scene_service.py           # Native and custom scene execution
│       │   ├── timer_service.py           # Sleep timer coordination
│       │   ├── ambilight_service.py       # Screen-sync configuration & lifecycle
│       │   ├── music_service.py           # Music-sync configuration & lifecycle
│       │   ├── settings_service.py        # Language and theme preferences
│       │   ├── rate_limiter.py  # 10 Hz UDP rate limiter and EMA smoothing
│       │   ├── sleep_timer.py   # Progressive fade-out timer
│       │   ├── ambilight_stream.py # Screen sampling stream manager
│       │   └── music_stream.py  # WASAPI audio reactive stream manager
│       └── adapters/            # Infrastructure implementations
│           ├── wiz/             # pywizlight UDP socket controller
│           ├── storage/         # %LOCALAPPDATA% atomic JSON file repositories
│           ├── ambilight/       # MSS screen sampler
│           ├── audio/           # WASAPI loopback audio sampler & FFT analysis
│           ├── platform/windows/# Win32 DWM chrome, multi-monitor geometry & menu helpers
│           ├── tray/            # Tray controller, WinForms/Pystray views and bulb icon renderer
│           ├── system/          # Windows autostart (registry) and single-instance guard
│           └── ui_webview/      # Hardened HTTP server, exposed IPC bridge and native menu
├── tests/                       # Offline unit, integration, security, and workflow tests
│   ├── simulators/              # In-memory WiZ UDP server simulator (`FakeWizBulbServer`)
│   ├── js/                      # Frontend unit, DOM a11y, and CSS perf tests (`node --test`)
│   └── waits.py                 # Bounded condition waits shared by the suite
└── ui/                          # Web frontend served over loopback HTTP inside WebView2
    ├── index.html               # Main console markup
    ├── themes.css               # 3-tier design tokens & theme overrides
    ├── styles.css               # Tokenized compact controller layout & components
    ├── scenes.json              # Built-in WiZ scene catalog synced with backend domain
    ├── i18n.js                  # English / Spanish localization dictionaries
    └── js/                      # Modular ES frontend (`app.js`, `bridge-client.js`,
                                 # `store.js`, `scenes.js`, `stage-controls.js`,
                                 # `fixtures.js`, `ambilight.js`, `music.js`,
                                 # `shortcuts.js`, `toasts.js`, `theme-boot.js`)
```

---

## Installation & Setup

### Option A — Windows Installer or Portable ZIP (Recommended for Users)

No Python installation is required. Download the latest release from [**GitHub Releases**](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/releases/latest):

- **Installer (`GestorDeLuces-Setup-<version>.exe`)**: Per-user setup (no administrator rights needed) that creates Start Menu shortcuts, optional desktop icon, and optional "Start with Windows" registration.
- **Portable (`GestorDeLuces-portable-<version>.zip`)**: Extract anywhere and run `GestorDeLuces.exe` (keep the `_internal` folder next to the executable).

**System Requirements:**
- Windows 10 (Build 1809+) or Windows 11 (64-bit).
- Microsoft Edge WebView2 Evergreen Runtime (preinstalled on Windows 11 and up-to-date Windows 10).
- Local network (LAN) with Philips WiZ bulbs on the same subnet (UDP port 38899).

---

### Option B — Run from Source (For Developers)

#### Prerequisites

- Operating System: Windows 10 (Build 1809+) or Windows 11.
- Python: Version 3.12 or higher (Python 3.14 fully supported).
- WebView2 Runtime: Microsoft Edge WebView2 Evergreen Runtime.

#### Step-by-Step Setup

1. Clone the repository and enter its folder:
   ```bash
   git clone https://github.com/AlexisAcevedo/wiz-architectural-lighting-console.git
   cd wiz-architectural-lighting-console
   ```

2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   # In Command Prompt:
   .venv\Scripts\activate.bat
   # In PowerShell:
   .venv\Scripts\Activate.ps1
   # In Git Bash:
   source .venv/Scripts/activate
   ```

3. Install the project in editable mode with the dev tooling (tests, static audit, packaging):
   ```bash
   pip install -e ".[dev]"
   ```

   To run the app from source without the development tooling, install only the
   runtime dependencies:
   ```bash
   pip install -e .
   ```

---

## Running the Application (From Source)

### 1. Graphical User Interface (GUI) Mode

Launch the desktop management console:

```bash
python -m gestor_luces
# or:
python -m gestor_luces.main
```

Supported CLI flags for `main.py`:
- `--debug`: Enable pywebview developer tools and inspector.
- `--minimized`: Start hidden in the system tray (this is the flag registered by "Start with Windows").
- `--multi-instance`: Bypass the single-instance guard to allow running multiple instances concurrently.
- `--smoke-test`: Initialize the composition root, verify UI and icon assets without opening native GUI windows, and exit with code 0.

### 2. Low-Level Network CLI Mode

Use `gestor_luces.cli` for direct network discovery, UDP diagnostic probing, and scriptable command execution without starting the graphical container:

```bash
# Discover all bulbs on the local subnet via UDP broadcast:
python -m gestor_luces.cli discover

# Query real-time status of a specific bulb:
python -m gestor_luces.cli status --ip 192.168.100.6

# Turn a bulb on at 80% brightness:
python -m gestor_luces.cli on --ip 192.168.100.6 --brightness 80

# Set bulb color using RGB:
python -m gestor_luces.cli color --ip 192.168.100.6 255 120 0 --brightness 100

# Set Correlated Color Temperature (CCT):
python -m gestor_luces.cli kelvin --ip 192.168.100.6 2700

# Turn a bulb off:
python -m gestor_luces.cli off --ip 192.168.100.6
```

---

## Verification & Testing

The test suite validates domain invariants, JSON persistence, rate limiters, PyWebView asynchronous bridging, system tray event handling, Ambilight smoothing, and WASAPI audio signal processing.

Tests execute completely offline using an asynchronous in-memory UDP simulator (`FakeWizBulbServer`) that handles WiZ JSON-RPC protocol requests (`getPilot`, `setPilot`, `getSystemConfig`).

Execute the test suite with:

```bash
pytest
```

Workflow tests auto-detect Git Bash on Windows (skipping WSL/WindowsApps shims), so the full `pytest` suite runs cleanly from PowerShell without `--ignore` exclusions.

Coverage is gated **per package**, not as one global percentage: `domain` at least 90 %, `application` at least 75 % and `adapters` at least 55 % (`scripts/check_coverage.py`, run by CI). The percentage in the coverage badge is published by `.github/workflows/coverage-badge.yml` on every push to `main`, so it is never edited by hand. Measure it locally with `pytest --cov=gestor_luces --cov-report=term-missing` and check the gate with `python scripts/check_coverage.py coverage.json`.

All tests should pass (see the CI badge at the top of this file for the live status).

The frontend modules under `ui/js` are tested separately with Node's built-in test runner, so the JS layer adds **no npm dependency and no lockfile**:

```bash
npm test
```

This runs the `tests/js/` suites covering the frontend ES modules (`bridge-client`, `app`, `ambilight`, `music`, `fixtures`, `stage-controls`, `toasts`, `store`, `scenes`, `theme-boot`) plus regression suites for layout/toasts, UX validation/Undo, WCAG AA accessibility, i18n key parity, and zero-flash boot (`stage1-layout-toasts` through `stage5-native-boot`) under a **60 % line-coverage floor** enforced by `--test-coverage-lines`. The `js tests` job of `.github/workflows/ci.yml` runs the same command on every push and pull request.

Static security analysis (`bandit`) and dependency vulnerability audits (`pip-audit`) run as **blocking** CI gates on every push and pull request (see `.github/workflows/ci.yml`). The bandit JSON report is published as a workflow artifact.

A nightly workflow (`.github/workflows/nightly.yml`) runs the whole suite five times in a row, each pass in a fresh process, to catch flaky tests that a single green run hides. Separate processes matter: in-process repetition (`--count`) carries threads, sockets and cached state from one pass to the next, so a failure there is not reproducible under `ci.yml`. Run it locally with `for pass in 1 2 3 4 5; do pytest -x --timeout=120 || exit 1; done`.

---

## Packaging & Distribution

Build everything (icon, PyInstaller one-folder app, portable ZIP and installer) with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Use `-SkipInstaller` to build only the app folder and the portable ZIP.

| Output (in `dist/`) | Description |
|---|---|
| `GestorDeLuces\GestorDeLuces.exe` | Portable one-folder app. Keep the `_internal` folder next to the executable. |
| `GestorDeLuces-portable-<version>.zip` | The same folder zipped. Extract anywhere and run `GestorDeLuces.exe`. |
| `GestorDeLuces-Setup-<version>.exe` | Per-user installer (no administrator rights): Start Menu entry, optional desktop shortcut, uninstaller. |
| `SHA256SUMS.txt` | SHA-256 checksums for all release artifacts generated in `dist/`. |

Build requirements: the project virtual environment (`pip install -e ".[dev]"`), and [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) for the installer. If Inno Setup is missing, the script skips the installer with a warning. If `signtool.exe` is in `PATH` and `SIGN_CERT_SHA1` is set to a code-signing certificate thumbprint, `scripts/build.ps1` signs `GestorDeLuces.exe` **before** building the portable ZIP and Inno Setup installer (so both archives carry the signed executable), then signs the installer using SHA-256 and HTTPS RFC 3161 timestamping (`https://timestamp.digicert.com`).

`packaging/gestor_luces.spec` excludes helper Python scripts (such as `make_icon.py`) from packaged `assets/`. `packaging/installer.iss` launches post-install execution with `runasoriginaluser`, removes the `HKCU\...\Run` autostart key unconditionally during uninstall, and provides bilingual English/Spanish `[CustomMessages]`.

### Releasing

Releases are built and published by CI; the commands above are for local builds. The procedure is:

1. Bump the version in `pyproject.toml` (`chore(release): bump version to X.Y.Z`).
2. Write `docs/releases/X.Y.Z.md` with the notes for that release ([convention](docs/releases/README.md)).
3. Merge, then tag the merged commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

`.github/workflows/release.yml` pins all third-party actions by commit SHA, pins Inno Setup (`6.7.1`), and scopes `contents: write` exclusively to the `publish` job. `guard` fails in seconds when the tag disagrees with `pyproject.toml` or when the notes file is missing; `build` produces the installer and the portable ZIP on a Windows runner; `verify` runs `sha256sum -c SHA256SUMS.txt` and `GestorDeLuces.exe --smoke-test` against the exact bytes that will ship; `publish` uploads to a **draft** release, compares the digests GitHub reports with the built files, and only then makes the release public. To rehearse, run the workflow manually with `dry_run` enabled: it repeats every step except the final publication and discards the draft.

Notes for target machines:
- Windows 10/11 64-bit with the Microsoft Edge WebView2 Runtime (preinstalled on Windows 11 and most up-to-date Windows 10). The installer warns when it is missing but does not install it.
- Unless built with `SIGN_CERT_SHA1`, executables are unsigned, so Windows SmartScreen shows "Windows protected your PC": choose **More info** then **Run anyway**. Verify the download against `SHA256SUMS.txt`.
- Per-user installation writes to `%LOCALAPPDATA%\Programs\GestorDeLuces` (no administrator prompt required); if you share the Windows account or require system-wide write-protected binaries under `C:\Program Files`, run the installer with administrator privileges or pass `/ALLUSERS`.
- User data lives in `%LOCALAPPDATA%\WizConsole` (with automatic one-time migration from legacy `%LOCALAPPDATA%\GestorDeLuces`, keeping the original files as backup), never next to the executable.
- If the portable folder is moved while "Start with Windows" is enabled, the registry entry is corrected on the next launch.
- Occasionally `Compress-Archive` fails with a locked file right after PyInstaller finishes (antivirus scanning); re-run the script.

---

## Further Reading

- [Architecture & Concurrency Deep Dive](docs/architecture.md): Detailed analysis of the Hexagonal design, threading topology, and race condition prevention.
- [WiZ UDP Protocol & Streaming Specification](docs/wiz_protocol.md): Low-level documentation of JSON-RPC datagram formats, rate limiting, and scene catalogs.
- [UI Redesign Specification](docs/design/ui_redesign_spec.md): Design direction for the dual-worktree UI redesign exploration.
- [Documentación en Español](README.es.md): Versión completa de esta documentación en español.

