# Diseño de Arquitectura y Modelo de Concurrencia

[English](architecture.md) | [Español](architecture.es.md)

Este documento detalla los fundamentos arquitectónicos, las capas estructurales, las topologías de hilos y los mecanismos de sincronización de concurrencia utilizados en **WiZ Architectural Lighting Console** (`wiz_console`).

---

## 1. Filosofía de Arquitectura: Puertos y Adaptadores (Hexagonal)

El principio rector del proyecto es el **aislamiento riguroso de las reglas de negocio e invariantes del dominio frente a detalles de infraestructura volátiles** (como sockets de red, librerías de interfaz gráfica, controladores de audio del sistema operativo o el sistema de archivos).

```
                                 ADAPTADORES PRIMARIOS
                             (Interfaces Entrantes / Driving)
            +-------------------------+     +-------------------------+
            |  PyWebView (WebView2)   |     |   Bandeja del Sistema   |
            |     WebviewBridge       |     |     TrayController      |
            +------------+------------+     +------------+------------+
                         |                               |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |      SERVICIO DE APLICACIÓN   |
                         |     (LightControlService)     |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |        MODELO DE DOMINIO      |
                         |   (Bulb, State, Color, Scene) |
                         +---------------+---------------+
                                         |
                         +---------------+---------------+
                         |                               |
                         v                               v
            +-------------------------+     +-------------------------+
            |  Puerto LightController |     |  Almacenamiento y Audio |
            +------------+------------+     +------------+------------+
                         |                               |
            +------------+------------+     +------------+------------+
            |    WizUdpController     |     |   JsonRepositories      |
            |   (UDP 38899 Local)     |     |   MssScreenSampler      |
            |                         |     |   WasapiAudioSampler    |
            +-------------------------+     +-------------------------+
                                ADAPTADORES SECUNDARIOS
                             (Interfaces Salientes / Driven)
```

### Separación de Responsabilidades por Capa

