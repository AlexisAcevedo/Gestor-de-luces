# Architectural Design & Concurrency Model

[English](architecture.md) | [Español](architecture.es.md)

This document details the architectural foundation, structural layers, threading topologies, and concurrency synchronization mechanics employed in **Gestor de Luces**.

---

## 1. Architectural Philosophy: Ports and Adapters (Hexagonal)

The core principle behind this project is **strict isolation of business invariants from volatile infrastructure details** (such as networking sockets, desktop UI frameworks, audio drivers, and file systems). 

```
                                  PRIMARY ADAPTERS
                           (Inbound / Driving Interfaces)
            +-------------------------+     +-------------------------+
            |  PyWebView (WebView2)   |     |   System Tray (Win32)   |
            |     WebviewBridge       |     |     TrayController      |
            +------------+------------+     +------------+------------+
                         |                               |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |      APPLICATION SERVICE      |
                         |     (LightControlService)     |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |         DOMAIN MODEL          |
                         |   (Bulb, State, Color, Scene) |
                         +---------------+---------------+
                                         |
                         +---------------+---------------+
                         |                               |
                         v                               v
            +-------------------------+     +-------------------------+
            |   LightController Port  |     |   Storage & Samplers    |
            +------------+------------+     +------------+------------+
                         |                               |
            +------------+------------+     +------------+------------+
            |    WizUdpController     |     |   JsonRepositories      |
            |   (Local UDP 38899)     |     |   MssScreenSampler      |
            |                         |     |   WasapiAudioSampler    |
            +-------------------------+     +-------------------------+
                                 SECONDARY ADAPTERS
                           (Outbound / Driven Interfaces)
```

### Layer Separation

1. **Domain Layer (`gestor_luces.domain`)**:
   - Contains pure entity models (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`) and Value Objects (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`).
   - Completely devoid of dependencies on external packages, operating system APIs, network libraries, or serialization frameworks.
   - Enforces business validation rules (e.g., RGB integers between 0 and 255, Kelvin bounds between 2,200K and 6,500K, and bulb identification constraints).

