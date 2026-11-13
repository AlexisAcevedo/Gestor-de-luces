# Diseño de Arquitectura y Modelo de Concurrencia

[English](architecture.md) | [Español](architecture.es.md)

Este documento detalla los fundamentos arquitectónicos, las capas estructurales, las topologías de hilos y los mecanismos de sincronización de concurrencia utilizados en **Gestor de Luces**.

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

1. **Capa de Dominio (`gestor_luces.domain`)**:
   - Aloja las entidades centrales (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`), los Objetos de Valor (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`) y las invariantes de preferencias globales de interfaz en `value_objects.py` (`SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, `SUPPORTED_THEMES` (`"architectural-stone"`, `"atmospheric-dark"`) y `DEFAULT_THEME` (`"architectural-stone"`)).
   - Libre de dependencias externas: no importa librerías de red, APIs de Windows ni frameworks de interfaz de usuario.
   - Aplica invariantes de negocio (enteros RGB entre 0 y 255, rangos de temperatura Kelvin entre 2.200 K y 6.500 K, restricciones de identificación de focos y validación de códigos de idioma y tema).

2. **Capa de Puertos (`gestor_luces.ports`)**:
   - Define contratos mediante `typing.Protocol` con el decorador `@runtime_checkable` (tipado estructural estático).
   - Los puertos salientes especifican qué necesita la aplicación del exterior sin atarse a tecnologías concretas:
     - `LightController`: Define las operaciones de red (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`, `close`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contratos para lectura y escritura del estado persistente.
     - `ScreenSampler`: Contrato para capturar fotogramas y calcular el color representativo de pantalla (`sample_frame`, `sample_average_color`, `list_monitors`, `close`).
     - `AudioSampler`: Contrato para muestrear la energía y el espectro frecuencial del audio del sistema (`sample_frame`, `sample_audio_metrics`, `list_audio_devices`, `close`).

3. **Capa de Aplicación (`gestor_luces.application`)**:
   - Orquesta los casos de uso a través de `LightControlService`.
   - Recibe fábricas perezosas de muestreo (`screen_sampler_factory`, `audio_sampler_factory`) inyectadas desde la raíz de composición (`main.py`) de modo que las capas internas (`domain`, `ports`, `application`) nunca importan `adapters` (verificado estáticamente vía AST en `tests/test_security_hardening.py`).
   - Administra operaciones concurrentes hacia múltiples focos mediante `asyncio.gather`.
   - Incluye servicios de dominio especializados:
     - `StreamRateLimiter`: Asegura una cadencia máxima de 10 Hz para transmisiones de alta frecuencia.
     - `SleepTimerManager`: Gestiona temporizadores no bloqueantes con desvanecimiento lineal progresivo del brillo.
     - `AmbilightStreamManager`: Controla los ciclos periódicos de captura y suavizado de color en pantalla.
     - `MusicSyncStreamManager`: Orquesta el muestreo por WASAPI loopback, el análisis FFT y el mapeo de frecuencias a color.

4. **Capa de Adaptadores e Infraestructura (`gestor_luces.adapters`)**:
   - Implementa los puertos conectando con el hardware y el sistema operativo:
     - `adapters.wiz.udp_controller`: Gestiona el descubrimiento por broadcast UDP y los datagramas JSON-RPC unicast mediante `pywizlight`.
     - `adapters.storage.json_repositories`: Implementa la persistencia atómica en disco dentro de `%LOCALAPPDATA%\GestorDeLuces`.
     - `adapters.ambilight.mss_sampler`: Implementa `ScreenSampler` accediendo al búfer GDI de Windows a alta velocidad con `mss`.
     - `adapters.audio.wasapi_sampler`: Implementa `AudioSampler` capturando la salida del sistema con `PyAudioWPatch` y aplicando `numpy.fft.rfft`.
     - `adapters.tray`: Integra la bandeja del sistema detrás de un contrato mínimo `TrayView`:
      - `tray_icon`: `TrayController` posee el modelo de menú, los handlers, el ejecutor y el único hilo de refresco; no importa ningún toolkit gráfico.
      - `tray_view`: protocolo `TrayView` (`run`/`stop`/`apply`) más el mapeo modelo→acción y el generador del icono.
      - `winforms_tray`: punto de entrada de la vista principal. `create_winforms_view` y `WinFormsTrayView` componen las piezas de abajo y conservan la política de aplicación (icono/tooltip siempre, rebuild del menú diferido mientras el menú está visible); reexporta la superficie que ya importaban sus consumidores.
      - `winforms_host`: el host STA. Resolución perezosa de pythonnet/WinForms, `CoInitializeEx`, el `Form` oculto de 0×0, `Application.Run(form)` y el marshalling con `Control.Invoke`. Ningún otro módulo importa .NET por su cuenta.
      - `winforms_icon`: `NotifyIcon` más una caché de `HICON` por color que destruye los handles reemplazados, y el límite de 63 caracteres del tooltip.
      - `winforms_menu`: construye el `ContextMenuStrip` y sus submenús desde el modelo puro `TrayMenuEntry`, es dueño de las firmas de menú/estado y engancha el acabado de ventana a cada superficie de menú.
      - `winforms_paint`: paletas por tema, parseo de colores y toda la operación de dibujo (painter de filas, hover, punto de nivel activo, chevron de submenú, separadores, geometría de la región redondeada escalada por DPI y el recorte de la `Region`).
      - `pystray_tray`: vista de respaldo (menú Win32 clásico) cuando pythonnet/WinForms no puede cargar.
     - `adapters.ui_webview.bridge`: Expone una API asíncrona segura de JavaScript hacia Python dentro del contenedor Edge WebView2 mediante una fachada pública restringida (lista blanca `JsApi`), impidiendo la invocación de métodos o callbacks internos desde JavaScript. El adaptador está partido en `dispatch` (la tabla explícita `JS_API_DISPATCH`, `JsApi` y el contrato de ajuste de ventana), `handlers` (un handler por capacidad) y `lifecycle` (event loop propio, sellado de envelopes, notificaciones de estado y apagado); `bridge.py` conserva `WebviewBridge` y reexporta toda la superficie, así que quien lo importa no cambia.

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
| HILO 2: Bucle de Eventos Asíncrono Dedicado (GestorLucesAsyncLoop)            |
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
| `GestorLucesAsyncLoop` (`ASYNC_LOOP_THREAD_NAME`) | `adapters/ui_webview/lifecycle.py` → `BridgeLifecycle._start_async_loop`, arrancado por `WebviewBridge.__init__` | Larga: uno por sesión, ejecuta el bucle `asyncio` privado del puente (`loop.run_forever()`) | `WebviewBridge.shutdown()` cancela los flujos activos, llama `loop.call_soon_threadsafe(loop.stop)` y `thread.join(timeout=2.0)`. Idempotente tras `_shutdown_lock`; lo invocan `DesktopApplication.cleanup()` y el evento `closed` de la ventana. |
| `GestorLucesTray` (`ICON_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start`, ejecuta `TrayView.run` | Larga: el bombeo nativo de mensajes de la vista (WinForms `Application.Run` en un hilo STA, o `pystray.Icon.run`) durante toda la sesión | `TrayController.stop()` marca `_stopped` y llama `TrayView.stop()` (WinForms cierra el form oculto, `pystray` detiene el icono), así que `run` retorna. Seguro de invocar varias veces y desde cualquier hilo. |
| `GestorLucesTrayRefresh` (`REFRESH_THREAD_NAME`) | `adapters/tray/tray_icon.py` → `TrayController.start` → `_refresh_worker` | Larga: espera en `_refresh_requested` con el timeout de `poll_interval` (5 s) | El mismo `TrayController.stop()`: marca `_stopped` y `_refresh_requested`, y el worker sale por la bandera. Es el único escritor del estado nativo de la bandeja (T-3.6). |
| `GestorLucesTrayAction` (literal en `_default_executor`) | `adapters/tray/tray_icon.py` → `TrayController.dispatch` → `_run_action` | Corta: un hilo por acción de menú despachada | Termina solo; nadie lo une (*join*). `quit_app` no desmonta la bandeja desde este hilo a propósito: el desmontaje ocurre después en `cleanup()`. |
| `GestorLucesMenuSync` (`MENU_SYNC_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.start` → `_menu_sync_worker` | Larga: espera en `_menu_sync_requested` y reaplica en vivo el `MenuStrip` nativo (pywebview no tiene API de actualización de menú) | `DesktopApplication.cleanup()` marca `is_quitting` y llama una vez a `request_menu_sync()`: el bucle despierta, ve la bandera y sale antes de reaplicar. |
| `GestorLucesHideOnClose` (`HIDE_ON_CLOSE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_closing` (evento `closing` de la ventana) | Corta: llama `hide_window` y termina | Termina sola. pywebview dispara `closing` de forma síncrona en el hilo GUI con `should_lock`, así que ocultar dentro del manejador podría reentrar o bloquearse; de ahí el hilo. |
| `GestorLucesHideOnMinimize` (`HIDE_ON_MINIMIZE_THREAD_NAME`) | `desktop/app.py` → `DesktopApplication.on_minimized` (evento `minimized` de la ventana) | Corta: llama `hide_window` y termina | Termina sola, por la misma razón que el cierre. |
| `GestorLucesSingleInstance` (literal en `listen`) | `adapters/system/single_instance.py` → `SingleInstanceGuard.listen` | Larga: sondea `WaitForSingleObject(handle, 500 ms)` esperando un segundo lanzamiento | `SingleInstanceGuard.release()` marca `self._stop` y el hilo sale dentro de un sondeo de 500 ms. Lo llama `DesktopApplication.cleanup()`. |

Contextos de hilo que la aplicación no crea:

| Contexto | Dueño (módulo) | Vida | Cómo se detiene |
| --- | --- | --- | --- |
| `MainThread` (bombeo de UI) | `webview.start()` (pywebview/WinForms), invocado desde `DesktopApplication.start` | Larga: bloquea hasta que la ventana nativa se destruye | `window.destroy()` desde `quit_app` (Salir de la bandeja o Archivo → Salir); `webview.start()` retorna y `cleanup()` corre en su `finally`. |
| Workers del ejecutor por defecto (asyncio_0, asyncio_1, …) | el pool por defecto del bucle `GestorLucesAsyncLoop`, poblado de forma perezosa por `asyncio.to_thread` en `application/ambilight_stream.py` (~10 Hz) y `application/music_stream.py` (~10.5 Hz) | Larga mientras corre la sesión; inactivos entre fotogramas | `BridgeLifecycle.shutdown()` detiene ambos flujos primero, y `loop.close()` dentro de `_run_loop` apaga el ejecutor por defecto (`shutdown(wait=False)`) al salir el bucle. |
| Hilo de callback de PortAudio (aparece como `Dummy-N`) | PortAudio/WASAPI: invoca el closure `stream_callback` de `adapters/audio/wasapi_session.py` | Larga mientras el flujo de música está activo: una llamada por búfer de audio | `WasapiLoopbackStreamSession.close()` (`stop_stream`, `close`, `pa.terminate()`), alcanzado desde `LightControlService.close_audio_sampler()` dentro de `shutdown()`. |
| `Thread-N (setup_handler)` | `pystray.Icon.run()` en la vista de respaldo `adapters/tray/pystray_tray.py`; pystray lo crea **sin nombre y sin `daemon`** | Corta: marca `icon.visible = True` cuando arranca el bombeo | `pystray.Icon.stop()` lo une con `SETUP_THREAD_TIMEOUT` (5 s) desde el hilo que llama `TrayView.stop()`. La vista WinForms no crea ese hilo. |

`cli.py` ejecuta `asyncio.run(...)` en el hilo llamador, así que la herramienta de línea de comandos no agrega hilos propios.

### Reglas de Hilos

- Cada `threading.Thread(` en `src/` conserva un `name=` explícito y `daemon=True`; un sitio nuevo sin ambos es un defecto.
- Solo `GestorLucesTrayRefresh` aplica el estado nativo de la bandeja, y solo `GestorLucesMenuSync` reaplica el menú nativo de la ventana: un escritor por superficie nativa.
- Solo `GestorLucesTrayAction` ejecuta acciones del menú de bandeja, así que una llamada UDP lenta nunca corre dentro de un bombeo nativo. La barra de menú de la ventana despacha en `MainThread` a través de pywebview y solo reaplica estado mediante `GestorLucesMenuSync`.
- Cerrar la aplicación libera los hilos de vida larga (`GestorLucesAsyncLoop`, `GestorLucesTray`, `GestorLucesTrayRefresh`, `GestorLucesSingleInstance`); los de vida corta (`GestorLucesTrayAction`, `GestorLucesHideOnClose`, `GestorLucesHideOnMinimize`) ya terminaron para entonces y nunca se unen al cerrar.
- **Regla de cierre:** `DesktopApplication.cleanup()` detiene todos los hilos de la app: marca `is_quitting` y despierta a `GestorLucesMenuSync`, libera la instancia única, detiene la vista de bandeja y su hilo de refresco, y apaga el bucle del puente. `tests/test_thread_lifecycle.py` demuestra con `threading.enumerate()` que ningún hilo con nombre de la app sobrevive al cierre, usando esperas acotadas por condición y no `sleep` fijos.

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
3. **Un único escritor por objeto nativo**: solo el hilo `GestorLucesTrayRefresh` aplica estado a la vista (ver la regla de hilos más abajo), así que el menú nativo no puede mutarse desde un segundo hilo que igual necesitaría un cerrojo.

### Regla de Hilos del Menú de Bandeja (T-3.6)

En la vista de respaldo `pystray`, `pystray.Icon.update_menu()` empieza destruyendo el `HMENU` vigente y creando uno nuevo. Si eso ocurre con el menú desplegado, todos los IDs de item y todos los `hSubMenu` ya creados quedan invalidados: los clics cancelan en silencio y los submenús dejan de abrir.

La regla que impone `TrayController` para cualquier vista:
- Las acciones del menú solo encolan trabajo en el ejecutor y terminan con `request_refresh()`; nunca tocan la vista.
- Solo el único hilo `GestorLucesTrayRefresh` llama `TrayView.apply`, de modo que el estado nativo de la bandeja siempre tiene un único escritor.
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

Cuando el usuario cierra la ventana principal, la aplicación intercepta el evento `window.events.closing`:
- La ventana se oculta (`window.hide()`) en lugar de destruirse, permitiendo que la aplicación continúe activa en segundo plano.
- Cuando el usuario hace doble clic en la bandeja o selecciona "Abrir Consola", `TrayController` despacha de forma segura `window.show()` y `window.restore()` en el hilo principal de la ventana.

---

## 4. Limitación de Frecuencia por Hardware y Streaming

Los focos WiZ están basados en microcontroladores de bajo consumo ESP8266 / ESP32. Enviar paquetes UDP a una tasa superior a la que su procesador puede absorber genera:
- Disparos del temporizador guardián (*watchdog timer*), provocando reinicios y parpadeos en el foco.
- Pérdida masiva de paquetes UDP y saltos visibles en las transiciones de luz.
- Congestión en la banda de 2.4 GHz de la red Wi-Fi.

### Mecanismo de Regulación a 10 Hz

Para garantizar la estabilidad del hardware, `StreamRateLimiter` impone una ventana temporal estricta:

$$\Delta t \ge 100\text{ ms} \quad (\text{Tasa máxima } = 10\text{ Hz})$$

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

### Suavizado por Media Móvil Exponencial (EMA)

Para evitar saltos abruptos generados por cambios súbitos de la pantalla (cortes de cámara o explosiones en videojuegos), el motor de Ambilight aplica un filtro de media móvil exponencial:

$$\vec{C}_{\text{suavizado}} = \alpha \cdot \vec{C}_{\text{nuevo}} + (1 - \alpha) \cdot \vec{C}_{\text{anterior}}$$

Donde $\alpha \in [0.1, 0.4]$ regula la inercia del color:
- Valores bajos de $\alpha$ generan transiciones cinematográficas muy fluidas.
- Valores más altos de $\alpha$ aumentan la reactividad inmediata para juegos de acción.

---

## 5. Estrategia de Persistencia y Almacenamiento

Las preferencias de usuario, las escenas personalizadas y el inventario de focos se almacenan localmente en el directorio de datos de aplicación de Windows:

$$\text{Ruta: } \%\text{LOCALAPPDATA}\%\backslash\text{GestorDeLuces}\backslash$$

Archivos gestionados:
- `bulbs.json`: Focos descubiertos o agregados manualmente (IP, MAC, modelo y alias de usuario).
- `custom_scenes.json`: Presets personalizados creados por el usuario (modo, RGB, CCT, brillo, velocidad, favorito).
- `settings.json`: Preferencias globales de usuario (`language`: `"en"` o `"es"`, y `theme`: `"architectural-stone"` o `"atmospheric-dark"`).

### Patrón de Escritura Atómica en Disco

Para prevenir la corrupción de los archivos JSON ante cortes imprevistos de energía o cierres forzados, todas las escrituras siguen el protocolo atómico:
1. Se serializa la información JSON a un búfer en memoria.
2. Se crea un archivo temporal único en la misma carpeta mediante `tempfile.mkstemp` (`.<archivo>.<aleatorio>.tmp`).
3. Se vuelcan y sincronizan los descriptores con el sistema de archivos (`flush()` + `os.fsync()`).
4. Se reemplaza de forma atómica el archivo de destino mediante `os.replace()`, garantizando una transacción de todo o nada en NTFS.


---

## 6. Shell de Escritorio, Autoinicio y Empaquetado

### Barra de Menú Nativa
`adapters/ui_webview/app_menu.py` es un modelo puro del menú de la ventana (Archivo: Mostrar/Ocultar, Iniciar con Windows, Salir; Ayuda: Atajos de teclado, Acerca de), localizado en inglés y español. `main.py` lo entrega a `webview.start(menu=...)`. Los menús de pywebview 6.2.1 son estáticos (sin ítems con tilde ni API de actualización), por lo que `main.py` actualiza en caliente el `MenuStrip` de WinForms desde un hilo de trabajo cuando cambia el idioma, la visibilidad de la ventana o el estado del autoinicio. Salir sigue el mismo camino que la acción Salir de la bandeja.

### Autoinicio (`--minimized`)
El puerto `AutostartManager` (`ports/autostart.py`) lo implementa `WindowsRegistryAutostart` (`adapters/system/windows_autostart.py`), que escribe en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. El comando registrado es `<exe> --minimized` en la versión empaquetada y `pythonw -m gestor_luces.main --minimized` en desarrollo. En cada arranque, `refresh_if_stale` reescribe la entrada si apunta a otra ruta (por ejemplo, al mover la carpeta portable). El registro es inyectable, así que las pruebas nunca tocan `HKCU`.

### Instancia Única
`adapters/system/single_instance.py` combina un mutex con nombre y un evento con nombre protegidos por una DACL SDDL explícita (`SY`/`BA`/`OW`). Una segunda ejecución señala el evento y termina; la primera instancia responde mostrando su ventana (salvo que se indique `--multi-instance` para ejecución simultánea de diagnóstico).

### Motor Multitema y Geometría Dinámica de Widget
- **Arquitectura de Tokens CSS de 3 Niveles**: `ui/themes.css` define tokens primitivos, semánticos y de componente tanto para `"architectural-stone"` (tema claro predeterminado en piedra mineral cálida) como para `"atmospheric-dark"` (tema oscuro en cristal esmerilado con halo fotométrico `oklab`), consumidos por las reglas estructurales de `ui/styles.css`.
- **Sincronización del Marco Nativo de Ventana (`THEME_WINDOW_CHROME`)**: `main.py` lee el tema persistido antes de crear la ventana de PyWebView para definir el `background_color` inicial de WebView2 (`#F4F1EA` o `#08090C`) y delega la barra de título de Windows DWM (`DwmSetWindowAttribute` `DWMWA_USE_IMMERSIVE_DARK_MODE = 20` con `0` para modo claro o `1` para modo oscuro) a `adapters/platform/windows/window_chrome.py` (`_set_windows_dark_titlebar_attribute`), tanto en el arranque como al cambiar el tema en tiempo de ejecución.
- **Autoajuste Dinámico de Altura según Contenido**: `adapters/platform/windows/window_geometry.py` implementa `_fit_native_window_height` mediante llamadas Win32 `ctypes` seguras en 64 bits (`GetWindowRect`, `GetClientRect`, `SetWindowPos`) despachadas en el hilo de interfaz de WinForms (`native_form.Invoke`) y acotadas al área de trabajo del monitor activo a través de `WebviewBridge.fit_window_height`.

### Servido del Frontend (HTTP por loopback + Módulos ES) · veredicto D4: A (2026-11-08)
El frontend se sirve por HTTP en loopback para poder partir `ui/app.js` en módulos ES
reales (Chromium bloquea `type="module"` sobre `file://`). `main.py` pasa la ruta de
archivo plana `str(index_path)` como URL de la ventana y arranca
`webview.start(http_server=True)`.

El spike D4-A (T-2.0) verificó lo siguiente, con evidencia:
- **Superficie solo-loopback**: el servidor Bottle integrado de pywebview enlaza
  únicamente `127.0.0.1` (observado `http://127.0.0.1:42001/`). Nunca se expone a la LAN.
- **El bridge sigue siendo IPC directo**: `window.pywebview.api` continúa como objeto
  host nativo de WebView2. El endpoint HTTP `/js_api/<uuid>` solo transporta callbacks de
  promesas JS, gateados por un `uuid` aleatorio por lanzamiento; no es el bridge de la app.
- **Servido estático + MIME para ESM**: `index.html` → `text/html`, `app.js`/`i18n.js` →
  `text/javascript` (compatible con módulos), `themes.css`/`styles.css` → `text/css`.
- **Traversal de rutas bloqueado**: `GET /../../<archivo>` devuelve `403 Forbidden`
  (`bottle.static_file` rechaza `..`).
- **Arranque en dev verificado**: `python -m gestor_luces --minimized --multi-instance`
  sirvió `index.html` con HTTP 200 en `127.0.0.1:42001` (título `WiZ Architectural
  Lighting Console`), sin errores en el log.
- **`resolve_ui_directory()` sin cambios**: devuelve `ui/` desde fuente y `_MEIPASS/ui`
  cuando está congelada; ambas son rutas planas, así que la raíz del servidor es idéntica
  en ambos casos (`resources.py`).

Gotchas registrados para T-2.2:
- La URL de la ventana **debe** ser una ruta plana (`str(index_path)`), no `.as_uri()`
  (`file://` no se reescribe a HTTP en `_resolve_url` de pywebview).
- El origen `'self'` de la CSP sigue el esquema: pasa a ser `http://127.0.0.1:42001`; los
  permisos explícitos `file:` quedan vestigiales (inofensivos) y pueden quitarse después.
- El origen de `localStorage` migra de `file://` a `http://127.0.0.1:42001`. El puerto es
  fijo (`settings['DEFAULT_HTTP_PORT']=42001`) porque `private_mode=False`, así que los
  datos persisten entre lanzamientos — pero el `localStorage` previo de `file://` no se
  transfiere (nota de migración única; la verdad de escenas/tema vive igual en los
  repositorios JSON).
- El puerto fijo `42001` puede colisionar bajo `--multi-instance` (dos servidores simultáneos).
- La ruta raíz `/` de pywebview es una ruta muerta y rota (500); las ventanas siempre cargan
  una ruta de archivo concreta (`/index.html`), así que nunca se ejecuta.

### Propiedad de la Internacionalización (i18n) · fuente única de verdad
Las traducciones tienen **un único dueño por dominio** (Gate 2 / T-2.3):

- **El backend es dueño solo de las cadenas de bandeja y los errores de dominio.** Las
  etiquetas del menú de bandeja viven en `adapters/tray/menu_model.py` (`_TRAY_STRINGS`),
  porque la bandeja del sistema no tiene acceso a la UI web. Sus claves son `snake_case`
  sin namespace (`hide_window`, `turn_off`, `brightness`, …).
- **La UI es dueña de todo el texto de pantalla.** Todo el texto visible de la página vive
  en `ui/i18n.js` (`DICTIONARIES`), con claves `namespace.camelCase` (`rail.scanBtn`,
  `stage.turnOff`, `shortcuts.brightness`, …).

Las dos convenciones son deliberadamente incompatibles para que una clave literal nunca
pueda colisionar: `tests/test_i18n.py::test_i18n_single_owner_backend_tray_vs_ui_screen`
garantiza que ninguna clave de `_TRAY_STRINGS` aparezca como clave de pantalla y viceversa.
Al agregar una cadena, ubicala en el dominio que le corresponde; nunca dupliques la misma
clave en ambos lugares.

### Empaquetado
`scripts/build.ps1` genera el icono (`assets/icon/make_icon.py`), ejecuta PyInstaller con `packaging/gestor_luces.spec` (carpeta, sin consola, incluyendo `ui/` y `assets/`), construye el ZIP portable y el instalador de Inno Setup (`packaging/installer.iss`, por usuario, sin permisos de administrador), firma los binarios si se define `SIGN_CERT_SHA1` y genera `dist/SHA256SUMS.txt`. `resources.py` resuelve los assets desde `sys._MEIPASS` cuando la app está congelada. Los datos del usuario siempre quedan en `%LOCALAPPDATA%\GestorDeLuces`.