1. **Capa de Dominio (`wiz_console.domain`)**:
   - Aloja las entidades centrales (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`), los Objetos de Valor (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`), validación de endpoints (`validate_local_endpoint`) y las invariantes de preferencias globales de interfaz en `value_objects.py` (`SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, `SUPPORTED_THEMES` (`"architectural-stone"`, `"atmospheric-dark"`) y `DEFAULT_THEME` (`"architectural-stone"`)).
   - Libre de dependencias externas: no importa librerías de red, APIs de Windows ni frameworks de interfaz de usuario.
   - Aplica invariantes de negocio (enteros RGB entre 0 y 255, rangos de temperatura Kelvin entre 2.200 K y 6.500 K, validación de endpoints IPv4 locales unicast rechazando direcciones sin especificar, broadcast o multicast, y códigos de idioma y tema permitidos).

2. **Capa de Puertos (`wiz_console.ports`)**:
   - Define contratos mediante `typing.Protocol` con el decorador `@runtime_checkable` distribuidos en `light_control.py`, `repositories.py` y `autostart.py`, sin un barril monolítico `interfaces.py`:
     - `LightControlServicePort` (`ports/light_control.py`): Contrato del servicio de aplicación consumido por `DesktopApplication`.
     - `LightController` (`ports/repositories.py`): Define las operaciones de red (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`, `close`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contratos para lectura y escritura del estado persistente.
     - `ScreenSampler`: Contrato para capturar fotogramas y calcular el color representativo de pantalla (`sample_frame`, `sample_average_color`, `list_monitors`, `close`).
     - `AudioSampler`: Contrato para muestrear la energía y el espectro frecuencial del audio del sistema (`sample_frame`, `sample_audio_metrics`, `list_audio_devices`, `close`).
     - `AutostartManager` (`ports/autostart.py`): Contrato de autoinicio en el registro.

3. **Capa de Aplicación (`wiz_console.application`)**:
   - Orquesta los casos de uso mediante `LightControlService` (`service.py`), delegando en servicios específicos (`bulb_control_service.py`, `bulb_inventory_service.py`, `scene_service.py`, `timer_service.py`, `ambilight_service.py`, `music_service.py`, `settings_service.py`) sobre un contexto compartido (`service_context.py`).
   - Recibe fábricas perezosas de muestreo (`screen_sampler_factory`, `audio_sampler_factory`) inyectadas desde la raíz de composición (`main.py`) de modo que las capas internas (`domain`, `ports`, `application`) nunca importan `adapters` (verificado estáticamente vía AST en `tests/test_security_hardening.py`).
   - Separa el cierre de recursos entre `close_audio_sampler()` (invocado mientras `BridgeLifecycle` detiene los flujos activos) y `close_all_resources()` al finalizar el cierre completo, con rotación de logs (`RotatingFileHandler`) y retroceso exponencial ante errores de flujo.
   - Aloja coordinadores especializados protegidos por guardas monotónicas de generación/ID de ejecución (`_generation` / `run_id`) frente a carreras al reiniciar:
     - `StreamRateLimiter`: Asegura una cadencia máxima de 10 Hz para transmisiones de alta frecuencia.
     - `SleepTimerManager`: Gestiona temporizadores no bloqueantes con desvanecimiento lineal progresivo del brillo.
     - `AmbilightStreamManager`: Controla los ciclos periódicos de captura y suavizado de color en pantalla.
     - `MusicSyncStreamManager`: Orquesta el muestreo por WASAPI loopback, el análisis FFT y el mapeo de frecuencias a color.

4. **Capa de Adaptadores e Infraestructura (`wiz_console.adapters`)**:
   - Implementa los puertos conectando con el hardware y el sistema operativo:
     - `adapters.wiz.udp_controller`: Gestiona el descubrimiento por broadcast UDP y los datagramas JSON-RPC unicast mediante `pywizlight`.
     - `adapters.storage.json_repositories`: Implementa la persistencia atómica en disco dentro de `%LOCALAPPDATA%\WizConsole` (migrando automáticamente los archivos de `%LOCALAPPDATA%\GestorDeLuces` en el primer arranque).
     - `adapters.ambilight.mss_sampler`: Implementa `ScreenSampler` accediendo al búfer GDI de Windows con `mss` y recuperación controlada ante `ScreenShotError`.
     - `adapters.audio.wasapi_sampler`: Implementa `AudioSampler` capturando la salida del sistema con `PyAudioWPatch` (`wasapi_session.py`, `wasapi_devices.py`) bajo bloqueo de ciclo de vida COM/sesión, recuperación ante desconexión en caliente, cierre sin fugas y caché de planes/búferes FFT en `wasapi_capture.py`.
     - `adapters.platform.windows`: Aísla el cromado DWM Win32 y caché de iconos (`window_chrome.py`), geometría multimonitor `WorkingArea` y DPI (`window_geometry.py`), foco de ventana (`foreground.py`), sincronización y tematizado claro/oscuro del `MenuStrip` nativo (`menu_sync.py`, `menu_state.py`) y diálogos (`message.py`).
     - `adapters.tray`: Integra la bandeja del sistema detrás de un contrato mínimo `TrayView`:
      - `tray_icon`: `TrayController` posee el modelo de menú, los handlers, el ejecutor, `show_notification` y el único hilo de refresco sincronizado por variable de condición (`_refresh_cond`); no importa ningún toolkit gráfico.
      - `tray_view`: protocolo `TrayView` (`run`/`stop`/`apply`) más el mapeo modelo→acción y el generador del icono.
      - `winforms_tray`: punto de entrada de la vista principal. `create_winforms_view` y `WinFormsTrayView` componen las piezas de abajo, conservan la política de aplicación (icono/tooltip siempre, rebuild del menú diferido mientras el menú está visible) y exponen `notify()` (`ShowBalloonTip`); reexporta la superficie que ya importaban sus consumidores.
      - `winforms_host`: el host STA. Resolución perezosa de pythonnet/WinForms, `CoInitializeEx`, el `Form` oculto de 0×0 protegido con `IsHandleCreated` —marcado `WS_EX_TOOLWINDOW` sobre el handle recién creado, así una ventana visible, transparente y minimizada nunca aparece como entrada del alt+tab—, `Application.Run(form)` y el marshalling con `Control.Invoke`. Ningún otro módulo importa .NET por su cuenta.
      - `winforms_icon`: `NotifyIcon` más una caché de `HICON` por color que destruye los handles reemplazados, y el límite de 63 caracteres del tooltip.
      - `winforms_menu`: construye el `ContextMenuStrip` y sus submenús desde el modelo puro `TrayMenuEntry`, es dueño de las firmas de menú/estado y engancha el acabado de ventana a cada superficie de menú.
      - `winforms_paint`: paletas por tema, parseo de colores, liberación previa de `Region` y toda la operación de dibujo (painter de filas, hover, punto de nivel activo, chevron de submenú, separadores, geometría de la región redondeada escalada por DPI y el recorte de la `Region`).
      - `pystray_tray`: vista de respaldo (menú Win32 clásico + `notify()`) cuando pythonnet/WinForms no puede cargar.
     - `adapters.ui_webview.bridge`: Expone funciones puntuales autorizadas explícitamente hacia Edge WebView2 (`BlockedJsApi` sobre `js_api` más `window.expose(*build_exposed_functions(js_api))`), bloqueando el recorrido por atributos encadenados (`getattr`) desde JavaScript. El adaptador se divide en `dispatch` (`BlockedJsApi`, `build_exposed_functions`, `JsApi` y ajuste de ventana), `handlers` (validación estricta de tipos y valores finitos, sanitización de errores y sondeo delta para Ambilight/Music Sync), `http_server` (`NoCacheBottleServer`) y `lifecycle` (`BridgeLifecycle` bajo `_loop_state_lock`, cancelación de tareas agotadas, sellado de envelopes, notificaciones de estado, `refresh_tray_states` y apagado); `bridge.py` mantiene `WebviewBridge` y reexporta la superficie pública.

---

## 2. Modelo de Concurrencia y Topología de Hilos

La aplicación declara ocho hilos con nombre y además ejecuta cuatro contextos de hilo que no crea ella misma. Todos deben interactuar fluidamente sin congelar la interfaz gráfica, sin perder paquetes de streaming y sin generar bloqueos mutuos (*deadlocks*). El inventario de abajo sale de `grep -rn "threading.Thread(" src/` y de seguir el ciclo de vida de cada hilo; lo verifica `tests/test_thread_lifecycle.py`.

```
+-------------------------------------------------------------------------------+
| HILO 1: Hilo de Interfaz WinForms / PyWebView (Punto de Entrada del Proceso)  |
|   - Administra el HWND de Windows y el motor Edge WebView2.                   |
|   - Despacha eventos del DOM y ejecuta JavaScript.                            |
+-------------------------------------------------------------------------------+
       |                                                                ^
       | Llamada síncrona a la API JS                                   | Notificación de Estado
       v                                                                |
+-------------------------------------------------------------------------------+
| HILO 2: Bucle de Eventos Asíncrono Dedicado (WizConsoleAsyncLoop)             |
|   - Ejecuta todo el I/O de red, corrutinas y flujos de servicio.              |
|   - Recibe tareas mediante asyncio.run_coroutine_threadsafe().                |
|   - Se comunica directamente con los sockets de WizUdpController.             |
+-------------------------------------------------------------------------------+
       ^                                                                ^
       | Snapshot periódico de estado                                   | Paquetes de streaming
       v                                                                |
+--------------------------------------+   +------------------------------------+
| HILO 3: Vista de la Bandeja          |   | HILO 4: Hilos de Streaming Continuo|
|   - `NotifyIcon` + menú contextual   |   |   - Bucle de Ambilight a 10 Hz     |
|     en su propio hilo STA (WinForms).|   |   - Callback de audio por WASAPI   |
|   - Vista de respaldo con `pystray`. |   |   - Hilo de análisis espectral FFT |
+--------------------------------------+   +------------------------------------+
```

### Inventario de Hilos (cada `threading.Thread(` en `src/`)

Cada llamada pasa un `name=` explícito y `daemon=True`: un `stop()` omitido no puede mantener vivo el proceso y todo hilo es identificable en `threading.enumerate()`. La columna `name` es el valor exacto de `threading.Thread.name`.

| Hilo (`name=`) | Dueño (módulo → creador) | Vida | Cómo se detiene |
| --- | --- | --- | --- |
| `WizConsoleAsyncLoop` (`ASYNC_LOOP_THREAD_NAME`) | `adapters/ui_webview/lifecycle.py` → `BridgeLifecycle._start_async_loop`, arrancado por `WebviewBridge.__init__` | Larga: uno por sesión, ejecuta el bucle `asyncio` privado del puente (`loop.run_forever()`) | `WebviewBridge.shutdown()` coordina el estado bajo `_loop_state_lock`, cancela los flujos activos y tareas agotadas, libera el muestreador de audio, llama `loop.call_soon_threadsafe(loop.stop)` y `thread.join(timeout=2.0)`. Idempotente tras `_shutdown_lock`; lo invocan `DesktopApplication.cleanup()` y el evento `closed` de la ventana. |
| `WizConsoleTray` (`ICON_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start`, ejecuta `TrayView.run` | Larga: el bombeo nativo de mensajes de la vista (WinForms `Application.Run` en un hilo STA, o `pystray.Icon.run`) durante toda la sesión | `TrayController.stop()` marca `_stopped` y llama `TrayView.stop()` (WinForms cierra el form oculto, `pystray` detiene el icono), así que `run` retorna. Seguro de invocar varias veces y desde cualquier hilo. |
| `WizConsoleTrayRefresh` (`REFRESH_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start` → `_refresh_worker` | Larga: espera en `_refresh_cond` con el timeout de `poll_interval` (5 s) | El mismo `TrayController.stop()`: adquiere `_refresh_cond`, marca `_stopped` y notifica, y el worker sale por la bandera. Es el único escritor del estado nativo de la bandeja (T-3.6). Solo un ciclo nacido del timeout (periódico) le pide al puente una lectura real `getPilot` mediante `refresh_tray_states`, que no sella el sobre de éxito; un refresco pedido por una acción conserva el cache que esa acción acaba de escribir. |
| `WizConsoleTrayAction` (literal en `_default_executor`) | `adapters/tray/tray_icon.py` → `TrayController.dispatch` → `_run_action` | Corta: un hilo por acción de menú despachada | Termina solo; nadie lo une (*join*). `quit_app` no desmonta la bandeja desde este hilo a propósito: el desmontaje ocurre después en `cleanup()`. |
| `WizConsoleMenuSync` (`MENU_SYNC_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.start` → `_menu_sync_worker` | Larga: espera en `_menu_sync_cond` (respaldado por `_state_lock`) y reaplica en vivo el `MenuStrip` nativo (pywebview no tiene API de actualización de menú) | `DesktopApplication.cleanup()` marca `is_quitting` bajo `_state_lock`, notifica `_menu_sync_cond` y el bucle sale antes de reaplicar. `DesktopApplication` mantiene además `_visibility_generation` para evitar carreras entre eventos de ocultar/mostrar y suprime sincronizaciones de barra/menú durante el arrastre de controles de luz. |
| `WizConsoleHideOnClose` (`HIDE_ON_CLOSE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_closing` (evento `closing` de la ventana) | Corta: llama `_hide_if_generation(generation, show_tray_hint=True)` y termina | Termina sola. pywebview dispara `closing` de forma síncrona en el hilo GUI con `should_lock`, así que ocultar dentro del manejador podría reentrar o bloquearse; de ahí el hilo. Emite el aviso único persistido en el primer ocultamiento. |
| `WizConsoleHideOnMinimize` (`HIDE_ON_MINIMIZE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_minimized` (evento `minimized` de la ventana) | Corta: llama `_hide_if_generation(generation, show_tray_hint=True)` y termina | Termina sola, por la misma razón que el cierre. |
| `WizConsoleSingleInstance` (literal en `listen`) | `adapters/system/single_instance.py` → `SingleInstanceGuard.listen` | Larga: sondea `WaitForSingleObject(handle, 500 ms)` esperando un segundo lanzamiento | `SingleInstanceGuard.release()` marca `self._stop` y el hilo sale dentro de un sondeo de 500 ms. Lo llama `DesktopApplication.cleanup()`. |

Contextos de hilo que la aplicación no crea:

| Contexto | Dueño (módulo) | Vida | Cómo se detiene |
| --- | --- | --- | --- |
| `MainThread` (bombeo de UI) | `webview.start()` (pywebview/WinForms), invocado desde `DesktopApplication.start` | Larga: bloquea hasta que la ventana nativa se destruye | `window.destroy()` desde `quit_app` (Salir en bandeja o Archivo → Salir); `webview.start()` retorna y `cleanup()` corre en su `finally`. |
| Workers del ejecutor por defecto (asyncio_0, asyncio_1, …) | el pool por defecto del bucle `WizConsoleAsyncLoop`, poblado de forma perezosa por `asyncio.to_thread` en `application/ambilight_stream.py` (~10 Hz) y `application/music_stream.py` (~10.5 Hz) | Larga mientras corre la sesión; inactivos entre fotogramas | `BridgeLifecycle.shutdown()` detiene ambos flujos primero, y `loop.close()` dentro de `_run_loop` apaga el ejecutor por defecto (`shutdown(wait=False)`) al salir el bucle. |
| Hilo de callback de PortAudio (aparece como `Dummy-N`) | PortAudio/WASAPI: invoca el closure `stream_callback` de `adapters/audio/wasapi_session.py` | Larga mientras el flujo de música está activo: una llamada por búfer de audio | `WasapiLoopbackStreamSession.close()` (`stop_stream`, `close`, `pa.terminate()`), alcanzado desde `LightControlService.close_audio_sampler()` dentro de `shutdown()`. |
| `Thread-N (setup_handler)` | `pystray.Icon.run()` en la vista de respaldo `adapters/tray/pystray_tray.py`; pystray lo crea **sin nombre y sin `daemon`** | Corta: marca `icon.visible = True` cuando arranca el bombeo | `pystray.Icon.stop()` lo une con `SETUP_THREAD_TIMEOUT` (5 s) desde el hilo que llama `TrayView.stop()`. La vista WinForms no crea ese hilo. |

`cli.py` ejecuta `asyncio.run(...)` en el hilo llamador, así que la herramienta de línea de comandos no agrega hilos propios.

### Reglas de Hilos

- Cada `threading.Thread(` en `src/` conserva un `name=` explícito y `daemon=True`; un sitio nuevo sin ambos es un defecto.
- Solo `WizConsoleTrayRefresh` aplica el estado nativo de la bandeja, y solo `WizConsoleMenuSync` reaplica el menú nativo de la ventana: un escritor por superficie nativa.
- Solo `WizConsoleTrayAction` ejecuta acciones del menú de bandeja, así que una llamada UDP lenta nunca corre dentro de un bombeo nativo. La barra de menú de la ventana despacha en `MainThread` a través de pywebview y solo reaplica estado mediante `WizConsoleMenuSync`.
- Cerrar la aplicación libera los hilos de vida larga (`WizConsoleAsyncLoop`, `WizConsoleTray`, `WizConsoleTrayRefresh`, `WizConsoleSingleInstance`); los de vida corta (`WizConsoleTrayAction`, `WizConsoleHideOnClose`, `WizConsoleHideOnMinimize`) ya terminaron para entonces y nunca se unen al cerrar.
- **Regla de cierre:** `DesktopApplication.cleanup()` detiene todos los hilos de la app: marca `is_quitting` y despierta a `WizConsoleMenuSync`, libera la instancia única, detiene la vista de bandeja y su hilo de refresco, y apaga el bucle del puente. `tests/test_thread_lifecycle.py` demuestra con `threading.enumerate()` que ningún hilo con nombre de la app sobrevive al cierre, usando esperas acotadas por condición y no `sleep` fijos.
- **El sondeo de fondo es silencioso:** un sondeo que solo relee estado usa un punto de entrada del puente que no sella el sobre de éxito (`refresh_tray_states`). Sellarlo notifica a la vista, que pide un refresh del menú nativo y de la barra de título: inofensivo una vez, pero cada cinco segundos multiplica trabajo nativo y choca con el desarme de la ventana. Los sondeos nunca usan los handlers que se exponen a JavaScript.
- **Ningún enumerador vivo de .NET en un camino de desarme:** las colecciones que llegan por pythonnet (`Form.Controls`, `ToolStrip.Items`, `DropDownItems`) se materializan con `list(...)` antes de recorrerlas. Un iterador vivo que se cruza con una mutación lanza `InvalidOperationException` dentro del bombeo de mensajes de WinForms, donde el handler por defecto abre un diálogo modal y congela el cierre.

---

## 3. Seguridad de Concurrencia y Prevención de Deadlocks

La comunicación entre hilos entre la vista de bandeja (`pystray` o WinForms) y `pywebview` (WinForms/WebView2) requiere un cuidado especial con el orden de adquisición de bloqueos.

### Caso de Estudio: Resolución del Bloqueo Mutuo en el Menú de la Bandeja

En prototipos iniciales, invocar `update_menu()` dentro de `TrayController` manteniendo un cerrojo interno provocaba bloqueos completos (histórico, se conserva porque explica la forma actual):
- `update_menu()` invoca internamente generadores dinámicos de menú (`_create_menu()`).
- Dichos generadores consultaban propiedades del controlador (`is_any_on`, `selected_ips`, `favorite_scenes`) que intentaban adquirir el mismo bloqueo.
- Si simultáneamente el despachador de eventos Win32 procesaba un clic del usuario esperando dicho bloqueo, se producía un clásico deadlock AB-BA.

**Solución Arquitectónica (diseño vigente)**:
1. **El estado llega por una costura, no generando el menú**: `TrayController` ya no expone las propiedades que leía un menú vivo. Pide una instantánea por refresco a `TrayActions.get_tray_snapshot()` (la implementa el puente, dueño del estado del servicio y de su propio timeout), así que construir un menú no puede reentrar en el controlador.
2. **El cerrojo protege solo el modelo cacheado**: `_spec`, `_title` y `_theme` viven detrás de un `threading.Lock` común que solo toman sus accesores y el refresco que los publica. Nunca se sostiene un cerrojo mientras se llama a una `TrayView` o a `pywebview`, lo que elimina el riesgo AB-BA por estructura y no por disciplina.
3. **Un único escritor por objeto nativo**: solo el hilo `WizConsoleTrayRefresh` aplica estado a la vista (ver la regla de hilos más abajo), así que el menú nativo no puede mutarse desde un segundo hilo que igual necesitaría un cerrojo.

### Regla de Hilos del Menú de Bandeja (T-3.6)

En la vista de respaldo `pystray`, `pystray.Icon.update_menu()` empieza destruyendo el `HMENU` vigente y creando uno nuevo. Si eso ocurre con el menú desplegado, todos los IDs de item y todos los `hSubMenu` ya creados quedan invalidados: los clics cancelan en silencio y los submenús dejan de abrir.

La regla que impone `TrayController` para cualquier vista:
- Las acciones del menú solo encolan trabajo en el ejecutor y terminan con `request_refresh()`; nunca tocan la vista.
- Solo el único hilo `WizConsoleTrayRefresh` llama `TrayView.apply`, de modo que el estado nativo de la bandeja siempre tiene un único escritor.
- La vista decide si el menú nativo se puede reconstruir en ese instante. La vista `pystray` consulta `adapters.platform.windows.menu_state._is_menu_open` (banderas de modo menú del hilo en primer plano vía `GetGUIThreadInfo`) y, si hay un menú abierto, deja el rebuild pendiente y lo reintenta en el próximo `apply`. La vista WinForms difiere mientras su `ContextMenuStrip.Visible` es verdadero y luego reemplaza y libera el menú en el siguiente refresco.

### Render del Menú de Bandeja y Paletas por Tema (T-3.8)

El menú clásico de `pystray` es un popup Win32 que se pinta con la clase de ventana que registra con `hbrBackground = COLOR_WINDOW + 1`, así que siempre usa el fondo blanco del sistema y el texto claro se vuelve ilegible («fondo blanco, letras blancas pareciera, mucho brillo»). Por eso la bandeja usa `System.Windows.Forms.NotifyIcon` + `ContextMenuStrip` como vista principal:

- `TrayView` (`adapters.tray.tray_view`) es el único contrato entre el controlador y una vista: `run()` (bombeo bloqueante), `stop()` y `apply(spec, title, rgb, theme)`. `resolve_entry_action` traduce una hoja del modelo a la acción a despachar, incluida la acción sintética `toggle_window` del ítem por defecto (mostrar/ocultar ventana).
- `winforms_tray` orquesta la política de aplicación y `winforms_menu` traduce el modelo puro `menu_model` a objetos `ToolStripMenuItem` reales: los submenús son `DropDownItems` (WinForms los abre al pasar el cursor, sin hacks de clic), los clics de hoja despachan `(action_id, payload)`, los niveles de brillo usan `CheckOnClick = False` + `Checked`, y una llamada UDP lenta no bloquea nada porque `TrayController` sigue despachando en su ejecutor.
- Los colores vienen de una tabla explícita indexada por el tema activo (`architectural-stone` → clara, `atmospheric-dark` → oscura, desconocido → clara). Fondo, texto, texto deshabilitado, hover (`selection`) y `separator` se aplican al `ContextMenuStrip`, a cada ítem y a cada panel de submenú; `RenderMode = System` evita que el cromo del dropdown repinte un margen de imagen brillante, y el bloque de hover, el texto, el nivel activo y los separadores los dibuja la propia vista (ver T-3.9 abajo).
- Restricción verificada del entorno: pythonnet 3.2.1 sobre .NET Framework 4.8 no emite tipos derivados aquí, así que las subclases Python de `ProfessionalColorTable`/`ToolStripRenderer` no reciben despacho virtual desde .NET. Por eso no hay tabla de colores ni renderer propio y la paleta se aplica control por control.
- Si WinForms no carga, `create_winforms_view` devuelve `None` y la raíz de composición cae a `pystray_tray`, de modo que el icono de bandeja nunca desaparece por un fallo del CLR.

### Acabado Moderno del Menú y Firmas Separadas (T-3.9)

Con `RenderMode = System` la vista todavía daba filas de ~20 px, un borde de 1 px en el color del tema de Windows, esquinas rectas y un resaltado plano del sistema: «parece de Windows 98». Ese borde no se puede recolorear sin subclasificar el renderer, cosa que este build de pythonnet no permite, así que la vista se hace cargo de cada píxel que puede pintar:

- Esquinas: en `ToolStripDropDown.Opened` (el `ContextMenuStrip` superior y cada submenú, suscripto por `winforms_menu.attach_menu_chrome`) la vista llama `winforms_menu.apply_menu_chrome`, que ejecuta `window_chrome._apply_corner_preference` —fijando `DWMWA_WINDOW_CORNER_PREFERENCE` (33) en `DWMWCP_ROUND` (2) con `DwmSetWindowAttribute` y un `dwmapi` inyectable— y después asigna una `Region` redondeada recortada 1 px (`winforms_paint.menu_region_geometry` para la geometría escalada por DPI, `winforms_paint.apply_menu_region` para recortarla). La región recortada es el único mecanismo disponible sin renderer propio que quita el borde de 1 px del renderer; como DWM no redondea ventanas con región propia, la región es la fuente efectiva de las esquinas, y el atributo de DWM es la degradación buena cuando la región no se puede crear.
- Filas: `ToolStripMenuItem.Padding` recibe `MENU_ITEM_PADDING_VERTICAL = 4` por lado, que convierte la fila por defecto de ~20 px en ~28 px.
- Pintado (`winforms_paint`): cada ítem se suscribe a `ToolStripItem.Paint` (se emite después del render del sistema) y dibuja su fondo, bloque de hover, texto, marca de nivel activo y flecha de submenú mediante `item_paint_style`/`paint_menu_item`; los separadores usan `separator_paint_style`/`paint_menu_separator` con `TrayPalette.separator`. El nivel de brillo activo es un punto en el color de texto de la paleta, así que no interviene ni una `Image` generada ni el glifo nativo de color fijo, y el hover usa el `TrayPalette.selection` existente.
- Firmas (`winforms_menu`): `menu_signature(spec, theme)` = `(tuple(spec), theme)` decide un rebuild, y `state_signature(spec, title, rgb, theme)` = `(firma del menú, title, rgb)` decide si cambió algo. Un `rgb` o un `title` distinto con el mismo spec y tema solo asigna `NotifyIcon.Icon`/`NotifyIcon.Text`, sin diferir nada y sin rebuild, así que el log con cinco `Tray menu rebuilt` idénticos en dos segundos no puede volver. Solo el rebuild se difiere mientras `ContextMenuStrip.Visible` es verdadero, `Tray menu rebuilt: [...]` se registra exactamente una vez por rebuild real, y la firma pendiente registra `rebuild deferred (menu open)` una sola vez.
- Cada llamada Win32/WinForms está protegida: un DWM ausente, un `GraphicsPath` no disponible o una región que no se puede crear degradan al marco plano del sistema en lugar de romper el menú.

### Ocultamiento y Restauración de Ventana

Cuando el usuario cierra o minimiza la ventana principal, la aplicación intercepta `window.events.closing` / `window.events.minimized`:
- La ventana se oculta (`window.hide()`) en lugar de destruirse, permitiendo que la aplicación continúe activa en segundo plano. En el primer cierre o minimizado iniciado por el usuario, `_maybe_show_tray_hint()` emite una notificación localizada no intrusiva (`tray_hint_title` / `tray_hint_message`) y persiste `tray_hint_seen: true` en `settings.json` para no repetirla luego.
- Cuando el usuario hace doble clic en la bandeja o selecciona «Mostrar ventana», `TrayController` despacha de forma segura `window.show()` y `window.restore()` en el hilo principal de la ventana.
- Ocultar la ventana principal no alcanza para salir del conmutador, y la ventana que hospeda el bombeo de la bandeja es otra: el `Form` oculto de 0×0 queda `IsWindowVisible` durante toda la sesión a propósito. `ShowInTaskbar = false` solo quita el botón de la barra, así que `winforms_host.create_host_form` fuerza el handle y aplica `WS_EX_TOOLWINDOW` antes de que el bombeo la muestre; una ventana visible de nivel superior sin ese estilo es exactamente lo que alt+tab lista como residuo.
- La identidad del botón de la barra de tareas no sale del icono de la ventana: Windows la resuelve con el AppUserModelID del proceso. Sin él, correr desde el fuente agrupa la ventana bajo `python.exe` y el botón muestra el logo del intérprete aunque pywebview haya puesto el `.ico` del paquete en el formulario. `main()` llama `window_chrome.apply_app_user_model_id()` antes de que exista la primera ventana, y `window_chrome.apply_window_icon()` reaplica el `.ico` con `WM_SETICON` (ambos tamaños) en cada evento `shown`.

### Estudio de Caso: Carrera de Colecciones al Cerrar

Salir desde la bandeja es el único camino donde la ventana se destruye mientras otros hilos siguen trabajando, así que es donde las colecciones nativas tienen más chance de cambiar bajo los pies de alguien:
- `menu_sync._sync_native_menu` corre en el `MainThread` vía `Control.Invoke` y recorría `native_form.Controls` con un iterador vivo. Durante `window.destroy()` esa colección se vacía en el mismo hilo, así que el recorrido lanzaba `InvalidOperationException` ("Colección modificada") fuera del bloque protegido, dentro del bombeo de WinForms.
- Una excepción del CLR que llega al bombeo la maneja `Application.ThreadException`: el diálogo modal de `.NET Framework` bloqueaba `webview.start()` en medio del desarme, así que `cleanup()` nunca corría, la bandeja nunca se detenía y el proceso había que matarlo. No quedaba nada en el log, porque ya no había ningún frame de Python involucrado.
- Los arreglos que mantienen el cierre aburrido: materializar toda colección de .NET antes de recorrerla, ignorar una aplicación tardía cuando la vista ya está detenida (`WinFormsTrayView._apply_native`) y no dejar que un sondeo de fondo genere notificaciones a la vista (ver las reglas de hilos).

---

## 4. Limitación de Frecuencia por Hardware y Streaming

Los focos WiZ están basados en microcontroladores de bajo consumo ESP8266 / ESP32. Enviar paquetes UDP a una tasa superior a la que su procesador puede absorber genera:
- Disparos del temporizador guardián (*watchdog timer*), provocando reinicios y parpadeos en el foco.
- Pérdida masiva de paquetes UDP y saltos visibles en las transiciones de luz.
- Congestión en la banda de 2.4 GHz de la red Wi-Fi.

### Mecanismo de Regulación a 10 Hz y Suavizado EMA

Para garantizar la estabilidad del hardware, `StreamRateLimiter` impone una ventana temporal estricta ($\Delta t \ge 100\text{ ms}$, tasa máxima $= 10\text{ Hz}$) por cada IP de foco junto con un filtro de Media Móvil Exponencial (EMA):

$$\vec{C}_{\text{suavizado}} = \alpha \cdot \vec{C}_{\text{nuevo}} + (1 - \alpha) \cdot \vec{C}_{\text{anterior}}$$

Donde $\alpha \in [0.1, 0.4]$ regula la inercia del color (valores bajos generan transiciones cinematográficas fluidas; valores más altos aumentan la reactividad para juegos). `StreamRateLimiter.prepare_frame()` rechaza factores de suavizado no finitos (`NaN`/`Inf`) y avanza `_TargetStreamState` más allá de la banda muerta del filtro EMA para que cambios pequeños de color converjan por completo sin estancarse.

---

## 5. Estrategia de Persistencia y Almacenamiento

Las preferencias de usuario, las escenas personalizadas y el inventario de focos se almacenan localmente en el directorio de datos de aplicación de Windows:

$$\text{Ruta: } \%\text{LOCALAPPDATA}\%\backslash\text{WizConsole}\backslash$$

En el primer arranque tras actualizar desde `GestorDeLuces`, `resolve_default_data_dir()` copia de forma atómica e idempotente `bulbs.json`, `custom_scenes.json` y `settings.json` desde `%LOCALAPPDATA%\GestorDeLuces` (o `~/.gestor_de_luces` fuera de Windows) conservando los originales como respaldo.

Archivos gestionados:
- `bulbs.json`: Focos descubiertos o agregados manualmente (IP, MAC, modelo y alias de usuario, revalidados al cargar mediante `validate_local_endpoint()`; `discover_bulbs()` reconcilia cambios de IP por DHCP mediante MAC y `remove_bulb()` elimina registros retirados).
- `custom_scenes.json`: Presets personalizados creados por el usuario (modo, RGB, CCT, brillo, velocidad, favorito).
- `settings.json`: Preferencias globales y estado de sesión (`language`, `theme`, `tray_hint_seen` opcional, `selected_ips`, `auto_sync`, `favorite_builtin_scenes`, `ambilight_prefs` y `music_prefs`), consumidos tanto por la interfaz web como por los toggles de la bandeja (`toggle_ambilight` / `toggle_music_sync`).

### Patrón de Escritura Atómica y Endurecimiento de Lectura

Para prevenir corrupción, manipulación o lecturas ilimitadas en disco, los repositorios en `adapters/storage/json_repositories.py` aplican límites de tamaño de archivo y validación estricta de esquema al leer, y siguen un protocolo de reemplazo atómico al escribir:
1. Se serializa la información JSON a un búfer en memoria.
2. Se crea un archivo temporal único en la misma carpeta mediante `tempfile.mkstemp` (`.<archivo>.<aleatorio>.tmp`).
3. Se vuelcan y sincronizan los descriptores con el sistema de archivos (`flush()` + `os.fsync()`).
4. Se reemplaza de forma atómica el archivo de destino mediante `os.replace()`, garantizando una transacción de todo o nada en NTFS.


---

## 6. Shell de Escritorio, Autoinicio y Empaquetado

### Barra de Menú Nativa y Sincronización de Tema
`adapters/ui_webview/app_menu.py` es un modelo puro del menú de la ventana (Archivo: Mostrar/Ocultar, Iniciar con Windows, Salir; Ayuda: Atajos de teclado, Acerca de) y del título localizado (`build_window_title`). La entrada Acerca de abre un cuadro nativo que informa el nombre visible, la versión resuelta, la licencia, el autor y el repositorio desde constantes del módulo, así que se lee igual desde el fuente y desde un build congelado (que no lleva ni `pyproject.toml` ni metadatos de importlib). `DesktopApplication.start()` entrega el menú a `webview.start(menu=...)` y `create_window()` inicializa el título localizado. Los menús de pywebview 6.2.1 son estáticos (sin ítems con tilde ni API de actualización, y con cromado por defecto de Windows), por lo que `DesktopApplication` actualiza etiquetas y tildes en vivo vía `menu_sync._sync_native_menu`, actualiza el título nativo vía `sync_window_title()`, y tematiza el `MenuStrip`, ítems principales, desplegables y separadores mediante `menu_sync._sync_native_menu_theme` usando `THEME_PALETTES` y handlers idempotentes de `ToolStripItem.Paint` y `Opened` (evitando subclasificar `ProfessionalColorTable` por `pythonnet 3.2.1`). Salir sigue el mismo camino de cierre que `Exit` / `Salir` en la bandeja.

### Autoinicio (`--minimized`)
El puerto `AutostartManager` (`ports/autostart.py`) lo implementa `WindowsRegistryAutostart` (`adapters/system/windows_autostart.py`), que escribe el valor `WizConsole` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. El comando registrado es `<exe> --minimized` en la versión empaquetada y `pythonw -m wiz_console.main --minimized` en desarrollo. En cada arranque, `refresh_if_stale` migra automáticamente cualquier entrada legacy `GestorDeLuces` hacia `WizConsole` y reescribe rutas desactualizadas (por ejemplo, al mover la carpeta portable). El registro es inyectable, así que las pruebas nunca tocan `HKCU`.

### Instancia Única
`adapters/system/single_instance.py` (`SingleInstanceGuard`) combina un mutex con nombre y un evento con nombre protegidos por una DACL SDDL explícita (`SY`/`BA`/`OW`), controlando errores `ERROR_ACCESS_DENIED` y `WAIT_FAILED` y liberando los handles de Win32 de forma determinista. Una segunda ejecución señala el evento y termina; la primera instancia responde mostrando su ventana (salvo que se indique `--multi-instance` para ejecución simultánea de diagnóstico).

### Motor Multitema y Geometría Dinámica de Widget
- **Arquitectura de Tokens CSS de 3 Niveles y Rendimiento de Compositor**: `ui/themes.css` define tokens primitivos, semánticos y de componente tanto para `"architectural-stone"` (tema claro predeterminado en piedra mineral cálida con contraste WCAG AA en `--ink-2`, `--ink-3`, `--accent-favorite`) como para `"atmospheric-dark"` (tema oscuro en cristal esmerilado con halo fotométrico `oklab` y tokens diferenciados de CTA primario `--primary-btn-bg` / `--primary-btn-ink`), consumidos por `ui/styles.css`. La regla global `[hidden] { display: none !important; }` evita conflictos con `display: flex`, `@container stage (max-width: 480px)` adapta `.mode-tabs` a grilla 3×2 sin recortes, las reglas costosas de `backdrop-filter` se restringen lejos de tarjetas y botones repetidos, `.music-meter-fill` se anima únicamente mediante `transform: scaleX(var(--meter-scale, 0))` en compositor, y `@media (prefers-reduced-motion)` evita hacks globales mientras `:focus-visible`, `:focus-within` y `@media (forced-colors: active)` preservan el foco visible por teclado.
- **Marco Nativo y Arranque Sin Destello de Tema/Idioma (`THEME_WINDOW_CHROME`)**: `DesktopApplication.create_window()` lee el tema e idioma persistidos antes de crear la ventana para definir el `background_color` inicial de WebView2 (`#F4F1EA` o `#08090C`) y el título localizado, envía `#theme=<theme>&lang=<lang>` vía `_build_initial_ui_url()`, y delega el atributo DWM de la barra de título (`DwmSetWindowAttribute` `DWMWA_USE_IMMERSIVE_DARK_MODE = 20` con `0` claro o `1` oscuro), el tematizado del `MenuStrip` (`_sync_native_menu_theme`) y la caché de `HICON` (`release_window_icons()`) a `adapters/platform/windows/`. Antes de cargar `themes.css`, `ui/js/theme-boot.js` se ejecuta de forma síncrona en `<head>` aplicando `data-theme`, `data-lang`, `html[lang]` y `<meta name="color-scheme">` desde el fragmento o `localStorage`, y `ui/i18n.js` invoca `translateDom()` síncronamente al cargar cuando `data-lang !== "en"`, evitando destellos tanto de tema (FOUC) como de idioma (FOUL) antes de iniciar `app.js`.
- **Autoajuste Dinámico de Altura según Contenido**: `adapters/platform/windows/window_geometry.py` implementa `_fit_native_window_height` mediante llamadas Win32 `ctypes` seguras en 64 bits (`GetWindowRect`, `GetClientRect`, `SetWindowPos`) despachadas en el hilo de interfaz de WinForms (`native_form.Invoke`) y acotadas al `WorkingArea` multimonitor y escalado DPI a través de `WebviewBridge.fit_window_height`.

### Servido del Frontend, Puente IPC y Sondeo Reactivo
El frontend se sirve por HTTP en loopback endurecido para cargar `ui/js/` como módulos ES nativos (Chromium bloquea `type="module"` sobre `file://`). `DesktopApplication.create_window()` arma la URL local con anti-caché vía `_build_initial_ui_url()` (`?v=<bust>#theme=<theme>&lang=<lang>`) y `start()` arranca `webview.start(http_server=True, server=NoCacheBottleServer, ...)`:

- **Servidor HTTP Loopback Endurecido (`NoCacheBottleServer`)**: Enlaza explícitamente `127.0.0.1` en un puerto efímero o configurado, utiliza un identificador criptográfico `secrets.token_urlsafe(24)`, deshabilita el endpoint HTTP de callbacks JS-API de pywebview (`server.js_api_endpoint = None`) y las cabeceras CORS abiertas (`Access-Control-Allow-*`), restringe los métodos a `GET`/`HEAD`, valida las cabeceras `Host` y `Origin` además de un límite de `64 KiB` en `Content-Length`, y adjunta cabeceras de no-caché y `SECURITY_HEADERS` incluida CSP (`frame-ancestors 'none'`).
- **Puente IPC por Lista Blanca (`BlockedJsApi` + `window.expose`)**: En lugar de exponer el árbol completo de atributos de `JsApi` sobre `window.pywebview.api` (lo que permitiría recorrer atributos encadenados con `getattr`), `DesktopApplication` enlaza una instancia de `BlockedJsApi` como `js_api` y registra únicamente las funciones explícitas devueltas por `build_exposed_functions(js_api)` mediante `window.expose(...)`. `handlers.py` valida números finitos (rechazando `NaN`, `Inf`, `OverflowError` y booleanos) y sanea las excepciones devueltas a JavaScript.
- **Cliente de Puente Resiliente y Sondeo Delta (`ui/js/`)**: `bridge-client.js` espera `pywebviewready` con respaldo de 2000 ms pero conserva la actualización al puente nativo ante eventos `pywebviewready` tardíos, devuelve éxito booleano en `invokeApi()`, descarta respuestas obsoletas fuera de orden mediante secuenciación monotónica y deduplica llamadas simultáneas con `dedupeKey`. `app.js` usa endpoints delta livianos (`get_ambilight_status`, `get_music_sync_status`) para los medidores en vivo, dispara un `refreshStates()` silencioso cuando se detiene un flujo, protege entradas con foco (`#input-hex`, sliders protegidos con `bindSliderInteraction()`, campos de escena y foco) y preserva el foco tras `replaceChildren()` mediante `captureFocusKey`/`restoreFocusKey`.
- **Controles Accesibles y Flujos UX Seguros**: `#toast-region` se renderiza en capa superior (`popover="manual"`) sobre diálogos `<dialog>` y soporta acciones (**Deshacer** de 5 s al eliminar presets, con volcado en `beforeunload`). Los modales validan IPv4 y campos requeridos en línea antes de cerrarse, `#stage-empty-banner` guía estados de 0 focos o 0 seleccionados, los objetivos interactivos cumplen `>= 24×24px`, `#select-all-fixtures` sincroniza `.indeterminate`, `aria-pressed` refleja grupos toggle/preset y el teclado soporta `Space` (encendido), `Alt+ArrowUp`/`Alt+ArrowDown` (brillo, liberando flechas simples para scroll), `Home`/`End` en `.mode-tabs` y `aria-valuetext` localizado en `#color-wheel-canvas` junto a controles sin anidamiento (`.scene-card-trigger` + botón hermano `.scene-fav-btn`).

### Propiedad de la Internacionalización (i18n) · fuente única de verdad
Las traducciones tienen **un único dueño por dominio** (Gate 2 / T-2.3):

- **El backend es dueño solo de las cadenas de bandeja y los errores de dominio.** Las etiquetas del menú de bandeja y el aviso único al ocultar ventana viven en `adapters/tray/menu_model.py` (`_TRAY_STRINGS`), porque la bandeja del sistema no tiene acceso a la UI web. Sus claves son `snake_case` sin namespace (`hide_window`, `turn_off`, `brightness`, `tray_hint_title`, …).
- **La UI es dueña de todo el texto de pantalla.** Todo el texto visible de la página vive en `ui/i18n.js` (`DICTIONARIES`), con claves `namespace.camelCase` (`rail.scanBtn`, `stage.turnOff`, `shortcuts.brightness`, …). Las opciones dinámicas recibidas del backend (resoluciones de monitores, dispositivos WASAPI, valores de enums en toasts y escena #19 en presets) también se formatean y localizan en la UI (`ambilight.js`, `music.js`, `scenes.js`).

Las dos convenciones son deliberadamente incompatibles para que una clave literal nunca pueda colisionar: `tests/test_i18n.py::test_i18n_single_owner_backend_tray_vs_ui_screen` garantiza que ninguna clave de `_TRAY_STRINGS` aparezca como clave de pantalla y viceversa, y `tests/js/stage4-copy-i18n.test.js` valida paridad de claves EN/ES y cero claves sin uso. Al agregar una cadena, ubicala en el dominio que le corresponde; nunca dupliques la misma clave en ambos lugares.

### Empaquetado
`scripts/build.ps1` genera el icono (`assets/icon/make_icon.py`), ejecuta PyInstaller con `packaging/wiz_console.spec` (carpeta, sin consola, incluyendo `ui/` y `assets/` mientras excluye scripts auxiliares `*.py` como `make_icon.py`), firma `WizConsole.exe` **antes** de empaquetar el ZIP portable y el instalador de Inno Setup (`packaging/installer.iss`, por usuario, preservando el `AppId` para actualizaciones limpias, `runasoriginaluser`, eliminación de `WizConsole` y de la entrada legacy `GestorDeLuces` en `HKCU\...\Run` al desinstalar y `[CustomMessages]` en inglés y español), firma el instalador con sello de tiempo RFC 3161 por HTTPS (`https://timestamp.digicert.com`) cuando se define `SIGN_CERT_SHA1` y escribe `dist/SHA256SUMS.txt`. `resources.py` resuelve los assets desde `sys._MEIPASS` cuando la app está congelada. Los datos del usuario siempre quedan en `%LOCALAPPDATA%\WizConsole`. El archivo de sumas se escribe con LF y sin BOM a propósito: `Set-Content -Encoding UTF8` agrega BOM y CRLF, y en Linux/macOS `sha256sum -c` entonces lee el retorno de carro como parte del nombre del archivo y toda línea falla con `FAILED open or read`.

### Pipeline de release (`release.yml`)

El CI corre el mismo script, así que ninguna release se arma a mano y el camino local no puede divergir del publicado. Todas las acciones de terceros están fijadas por SHA de commit de 40 caracteres, Inno Setup está fijado en la versión `6.7.1`, el workflow usa `permissions: contents: read` por defecto y `contents: write` queda restringido al job `publish`. Cuatro jobs, cada uno lo bastante barato como para fallar temprano:

| Job | Runner | Qué decide |
|---|---|---|
| `guard` | `ubuntu-latest` | Resuelve la versión una sola vez —del tag en un push `v*`, de un input obligatorio en `workflow_dispatch`, porque en una corrida manual `GITHUB_REF_NAME` es la rama— y falla cuando no coincide con `pyproject.toml` o cuando falta `docs/releases/<versión>.md`. |
| `build` | `windows-latest` | Instala el extra `dev` (PyInstaller viene ahí) más Inno Setup (`6.7.1`) desde Chocolatey, corre `scripts/build.ps1` sin argumento de versión y sube `dist/`. |
| `verify` | `windows-latest` | Compara el conjunto de artefactos contra los tres nombres esperados, corre `sha256sum -c SHA256SUMS.txt` y `WizConsole.exe --smoke-test` sobre el build congelado. Cuenta solo archivos, porque `dist/` también tiene el directorio de la app. |
| `publish` | `ubuntu-latest` | Crea una release en borrador (reusa la que dejó un re-run), sube con `--clobber`, re-verifica el digest que informa GitHub de cada asset contra el SHA-256 local y recién entonces publica. Un grupo `concurrency` por tag evita que dos corridas del mismo tag intercalen la publicación. |

Una corrida con `dry_run` ejecuta todos los pasos hasta la publicación y después borra su borrador descartable: así se ensaya el pipeline sin publicar nada. El workflow no necesita ningún secreto más allá del `GITHUB_TOKEN` por defecto; los binarios siguen sin firmar hasta que exista un certificado y `SIGN_CERT_SHA1`.