2. **Ports Layer (`gestor_luces.ports`)**:
   - Defines structural typing contracts using Python's `typing.Protocol` with `@runtime_checkable`.
   - Driven ports specify external requirements without binding to specific drivers:
     - `LightController`: Defines network primitives (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contract for loading and storing application state.
     - `ScreenSampler`: Contract for capturing monitor pixels and computing dominant color.
     - `AudioSampler`: Contract for sampling system audio energy and frequency spectrum.

3. **Application Layer (`gestor_luces.application`)**:
   - Coordinates business workflows through `LightControlService`.
   - Manages asynchronous orchestration across single or multiple bulbs concurrently using `asyncio.gather`.
   - Houses specialized domain services:
     - `StreamRateLimiter`: Enforces maximum transmission pacing (10 Hz) for high-frequency streams.
     - `SleepTimerManager`: Coordinates non-blocking countdown timers with progressive linear brightness fade-out.
     - `AmbilightStreamManager`: Runs dedicated screen-sampling streaming cycles.
     - `MusicSyncStreamManager`: Orchestrates WASAPI loopback audio sampling, FFT transformation, and color mapping.

4. **Adapters Layer (`gestor_luces.adapters`)**:
   - Implements ports with real-world infrastructure:
     - `adapters.wiz.udp_controller`: Manages UDP broadcast discovery and unicast JSON-RPC datagrams via `pywizlight`.
     - `adapters.storage.json_repositories`: Implements filesystem atomic persistence into `%LOCALAPPDATA%\GestorLuces`.
     - `adapters.ambilight.mss_sampler`: Implements `ScreenSampler` using high-speed Win32 GDI screen buffers via `mss`.
     - `adapters.audio.wasapi_sampler`: Implements `AudioSampler` using `PyAudioWPatch` loopback capture and `numpy.fft.rfft`.
     - `adapters.tray.tray_icon`: Implements Windows notification area integration using `pystray`.
     - `adapters.ui_webview.bridge`: Primary driver exposing a thread-safe JavaScript API inside Microsoft Edge WebView2.

---

## 2. Concurrency and Threading Model

The desktop application spans four distinct thread contexts that must interact safely without freezing the user interface, dropping streaming frames, or causing deadlocks.

```
+-------------------------------------------------------------------------------+
| THREAD 1: WinForms / PyWebView UI Thread (Main Process Entrypoint)            |
|   - Owns Windows HWND and native Edge WebView2 container.                     |
|   - Dispatches DOM events and executes JavaScript engine.                     |
+-------------------------------------------------------------------------------+
       |                                                                ^
       | Synchronous JS API Call                                        | UI State Callback
       v                                                                |
+-------------------------------------------------------------------------------+
| THREAD 2: Dedicated Asyncio Event Loop Worker (_bridge_worker)                |
|   - Executes all network I/O, coroutines, and service workflows.             |
|   - Runs asyncio.run_coroutine_threadsafe() to dispatch work safely.         |
|   - Interfaces with WizUdpController sockets.                                |
+-------------------------------------------------------------------------------+
       ^                                                                ^
       | Periodic State Snapshot                                        | Stream Frames
       v                                                                |
+--------------------------------------+   +------------------------------------+
| THREAD 3: System Tray (pystray)      |   | THREAD 4: Streaming Workers        |
|   - Runs native Win32 message loop   |   |   - Ambilight 10 Hz capture loop   |
|     via icon.run_detached().         |   |   - WASAPI loopback audio callback |
|   - Renders context menus on demand. |   |   - FFT spectral analysis thread   |
+--------------------------------------+   +------------------------------------+
```

### Thread Descriptions & Responsibilities

1. **Main UI Thread**:
   - Initialized by `webview.start()`.
   - Runs the Win32/WinForms window loop and hosts Microsoft Edge Chromium (WebView2).
   - Any long-running or blocking call on this thread immediately freezes the user interface.

2. **Asyncio Bridge Worker Thread**:
   - Created at application startup in `WebviewBridge.start_event_loop()`.
   - Owns an isolated, long-running `asyncio.AbstractEventLoop`.
   - JavaScript calls invoked via the `window.pywebview.api` interface are routed through `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)` with a guarded timeout to prevent indefinitely blocking the UI thread on network timeouts.

3. **System Tray Daemon Thread**:
   - Initialized via `pystray.Icon.run_detached()`.
   - Maintains a secondary Win32 message pump for the notification area tray icon and context menus.
   - Operates detached from the main window, permitting the window to be hidden, restored, or destroyed independently.

4. **Hardware Streaming Threads (Ambilight & Audio)**:
   - Managed as background daemon threads by `AmbilightStreamManager` and `MusicSyncStreamManager`.
   - Wake up on fixed intervals (e.g., 100 ms for Ambilight) or audio hardware buffer interrupts (WASAPI loopback).
   - Use fire-and-forget UDP packets (`stream_pilot`) without waiting for network ACKs, preventing pipeline stalls.

---

## 3. Concurrency Safety & Deadlock Prevention

Inter-thread communication between `pystray` (WinForms/Win32) and `pywebview` (WinForms/WebView2) introduces severe deadlock hazards if locks are held while evaluating menus or restoring windows.

### Case Study: System Tray Menu Deadlock Resolution

In early prototypes, calling `update_menu()` inside `TrayController` while holding an internal lock caused hard lockups:
- `update_menu()` internally invokes dynamic menu generators (`_create_menu()`).
- Those generators query `is_any_on`, `selected_ips`, or `favorite_scenes`, which attempted to acquire the same lock.
- If the Win32 message pump was simultaneously dispatching a tray click callback waiting for the lock, a classic AB-BA deadlock occurred.

**Architectural Fix**:
1. **Separation of State Snapshot from View Rendering**:
   - `TrayController` maintains a lightweight internal `_state_snapshot` dictionary protected by a reentrant `threading.RLock`.
   - `update_menu()` is called strictly **outside** the locked section after copying the snapshot.
2. **Re-entrant Synchronization**:
   - All internal mutexes are configured as `threading.RLock` to allow recursive inspections from the same thread without self-deadlock.

```python
# Safe pattern implemented in TrayController:
def set_state_snapshot(self, snapshot: dict[str, Any]) -> None:
    with self._lock:
        self._state_snapshot = dict(snapshot)
    # update_menu() is executed outside the lock
    self.update_menu()
```

### Case Study: Window Hide and Restore Lifecycle

When the user closes the main window, `gestor_luces` intercepts the `window.events.closing` event:
- The window is hidden (`window.hide()`) rather than destroyed, allowing the application to continue running in the background.
- When the user clicks "Open Console" or double-clicks the tray icon, `TrayController` schedules `window.show()` and `window.restore()` safely onto the main thread using thread-safe event posting.

---

## 4. Hardware Rate Limiting & Streaming Architecture

WiZ light bulbs are powered by low-power ESP8266 / ESP32 microcontrollers. Sending UDP packets faster than their internal buffer processing rate causes:
- WiZ device watchdog timer resets (light bulb reboots and flickers).
- Dropped UDP frames and visible stutters.
- Network congestion on 2.4 GHz Wi-Fi channels.

### The 10 Hz Leaky Pacing Mechanism

To protect device integrity, `StreamRateLimiter` enforces a strict leaky-pacing window:

$$\Delta t \ge 100\text{ ms} \quad (\text{Max rate } = 10\text{ Hz})$$

```python
class StreamRateLimiter:
    def __init__(self, min_interval_seconds: float = 0.10) -> None:
        self._min_interval = min_interval_seconds
        self._last_dispatch: float = 0.0

    def should_dispatch(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if current - self._last_dispatch >= self._min_interval:
            self._last_dispatch = current
            return True
        return False
```

### Exponential Moving Average (EMA) Smoothing

To eliminate jarring transitions caused by abrupt screen changes (e.g., scene cuts in movies or rapid weapon firing in games), the Ambilight engine applies an Exponential Moving Average filter to the color stream:

$$\vec{C}_{\text{smoothed}} = \alpha \cdot \vec{C}_{\text{new}} + (1 - \alpha) \cdot \vec{C}_{\text{prev}}$$

Where $\alpha \in [0.1, 0.4]$ controls the smoothing factor:
- Lower $\alpha$ values produce cinematic, fluid transitions.
- Higher $\alpha$ values increase responsiveness for fast-paced gaming.

---

## 5. Persistence & Storage Strategy

Application settings, custom presets, and known bulb configurations are stored locally in the user's application data directory:

$$\text{Path: } \%\text{LOCALAPPDATA}\%\backslash\text{GestorLuces}\backslash$$

Files managed:
- `bulbs.json`: Discovered and manually added bulb IPs, MAC addresses, module types, and user-assigned aliases.
- `scenes.json`: User-created custom lighting scenes (mode, RGB, CCT, brightness, speed).
- `settings.json`: Global user preferences (active language `en` or `es`, last selected bulbs, default window size).

### Atomic File Write Pattern

To prevent JSON corruption in the event of sudden power cuts or process termination, writes follow the atomic replacement protocol:
1. Serialize JSON payload to an in-memory buffer.
2. Write buffer to a temporary file in the same directory (`filename.json.tmp`).
3. Flush and synchronize file descriptor (`flush()` + `os.fsync()`).
4. Atomically replace the target file via `os.replace()`, guaranteeing an all-or-nothing filesystem transaction on NTFS.

