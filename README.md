# Gestor de Luces

[English](README.md) | [Español](README.es.md)

Desktop control center for Philips WiZ smart lighting systems over local area networks (LAN). Engineered with Python, Hexagonal Architecture (Ports and Adapters), and Microsoft WebView2 (PyWebView), operating exclusively through local UDP packets without cloud dependencies, external bridges, or internet access requirements.

---

## Architectural Highlights

- Zero Cloud Dependency: Direct local communication with WiZ bulbs over UDP port 38899.
- Hexagonal Architecture: Complete decoupling of domain logic, state management, UI, hardware streaming, and storage persistence.
- Multi-Threaded Concurrency: Independent event loop for asynchronous network I/O, isolated background streaming threads, and non-blocking desktop tray integration.
- Hardware Rate Limiting: Leaky-bucket pacing enforced at 10 Hz (100 ms) to avoid saturating bulb ESP microcontrollers during continuous streaming.
- Fully Offline Testable: Suite of 73 automated tests with an in-memory UDP simulator fixture reproducing WiZ JSON RPC behavior.

---

## Key Features

1. Complete Photometric Control:
   - Real-time power toggle, dimming curve adjustment (10% to 100%), and status polling.
   - Correlated Color Temperature (CCT) tuning from 2,200K (Warm Incandescent) to 6,500K (Cool Daylight).
   - RGB color selection with live palette preview and hexadecimal input.

2. Firmware Scene Catalog & Custom Presets:
   - Full catalog of all 36 native WiZ firmware scenes with dynamic speed regulation (20% to 200%).
   - User-defined custom lighting presets saved to local storage with one-click recall and deletion.

3. Ambient Screen Sync (Ambilight):
   - Real-time display screen sampling using pure-Python Win32 GDI screen capture (`mss`).
   - Multiple sampling algorithms: screen average color, dominant edge color, or high-luminance centroid.
   - Continuous 10 Hz fire-and-forget UDP streaming with Exponential Moving Average (EMA) color smoothing.

4. WASAPI Loopback Reactive Music Sync:
   - Real-time system audio capture via Windows Audio Session API (WASAPI) loopback (`PyAudioWPatch`).
   - Fast Fourier Transform (FFT) spectral decomposition into Bass, Mid, and Treble energy bands using `numpy`.
   - Frequency-to-color mapping with configurable gain sensitivity and smoothing decay.

5. System Tray & Background Residency:
   - Runs silently in the Windows Notification Area via `pystray`.
   - Quick presets menu, master power toggle, and graceful minimize-to-tray on window close.
   - Deadlock-free WinForms and PyWebView synchronization.

6. Progressive Sleep Timer:
   - Configurable countdown timer (1 to 120 minutes) with progressive brightness dimming down to zero before powering off.

7. Bilingual Desktop Console:
   - Native bilingual interface in English (`en`) and Spanish (`es`) with dynamic instant switching across UI, System Tray and the window menu bar.

8. Windows Desktop Integration:
   - Custom light-bulb icon for the window, taskbar, tray and executable.
   - Native menu bar: **File** (Show/Hide window, Start with Windows, Exit) and **Help** (Keyboard shortcuts, About).
   - Optional "Start with Windows" toggle (File menu) that registers the app under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` and launches it minimized to the tray.
   - Single-instance guard: launching a second copy brings the running window to the front instead of opening another one.
   - Distributed as a per-user installer or a portable ZIP (see [Packaging & Distribution](#packaging--distribution)).

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Desktop UI (WebView2 / HTML5)   |
                      |       System Tray (pystray / Win32)   |
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
|   JsonRepositories   - Persistence in %LOCALAPPDATA%/GestorDeLuces                |
|   MssScreenSampler   - Windows desktop frame grabber                              |
|   WasapiAudioSampler - Windows WASAPI loopback audio stream sampler               |
+-----------------------------------------------------------------------------------+
```

Detailed technical breakdown, concurrency models, and thread lifecycle documentation are available in [docs/architecture.md](docs/architecture.md).

---

## Technology Stack

