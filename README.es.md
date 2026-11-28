# Gestor de Luces

[English](README.md) | [Español](README.es.md)

[![CI](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/AlexisAcevedo/wiz-architectural-lighting-console/badges/coverage.json)](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/blob/main/.github/workflows/coverage-badge.yml)

Centro de control de escritorio para sistemas de iluminación inteligente Philips WiZ sobre redes de área local (LAN). Diseñado con Python, Arquitectura Hexagonal (Puertos y Adaptadores) y Microsoft WebView2 (PyWebView), operando de manera exclusiva mediante paquetes UDP locales sin dependencias de la nube, puentes externos ni necesidad de conexión a Internet.

---

## Aspectos Destacados de la Arquitectura

- Cero Dependencia de la Nube: Comunicación local directa con los focos WiZ mediante el puerto UDP 38899.
- Arquitectura Hexagonal: Las capas de dominio, puertos y aplicación nunca importan adaptadores (verificado por `test_inner_hexagonal_layers_never_import_adapters`).
- Concurrencia Multihilo: Bucle de eventos asíncrono e independiente para I/O de red, hilos aislados en segundo plano para streaming y bandeja del sistema no bloqueante.
- Limitación de Frecuencia por Hardware: Regulación estricta a 10 Hz (100 ms) para evitar la saturación de los microcontroladores ESP integrados en los focos durante el streaming continuo.
- Pruebas 100% Fuera de Línea: Suite de pruebas automatizadas que utilizan un simulador UDP en memoria que replica fielmente el comportamiento JSON-RPC de WiZ.

---

## Características Principales

1. Control Fotométrico Completo:
   - Encendido y apagado en tiempo real, ajuste de curva de atenuación (10% a 100%) y sondeo de estado.
   - Regulación de Temperatura de Color Correlacionada (CCT) desde 2.200 K (Blanco Cálido Incandescente) hasta 6.500 K (Luz Día Fría).
   - Selección de color RGB con previsualización en vivo e ingreso hexadecimal.

2. Catálogo de Escenas Nativas y Presets Personalizados:
   - Catálogo completo de las 36 escenas de fábrica de WiZ con regulación dinámica de velocidad (10% a 200%).
   - Presets guardados por el usuario en disco local con aplicación en un clic, edición y eliminación protegida por un aviso **Deshacer** de 5 segundos en capa superior (`popover="manual"`).

3. Sincronización Ambiental de Pantalla (Ambilight):
   - Muestreo en tiempo real de la pantalla utilizando captura GDI Win32 pura en Python (`mss`).
   - Múltiples algoritmos de muestreo: color promedio general, color dominante de bordes o centroide de alta luminosidad.
   - Streaming continuo a 10 Hz mediante paquetes UDP sin confirmación (fire-and-forget) y suavizado de color por Media Móvil Exponencial (EMA).

4. Sincronización Musical Reactiva por WASAPI Loopback:
   - Captura de audio del sistema en tiempo real mediante loopback de Windows Audio Session API (WASAPI) (`PyAudioWPatch`).
   - Descomposición espectral por Transformada Rápida de Fourier (FFT) en bandas de Bajos, Medios y Agudos mediante `numpy`.
   - Mapeo de frecuencias a color con sensibilidad de ganancia configurable y caída suavizada.

5. Bandeja del Sistema y Ejecución en Segundo Plano:
   - Ejecución silenciosa en el Área de Notificación de Windows mediante un menú nativo
     WinForms `NotifyIcon` pintado con el tema activo (con respaldo `pystray` si WinForms no
     puede cargar).
   - Menú unificado (`Mostrar ventana` / `Ocultar ventana`, `Presets favoritos`, `Salir`), alternancia de encendido general y minimización elegante a la bandeja al cerrar o minimizar la ventana, con aviso único (`tray_hint_seen` persistido en `settings.json`).
   - El item de encendido/apagado actúa sobre el estado real del foco: relee los focos objetivo antes de invertir, y la etiqueta, el tooltip y el color del icono se refrescan desde los focos en cada sondeo, así que una luz cambiada desde la llave de pared o la app del teléfono no invierte el próximo clic.
   - Ocultarse en la bandeja no deja residuo en alt+tab (la ventana del bombeo de la bandeja es una ventana de herramienta) y salir desde el menú cierra limpio.
   - Sincronización libre de bloqueos mutuos (deadlocks) entre WinForms y PyWebView.

