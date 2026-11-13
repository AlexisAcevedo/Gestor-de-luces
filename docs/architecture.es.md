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
      - `winforms_tray`: vista principal. `NotifyIcon` + `ContextMenuStrip` en un hilo STA propio, con paletas explícitas por tema y submenús por hover.
      - `pystray_tray`: vista de respaldo (menú Win32 clásico) cuando pythonnet/WinForms no puede cargar.
     - `adapters.ui_webview.bridge`: Expone una API asíncrona segura de JavaScript hacia Python dentro del contenedor Edge WebView2 mediante una fachada pública restringida (lista blanca `JsApi`), impidiendo la invocación de métodos o callbacks internos desde JavaScript.

---

## 2. Modelo de Concurrencia y Topología de Hilos

La aplicación coordina cuatro contextos de ejecución concurrentes que deben interactuar fluidamente sin congelar la interfaz gráfica, sin perder paquetes de streaming y sin generar bloqueos mutuos (*deadlocks*).

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
| HILO 2: Bucle de Eventos Asíncrono Dedicado (_bridge_worker)                  |
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

### Roles y Responsabilidades de los Hilos

1. **Hilo Principal de UI**:
   - Se inicia con `webview.start()`.
   - Controla el bucle de mensajes de la ventana Win32/WinForms y hospeda Microsoft Edge Chromium (WebView2).
   - Cualquier operación pesada o bloqueante en este hilo congela de inmediato la interfaz.

2. **Hilo Asíncrono de Trabajo (`_bridge_worker` / `GestorLucesAsyncLoop`)**:
   - Se crea durante el arranque de la aplicación en `WebviewBridge.start_event_loop()`.
   - Contiene un `asyncio.AbstractEventLoop` independiente de larga duración.
   - Las invocaciones de JavaScript (`window.pywebview.api`) se despachan con `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)` con un tiempo límite de protección para no bloquear la interfaz en caso de problemas de red.
   - Sincroniza las instantáneas de estado (`_build_response()`): canaliza las lecturas de estado (`_collect_response_snapshot()`) hacia el hilo de trabajo dedicado `GestorLucesAsyncLoop` (manteniendo en caché las listas de monitores y dispositivos de audio tras su enumeración inicial) para prevenir condiciones de carrera entre el hilo de la interfaz y las operaciones asíncronas.

3. **Hilo de la Vista de Bandeja**:
   - Ejecuta `TrayView.run()` en un hilo demonio dedicado (`GestorLucesTray`), nunca en el hilo de la UI y nunca como hilo no demonio, para que un `stop()` omitido no mantenga vivo el proceso.
   - Vista principal (`winforms_tray`): el hilo llama `CoInitializeEx` (STA) y hospeda el bombeo `Application.Run(form)` de un `Form` oculto de 0×0 que es dueño del `NotifyIcon` y su `ContextMenuStrip`.
   - Vista de respaldo (`pystray_tray`): el hilo ejecuta `pystray.Icon.run()`, que mantiene su propio bombeo Win32 para el icono clásico.
   - Opera de forma desacoplada de la ventana principal, permitiendo que esta se oculte, restaure o minimice sin afectar el proceso en segundo plano.

4. **Hilos de Streaming de Hardware (Ambilight y Música)**:
   - Administrados como hilos demonio en segundo plano por `AmbilightStreamManager` y `MusicSyncStreamManager`.
   - Se activan por intervalos fijos (100 ms para Ambilight) o por interrupciones del búfer de audio (WASAPI loopback).
   - Transmiten paquetes UDP sin confirmación (`stream_pilot`), evitando que la espera de respuestas de red congele el flujo continuo.

---

## 3. Seguridad de Concurrencia y Prevención de Deadlocks

La comunicación entre hilos entre la vista de bandeja (`pystray` o WinForms) y `pywebview` (WinForms/WebView2) requiere un cuidado especial con el orden de adquisición de bloqueos.

### Caso de Estudio: Resolución del Bloqueo Mutuo en el Menú de la Bandeja

En prototipos iniciales, invocar `update_menu()` dentro de `TrayController` manteniendo un cerrojo interno provocaba bloqueos completos:
- `update_menu()` invoca internamente generadores dinámicos de menú (`_create_menu()`).
- Dichos generadores consultan propiedades protegidas como `is_any_on`, `selected_ips` o `favorite_scenes`, intentando adquirir el mismo bloqueo.
- Si simultáneamente el despachador de eventos Win32 procesaba un clic del usuario esperando dicho bloqueo, se producía un clásico deadlock AB-BA.