| Layer | Component | Version | Description |
|---|---|---|---|
| Runtime | Python | >= 3.11 (tested on 3.14) | Base language platform |
| Networking | `pywizlight` | 0.6.6 | Local UDP 38899 socket transport |
| Desktop Container | `pywebview` | 6.2.1 | Native window wrapping Microsoft Edge WebView2 |
| System Tray | `pystray` / `Pillow` | 0.19.5 / 13.0.0 | Windows system notification area icon and menu |
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
├── pyproject.toml               # Project metadata and pytest configuration
├── requirements.txt             # Locked production and testing dependencies
├── requirements-dev.txt         # Dev, static security audit, and build dependencies
├── README.md                    # Primary English documentation
├── README.es.md                 # Spanish translation of project documentation
├── docs/
│   ├── architecture.md          # Architectural deep-dive and concurrency design (EN)
│   ├── architecture.es.md       # Architectural deep-dive and concurrency design (ES)
│   ├── wiz_protocol.md          # WiZ UDP protocol specifications and RPC schema (EN)
│   └── wiz_protocol.es.md       # WiZ UDP protocol specifications and RPC schema (ES)
├── src/
│   └── gestor_luces/
│       ├── __init__.py
│       ├── main.py              # Composition root and application entrypoint
│       ├── cli.py               # Low-level network probe and CLI diagnostics
│       ├── resources.py         # Asset/version resolution (dev and PyInstaller-frozen)
│       ├── domain/              # Pure domain logic and entities
│       │   ├── models.py        # Bulb, LightState, and Group entities
│       │   ├── scenes.py        # Built-in WiZ catalog and custom scene models
│       │   └── value_objects.py # Color, Brightness, Kelvin, LightMode validation
│       ├── ports/               # Driven contracts (typing.Protocol interfaces)
│       │   ├── interfaces.py    # Public interface exports
│       │   ├── repositories.py  # Controller, Repository, and Sampler protocols
│       │   └── autostart.py     # AutostartManager protocol
│       ├── application/         # Use cases and streaming managers
│       │   ├── service.py       # Core orchestration service
│       │   ├── rate_limiter.py  # 10 Hz UDP rate limiter
│       │   ├── sleep_timer.py   # Progressive fade-out timer
│       │   ├── ambilight_stream.py # Screen sampling stream manager
│       │   └── music_stream.py  # WASAPI audio reactive stream manager
│       └── adapters/            # Infrastructure implementations
│           ├── wiz/             # pywizlight UDP socket controller
│           ├── storage/         # %LOCALAPPDATA% JSON file repositories
│           ├── ambilight/       # MSS screen sampler
│           ├── audio/           # WASAPI loopback audio sampler
│           ├── tray/            # Pystray tray controller and shared bulb icon renderer
│           ├── system/          # Windows autostart (registry) and single-instance guard
│           └── ui_webview/      # Thread-safe JS-Python bridge and native menu model
├── tests/                       # Automated test suite (73 tests)
│   ├── simulators/              # In-memory WiZ UDP server simulator
│   ├── test_domain.py           # Domain validation tests
│   ├── test_rate_limiter.py     # Pacing and interval tests
│   ├── test_persistence_and_scenes.py # JSON storage and preset tests
│   ├── test_wiz_integration.py  # UDP integration tests against simulator
│   ├── test_ui_bridge.py        # Asynchronous JS API bridge tests
│   ├── test_tray.py             # System tray synchronization and menu tests
│   ├── test_ambilight.py        # Screen capture and EMA streaming tests
│   ├── test_music_sync.py       # WASAPI and FFT DSP tests
│   ├── test_i18n.py             # Bilingual localization tests
│   ├── test_app_shell.py        # Menu model, autostart, --minimized and asset tests
│   └── test_security_hardening.py # Security and performance regression tests
└── ui/                          # Web frontend rendered inside WebView2
    ├── index.html               # Main console markup
    ├── styles.css               # Architectural photometric styling (Dark theme)
    ├── app.js                   # Reactive frontend state controller
    └── i18n.js                  # English / Spanish localization dictionaries
```

---

## Installation & Setup

### Option A — Windows Installer or Portable ZIP (Recommended for Users)

No Python installation is required. Download the latest release from [**GitHub Releases**](https://github.com/AlexisAcevedo/Gestor-de-luces/releases/latest):

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
- Python: Version 3.11 or higher (Python 3.14 fully supported).
- WebView2 Runtime: Microsoft Edge WebView2 Evergreen Runtime.

#### Step-by-Step Setup

1. Clone the repository and enter its folder:
   ```bash
   git clone https://github.com/AlexisAcevedo/Gestor-de-luces.git
   cd Gestor-de-luces
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