6. Temporizador de Apagado Progresivo (Sleep Timer):
   - Cuenta regresiva configurable (1 a 240 minutos) con atenuación progresiva del brillo hasta cero antes del apagado final.

7. Consola de Escritorio Bilingüe y Multitema:
   - Interfaz bilingüe nativa en inglés (`en`) y español (`es`) con cambio instantáneo en la UI, título de ventana nativo localizado, bandeja y barra de menú, además de arranque sin destello para tema e idioma (`#theme=<theme>&lang=<lang>`).
   - Cambio de tema en tiempo de ejecución entre **Architectural Stone** (tema claro predeterminado inspirado en botoneras de hardware Braun/Lutron) y **Atmospheric Dark** (cristal esmerilado y halo fotométrico dinámico en espacio `oklab`), persistido en `settings.json` con sincronización automática de la barra de título Windows DWM y la paleta del `MenuStrip` nativo.

8. Integración con el Escritorio de Windows:
   - Geometría de widget compacta (abre en `620x760` y después se ajusta al contenido de la sección activa) e icono de bombilla propio para la ventana, la barra de tareas, la bandeja y el ejecutable. La app lleva además identidad propia en la barra de tareas (`AppUserModelID`), así que el botón muestra ese icono y se ancla como aplicación en vez de como el intérprete de Python, incluso corriendo desde el fuente.
   - Barra de menú nativa tematizada (claro/oscuro): **Archivo** (Mostrar/Ocultar ventana, Iniciar con Windows, Salir) y **Ayuda** (Atajos de teclado, Acerca de). Acerca de informa el nombre visible localizado, la versión, la licencia (MIT), el autor y el repositorio.
   - Ergonomía y atajos accesibles: `Space` para encendido, `Alt+Flecha Arriba/Abajo` para brillo (dejando las flechas simples para el desplazamiento vertical), `1`–`6` y `Inicio`/`Fin` entre pestañas de modo, y acceso de ayuda `?` en la barra superior.
   - Opción "Iniciar con Windows" (menú Archivo) que registra la app en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`WizConsole`, migrando automáticamente entradas legacy `GestorDeLuces`) y la inicia minimizada en la bandeja.
   - Instancia única: abrir una segunda copia trae al frente la ventana ya abierta en lugar de crear otra (con opción `--multi-instance` para diagnósticos lado a lado).
   - Se distribuye como instalador por usuario o como ZIP portable (ver [Empaquetado y Distribución](#empaquetado-y-distribución)).

---

## Diagrama de Arquitectura

```
                      +---------------------------------------+
                      |       Interfaz Gráfica (WebView2)     |
                      |   Bandeja del Sistema (NotifyIcon)    |
                      |       Utilidad de Diagnóstico CLI     |
                      +-------------------+-------------------+
                                          |
                              (Puertos Primarios / Driving)
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| CAPA DE APLICACIÓN                                                                |
|   LightControlService  - Orquesta casos de uso y multidifusión a focos            |
|   StreamRateLimiter    - Asegura la tasa de 10 Hz para flujos UDP continuos       |
|   AmbilightStream      - Gestiona la captura de pantalla y el suavizado de color  |
|   MusicSyncStream      - Coordina WASAPI loopback, análisis FFT y mapeo de color   |
|   SleepTimerManager    - Controla el desvanecimiento progresivo del brillo        |
+-----------------------------------------+-----------------------------------------+
                                          |
                              (Puertos Secundarios / Driven)
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| CAPA DE DOMINIO                                                                   |
|   Entidades: Bulb, LightState, CustomScene, BuiltInScene                          |
|   Value Objects: Color, Brightness, ColorTemperature, LightMode, SceneSpeed       |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| ADAPTADORES E INFRAESTRUCTURA                                                     |
|   WizUdpController   - Comunicación por sockets UDP 38899 vía pywizlight          |
|   JsonRepositories   - Persistencia local en %LOCALAPPDATA%/WizConsole             |
|   MssScreenSampler   - Capturador de fotogramas de pantalla de Windows            |
|   WasapiAudioSampler - Muestreador de audio del sistema mediante WASAPI loopback  |
+-----------------------------------------------------------------------------------+
```

Para una explicación exhaustiva de los patrones de diseño, modelo de hilos y prevención de bloqueos, consultá [docs/architecture.es.md](docs/architecture.es.md).

---

## Pila Tecnológica

| Capa | Componente | Versión | Descripción |
|---|---|---|---|
| Entorno de Ejecución | Python | >= 3.12 (verificado en 3.14) | Plataforma base del lenguaje |
| Red | `pywizlight` | 0.6.6 | Transporte por sockets UDP en puerto 38899 |
| Contenedor de Escritorio | `pywebview` | 6.2.1 | Ventana nativa sobre Microsoft Edge WebView2 |
| Bandeja del Sistema | `Pillow` / `pystray` | 13.0.0 / 0.19.5 | `Pillow` dibuja el icono del foco; el menú es un `NotifyIcon` de WinForms y `pystray` queda como vista de respaldo |
| Captura de Pantalla | `mss` | 10.2.0 | Captura eficiente del búfer GDI de Win32 |
| Captura de Audio | `PyAudioWPatch` | 0.2.12.9 | Captura de la salida del sistema vía WASAPI loopback |
| Procesamiento de Señal | `numpy` | 2.5.4 | Transformada Discreta de Fourier y análisis espectral en tiempo real |
| Pruebas | `pytest` / `pytest-asyncio` | 9.0.3 / 1.3.0 | Entorno de pruebas unitarias y de integración |

---

## Estructura del Proyecto

```
.
├── .gitignore
├── assets/
│   └── icon/                    # make_icon.py más app.ico / app.png generados
├── packaging/
│   ├── gestor_luces.spec        # Definición del build PyInstaller (carpeta)
│   └── installer.iss            # Script del instalador por usuario (Inno Setup)
├── scripts/
│   └── build.ps1                # Icono + PyInstaller + ZIP portable + instalador
├── pyproject.toml               # Dependencias, metadatos del proyecto y configuración de pytest
├── README.md                    # Documentación principal en inglés
├── README.es.md                 # Traducción de la documentación al español
├── docs/
│   ├── architecture.md          # Especificación técnica de arquitectura y concurrencia (EN)
│   ├── architecture.es.md       # Especificación técnica de arquitectura y concurrencia (ES)
│   ├── wiz_protocol.md          # Protocolo WiZ UDP y esquemas RPC (EN)
│   ├── wiz_protocol.es.md       # Protocolo WiZ UDP y esquemas RPC (ES)
│   └── design/
│       ├── ui_redesign_spec.md     # Especificación de rediseño de UI (EN)
│       └── ui_redesign_spec.es.md  # Especificación de rediseño de UI (ES)
├── src/
│   └── gestor_luces/
│       ├── __init__.py
│       ├── __main__.py              # Punto de entrada del paquete (python -m gestor_luces)
│       ├── main.py              # Raíz de composición y punto de entrada de la app
│       ├── cli.py               # Herramienta de sondeo y diagnóstico de red por CLI
│       ├── resources.py         # Resolución de assets y versión (dev y congelado con PyInstaller)
│       ├── desktop/             # Ciclo de vida del shell de escritorio y ventana
│       │   └── app.py           # DesktopApplication, sync de menú y eventos de ventana
│       ├── domain/              # Lógica pura del dominio y entidades
│       │   ├── models.py        # Entidades Bulb y LightState
│       │   ├── scenes.py        # Catálogo nativo de WiZ y modelo de presets personalizados
│       │   └── value_objects.py # Validación de Color, Brillo, Kelvin, endpoints y modos
│       ├── ports/               # Contratos (interfaces typing.Protocol)
│       │   ├── light_control.py # Protocolo LightControlServicePort para el escritorio
│       │   ├── repositories.py  # Protocolos de controladores, persistencia y muestreo
│       │   └── autostart.py     # Protocolo AutostartManager
│       ├── application/         # Casos de uso, servicios acotados y gestores de streaming
│       │   ├── service.py       # Fachada principal de orquestación
│       │   ├── service_context.py # Estado compartido, repositorios y cierre de recursos
│       │   ├── bulb_control_service.py    # Comandos de encendido, color, CCT y brillo
│       │   ├── bulb_inventory_service.py  # Descubrimiento, sondeo y gestión de alias
│       │   ├── scene_service.py           # Ejecución de escenas nativas y personalizadas
│       │   ├── timer_service.py           # Coordinación del temporizador de apagado
│       │   ├── ambilight_service.py       # Configuración y ciclo de Ambilight
│       │   ├── music_service.py           # Configuración y ciclo de Music Sync
│       │   ├── settings_service.py        # Preferencias de idioma y tema
│       │   ├── rate_limiter.py  # Limitador de tasa UDP a 10 Hz y suavizado EMA
│       │   ├── sleep_timer.py   # Temporizador de apagado progresivo
│       │   ├── ambilight_stream.py # Gestor de streaming de captura de pantalla
│       │   └── music_stream.py  # Gestor de streaming reactivo a música por WASAPI
│       └── adapters/            # Implementaciones de infraestructura
│           ├── wiz/             # Controlador UDP mediante pywizlight
│           ├── storage/         # Repositorios atómicos en disco JSON (%LOCALAPPDATA%)
│           ├── ambilight/       # Muestreador de pantalla MSS
│           ├── audio/           # Muestreador de audio WASAPI loopback y análisis FFT
│           ├── platform/windows/# Cromado DWM Win32, geometría multimonitor y menús
│           ├── tray/            # Controlador de bandeja, vistas WinForms/Pystray e icono
│           ├── system/          # Autoinicio de Windows (registro) e instancia única
│           └── ui_webview/      # Servidor HTTP endurecido, puente IPC y menú nativo
├── tests/                       # Suite offline de pruebas unitarias, integración, seguridad y CI
│   ├── simulators/              # Servidor simulador UDP de foco WiZ en memoria (`FakeWizBulbServer`)
│   ├── js/                      # Pruebas unitarias, accesibilidad DOM y rendimiento CSS (`node --test`)
│   └── waits.py                 # Esperas acotadas por condición compartidas por la suite
└── ui/                          # Frontend web servido por HTTP loopback dentro de WebView2
    ├── index.html               # Estructura visual de la consola
    ├── themes.css               # Tokens de diseño de 3 niveles y temas
    ├── styles.css               # Disposición de controlador compacto y componentes tokenizados
    ├── scenes.json              # Catálogo nativo de escenas WiZ sincronizado con el dominio
    ├── i18n.js                  # Diccionarios de localización en inglés y español
    └── js/                      # Módulos ES del frontend (`app.js`, `bridge-client.js`,
                                 # `store.js`, `scenes.js`, `stage-controls.js`,
                                 # `fixtures.js`, `ambilight.js`, `music.js`,
                                 # `shortcuts.js`, `toasts.js`, `theme-boot.js`)
```

---

## Instalación y Configuración

### Opción A — Instalador de Windows o ZIP Portable (Recomendado para Usuarios)

No requiere tener Python instalado. Descargá la última versión desde [**GitHub Releases**](https://github.com/AlexisAcevedo/wiz-architectural-lighting-console/releases/latest):

- **Instalador (`GestorDeLuces-Setup-<versión>.exe`)**: Instalación por usuario (sin pedir permisos de administrador) con accesos en el Menú Inicio, icono opcional en el escritorio y registro opcional de "Iniciar con Windows".
- **Portable (`GestorDeLuces-portable-<versión>.zip`)**: Extraelo en cualquier carpeta y ejecutá `GestorDeLuces.exe` (mantené la carpeta `_internal` junto al ejecutable).

**Requisitos del Sistema:**
- Windows 10 (Compilación 1809+) o Windows 11 (64 bits).
- Microsoft Edge WebView2 Evergreen Runtime (preinstalado en Windows 11 y Windows 10 actualizado).
- Red local (LAN) con los focos Philips WiZ en la misma subred (puerto UDP 38899).

---

### Opción B — Ejecutar desde Código Fuente (Para Desarrolladores)

#### Requisitos Previos

- Sistema Operativo: Windows 10 (Compilación 1809 o superior) o Windows 11.
- Python: Versión 3.12 o posterior (probado y verificado en Python 3.14).
- Runtime de WebView2: Microsoft Edge WebView2 Evergreen Runtime.

#### Proceso de Instalación

1. Clonar el repositorio y ubicarse en su carpeta:
   ```bash
   git clone https://github.com/AlexisAcevedo/wiz-architectural-lighting-console.git
   cd wiz-architectural-lighting-console
   ```

2. Crear y activar el entorno virtual de Python:
   ```bash
   python -m venv .venv
   # En Command Prompt (CMD):
   .venv\Scripts\activate.bat
   # En PowerShell:
   .venv\Scripts\Activate.ps1
   # En Git Bash:
   source .venv/Scripts/activate
   ```

3. Instalar el proyecto en modo editable con las herramientas de desarrollo (pruebas, auditoría estática y empaquetado):
   ```bash
   pip install -e ".[dev]"
   ```

   Para ejecutar la app desde el código fuente sin las herramientas de desarrollo,
   instala solo las dependencias de ejecución:
   ```bash
   pip install -e .
   ```

---

## Ejecución de la Aplicación (Desde Código Fuente)

### 1. Modo Interfaz Gráfica (GUI)

Inicia la consola de escritorio completa:

```bash
python -m gestor_luces
# o bien:
python -m gestor_luces.main
```

Parámetros opcionales aceptados por `main.py`:
- `--debug`: Habilita el inspector y las herramientas de desarrollo de pywebview.
- `--minimized`: Inicia oculta en la bandeja del sistema (es el parámetro que registra "Iniciar con Windows").
- `--multi-instance`: Omite el bloqueo de instancia única para permitir ejecutar múltiples instancias simultáneamente.
- `--smoke-test`: Construye la raíz de composición, verifica la integridad de la UI y los iconos sin abrir ventanas nativas, y finaliza con código de salida 0.

### 2. Modo Diagnóstico por Consola (CLI)

El módulo `gestor_luces.cli` permite realizar descubrimientos de red, consultas de estado y pruebas de control por línea de comandos sin inicializar la interfaz gráfica:

```bash
# Descubrir todos los focos presentes en la subred local:
python -m gestor_luces.cli discover

# Consultar el estado en tiempo real de un foco específico:
python -m gestor_luces.cli status --ip 192.168.100.6

# Encender el foco con un 80% de brillo:
python -m gestor_luces.cli on --ip 192.168.100.6 --brightness 80

# Establecer un color RGB:
python -m gestor_luces.cli color --ip 192.168.100.6 255 120 0 --brightness 100

# Ajustar la temperatura de color (CCT en Kelvin):
python -m gestor_luces.cli kelvin --ip 192.168.100.6 2700

# Apagar el foco:
python -m gestor_luces.cli off --ip 192.168.100.6
```

---

## Verificación y Pruebas Automatizadas

La suite de pruebas valida exhaustivamente las reglas de negocio, la persistencia en formato JSON, los límites de frecuencia, el puente asíncrono de PyWebView, la sincronización de la bandeja del sistema, los algoritmos de captura de pantalla y el procesamiento de señales de audio.

Las pruebas se ejecutan de forma 100% independiente de la red real gracias a un servidor simulador UDP en memoria (`FakeWizBulbServer`) que responde a las peticiones JSON-RPC (`getPilot`, `setPilot`, `getSystemConfig`).

Para correr las pruebas:

```bash
pytest
```

Las pruebas de workflows detectan automáticamente Git Bash en Windows (descartando los stubs de WSL y WindowsApps), por lo que la suite completa de `pytest` se ejecuta sin problemas desde PowerShell sin exclusiones `--ignore`.

La cobertura se controla **por paquete**, no como un porcentaje global: `domain` al menos 90 %, `application` al menos 75 % y `adapters` al menos 55 % (`scripts/check_coverage.py`, ejecutado por el CI). El porcentaje del badge de cobertura lo publica `.github/workflows/coverage-badge.yml` en cada push a `main`, así que no se edita a mano. Se mide localmente con `pytest --cov=gestor_luces --cov-report=term-missing` y se verifica con `python scripts/check_coverage.py coverage.json`.

Todas las pruebas deben pasar (ver el badge de CI al inicio de este archivo para el estado en vivo).

Los módulos del frontend bajo `ui/js` se prueban aparte con el runner integrado de Node, así que la capa JS **no agrega ninguna dependencia de npm ni lockfile**:

```bash
npm test
```

Ejecuta las suites bajo `tests/js/` sobre los módulos ES del frontend (`bridge-client`, `app`, `ambilight`, `music`, `fixtures`, `stage-controls`, `toasts`, `store`, `scenes`, `theme-boot`) junto con las suites de regresión de layout/toasts, flujos UX/Undo, accesibilidad WCAG AA, paridad i18n y arranque sin destello (`stage1-layout-toasts` hasta `stage5-native-boot`) bajo un **piso de 60 % de cobertura de líneas** verificado por `--test-coverage-lines`. El job `js tests` de `.github/workflows/ci.yml` corre el mismo comando en cada push y pull request.

El análisis estático de seguridad (`bandit`) y la auditoría de vulnerabilidades en dependencias (`pip-audit`) se ejecutan como comprobaciones **bloqueantes** en el CI en cada push y pull request (ver `.github/workflows/ci.yml`). El reporte JSON de bandit se publica como artefacto del workflow.

Un workflow nocturno (`.github/workflows/nightly.yml`) corre la suite completa cinco veces seguidas, cada pasada en un proceso nuevo, para detectar tests inestables que una sola corrida en verde esconde. Que los procesos sean separados importa: la repeticion dentro del mismo proceso (`--count`) arrastra hilos, sockets y estado cacheado de una pasada a la siguiente, asi que un fallo ahi no se reproduce bajo `ci.yml`. Se puede correr localmente con `for pass in 1 2 3 4 5; do pytest -x --timeout=120 || exit 1; done`.

---

## Empaquetado y Distribución

Para generar todo (icono, app PyInstaller en carpeta, ZIP portable e instalador):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Con `-SkipInstaller` se construyen solo la carpeta de la app y el ZIP portable.

| Salida (en `dist/`) | Descripción |
|---|---|
| `GestorDeLuces\GestorDeLuces.exe` | App portable en carpeta. La carpeta `_internal` debe quedar junto al ejecutable. |
| `GestorDeLuces-portable-<versión>.zip` | La misma carpeta comprimida. Se extrae en cualquier lado y se ejecuta `GestorDeLuces.exe`. |
| `GestorDeLuces-Setup-<versión>.exe` | Instalador por usuario (sin permisos de administrador): acceso en el Menú Inicio, acceso directo opcional en el escritorio y desinstalador. |
| `SHA256SUMS.txt` | Hashes SHA-256 de todos los artefactos generados en `dist/`. |

Requisitos para compilar: el entorno virtual del proyecto (`pip install -e ".[dev]"`), e [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) para el instalador. Si falta Inno Setup, el script omite el instalador con una advertencia. Si `signtool.exe` está en el `PATH` y se define la variable de entorno `SIGN_CERT_SHA1` con el thumbprint del certificado, `scripts/build.ps1` firma `GestorDeLuces.exe` **antes** de crear el ZIP portable y el instalador de Inno Setup (para que ambos incluyan el ejecutable firmado) y luego firma el instalador con SHA-256 y sello de tiempo RFC 3161 por HTTPS (`https://timestamp.digicert.com`).

`packaging/gestor_luces.spec` excluye scripts auxiliares de Python (como `make_icon.py`) del directorio `assets/` empaquetado. `packaging/installer.iss` inicia la ejecución post-instalación con `runasoriginaluser`, elimina de forma incondicional la clave de autoinicio en `HKCU\...\Run` al desinstalar e incluye mensajes personalizados bilingües en inglés y español (`[CustomMessages]`).

### Publicar una release

Las releases las compila y publica el CI; los comandos de arriba son para compilaciones locales. El procedimiento es:

1. Subir la versión en `pyproject.toml` (`chore(release): bump version to X.Y.Z`).
2. Escribir `docs/releases/X.Y.Z.md` con las notas de esa release ([convención](docs/releases/README.md)).
3. Mergear, y después taggear el commit mergeado y pushear el tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

`.github/workflows/release.yml` fija todas las acciones de terceros por su SHA de commit, fija la versión de Inno Setup (`6.7.1`) y restringe `contents: write` exclusivamente al job `publish`. `guard` falla en segundos cuando el tag no coincide con `pyproject.toml` o cuando falta el archivo de notas; `build` genera el instalador y el ZIP portable en un runner Windows; `verify` corre `sha256sum -c SHA256SUMS.txt` y `GestorDeLuces.exe --smoke-test` sobre exactamente los bytes que se van a publicar; `publish` sube a una release en **borrador**, compara los digests que informa GitHub contra los archivos compilados y recién entonces publica. Para ensayar, se corre el workflow a mano con `dry_run` activado: repite todos los pasos menos la publicación final y descarta el borrador.

Notas para las PCs de destino:
- Windows 10/11 de 64 bits con el Runtime de Microsoft Edge WebView2 (viene en Windows 11 y en la mayoría de los Windows 10 actualizados). El instalador avisa si falta, pero no lo instala.
- Salvo que se compile con `SIGN_CERT_SHA1`, los ejecutables no están firmados, así que SmartScreen muestra "Windows protegió tu PC": elegí **Más información** y luego **Ejecutar de todas formas**. Verificá la descarga contra `SHA256SUMS.txt`.
- La instalación por defecto es por usuario en `%LOCALAPPDATA%\Programs\GestorDeLuces` (no pide permisos de administrador); si se requiere proteger los binarios bajo `C:\Program Files`, ejecutá el instalador como administrador o con `/ALLUSERS`.
- Los datos del usuario viven en `%LOCALAPPDATA%\WizConsole` (con migración automática única desde `%LOCALAPPDATA%\GestorDeLuces`, conservando los archivos originales como respaldo), nunca junto al ejecutable.
- Si se mueve la carpeta portable con "Iniciar con Windows" activado, la entrada del registro se corrige en el siguiente arranque.
- A veces `Compress-Archive` falla por un archivo bloqueado justo después de PyInstaller (el antivirus lo está escaneando); volvé a correr el script.

---

## Documentación Técnica Detallada

- [Arquitectura y Concurrencia](docs/architecture.es.md): Análisis detallado del diseño hexagonal, ciclo de vida de los hilos y prevención de condiciones de carrera.
- [Protocolo WiZ UDP y Modos de Streaming](docs/wiz_protocol.es.md): Especificación técnica de los paquetes JSON-RPC, regulación a 10 Hz y catálogo de escenas.
- [Especificación de Rediseño de UI](docs/design/ui_redesign_spec.es.md): Dirección de diseño para la exploración de rediseño de UI en dos worktrees.
- [English Documentation](README.md): Full documentation in English.

