# Architectural Design & Concurrency Model

[English](architecture.md) | [Español](architecture.es.md)

This document details the architectural foundation, structural layers, threading topologies, and concurrency synchronization mechanics employed in **WiZ Architectural Lighting Console** (`wiz_console`).

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

1. **Domain Layer (`wiz_console.domain`)**:
   - Contains pure entity models (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`), Value Objects (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`), endpoint validation (`validate_local_endpoint`), and global UI preference invariants in `value_objects.py` (`SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, `SUPPORTED_THEMES` (`"architectural-stone"`, `"atmospheric-dark"`), and `DEFAULT_THEME` (`"architectural-stone"`)).
   - Completely devoid of dependencies on external packages, operating system APIs, network libraries, or serialization frameworks.
   - Enforces business validation rules (e.g., RGB integers between 0 and 255, Kelvin bounds between 2,200K and 6,500K, local unicast IPv4 endpoint checks rejecting unspecified/broadcast/multicast addresses, and supported language/theme tokens).

2. **Ports Layer (`wiz_console.ports`)**:
   - Defines structural typing contracts using Python's `typing.Protocol` with `@runtime_checkable` across `light_control.py`, `repositories.py`, and `autostart.py`.
   - Driving and driven contracts decouple the desktop shell and infrastructure drivers without a monolithic `interfaces.py` barrel:
     - `LightControlServicePort` (`ports/light_control.py`): Desktop-facing application service contract injected into `DesktopApplication`.
     - `LightController` (`ports/repositories.py`): Defines network primitives (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`, `close`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contract for loading and storing application state.
     - `ScreenSampler`: Contract for capturing monitor pixels and computing dominant color (`sample_frame`, `sample_average_color`, `list_monitors`, `close`).
     - `AudioSampler`: Contract for sampling system audio energy and frequency spectrum (`sample_frame`, `sample_audio_metrics`, `list_audio_devices`, `close`).
     - `AutostartManager` (`ports/autostart.py`): Registry autostart contract.

3. **Application Layer (`wiz_console.application`)**:
   - Coordinates business workflows through `LightControlService` (`service.py`), delegating to bounded capability services (`bulb_control_service.py`, `bulb_inventory_service.py`, `scene_service.py`, `timer_service.py`, `ambilight_service.py`, `music_service.py`, `settings_service.py`) over a shared `service_context.py`.
   - Receives lazy sampler factories (`screen_sampler_factory`, `audio_sampler_factory`) injected from the composition root (`main.py`) so inner layers (`domain`, `ports`, `application`) never import `adapters` (enforced via AST static verification in `tests/test_security_hardening.py`).
   - Splits resource teardown between `close_audio_sampler()` (released while `BridgeLifecycle` closes active streams) and `close_all_resources()` during full shutdown, with rotating log files (`RotatingFileHandler`) and stream error backoff.
   - Houses specialized streaming and pacing coordinators protected by monotonic generation/run-ID guards (`_generation` / `run_id`) to prevent restart races:
     - `StreamRateLimiter`: Enforces maximum transmission pacing (10 Hz) for high-frequency streams.
     - `SleepTimerManager`: Coordinates non-blocking countdown timers with progressive linear brightness fade-out.
     - `AmbilightStreamManager`: Runs dedicated screen-sampling streaming cycles.
     - `MusicSyncStreamManager`: Orchestrates WASAPI loopback audio sampling, FFT transformation, and color mapping.

4. **Adapters Layer (`wiz_console.adapters`)**:
   - Implements ports with real-world infrastructure:
     - `adapters.wiz.udp_controller`: Manages UDP broadcast discovery and unicast JSON-RPC datagrams via `pywizlight`.
     - `adapters.storage.json_repositories`: Implements filesystem atomic persistence into `%LOCALAPPDATA%\WizConsole` (migrating legacy `%LOCALAPPDATA%\GestorDeLuces` files automatically on first launch).
     - `adapters.ambilight.mss_sampler`: Implements `ScreenSampler` using high-speed Win32 GDI screen buffers via `mss` with `ScreenShotError` boundary recovery.
     - `adapters.audio.wasapi_sampler`: Implements `AudioSampler` using `PyAudioWPatch` loopback capture (`wasapi_session.py`, `wasapi_devices.py`) with COM/session lifecycle locking, hot-unplug recovery, leak-free teardown, and cached FFT plans/buffers in `wasapi_capture.py`.
     - `adapters.platform.windows`: Isolates Win32 DWM chrome and icon caching (`window_chrome.py`), multi-monitor `WorkingArea` and high-DPI window sizing (`window_geometry.py`), foreground activation (`foreground.py`), native menu synchronization and light/dark `MenuStrip` theming (`menu_sync.py`, `menu_state.py`), and dialogs (`message.py`).
     - `adapters.tray`: Implements Windows notification area integration behind a minimal `TrayView` contract:
      - `tray_icon`: `TrayController` owns the menu model, handlers, executor, `show_notification`, and condition-variable-driven refresh thread (`_refresh_cond`); it never imports a GUI toolkit.
      - `tray_view`: `TrayView` protocol (`run`/`stop`/`apply`) plus the shared model-to-action mapping and icon rendering.
      - `winforms_tray`: Primary view entry point. `create_winforms_view` and `WinFormsTrayView` compose the pieces below, keep the apply policy (icon/tooltip always, menu rebuild deferred while the menu is visible), and expose `notify()` (`ShowBalloonTip`); it re-exports the module surface importers used before the split.
      - `winforms_host`: the STA host. Lazy pythonnet/WinForms resolution, `CoInitializeEx`, the hidden 0×0 `Form` guarded with `IsHandleCreated` — marked `WS_EX_TOOLWINDOW` on its freshly created handle, so a window that is visible, transparent and minimised never shows up as an alt+tab entry —, `Application.Run(form)` and `Control.Invoke` marshalling. No other module imports .NET on its own.
      - `winforms_icon`: `NotifyIcon` plus a per-color `HICON` cache that destroys replaced handles, and the 63-character tooltip limit.
      - `winforms_menu`: builds the `ContextMenuStrip` and its submenus from the pure `TrayMenuEntry` model, owns the menu/state signatures, and attaches the window finish to every menu surface.
      - `winforms_paint`: theme palettes, hex parsing, prior `Region` disposal, and every drawing operation (row painter, hover, check dot, submenu chevron, separators, DPI-scaled rounded-region geometry and the rounded `Region` cut).
      - `pystray_tray`: Fallback view (classic Win32 menu + `notify()`) used when pythonnet/WinForms cannot load.
     - `adapters.ui_webview.bridge`: Primary driver exposing an explicitly whitelisted set of top-level functions inside Microsoft Edge WebView2 (`BlockedJsApi` on `js_api` plus `window.expose(*build_exposed_functions(js_api))`), preventing dotted `getattr` traversal from JavaScript. The adapter is split into `dispatch` (`BlockedJsApi`, `build_exposed_functions`, `JsApi`, and the window-fit contract), `handlers` (capability handlers with strict finite/type input validation, sanitized error responses, and delta status polling for Ambilight/Music Sync), `http_server` (`NoCacheBottleServer`), and `lifecycle` (`BridgeLifecycle` behind `_loop_state_lock`, timed-out task cancellation, envelope sealing, state notifications, `refresh_tray_states`, and shutdown); `bridge.py` keeps `WebviewBridge` and re-exports the public surface.

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
| THREAD 2: Dedicated Asyncio Event Loop (WizConsoleAsyncLoop)                  |
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
| `WizConsoleAsyncLoop` (`ASYNC_LOOP_THREAD_NAME`) | `adapters/ui_webview/lifecycle.py` → `BridgeLifecycle._start_async_loop`, started by `WebviewBridge.__init__` | Long-lived: one per session, runs the bridge's private `asyncio` loop (`loop.run_forever()`) | `WebviewBridge.shutdown()` coordinates state under `_loop_state_lock`, cancels active streams and timed-out tasks, releases audio sampler resources, calls `loop.call_soon_threadsafe(loop.stop)` and `thread.join(timeout=2.0)`. Idempotent behind `_shutdown_lock`; invoked by `DesktopApplication.cleanup()` and by the window `closed` event. |
| `WizConsoleTray` (`ICON_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start`, runs `TrayView.run` | Long-lived: the view's native message pump (WinForms `Application.Run` on an STA thread, or `pystray.Icon.run`) for the whole session | `TrayController.stop()` sets `_stopped` and calls `TrayView.stop()` (WinForms closes the hidden form, `pystray` stops the icon), so `run` returns. Safe to call repeatedly and from any thread. |
| `WizConsoleTrayRefresh` (`REFRESH_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start` → `_refresh_worker` | Long-lived: waits on `_refresh_cond` with the `poll_interval` timeout (5 s) | Same `TrayController.stop()`: acquires `_refresh_cond`, sets `_stopped` and notifies, and the worker exits on the flag. It is the single writer of native tray state (T-3.6). Only a timeout-driven (periodic) cycle asks the bridge for a live `getPilot` read through `refresh_tray_states`, which does not seal the success envelope; a refresh requested by an action keeps the cache that action just wrote. |
| `WizConsoleTrayAction` (literal in `_default_executor`) | `adapters/tray/tray_icon.py` → `TrayController.dispatch` → `_run_action` | Short-lived: one thread per dispatched menu action | Self-terminating; nothing joins it. `quit_app` deliberately does not tear the tray down from this thread — the teardown runs later in `cleanup()`. |
| `WizConsoleMenuSync` (`MENU_SYNC_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.start` → `_menu_sync_worker` | Long-lived: waits on `_menu_sync_cond` (backed by `_state_lock`) and re-applies the live native `MenuStrip` (pywebview has no menu update API) | `DesktopApplication.cleanup()` sets `is_quitting` under `_state_lock`, notifies `_menu_sync_cond`, and the loop exits before re-applying. `DesktopApplication` also tracks `_visibility_generation` so overlapping hide/show events cannot clobber each other, and suppresses titlebar/menu sync churn during light-control drags. |
| `WizConsoleHideOnClose` (`HIDE_ON_CLOSE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_closing` (window `closing` event) | Short-lived: calls `_hide_if_generation(generation, show_tray_hint=True)` and exits | Self-terminating. pywebview raises `closing` synchronously on the GUI thread with `should_lock`, so hiding from inside the handler could re-enter or deadlock; hence the thread. Shows the one-time persisted tray hint on first hide. |
| `WizConsoleHideOnMinimize` (`HIDE_ON_MINIMIZE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_minimized` (window `minimized` event) | Short-lived: calls `_hide_if_generation(generation, show_tray_hint=True)` and exits | Self-terminating, for the same reason as hide-on-close. |
| `WizConsoleSingleInstance` (literal in `listen`) | `adapters/system/single_instance.py` → `SingleInstanceGuard.listen` | Long-lived: polls `WaitForSingleObject(handle, 500 ms)` for a second launch | `SingleInstanceGuard.release()` sets `self._stop`; the thread exits within one 500 ms poll. Called by `DesktopApplication.cleanup()`. |

Thread contexts the application does not create itself:

| Context | Owner (module) | Lifetime | How it is stopped |
| --- | --- | --- | --- |
| `MainThread` (UI pump) | `webview.start()` (pywebview/WinForms), called from `DesktopApplication.start` | Long-lived: blocks until the native window is destroyed | `window.destroy()` from `quit_app` (tray `Exit` or `File → Exit`); `webview.start()` returns and `cleanup()` runs in its `finally`. |
| Default-executor workers (asyncio_0, asyncio_1, …) | the `WizConsoleAsyncLoop` loop's default executor thread pool, filled lazily by `asyncio.to_thread` in `application/ambilight_stream.py` (~10 Hz) and `application/music_stream.py` (~10.5 Hz) | Long-lived while the session runs; idle between frames | `BridgeLifecycle.shutdown()` stops both streams first, and `loop.close()` inside `_run_loop` shuts the default executor down (`shutdown(wait=False)`) when the loop exits. |
| PortAudio callback thread (surfaces as `Dummy-N`) | PortAudio/WASAPI: it calls the `stream_callback` closure of `adapters/audio/wasapi_session.py` | Long-lived while the music stream is active: one call per audio buffer | `WasapiLoopbackStreamSession.close()` (`stop_stream`, `close`, `pa.terminate()`), reached from `LightControlService.close_audio_sampler()` inside `shutdown()`. |
| `Thread-N (setup_handler)` | `pystray.Icon.run()` in the fallback view `adapters/tray/pystray_tray.py`; pystray creates it **without a name and without `daemon`** | Short-lived: sets `icon.visible = True` once the pump starts | `pystray.Icon.stop()` joins it with `SETUP_THREAD_TIMEOUT` (5 s) from the thread that calls `TrayView.stop()`. The WinForms view creates no such thread. |

`cli.py` runs `asyncio.run(...)` on the calling thread, so the command-line tool adds no thread of its own.

### Thread Rules

- Every `threading.Thread(` in `src/` keeps an explicit `name=` and `daemon=True`; a new call site without both is a defect.
- Only `WizConsoleTrayRefresh` applies native tray state, and only `WizConsoleMenuSync` re-applies the native window menu: one writer per native surface.
- Only `WizConsoleTrayAction` performs tray menu actions, so a slow UDP call never runs inside a native message pump. The window menu bar dispatches on `MainThread` through pywebview and only re-applies state through `WizConsoleMenuSync`.
- Closing the app releases the long-lived threads (`WizConsoleAsyncLoop`, `WizConsoleTray`, `WizConsoleTrayRefresh`, `WizConsoleSingleInstance`); the short-lived ones (`WizConsoleTrayAction`, `WizConsoleHideOnClose`, `WizConsoleHideOnMinimize`) have already finished by then and are never joined at close.
- **Closing rule:** `DesktopApplication.cleanup()` stops every app-owned thread: it sets `is_quitting` and wakes `WizConsoleMenuSync`, releases the single-instance guard, stops the tray view and its refresh thread, and shuts the bridge loop down. `tests/test_thread_lifecycle.py` proves with `threading.enumerate()` that no app-named thread survives close, using bounded condition waits rather than fixed sleeps.
- **Background polling is silent:** a poller that only re-reads state uses a bridge entry point that does not seal the success envelope (`refresh_tray_states`). Sealing it notifies the view, which requests a native menu sync and a titlebar sync — harmless once, but at five-second intervals it multiplies native work and collides with window teardown. Pollers never use the JavaScript-facing handlers.
- **No live .NET enumerator on a teardown path:** collections reached through pythonnet (`Form.Controls`, `ToolStrip.Items`, `DropDownItems`) are materialised with `list(...)` before being walked. A live iterator that meets a concurrent mutation throws `InvalidOperationException` inside the WinForms message loop, where the default handler raises a modal dialog and freezes shutdown.

---

## 3. Concurrency Safety & Deadlock Prevention

Inter-thread communication between the tray view (`pystray` or WinForms) and `pywebview` (WinForms/WebView2) introduces severe deadlock hazards if locks are held while evaluating menus or restoring windows.

### Case Study: System Tray Menu Deadlock Resolution

In early prototypes, calling `update_menu()` inside `TrayController` while holding an internal lock caused hard lockups (historical, kept here because it explains the current shape):
- `update_menu()` internally invokes dynamic menu generators (`_create_menu()`).
- Those generators queried controller properties (`is_any_on`, `selected_ips`, `favorite_scenes`) that attempted to acquire the same lock.
- If the Win32 message pump was simultaneously dispatching a tray click callback waiting for the lock, a classic AB-BA deadlock occurred.

**Architectural Fix (current design)**:
1. **The state arrives through a seam, not through menu generation**: `TrayController` no longer exposes the properties a live menu reads. It pulls one snapshot per refresh from `TrayActions.get_tray_snapshot()` (implemented by the bridge, which owns the service state and its own timeout), so building a menu can never re-enter the controller.
2. **The lock guards only the cached model**: `_spec`, `_title` and `_theme` sit behind a plain `threading.Lock` taken only by their accessors and by the refresh that publishes them. No lock is held while calling into a `TrayView` or into `pywebview`, which removes the AB-BA hazard structurally instead of by discipline.
3. **One writer per native object**: only the `WizConsoleTrayRefresh` thread applies state to the view (see the threading rule below), so the native menu cannot be mutated from a second thread that would need a lock anyway.

### Tray Menu Threading Rule (T-3.6)

In the `pystray` fallback view, `pystray.Icon.update_menu()` starts by destroying the current `HMENU` and creating a new one. If that happens while the popup menu is displayed, every item ID and every `hSubMenu` already created becomes invalid: clicks cancel silently and submenus stop opening.

The rule enforced by `TrayController` for every view:
- Menu actions only queue work on the executor thread and end with `request_refresh()`; they never touch the view.
- Only the single `WizConsoleTrayRefresh` thread calls `TrayView.apply`, so native tray state always has one writer.
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

When the user closes or minimizes the main window, `wiz_console` intercepts `window.events.closing` / `window.events.minimized`:
- The window is hidden (`window.hide()`) rather than destroyed, allowing the application to continue running in the background. On the first user-initiated close/minimize hide, `_maybe_show_tray_hint()` dispatches a non-blocking localized tray notification (`tray_hint_title` / `tray_hint_message`) and persists `tray_hint_seen: true` in `settings.json` so subsequent hides remain silent.
- When the user clicks "Show window" or double-clicks the tray icon, `TrayController` schedules `window.show()` and `window.restore()` safely onto the main thread using thread-safe event posting.
- Hiding is not enough to leave the task switcher, and the window that hosts the tray message pump is a second one: the main form is genuinely hidden, but the hidden 0×0 tray `Form` stays `IsWindowVisible` for the whole session on purpose. `ShowInTaskbar = false` only removes the taskbar button, so `winforms_host.create_host_form` forces the handle and applies `WS_EX_TOOLWINDOW` before the pump shows it; a visible top-level window without that style is exactly what alt+tab lists as a leftover entry.
- The taskbar button's identity does not come from the window icon: Windows resolves it from the process AppUserModelID. Without one, running from source groups the window under `python.exe` and the button shows the interpreter's logo even though pywebview set the shipped `.ico` on the form. `main()` calls `window_chrome.apply_app_user_model_id()` before the first window exists, and `window_chrome.apply_window_icon()` re-applies the `.ico` with `WM_SETICON` (both icon sizes) on every `shown` event.

### Case Study: Shutdown Collection Race

Quitting from the tray is the only path where the window is destroyed while other threads are still working, so it is where native collections are most likely to change under someone's feet:
- `menu_sync._sync_native_menu` runs on the `MainThread` through `Control.Invoke` and used to walk `native_form.Controls` with a live iterator. During `window.destroy()` that collection is emptied on the same thread, so the walk threw `InvalidOperationException` ("Collection was modified") outside the guarded block, inside the WinForms message loop.
- A CLR exception that reaches the message loop is handled by `Application.ThreadException`: the modal `.NET Framework` dialog blocked `webview.start()` mid-destroy, so `cleanup()` never ran, the tray was never stopped and the process had to be killed. Nothing was logged, because no Python frame was involved any more.
- Fixes that keep the shutdown boring: materialise every .NET collection before walking it, ignore a late `apply()` once the view is stopped (`WinFormsTrayView._apply_native`), and never let a background poller generate view notifications (see the thread rules).

---

## 4. Hardware Rate Limiting & Streaming Architecture

WiZ light bulbs are powered by low-power ESP8266 / ESP32 microcontrollers. Sending UDP packets faster than their internal buffer processing rate causes:
- WiZ device watchdog timer resets (light bulb reboots and flickers).
- Dropped UDP frames and visible stutters.
- Network congestion on 2.4 GHz Wi-Fi channels.

### The 10 Hz Leaky Pacing Mechanism & EMA Smoothing

To protect device integrity, `StreamRateLimiter` enforces a strict leaky-pacing window ($\Delta t \ge 100\text{ ms}$, max rate $= 10\text{ Hz}$) per target bulb IP alongside an Exponential Moving Average (EMA) color filter:

$$\vec{C}_{\text{smoothed}} = \alpha \cdot \vec{C}_{\text{new}} + (1 - \alpha) \cdot \vec{C}_{\text{prev}}$$

Where $\alpha \in [0.1, 0.4]$ controls the smoothing factor (lower $\alpha$ produces fluid cinema transitions; higher $\alpha$ prioritizes fast gaming reactivity). `StreamRateLimiter.prepare_frame()` rejects non-finite smoothing values (`NaN`/`Inf`) and advances `_TargetStreamState` beyond the EMA deadband threshold so small color changes converge completely instead of stalling.

---

## 5. Persistence & Storage Strategy

Application settings, custom presets, and known bulb configurations are stored locally in the user's application data directory:

$$\text{Path: } \%\text{LOCALAPPDATA}\%\backslash\text{WizConsole}\backslash$$

On the first launch after upgrading from `GestorDeLuces`, `resolve_default_data_dir()` atomically copies existing `bulbs.json`, `custom_scenes.json`, and `settings.json` from `%LOCALAPPDATA%\GestorDeLuces` (or `~/.gestor_de_luces` outside Windows) without deleting the legacy backup.

Files managed:
- `bulbs.json`: Discovered and manually added bulb IPs, MAC addresses, module types, and user-assigned aliases (re-validated via `validate_local_endpoint()` on load).
- `custom_scenes.json`: User-created custom lighting scenes (mode, RGB, CCT, brightness, speed, favorite flag).
- `settings.json`: Global user preferences (`language`: `"en"` or `"es"`, `theme`: `"architectural-stone"` or `"atmospheric-dark"`, and optional `tray_hint_seen`: `true` once the first hide-to-tray notice has been displayed).

### Atomic File Write & Read Hardening

To prevent JSON corruption, tampering, or unbounded reads, repositories in `adapters/storage/json_repositories.py` enforce input file-size caps and strict schema validation on load, and follow an atomic replacement protocol on write:
1. Serialize JSON payload to an in-memory buffer.
2. Create a unique temporary file in the same directory via `tempfile.mkstemp` (`.<filename>.<random>.tmp`).
3. Write, flush, and synchronize the file descriptor (`flush()` + `os.fsync()`).
4. Atomically replace the target file via `os.replace()`, guaranteeing an all-or-nothing filesystem transaction on NTFS.


---

## 6. Desktop Shell, Autostart & Packaging

### Native Menu Bar & Theme Synchronization
`adapters/ui_webview/app_menu.py` is a pure model of the window menu (File: Show/Hide, Start with Windows, Exit; Help: Keyboard shortcuts, About) and localized window title (`build_window_title`). The About entry opens a native message box that reports the display name, the resolved version, the licence, the author and the repository from module constants, so it reads the same from source and from a frozen build (which ships neither `pyproject.toml` nor importlib metadata). `DesktopApplication.start()` passes the menus to `webview.start(menu=...)` and `create_window()` initializes the localized window title. pywebview 6.2.1 menus are static (no checkable items, no update API, and unstyled system `MenuStrip` chrome), so `DesktopApplication` updates labels/checks in place via `menu_sync._sync_native_menu`, updates the native window title via `sync_window_title()`, and themes the live `MenuStrip`, its top-level items, dropdowns, and separators via `menu_sync._sync_native_menu_theme` using `THEME_PALETTES` and idempotent `ToolStripItem.Paint` + `Opened` chrome handlers (avoiding `ProfessionalColorTable` subclassing under `pythonnet 3.2.1`). Exit follows the same shutdown path as the tray's `Exit` action.

### Autostart (`--minimized`)
The `AutostartManager` port (`ports/autostart.py`) is implemented by `WindowsRegistryAutostart` (`adapters/system/windows_autostart.py`), which writes the `WizConsole` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. The registered command is `<exe> --minimized` when frozen and `pythonw -m wiz_console.main --minimized` in development. On every launch, `refresh_if_stale` migrates any legacy `GestorDeLuces` entry to `WizConsole` and rewrites stale paths (for example after moving the portable folder). The registry is injectable, so tests never touch `HKCU`.

### Single Instance
`adapters/system/single_instance.py` (`SingleInstanceGuard`) combines a named mutex with a named event protected by an explicit SDDL DACL (`SY`/`BA`/`OW`), guarding Win32 handles against `ERROR_ACCESS_DENIED` and `WAIT_FAILED` while cleaning up handles deterministically on release. A second launch signals the event and exits; the first instance reacts by showing its window (unless bypassed via `--multi-instance` for side-by-side diagnostics).

### Multi-Theme Engine & Dynamic Widget Geometry
- **3-Tier CSS Token Architecture & Compositor Performance**: `ui/themes.css` defines primitive, semantic, and component-level tokens for both `"architectural-stone"` (default warm mineral Light theme with WCAG AA contrast tokens `--ink-2`, `--ink-3`, `--accent-favorite`) and `"atmospheric-dark"` (translucent glass Dark theme with `oklab` photometric halo and distinct primary CTA tokens `--primary-btn-bg` / `--primary-btn-ink`), consumed by `ui/styles.css`. Global `[hidden] { display: none !important; }` prevents `display: flex` overrides on hidden field groups, `@container stage (max-width: 480px)` adapts the mode tabs into a 3×2 grid cleanly without clipping, expensive `backdrop-filter` rules are scoped away from high-count cards and buttons, `.music-meter-fill` animates strictly via compositor `transform: scaleX(var(--meter-scale, 0))`, and `@media (prefers-reduced-motion)` avoids global zero-duration hacks while `:focus-visible`, `:focus-within`, and `@media (forced-colors: active)` preserve keyboard visibility.
- **Native Window Chrome & Zero-Flash Theme/Language Boot (`THEME_WINDOW_CHROME`)**: `DesktopApplication.create_window()` reads persisted theme and language before creating the PyWebView window to set the initial WebView2 `background_color` (`#F4F1EA` or `#08090C`) and localized window title, passes `#theme=<theme>&lang=<lang>` via `_build_initial_ui_url()`, and delegates the Windows DWM titlebar attribute (`DwmSetWindowAttribute` `DWMWA_USE_IMMERSIVE_DARK_MODE = 20` with `0` for light or `1` for dark), WinForms `MenuStrip` theming (`_sync_native_menu_theme`), and cached `HICON` lifecycle (`release_window_icons()`) to `adapters/platform/windows/`. Before `themes.css` loads, `ui/js/theme-boot.js` runs synchronously in `<head>` to set `data-theme`, `data-lang`, `html[lang]`, and `<meta name="color-scheme">` from the URL fragment or `localStorage`, and `ui/i18n.js` synchronously calls `translateDom()` on load when `data-lang !== "en"`, eliminating both theme FOUC and untranslated-language flashes prior to `app.js` initialization.
- **Content-Driven Window Height Auto-Fit**: `adapters/platform/windows/window_geometry.py` implements `_fit_native_window_height` using 64-bit-safe Win32 `ctypes` (`GetWindowRect`, `GetClientRect`, `SetWindowPos`) marshaled onto the WinForms UI thread (`native_form.Invoke`), clamped across multi-monitor `WorkingArea` bounds and high-DPI scaling via `WebviewBridge.fit_window_height`.

### Frontend Serving, IPC Bridge & Reactive Polling
The frontend is served over hardened loopback HTTP so `ui/js/` loads as native ES modules (Chromium blocks `type="module"` over `file://`). `DesktopApplication.create_window()` builds the cache-busted local URL via `_build_initial_ui_url()` (`?v=<bust>#theme=<theme>&lang=<lang>`) and `start()` runs `webview.start(http_server=True, server=NoCacheBottleServer, ...)`:

- **Hardened Loopback HTTP (`NoCacheBottleServer`)**: Binds explicitly to `127.0.0.1` on an ephemeral or configured port, uses a cryptographically random `secrets.token_urlsafe(24)` server ID, disables pywebview's HTTP JS-API callback endpoint (`server.js_api_endpoint = None`) and wildcard CORS (`Access-Control-Allow-*` headers removed), enforces `GET`/`HEAD` methods only, validates `Host` and `Origin` headers plus a `64 KiB` `Content-Length` limit, and attaches strict cache-control and `SECURITY_HEADERS` including CSP (`frame-ancestors 'none'`).
- **Whitelist-Exposed Native IPC (`BlockedJsApi` + `window.expose`)**: Rather than exposing the full `JsApi` object attribute tree on `window.pywebview.api` (which would permit dotted `getattr` traversal), `DesktopApplication` binds a `BlockedJsApi` wrapper as `js_api` and registers only the explicitly curated callables returned by `build_exposed_functions(js_api)` via `window.expose(...)`. `handlers.py` validates finite numbers (`NaN`/`Inf`/`OverflowError`/`bool` rejected) and sanitizes exceptions returned to JavaScript.
- **Resilient Frontend Bridge & Delta Polling (`ui/js/`)**: `bridge-client.js` awaits `pywebviewready` with a 2000 ms fallback while still upgrading to the native bridge on late `pywebviewready` events, returns semantic `boolean` success from `invokeApi()`, drops stale out-of-order responses via monotonic request sequencing, and deduplicates overlapping calls via `dedupeKey`. `app.js` uses lightweight delta endpoints (`get_ambilight_status`, `get_music_sync_status`) for live stream meters, triggers a silent `refreshStates()` when a stream stops, performs selective panel DOM updates while protecting focused inputs (`#input-hex`, `bindSliderInteraction()` active sliders, scene/bulb inputs), and retains focus across `replaceChildren()` re-renders via `captureFocusKey`/`restoreFocusKey`.
- **Accessible Controls & Safe UX Flows**: `#toast-region` renders in Chromium's top layer (`popover="manual"`) above native `<dialog>` drawers and supports action buttons (5-second **Undo** before deleting custom presets, flushed on `beforeunload`). Dialogs validate IPv4/required fields inline before closing, `#stage-empty-banner` guides 0-bulb / 0-selected states cleanly, interactive targets enforce `>= 24×24px`, `#select-all-fixtures` reflects `.indeterminate` state, `aria-pressed` tracks toggle/preset groups, and keyboard navigation supports `Space` power, `Alt+ArrowUp`/`Alt+ArrowDown` brightness (keeping bare arrows for vertical scrolling), `Home`/`End` across `.mode-tabs`, and localized `aria-valuetext` on `#color-wheel-canvas` alongside unnested card controls (`.scene-card-trigger` + sibling `.scene-fav-btn`).

### Internationalization (i18n) Ownership · single source of truth
Translations have a **single owner per domain** (Gate 2 / T-2.3):

- **Backend owns tray strings and domain errors only.** The tray menu labels and one-time hide-to-tray notification strings live in `adapters/tray/menu_model.py` (`_TRAY_STRINGS`), because the system tray has no access to the web UI. Their keys are `snake_case` with no namespace (`hide_window`, `turn_off`, `brightness`, `tray_hint_title`, …).
- **The UI owns every on-screen string.** All visible page text lives in `ui/i18n.js` (`DICTIONARIES`), keyed as `namespace.camelCase` (`rail.scanBtn`, `stage.turnOff`, `shortcuts.brightness`, …). Dynamic backend descriptors (Ambilight monitor widths/heights, WASAPI audio devices, enum status values, and built-in scene `#19` summaries) are also formatted into localized UI labels by `ambilight.js`, `music.js`, and `scenes.js`.

The two conventions are deliberately incompatible so a literal key can never collide: `tests/test_i18n.py::test_i18n_single_owner_backend_tray_vs_ui_screen` enforces that no `_TRAY_STRINGS` key appears as a screen key and vice-versa, and `tests/js/stage4-copy-i18n.test.js` enforces EN/ES dictionary parity and zero unreferenced keys. When adding a string, put it in the domain that owns it; never mirror the same key in both places.

### Packaging
`scripts/build.ps1` generates the icon (`assets/icon/make_icon.py`), runs PyInstaller with `packaging/wiz_console.spec` (one-folder, windowed, bundling `ui/` and `assets/` while excluding helper `*.py` scripts such as `make_icon.py`), signs `WizConsole.exe` **before** archiving into the portable ZIP and Inno Setup installer (`packaging/installer.iss`, per-user, preserving `AppId` for upgrades, `runasoriginaluser`, `HKCU\...\Run` cleanup for both `WizConsole` and legacy `GestorDeLuces` on uninstall, and English/Spanish `[CustomMessages]`), signs the installer with HTTPS RFC 3161 timestamping (`https://timestamp.digicert.com`) when `SIGN_CERT_SHA1` is provided, and writes `dist/SHA256SUMS.txt`. `resources.py` resolves assets from `sys._MEIPASS` when frozen. User data always stays in `%LOCALAPPDATA%\WizConsole`. The checksum file is written with LF and no BOM on purpose: `Set-Content -Encoding UTF8` adds a BOM and CRLF, and on Linux/macOS `sha256sum -c` then reads the carriage return as part of the file name and every line fails with `FAILED open or read`.

### Release Pipeline (`release.yml`)

The same script is what CI runs, so a release is never assembled by hand and the local build path cannot drift from the published one. All third-party actions are pinned to 40-character commit SHAs, Inno Setup is pinned (`6.7.1`), the workflow defaults to `permissions: contents: read`, and `contents: write` is scoped strictly to `publish`. Four jobs, each one cheap enough to fail early:

| Job | Runner | What it decides |
|---|---|---|
| `guard` | `ubuntu-latest` | Resolves the version once — from the tag on a `v*` push, from a mandatory input on `workflow_dispatch`, because on a manual run `GITHUB_REF_NAME` is the branch — and fails when it does not match `pyproject.toml` or when `docs/releases/<version>.md` is missing. |
| `build` | `windows-latest` | Installs the `dev` extra (PyInstaller ships in it) plus Inno Setup (`6.7.1`) from Chocolatey, runs `scripts/build.ps1` with no version argument, uploads `dist/`. |
| `verify` | `windows-latest` | Compares the artifact set against the three expected names, runs `sha256sum -c SHA256SUMS.txt` and `WizConsole.exe --smoke-test` on the frozen build. Counts files only, because `dist/` also holds the one-folder app directory. |
| `publish` | `ubuntu-latest` | Creates a draft release (reusing one left by a re-run), uploads with `--clobber`, re-verifies each asset's GitHub digest against the local SHA-256, and only then un-drafts. A `concurrency` group keyed by tag keeps two runs of the same tag from interleaving their publish steps. |

A `dry_run` run executes every step up to the un-draft and then deletes its throwaway draft, which is how the pipeline is rehearsed without publishing anything. The workflow needs no secret beyond the default `GITHUB_TOKEN`; binaries stay unsigned until a certificate and `SIGN_CERT_SHA1` exist.