3. Install dependencies (`requirements.txt` for runtime/tests, or `requirements-dev.txt` to include audit and packaging tools):
   ```bash
   pip install -r requirements-dev.txt
   ```

---

## Running the Application (From Source)

### 1. Graphical User Interface (GUI) Mode

Launch the desktop management console:

```bash
python -m gestor_luces.main
```

Supported CLI flags for `main.py`:
- `--debug`: Enable pywebview developer tools and inspector.
- `--minimized`: Start hidden in the system tray (this is the flag registered by "Start with Windows").
- `--smoke-test`: Initialize the composition root, verify UI and icon assets without opening native GUI windows, and exit with code 0.

### 2. Low-Level Network CLI Mode

Use `gestor_luces.cli` for direct network discovery, UDP diagnostic probing, and scriptable command execution without starting the graphical container:

```bash
# Discover all bulbs on the local subnet via UDP broadcast:
python -m gestor_luces.cli discover

# Query real-time status of a specific bulb:
python -m gestor_luces.cli status 192.168.100.6

# Turn a bulb on at 80% brightness:
python -m gestor_luces.cli on 192.168.100.6 --brightness 80

# Set bulb color using RGB:
python -m gestor_luces.cli color 192.168.100.6 255 120 0 --brightness 100

# Set Correlated Color Temperature (CCT):
python -m gestor_luces.cli temp 192.168.100.6 2700

# Activate built-in scene by ID:
python -m gestor_luces.cli scene 192.168.100.6 5 --speed 120

# Turn a bulb off:
python -m gestor_luces.cli off 192.168.100.6
```

---

## Verification & Testing

The test suite validates domain invariants, JSON persistence, rate limiters, PyWebView asynchronous bridging, system tray event handling, Ambilight smoothing, and WASAPI audio signal processing.

Tests execute completely offline using an asynchronous in-memory UDP simulator (`FakeWizBulbServer`) that handles WiZ JSON-RPC protocol requests (`getPilot`, `setPilot`, `getSystemConfig`).

Execute the test suite with:

```bash
pytest
```

Expected output:
```
73 passed in ~2.0s
```

To run static security analysis and dependency vulnerability checks (using `requirements-dev.txt`):

```bash
python -m bandit -r src -q
python -m pip_audit -r requirements.txt
```

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

Build requirements: the project virtual environment with `requirements.txt` (or `requirements-dev.txt`), and [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) for the installer. If Inno Setup is missing, the script skips the installer with a warning. If `signtool.exe` is in `PATH` and `SIGN_CERT_SHA1` is set to a code-signing certificate thumbprint, `build.ps1` automatically signs the executable and installer with SHA-256 + RFC 3161 timestamping.

Notes for target machines:
- Windows 10/11 64-bit with the Microsoft Edge WebView2 Runtime (preinstalled on Windows 11 and most up-to-date Windows 10). The installer warns when it is missing but does not install it.
- Unless built with `SIGN_CERT_SHA1`, executables are unsigned, so Windows SmartScreen shows "Windows protected your PC": choose **More info** then **Run anyway**. Verify the download against `SHA256SUMS.txt`.
- Per-user installation writes to `%LOCALAPPDATA%\Programs\GestorDeLuces` (no administrator prompt required); if you share the Windows account or require system-wide write-protected binaries under `C:\Program Files`, run the installer with administrator privileges or pass `/ALLUSERS`.
- User data lives in `%LOCALAPPDATA%\GestorDeLuces`, never next to the executable.
- If the portable folder is moved while "Start with Windows" is enabled, the registry entry is corrected on the next launch.
- Occasionally `Compress-Archive` fails with a locked file right after PyInstaller finishes (antivirus scanning); re-run the script.

---

## Further Reading

- [Architecture & Concurrency Deep Dive](docs/architecture.md): Detailed analysis of the Hexagonal design, threading topology, and race condition prevention.
- [WiZ UDP Protocol & Streaming Specification](docs/wiz_protocol.md): Low-level documentation of JSON-RPC datagram formats, rate limiting, and scene catalogs.
- [Documentación en Español](README.es.md): Versión completa de esta documentación en español.

