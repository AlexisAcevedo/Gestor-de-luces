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
   - Aloja las entidades centrales (`Bulb`, `LightState`, `CustomScene`, `BuiltInScene`) y los Objetos de Valor (`Color`, `Brightness`, `ColorTemperature`, `LightMode`, `SceneSpeed`).
   - Libre de dependencias externas: no importa librerías de red, APIs de Windows ni frameworks de interfaz de usuario.
   - Aplica invariantes de negocio (enteros RGB entre 0 y 255, rangos de temperatura Kelvin entre 2.200 K y 6.500 K, y restricciones de identificación de focos).

2. **Capa de Puertos (`gestor_luces.ports`)**:
   - Define contratos mediante `typing.Protocol` con el decorador `@runtime_checkable` (tipado estructural estático).
   - Los puertos salientes especifican qué necesita la aplicación del exterior sin atarse a tecnologías concretas:
     - `LightController`: Define las operaciones de red (`discover`, `get_state`, `set_power`, `set_color`, `set_temperature`, `set_scene`, `stream_pilot`).
     - `BulbRepository`, `SceneRepository`, `SettingsRepository`: Contratos para lectura y escritura del estado persistente.
     - `ScreenSampler`: Contrato para capturar fotogramas y calcular el color representativo de pantalla.
     - `AudioSampler`: Contrato para muestrear la energía y el espectro frecuencial del audio del sistema.

3. **Capa de Aplicación (`gestor_luces.application`)**:
   - Orquesta los casos de uso a través de `LightControlService`.
   - Administra operaciones concurrentes hacia múltiples focos mediante `asyncio.gather`.
   - Incluye servicios de dominio especializados:
     - `StreamRateLimiter`: Asegura una cadencia máxima de 10 Hz para transmisiones de alta frecuencia.
     - `SleepTimerManager`: Gestiona temporizadores no bloqueantes con desvanecimiento lineal progresivo del brillo.
     - `AmbilightStreamManager`: Controla los ciclos periódicos de captura y suavizado de color en pantalla.
     - `MusicSyncStreamManager`: Orquesta el muestreo por WASAPI loopback, el análisis FFT y el mapeo de frecuencias a color.

4. **Capa de Adaptadores e Infraestructura (`gestor_luces.adapters`)**:
   - Implementa los puertos conectando con el hardware y el sistema operativo:
     - `adapters.wiz.udp_controller`: Gestiona el descubrimiento por broadcast UDP y los datagramas JSON-RPC unicast mediante `pywizlight`.
     - `adapters.storage.json_repositories`: Implementa la persistencia atómica en disco dentro de `%LOCALAPPDATA%\GestorLuces`.
     - `adapters.ambilight.mss_sampler`: Implementa `ScreenSampler` accediendo al búfer GDI de Windows a alta velocidad con `mss`.
     - `adapters.audio.wasapi_sampler`: Implementa `AudioSampler` capturando la salida del sistema con `PyAudioWPatch` y aplicando `numpy.fft.rfft`.
     - `adapters.tray.tray_icon`: Integra el icono y menú de la bandeja del sistema mediante `pystray`.
     - `adapters.ui_webview.bridge`: Expone una API asíncrona segura de JavaScript hacia Python dentro del contenedor Edge WebView2.

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
| HILO 3: Bandeja del Sistema          |   | HILO 4: Hilos de Streaming Continuo|
|   - Corre el bucle Win32 nativo      |   |   - Bucle de Ambilight a 10 Hz     |
|     mediante icon.run_detached().    |   |   - Callback de audio por WASAPI   |
|   - Renderiza menús contextuales.    |   |   - Hilo de análisis espectral FFT |
+--------------------------------------+   +------------------------------------+
```

### Roles y Responsabilidades de los Hilos

1. **Hilo Principal de UI**:
   - Se inicia con `webview.start()`.
   - Controla el bucle de mensajes de la ventana Win32/WinForms y hospeda Microsoft Edge Chromium (WebView2).
   - Cualquier operación pesada o bloqueante en este hilo congela de inmediato la interfaz.

2. **Hilo Asíncrono de Trabajo (`_bridge_worker`)**:
   - Se crea durante el arranque de la aplicación en `WebviewBridge.start_event_loop()`.
   - Contiene un `asyncio.AbstractEventLoop` independiente de larga duración.
   - Las invocaciones de JavaScript (`window.pywebview.api`) se despachan con `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)` con un tiempo límite de protección para no bloquear la interfaz en caso de problemas de red.

3. **Hilo Demonio de la Bandeja del Sistema**:
   - Se inicia mediante `pystray.Icon.run_detached()`.
   - Mantiene un bucle Win32 secundario para renderizar el icono en el Área de Notificaciones y sus menús desplegables.
   - Opera de forma desacoplada de la ventana principal, permitiendo que esta se oculte, restaure o minimice sin afectar el proceso en segundo plano.

4. **Hilos de Streaming de Hardware (Ambilight y Música)**:
   - Administrados como hilos demonio en segundo plano por `AmbilightStreamManager` y `MusicSyncStreamManager`.
   - Se activan por intervalos fijos (100 ms para Ambilight) o por interrupciones del búfer de audio (WASAPI loopback).
   - Transmiten paquetes UDP sin confirmación (`stream_pilot`), evitando que la espera de respuestas de red congele el flujo continuo.

---

## 3. Seguridad de Concurrencia y Prevención de Deadlocks

La comunicación entre hilos entre `pystray` (WinForms/Win32) y `pywebview` (WinForms/WebView2) requiere un cuidado especial con el orden de adquisición de bloqueos.

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

$$\text{Ruta: } \%\text{LOCALAPPDATA}\%\backslash\text{GestorLuces}\backslash$$

Archivos gestionados:
- `bulbs.json`: Focos descubiertos o agregados manualmente (IP, MAC, modelo y alias de usuario).
- `scenes.json`: Presets personalizados creados por el usuario (modo, RGB, CCT, brillo, velocidad).
- `settings.json`: Configuración global (idioma activo `en` o `es`, focos seleccionados por defecto, etc.).

### Patrón de Escritura Atómica en Disco

Para prevenir la corrupción de los archivos JSON ante cortes imprevistos de energía o cierres forzados, todas las escrituras siguen el protocolo atómico:
1. Se serializa la información JSON a un búfer en memoria.
2. Se escribe en un archivo temporal en la misma carpeta (`archivo.json.tmp`).
3. Se sincronizan los descriptores con el sistema de archivos (`flush()` + `os.fsync()`).
4. Se reemplaza de forma atómica el archivo de destino mediante `os.replace()`, garantizando una transacción de todo o nada en NTFS.

