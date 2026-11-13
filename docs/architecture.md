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
   - Contains pure entity models (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`), Value Objects (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`), and global UI preference invariants in `value_objects.py` (`SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, `SUPPORTED_THEMES` (`"architectural-stone"`, `"atmospheric-dark"`), and `DEFAULT_THEME` (`"architectural-stone"`)).
   - Completely devoid of dependencies on external packages, operating system APIs, network libraries, or serialization frameworks.
   - Enforces business validation rules (e.g., RGB integers between 0 and 255, Kelvin bounds between 2,200K and 6,500K, bulb identification constraints, and supported language/theme tokens).

2. **Ports Layer (`gestor_luces.ports`)**:
   - Defines structural typing contracts using Python's `typing.Protocol` with `@runtime_checkable`.
   - Driven ports specify external requirements without binding to specific drivers:
     - `LightController`: Defines network primitives (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`, `close`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contract for loading and storing application state.
     - `ScreenSampler`: Contract for capturing monitor pixels and computing dominant color (`sample_frame`, `sample_average_color`, `list_monitors`, `close`).
     - `AudioSampler`: Contract for sampling system audio energy and frequency spectrum (`sample_frame`, `sample_audio_metrics`, `list_audio_devices`, `close`).

3. **Application Layer (`gestor_luces.application`)**:
   - Coordinates business workflows through `LightControlService`.
   - Receives lazy sampler factories (`screen_sampler_factory`, `audio_sampler_factory`) injected from the composition root (`main.py`) so inner layers (`domain`, `ports`, `application`) never import `adapters` (enforced via AST static verification in `tests/test_security_hardening.py`).
   - Manages asynchronous orchestration across single or multiple bulbs concurrently using `asyncio.gather`.
   - Houses specialized domain services:
     - `StreamRateLimiter`: Enforces maximum transmission pacing (10 Hz) for high-frequency streams.
     - `SleepTimerManager`: Coordinates non-blocking countdown timers with progressive linear brightness fade-out.
     - `AmbilightStreamManager`: Runs dedicated screen-sampling streaming cycles.
     - `MusicSyncStreamManager`: Orchestrates WASAPI loopback audio sampling, FFT transformation, and color mapping.

4. **Adapters Layer (`gestor_luces.adapters`)**:
   - Implements ports with real-world infrastructure:
     - `adapters.wiz.udp_controller`: Manages UDP broadcast discovery and unicast JSON-RPC datagrams via `pywizlight`.
     - `adapters.storage.json_repositories`: Implements filesystem atomic persistence into `%LOCALAPPDATA%\GestorDeLuces`.
     - `adapters.ambilight.mss_sampler`: Implements `ScreenSampler` using high-speed Win32 GDI screen buffers via `mss`.
     - `adapters.audio.wasapi_sampler`: Implements `AudioSampler` using `PyAudioWPatch` loopback capture and `numpy.fft.rfft`.
     - `adapters.tray`: Implements Windows notification area integration behind a minimal `TrayView` contract:
      - `tray_icon`: `TrayController` owns the menu model, handlers, executor and the single refresh thread; it never imports a GUI toolkit.
      - `tray_view`: `TrayView` protocol (`run`/`stop`/`apply`) plus the shared model-to-action mapping and icon rendering.
      - `winforms_tray`: Primary view entry point. `create_winforms_view` and `WinFormsTrayView` compose the pieces below and keep the apply policy (icon/tooltip always, menu rebuild deferred while the menu is visible); it re-exports the module surface importers used before the split.
      - `winforms_host`: the STA host. Lazy pythonnet/WinForms resolution, `CoInitializeEx`, the hidden 0×0 `Form`, `Application.Run(form)` and `Control.Invoke` marshalling. No other module imports .NET on its own.
      - `winforms_icon`: `NotifyIcon` plus a per-color `HICON` cache that destroys replaced handles, and the 63-character tooltip limit.
      - `winforms_menu`: builds the `ContextMenuStrip` and its submenus from the pure `TrayMenuEntry` model, owns the menu/state signatures, and attaches the window finish to every menu surface.
      - `winforms_paint`: theme palettes, hex parsing, and every drawing operation (row painter, hover, check dot, submenu chevron, separators, DPI-scaled rounded-region geometry and the rounded `Region` cut).
      - `pystray_tray`: Fallback view (classic Win32 menu) used when pythonnet/WinForms cannot load.
     - `adapters.ui_webview.bridge`: Primary driver exposing a thread-safe JavaScript API inside Microsoft Edge WebView2 through a restricted public facade (`JsApi` whitelist) so internal methods and callbacks cannot be invoked from JavaScript. The adapter is split into `dispatch` (the explicit `JS_API_DISPATCH` table, `JsApi` and the window-fit contract), `handlers` (one handler per capability) and `lifecycle` (dedicated event loop, envelope sealing, state notifications and shutdown); `bridge.py` keeps `WebviewBridge` and re-exports the whole surface, so importers are unaffected.

---

## 2. Concurrency and Threading Model

The desktop application declares eight named threads and also runs four thread contexts that it does not create itself. They must interact safely without freezing the user interface, dropping streaming frames, or causing deadlocks. The inventory below is derived from `grep -rn "threading.Thread(" src/` and from following each thread's lifecycle; it is verified by `tests/test_thread_lifecycle.py`.

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
| THREAD 2: Dedicated Asyncio Event Loop (GestorLucesAsyncLoop)                 |
|   - Executes all network I/O, coroutines, and service workflows.             |
|   - Runs asyncio.run_coroutine_threadsafe() to dispatch work safely.         |
|   - Interfaces with WizUdpController sockets.                                |
+-------------------------------------------------------------------------------+
       ^                                                                ^
       | Periodic State Snapshot                                        | Stream Frames
       v                                                                |
+--------------------------------------+   +------------------------------------+
| THREAD 3: System Tray View           |   | THREAD 4: Streaming Workers        |
|   - `NotifyIcon` + context menu on   |   |   - Ambilight 10 Hz capture loop   |
|     its own STA thread (WinForms).   |   |   - WASAPI loopback audio callback |
|   - `pystray` fallback view.         |   |   - FFT spectral analysis thread   |
+--------------------------------------+   +------------------------------------+
```

### Thread Inventory (every `threading.Thread(` in `src/`)

Every call site passes an explicit `name=` and `daemon=True`: an omitted `stop()` can never keep the process alive, and every thread is identifiable in `threading.enumerate()`. The `name` column is the exact `threading.Thread.name` value.

| Thread (`name=`) | Owner (module → creator) | Lifetime | How it is stopped |
| --- | --- | --- | --- |
| `GestorLucesAsyncLoop` (`ASYNC_LOOP_THREAD_NAME`) | `adapters/ui_webview/lifecycle.py` → `BridgeLifecycle._start_async_loop`, started by `WebviewBridge.__init__` | Long-lived: one per session, runs the bridge's private `asyncio` loop (`loop.run_forever()`) | `WebviewBridge.shutdown()` cancels the active streams, calls `loop.call_soon_threadsafe(loop.stop)` and `thread.join(timeout=2.0)`. Idempotent behind `_shutdown_lock`; invoked by `DesktopApplication.cleanup()` and by the window `closed` event. |
| `GestorLucesTray` (`ICON_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start`, runs `TrayView.run` | Long-lived: the view's native message pump (WinForms `Application.Run` on an STA thread, or `pystray.Icon.run`) for the whole session | `TrayController.stop()` sets `_stopped` and calls `TrayView.stop()` (WinForms closes the hidden form, `pystray` stops the icon), so `run` returns. Safe to call repeatedly and from any thread. |
| `GestorLucesTrayRefresh` (`REFRESH_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start` → `_refresh_worker` | Long-lived: waits on `_refresh_requested` with the `poll_interval` timeout (5 s) | Same `TrayController.stop()`: it sets `_stopped` and `_refresh_requested` and the worker exits on the flag. It is the single writer of native tray state (T-3.6). |
| `GestorLucesTrayAction` (literal in `_default_executor`) | `adapters/tray/tray_icon.py` → `TrayController.dispatch` → `_run_action` | Short-lived: one thread per dispatched menu action | Self-terminating; nothing joins it. `quit_app` deliberately does not tear the tray down from this thread — the teardown runs later in `cleanup()`. |
| `GestorLucesMenuSync` (`MENU_SYNC_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.start` → `_menu_sync_worker` | Long-lived: waits on `_menu_sync_requested` and re-applies the live native `MenuStrip` (pywebview has no menu update API) | `DesktopApplication.cleanup()` sets `is_quitting` and calls `request_menu_sync()` once: the loop wakes, sees the flag and exits before re-applying. |
| `GestorLucesHideOnClose` (`HIDE_ON_CLOSE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_closing` (window `closing` event) | Short-lived: calls `hide_window` and exits | Self-terminating. pywebview raises `closing` synchronously on the GUI thread with `should_lock`, so hiding from inside the handler could re-enter or deadlock; hence the thread. |
| `GestorLucesHideOnMinimize` (`HIDE_ON_MINIMIZE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_minimized` (window `minimized` event) | Short-lived: calls `hide_window` and exits | Self-terminating, for the same reason as hide-on-close. |
| `GestorLucesSingleInstance` (literal in `listen`) | `adapters/system/single_instance.py` → `SingleInstanceGuard.listen` | Long-lived: polls `WaitForSingleObject(handle, 500 ms)` for a second launch | `SingleInstanceGuard.release()` sets `self._stop`; the thread exits within one 500 ms poll. Called by `DesktopApplication.cleanup()`. |

Thread contexts the application does not create itself:

| Context | Owner (module) | Lifetime | How it is stopped |
| --- | --- | --- | --- |
| `MainThread` (UI pump) | `webview.start()` (pywebview/WinForms), called from `DesktopApplication.start` | Long-lived: blocks until the native window is destroyed | `window.destroy()` from `quit_app` (tray Quit or File → Exit); `webview.start()` returns and `cleanup()` runs in its `finally`. |
| Default-executor workers (asyncio_0, asyncio_1, …) | the `GestorLucesAsyncLoop` loop's default executor thread pool, filled lazily by `asyncio.to_thread` in `application/ambilight_stream.py` (~10 Hz) and `application/music_stream.py` (~10.5 Hz) | Long-lived while the session runs; idle between frames | `BridgeLifecycle.shutdown()` stops both streams first, and `loop.close()` inside `_run_loop` shuts the default executor down (`shutdown(wait=False)`) when the loop exits. |
| PortAudio callback thread (surfaces as `Dummy-N`) | PortAudio/WASAPI: it calls the `stream_callback` closure of `adapters/audio/wasapi_session.py` | Long-lived while the music stream is active: one call per audio buffer | `WasapiLoopbackStreamSession.close()` (`stop_stream`, `close`, `pa.terminate()`), reached from `LightControlService.close_audio_sampler()` inside `shutdown()`. |
| `Thread-N (setup_handler)` | `pystray.Icon.run()` in the fallback view `adapters/tray/pystray_tray.py`; pystray creates it **without a name and without `daemon`** | Short-lived: sets `icon.visible = True` once the pump starts | `pystray.Icon.stop()` joins it with `SETUP_THREAD_TIMEOUT` (5 s) from the thread that calls `TrayView.stop()`. The WinForms view creates no such thread. |

`cli.py` runs `asyncio.run(...)` on the calling thread, so the command-line tool adds no thread of its own.

### Thread Rules

- Every `threading.Thread(` in `src/` keeps an explicit `name=` and `daemon=True`; a new call site without both is a defect.
- Only `GestorLucesTrayRefresh` applies native tray state, and only `GestorLucesMenuSync` re-applies the native window menu: one writer per native surface.
- Only `GestorLucesTrayAction` performs tray menu actions, so a slow UDP call never runs inside a native message pump. The window menu bar dispatches on `MainThread` through pywebview and only re-applies state through `GestorLucesMenuSync`.
- Closing the app releases the long-lived threads (`GestorLucesAsyncLoop`, `GestorLucesTray`, `GestorLucesTrayRefresh`, `GestorLucesSingleInstance`); the short-lived ones (`GestorLucesTrayAction`, `GestorLucesHideOnClose`, `GestorLucesHideOnMinimize`) have already finished by then and are never joined at close.
- **Closing rule:** `DesktopApplication.cleanup()` stops every app-owned thread: it sets `is_quitting` and wakes `GestorLucesMenuSync`, releases the single-instance guard, stops the tray view and its refresh thread, and shuts the bridge loop down. `tests/test_thread_lifecycle.py` proves with `threading.enumerate()` that no app-named thread survives close, using bounded condition waits rather than fixed sleeps.

---

## 3. Concurrency Safety & Deadlock Prevention

Inter-thread communication between the tray view (`pystray` or WinForms) and `pywebview` (WinForms/WebView2) introduces severe deadlock hazards if locks are held while evaluating menus or restoring windows.

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

### Tray Menu Threading Rule (T-3.6)

In the `pystray` fallback view, `pystray.Icon.update_menu()` starts by destroying the current `HMENU` and creating a new one. If that happens while the popup menu is displayed, every item ID and every `hSubMenu` already created becomes invalid: clicks cancel silently and submenus stop opening.

The rule enforced by `TrayController` for every view:
- Menu actions only queue work on the executor thread and end with `request_refresh()`; they never touch the view.
- Only the single `GestorLucesTrayRefresh` thread calls `TrayView.apply`, so native tray state always has one writer.
- The view decides whether the native menu can be rebuilt right now. The `pystray` view asks `adapters.platform.windows.menu_state._is_menu_open` (foreground menu-mode flags via `GetGUIThreadInfo`) and, when a menu is open, marks the rebuild pending and retries it on the next `apply`. The WinForms view defers while its `ContextMenuStrip.Visible` is true, then swaps and disposes the menu on the next refresh.

### Tray Menu Rendering and Theme Palettes (T-3.8)

The classic `pystray` menu is a Win32 popup painted by the window class it registers with `hbrBackground = COLOR_WINDOW + 1`, so it always uses the system white background and light text becomes illegible ("white background, white letters, too much brightness"). The tray therefore uses `System.Windows.Forms.NotifyIcon` + `ContextMenuStrip` as its primary view:

- `TrayView` (`adapters.tray.tray_view`) is the only contract between the controller and a view: `run()` (blocking pump), `stop()`, and `apply(spec, title, rgb, theme)`. `resolve_entry_action` maps a model leaf to the action to dispatch, including the synthetic `toggle_window` action for the default show/hide item.
- `winforms_tray` orchestrates the apply policy and `winforms_menu` maps the pure `menu_model` to real `ToolStripMenuItem` objects: submenus are `DropDownItems` (so WinForms opens them on hover, no click hack), leaf clicks dispatch `(action_id, payload)`, checked radio levels use `CheckOnClick = False` + `Checked`, and a synthetic action cannot be blocked by a slow UDP call because `TrayController` still dispatches on its executor.
- Colors come from an explicit palette table keyed by the active theme (`architectural-stone` → light, `atmospheric-dark` → dark, unknown → light). Background, text, disabled text, hover (`selection`) and `separator` are applied to the `ContextMenuStrip`, each item and each submenu panel; `RenderMode = System` keeps the dropdown chrome from re-painting a bright image margin, and the view draws the hover block, the text, the checked level and the separators itself (see T-3.9 below).
- Verified environment constraint: pythonnet 3.2.1 on .NET Framework 4.8 does not emit derived .NET types here, so Python subclasses of `ProfessionalColorTable`/`ToolStripRenderer` receive no virtual dispatch from .NET. A custom color table or renderer is therefore not available, which is why the palette is applied per control instead.
- If WinForms cannot load, `create_winforms_view` returns `None` and the composition root falls back to `pystray_tray`, so the tray icon can never disappear because of the CLR.

### Modern Menu Finish and Split Signatures (T-3.9)

With `RenderMode = System` the view still got ~20 px rows, a 1 px border in the Windows theme color, square corners and a flat system highlight: "it looks like Windows 98". The system border cannot be recoloured without subclassing the renderer, which this pythonnet build cannot do, so the view takes over every pixel it is allowed to paint:

- Corners: on `ToolStripDropDown.Opened` (the top `ContextMenuStrip` and every submenu, subscribed by `winforms_menu.attach_menu_chrome`) the view calls `winforms_menu.apply_menu_chrome`, which runs `window_chrome._apply_corner_preference` — setting `DWMWA_WINDOW_CORNER_PREFERENCE` (33) to `DWMWCP_ROUND` (2) through `DwmSetWindowAttribute` with an injectable `dwmapi` — and then assigns a rounded `Region` inset by 1 px (`winforms_paint.menu_region_geometry` for the DPI-scaled geometry, `winforms_paint.apply_menu_region` to clip it). The inset region is the only mechanism available without a custom renderer that removes the renderer's 1 px frame; because a window with a custom region is not rounded by DWM, the region is the effective corner source, while the DWM attribute is the graceful path when the region cannot be created.
- Rows: `ToolStripMenuItem.Padding` gets `MENU_ITEM_PADDING_VERTICAL = 4` per side, which turns the ~20 px default row into ~28 px.
- Painting (`winforms_paint`): each item subscribes to `ToolStripItem.Paint` (raised after the system render) and draws its background, hover block, text, check mark and submenu chevron through `item_paint_style`/`paint_menu_item`; separators use `separator_paint_style`/`paint_menu_separator` with `TrayPalette.separator`. The active brightness level is a dot in the palette text color, so neither a generated `Image` nor the fixed-color native check glyph is involved, and the hover block uses the existing `TrayPalette.selection`.
- Signatures (`winforms_menu`): `menu_signature(spec, theme)` = `(tuple(spec), theme)` decides a rebuild, and `state_signature(spec, title, rgb, theme)` = `(menu signature, title, rgb)` decides whether anything changed at all. A different `rgb` or `title` with the same spec and theme only assigns `NotifyIcon.Icon`/`NotifyIcon.Text`, with no deferral and no rebuild, so the log with five identical `Tray menu rebuilt` lines in two seconds cannot come back. Only a rebuild is deferred while `ContextMenuStrip.Visible` is true, `Tray menu rebuilt: [...]` is logged exactly once per actual rebuild, and the pending signature logs `rebuild deferred (menu open)` once.
- Every Win32/WinForms call is guarded: a missing DWM, an unavailable `GraphicsPath` or a region that cannot be created degrades to the plain system frame instead of breaking the menu.

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

$$\text{Path: } \%\text{LOCALAPPDATA}\%\backslash\text{GestorDeLuces}\backslash$$

Files managed:
- `bulbs.json`: Discovered and manually added bulb IPs, MAC addresses, module types, and user-assigned aliases.
- `custom_scenes.json`: User-created custom lighting scenes (mode, RGB, CCT, brightness, speed, favorite flag).
- `settings.json`: Global user preferences (`language`: `"en"` or `"es"`, and `theme`: `"architectural-stone"` or `"atmospheric-dark"`).

### Atomic File Write Pattern

To prevent JSON corruption in the event of sudden power cuts or process termination, writes follow the atomic replacement protocol:
1. Serialize JSON payload to an in-memory buffer.
2. Create a unique temporary file in the same directory via `tempfile.mkstemp` (`.<filename>.<random>.tmp`).
3. Write, flush, and synchronize the file descriptor (`flush()` + `os.fsync()`).
4. Atomically replace the target file via `os.replace()`, guaranteeing an all-or-nothing filesystem transaction on NTFS.


---

## 6. Desktop Shell, Autostart & Packaging

### Native Menu Bar
`adapters/ui_webview/app_menu.py` is a pure model of the window menu (File: Show/Hide, Start with Windows, Exit; Help: Keyboard shortcuts, About), localized in English and Spanish. `main.py` passes it to `webview.start(menu=...)`. pywebview 6.2.1 menus are static (no checkable items, no update API), so `main.py` updates the live WinForms `MenuStrip` in place on a worker thread when the language, window visibility or autostart state changes. Exit follows the same path as the tray's Quit action.

### Autostart (`--minimized`)
The `AutostartManager` port (`ports/autostart.py`) is implemented by `WindowsRegistryAutostart` (`adapters/system/windows_autostart.py`), which writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. The registered command is `<exe> --minimized` when frozen and `pythonw -m gestor_luces.main --minimized` in development. On every launch, `refresh_if_stale` rewrites the entry if it points to a different path (for example after moving the portable folder). The registry is injectable, so tests never touch `HKCU`.

### Single Instance
`adapters/system/single_instance.py` combines a named mutex with a named event protected by an explicit SDDL DACL (`SY`/`BA`/`OW`). A second launch signals the event and exits; the first instance reacts by showing its window (unless bypassed via `--multi-instance` for side-by-side diagnostics).

### Multi-Theme Engine & Dynamic Widget Geometry
- **3-Tier CSS Token Architecture**: `ui/themes.css` defines primitive, semantic, and component-level tokens for both `"architectural-stone"` (default warm mineral Light theme) and `"atmospheric-dark"` (translucent glass Dark theme with `oklab` photometric halo), consumed by the layout and component rules in `ui/styles.css`.
- **Native Window Chrome Synchronization (`THEME_WINDOW_CHROME`)**: `main.py` reads the persisted theme before creating the PyWebView window to set the initial WebView2 `background_color` (`#F4F1EA` or `#08090C`) and delegates the Windows DWM titlebar attribute (`DwmSetWindowAttribute` `DWMWA_USE_IMMERSIVE_DARK_MODE = 20` with `0` for light or `1` for dark) to `adapters/platform/windows/window_chrome.py` (`_set_windows_dark_titlebar_attribute`), both on startup and bidirectionally at runtime when the user switches themes.
- **Content-Driven Window Height Auto-Fit**: `adapters/platform/windows/window_geometry.py` implements `_fit_native_window_height` using 64-bit-safe Win32 `ctypes` (`GetWindowRect`, `GetClientRect`, `SetWindowPos`) marshaled onto the WinForms UI thread (`native_form.Invoke`), clamped to the active monitor's work area via `WebviewBridge.fit_window_height`.

### Frontend Serving (loopback HTTP + ES Modules) · D4 verdict: A (2026-11-08)
The frontend is served over loopback HTTP so `ui/app.js` can be split into real ES
modules (Chromium blocks `type="module"` over `file://`). `main.py` passes the plain
filesystem path `str(index_path)` as the window URL and starts `webview.start(http_server=True)`.

The D4-A spike (T-2.0) verified the following, with evidence:
- **Loopback-only surface**: pywebview's built-in Bottle server binds `127.0.0.1` only
  (observed `http://127.0.0.1:42001/`). It is never exposed to the LAN.
- **Bridge stays direct IPC**: `window.pywebview.api` remains a native WebView2 host
  object. The HTTP `/js_api/<uuid>` endpoint only carries JS promise callbacks, gated by
  a per-launch random `uuid`; it is not the application bridge.
- **Static serving + ESM MIME**: `index.html` → `text/html`, `app.js`/`i18n.js` →
  `text/javascript` (module-compatible), `themes.css`/`styles.css` → `text/css`.
- **Path traversal blocked**: `GET /../../<file>` returns `403 Forbidden`
  (`bottle.static_file` rejects `..`).
- **Dev boot verified**: `python -m gestor_luces --minimized --multi-instance` served
  `index.html` with HTTP 200 on `127.0.0.1:42001` (title `WiZ Architectural Lighting
  Console`), no errors in the log.
- **`resolve_ui_directory()` unchanged**: returns `ui/` from source and `_MEIPASS/ui`
  when frozen; both are plain paths, so the server root is identical either way
  (`resources.py`).

Gotchas recorded for T-2.2:
- The window URL **must** be a plain path (`str(index_path)`), not `.as_uri()`
  (`file://` is not rewritten to HTTP by pywebview's `_resolve_url`).
- The CSP `'self'` origin follows the scheme: it becomes `http://127.0.0.1:42001`;
  the explicit `file:` allowances become vestigial (harmless) and can be dropped later.
- `localStorage` origin migrates from `file://` to `http://127.0.0.1:42001`. The port is
  fixed (`settings['DEFAULT_HTTP_PORT']=42001`) because `private_mode=False`, so data
  persists across launches — but pre-existing `file://` localStorage does not carry over
  (one-time migration note; scene/theme truth lives in the JSON repositories anyway).
- Fixed port `42001` can collide under `--multi-instance` (two simultaneous servers).
- pywebview's root route `/` is a dead, buggy route (500); windows always load a
  concrete file path (`/index.html`), so it is never exercised.

### Internationalization (i18n) Ownership · single source of truth
Translations have a **single owner per domain** (Gate 2 / T-2.3):

- **Backend owns tray strings and domain errors only.** The tray menu labels live in
  `adapters/tray/menu_model.py` (`_TRAY_STRINGS`), because the system tray has no access
  to the web UI. Their keys are `snake_case` with no namespace (`hide_window`,
  `turn_off`, `brightness`, …).
- **The UI owns every on-screen string.** All visible page text lives in `ui/i18n.js`
  (`DICTIONARIES`), keyed as `namespace.camelCase` (`rail.scanBtn`, `stage.turnOff`,
  `shortcuts.brightness`, …).

The two conventions are deliberately incompatible so a literal key can never collide:
`tests/test_i18n.py::test_i18n_single_owner_backend_tray_vs_ui_screen` enforces that no
`_TRAY_STRINGS` key appears as a screen key and vice-versa. When adding a string, put it
in the domain that owns it; never mirror the same key in both places.

### Packaging
`scripts/build.ps1` generates the icon (`assets/icon/make_icon.py`), runs PyInstaller with `packaging/gestor_luces.spec` (one-folder, windowed, bundling `ui/` and `assets/`), builds the portable ZIP and the Inno Setup installer (`packaging/installer.iss`, per-user, no administrator rights), signs binaries when `SIGN_CERT_SHA1` is provided, and writes `dist/SHA256SUMS.txt`. `resources.py` resolves assets from `sys._MEIPASS` when frozen. User data always stays in `%LOCALAPPDATA%\GestorDeLuces`.