**Solución Arquitectónica**:
1. **Separación de la Instantánea de Estado y el Renderizado**:
   - `TrayController` almacena una instantánea (`_state_snapshot`) protegida por un cerrojo reentrante (`threading.RLock`).
   - `update_menu()` se ejecuta **estrictamente fuera** de la sección protegida, una vez copiada la información requerida.
2. **Sincronización Reentrante**:
   - Todos los mutex internos están configurados como `threading.RLock`, permitiendo inspecciones recursivas desde el mismo hilo sin autobloqueo.

```python
# Patrón seguro implementado en TrayController:
def set_state_snapshot(self, snapshot: dict[str, Any]) -> None:
    with self._lock:
        self._state_snapshot = dict(snapshot)
    # update_menu() se ejecuta completamente fuera del bloqueo
    self.update_menu()
```

### Regla de Hilos del Menú de Bandeja (T-3.6)

En la vista de respaldo `pystray`, `pystray.Icon.update_menu()` empieza destruyendo el `HMENU` vigente y creando uno nuevo. Si eso ocurre con el menú desplegado, todos los IDs de item y todos los `hSubMenu` ya creados quedan invalidados: los clics cancelan en silencio y los submenús dejan de abrir.

La regla que impone `TrayController` para cualquier vista:
- Las acciones del menú solo encolan trabajo en el ejecutor y terminan con `request_refresh()`; nunca tocan la vista.
- Solo el único hilo `GestorLucesTrayRefresh` llama `TrayView.apply`, de modo que el estado nativo de la bandeja siempre tiene un único escritor.
- La vista decide si el menú nativo se puede reconstruir en ese instante. La vista `pystray` consulta `adapters.platform.windows.menu_state._is_menu_open` (banderas de modo menú del hilo en primer plano vía `GetGUIThreadInfo`) y, si hay un menú abierto, deja el rebuild pendiente y lo reintenta en el próximo `apply`. La vista WinForms difiere mientras su `ContextMenuStrip.Visible` es verdadero y luego reemplaza y libera el menú en el siguiente refresco.

### Render del Menú de Bandeja y Paletas por Tema (T-3.8)

El menú clásico de `pystray` es un popup Win32 que se pinta con la clase de ventana que registra con `hbrBackground = COLOR_WINDOW + 1`, así que siempre usa el fondo blanco del sistema y el texto claro se vuelve ilegible («fondo blanco, letras blancas pareciera, mucho brillo»). Por eso la bandeja usa `System.Windows.Forms.NotifyIcon` + `ContextMenuStrip` como vista principal:

- `TrayView` (`adapters.tray.tray_view`) es el único contrato entre el controlador y una vista: `run()` (bombeo bloqueante), `stop()` y `apply(spec, title, rgb, theme)`. `resolve_entry_action` traduce una hoja del modelo a la acción a despachar, incluida la acción sintética `toggle_window` del ítem por defecto (mostrar/ocultar ventana).
- `winforms_tray` traduce el modelo puro `menu_model` a objetos `ToolStripMenuItem` reales: los submenús son `DropDownItems` (WinForms los abre al pasar el cursor, sin hacks de clic), los clics de hoja despachan `(action_id, payload)`, los niveles de brillo usan `CheckOnClick = False` + `Checked`, y una llamada UDP lenta no bloquea nada porque `TrayController` sigue despachando en su ejecutor.
- Los colores vienen de una tabla explícita indexada por el tema activo (`architectural-stone` → clara, `atmospheric-dark` → oscura, desconocido → clara). Fondo, texto y texto deshabilitado se aplican al `ContextMenuStrip`, a cada ítem y a cada panel de submenú (`selection`); `RenderMode = System` evita que el cromo del dropdown repinte un margen de imagen brillante. El nivel de brillo activo además lleva un punto generado en el color de texto de la paleta, porque el glifo de check nativo tiene color fijo y desaparece sobre la paleta oscura.
- Restricción verificada del entorno: pythonnet 3.2.1 sobre .NET Framework 4.8 no emite tipos derivados aquí, así que las subclases Python de `ProfessionalColorTable`/`ToolStripRenderer` no reciben despacho virtual desde .NET. Por eso no hay tabla de colores ni renderer propio y la paleta se aplica control por control.
- Si WinForms no carga, `create_winforms_view` devuelve `None` y la raíz de composición cae a `pystray_tray`, de modo que el icono de bandeja nunca desaparece por un fallo del CLR.

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
