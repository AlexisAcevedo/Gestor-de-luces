# Gestor de Luces

[English](README.md) | [Español](README.es.md)

Centro de control de escritorio para sistemas de iluminación inteligente Philips WiZ sobre redes de área local (LAN). Diseñado con Python, Arquitectura Hexagonal (Puertos y Adaptadores) y Microsoft WebView2 (PyWebView), operando de manera exclusiva mediante paquetes UDP locales sin dependencias de la nube, puentes externos ni necesidad de conexión a Internet.

---

## Aspectos Destacados de la Arquitectura

- Cero Dependencia de la Nube: Comunicación local directa con los focos WiZ mediante el puerto UDP 38899.
- Arquitectura Hexagonal: Desacoplamiento total entre la lógica del dominio, la gestión del estado, la interfaz de usuario, el streaming de hardware y la persistencia de datos.
- Concurrencia Multihilo: Bucle de eventos asíncrono e independiente para I/O de red, hilos aislados en segundo plano para streaming y bandeja del sistema no bloqueante.
- Limitación de Frecuencia por Hardware: Regulación estricta a 10 Hz (100 ms) para evitar la saturación de los microcontroladores ESP integrados en los focos durante el streaming continuo.
- Pruebas 100% Fuera de Línea: Suite de 73 pruebas automatizadas que utilizan un simulador UDP en memoria que replica fielmente el comportamiento JSON-RPC de WiZ.

---

## Características Principales

1. Control Fotométrico Completo:
   - Encendido y apagado en tiempo real, ajuste de curva de atenuación (10% a 100%) y sondeo de estado.
   - Regulación de Temperatura de Color Correlacionada (CCT) desde 2.200 K (Blanco Cálido Incandescente) hasta 6.500 K (Luz Día Fría).
   - Selección de color RGB con previsualización en vivo e ingreso hexadecimal.

2. Catálogo de Escenas Nativas y Presets Personalizados:
   - Catálogo completo de las 36 escenas de fábrica de WiZ con regulación dinámica de velocidad (20% a 200%).
   - Presets de iluminación personalizados por el usuario, almacenados localmente con recuperación y eliminación en un clic.

3. Sincronización Ambiental de Pantalla (Ambilight):
   - Muestreo en tiempo real de la pantalla utilizando captura GDI Win32 pura en Python (`mss`).
   - Múltiples algoritmos de muestreo: color promedio general, color dominante de bordes o centroide de alta luminosidad.
   - Streaming continuo a 10 Hz mediante paquetes UDP sin confirmación (fire-and-forget) y suavizado de color por Media Móvil Exponencial (EMA).

4. Sincronización Musical Reactiva por WASAPI Loopback:
   - Captura de audio del sistema en tiempo real mediante loopback de Windows Audio Session API (WASAPI) (`PyAudioWPatch`).
   - Descomposición espectral por Transformada Rápida de Fourier (FFT) en bandas de Bajos, Medios y Agudos mediante `numpy`.
   - Mapeo de frecuencias a color con sensibilidad de ganancia configurable y caída suavizada.

5. Bandeja del Sistema y Ejecución en Segundo Plano:
   - Ejecución silenciosa en el Área de Notificación de Windows mediante `pystray`.
   - Menú de presets rápidos, alternancia de encendido general y minimización elegante a la bandeja al cerrar la ventana.
   - Sincronización libre de bloqueos mutuos (deadlocks) entre WinForms y PyWebView.

6. Temporizador de Apagado Progresivo (Sleep Timer):
   - Cuenta regresiva configurable (1 a 120 minutos) con atenuación progresiva del brillo hasta cero antes del apagado final.

7. Consola de Escritorio Bilingüe:
   - Interfaz bilingüe nativa en inglés (`en`) y español (`es`) con cambio instantáneo y dinámico en la UI, el menú de la bandeja y la barra de menú de la ventana.

8. Integración con el Escritorio de Windows:
   - Icono de bombilla propio para la ventana, la barra de tareas, la bandeja y el ejecutable.
   - Barra de menú nativa: **Archivo** (Mostrar/Ocultar ventana, Iniciar con Windows, Salir) y **Ayuda** (Atajos de teclado, Acerca de).
   - Opción "Iniciar con Windows" (menú Archivo) que registra la app en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` y la inicia minimizada en la bandeja.
   - Instancia única: abrir una segunda copia trae al frente la ventana ya abierta en lugar de crear otra.
   - Se distribuye como instalador por usuario o como ZIP portable (ver [Empaquetado y Distribución](#empaquetado-y-distribución)).

---

## Diagrama de Arquitectura

```
                      +---------------------------------------+
                      |       Interfaz Gráfica (WebView2)     |
                      |       Bandeja del Sistema (pystray)   |
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
|   JsonRepositories   - Persistencia local en %LOCALAPPDATA%/GestorDeLuces         |
|   MssScreenSampler   - Capturador de fotogramas de pantalla de Windows            |
|   WasapiAudioSampler - Muestreador de audio del sistema mediante WASAPI loopback  |
+-----------------------------------------------------------------------------------+
```

Para una explicación exhaustiva de los patrones de diseño, modelo de hilos y prevención de bloqueos, consultá [docs/architecture.es.md](docs/architecture.es.md).

---

## Pila Tecnológica

| Capa | Componente | Versión | Descripción |
|---|---|---|---|
| Entorno de Ejecución | Python | >= 3.11 (verificado en 3.14) | Plataforma base del lenguaje |
| Red | `pywizlight` | 0.6.6 | Transporte por sockets UDP en puerto 38899 |
| Contenedor de Escritorio | `pywebview` | 6.2.1 | Ventana nativa sobre Microsoft Edge WebView2 |
| Bandeja del Sistema | `pystray` / `Pillow` | 0.19.5 / 13.0.0 | Icono y menú en el Área de Notificaciones de Windows |
| Captura de Pantalla | `mss` | 10.2.0 | Captura eficiente del búfer GDI de Win32 |
| Captura de Audio | `PyAudioWPatch` | 0.2.12.9 | Captura de la salida del sistema vía WASAPI loopback |
| Procesamiento de Señal | `numpy` | 2.5.4 | Transformada Discreta de Fourier y análisis espectral en tiempo real |
| Testing | `pytest` / `pytest-asyncio` | 9.0.3 / 1.3.0 | Entorno de pruebas unitarias y de integración |

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
├── pyproject.toml               # Metadatos del proyecto y configuración de pytest
├── requirements.txt             # Dependencias fijadas para producción y pruebas
├── requirements-dev.txt         # Dependencias de desarrollo, auditoría y empaquetado
├── README.md                    # Documentación principal en inglés
├── README.es.md                 # Traducción de la documentación al español
├── docs/
│   ├── architecture.md          # Especificación técnica de arquitectura y concurrencia (EN)
│   ├── architecture.es.md       # Especificación técnica de arquitectura y concurrencia (ES)
│   ├── wiz_protocol.md          # Protocolo WiZ UDP y esquemas RPC (EN)
│   └── wiz_protocol.es.md       # Protocolo WiZ UDP y esquemas RPC (ES)
├── src/
│   └── gestor_luces/
│       ├── __init__.py
│       ├── main.py              # Raíz de composición y punto de entrada de la app
│       ├── cli.py               # Herramienta de sondeo y diagnóstico de red por CLI
│       ├── resources.py         # Resolución de assets y versión (dev y congelado con PyInstaller)
│       ├── domain/              # Lógica pura del dominio y entidades
│       │   ├── models.py        # Entidades Bulb, LightState y Group
│       │   ├── scenes.py        # Catálogo nativo de WiZ y modelo de presets personalizados
│       │   └── value_objects.py # Validación de Color, Brillo, Kelvin y Modos
│       ├── ports/               # Contratos (interfaces typing.Protocol)
│       │   ├── interfaces.py    # Exportación centralizada de puertos
│       │   ├── repositories.py  # Protocolos de controladores, persistencia y muestreo
│       │   └── autostart.py     # Protocolo AutostartManager
│       ├── application/         # Casos de uso y gestores de streaming
│       │   ├── service.py       # Servicio principal de orquestación
│       │   ├── rate_limiter.py  # Limitador de tasa UDP a 10 Hz
│       │   ├── sleep_timer.py   # Temporizador de apagado progresivo
│       │   ├── ambilight_stream.py # Gestor de streaming de captura de pantalla
│       │   └── music_stream.py  # Gestor de streaming reactivo a música por WASAPI
│       └── adapters/            # Implementaciones de infraestructura
│           ├── wiz/             # Controlador UDP mediante pywizlight
│           ├── storage/         # Repositorios en disco JSON (%LOCALAPPDATA%)
│           ├── ambilight/       # Muestreador de pantalla MSS
│           ├── audio/           # Muestreador de audio WASAPI loopback
│           ├── tray/            # Bandeja del sistema con pystray y render compartido de la bombilla
│           ├── system/          # Autoinicio de Windows (registro) e instancia única
│           └── ui_webview/      # Puente seguro JS-Python y modelo del menú nativo
├── tests/                       # Suite de pruebas automatizadas (73 tests)
│   ├── simulators/              # Servidor simulador UDP de foco WiZ en memoria
│   ├── test_domain.py           # Pruebas de reglas e invariantes del dominio
│   ├── test_rate_limiter.py     # Pruebas del limitador de frecuencia
│   ├── test_persistence_and_scenes.py # Pruebas de persistencia JSON y presets
│   ├── test_wiz_integration.py  # Pruebas de integración UDP contra el simulador
│   ├── test_ui_bridge.py        # Pruebas del puente asíncrono con la interfaz gráfica
│   ├── test_tray.py             # Pruebas de la bandeja del sistema y sincronización
│   ├── test_ambilight.py        # Pruebas de captura de pantalla y suavizado EMA
│   ├── test_music_sync.py       # Pruebas de análisis espectral FFT y WASAPI
│   ├── test_i18n.py             # Pruebas de localización bilingüe
│   ├── test_app_shell.py        # Pruebas del menú, autoinicio, --minimized y assets
│   └── test_security_hardening.py # Pruebas de regresión de seguridad y rendimiento
└── ui/                          # Frontend web embebido en WebView2
    ├── index.html               # Estructura visual de la consola
    ├── styles.css               # Estilos de consola fotométrica oscura
    ├── app.js                   # Controlador de estado reactivo de la interfaz
    └── i18n.js                  # Diccionarios de localización en inglés y español
```

---

## Instalación y Configuración

### Opción A — Instalador de Windows o ZIP Portable (Recomendado para Usuarios)

No requiere tener Python instalado. Descargá la última versión desde [**GitHub Releases**](https://github.com/AlexisAcevedo/Gestor-de-luces/releases/latest):

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
- Python: Versión 3.11 o posterior (probado y verificado en Python 3.14).
- Runtime de WebView2: Microsoft Edge WebView2 Evergreen Runtime.

#### Proceso de Instalación

1. Clonar el repositorio y ubicarse en su carpeta:
   ```bash
   git clone https://github.com/AlexisAcevedo/Gestor-de-luces.git
   cd Gestor-de-luces
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

3. Instalar las dependencias (`requirements.txt` para ejecución/pruebas, o `requirements-dev.txt` para incluir auditoría estática y empaquetado):
   ```bash
   pip install -r requirements-dev.txt
   ```

---

## Ejecución de la Aplicación (Desde Código Fuente)

### 1. Modo Interfaz Gráfica (GUI)

Inicia la consola de escritorio completa:

```bash
python -m gestor_luces.main
```

Parámetros opcionales aceptados por `main.py`:
- `--debug`: Habilita el inspector y las herramientas de desarrollo de pywebview.
- `--minimized`: Inicia oculta en la bandeja del sistema (es el parámetro que registra "Iniciar con Windows").
- `--smoke-test`: Construye la raíz de composición, verifica la integridad de la UI y los iconos sin abrir ventanas nativas, y finaliza con código de salida 0.

### 2. Modo Diagnóstico por Consola (CLI)

El módulo `gestor_luces.cli` permite realizar descubrimientos de red, consultas de estado y pruebas de control por línea de comandos sin inicializar la interfaz gráfica:

```bash
# Descubrir todos los focos presentes en la subred local:
python -m gestor_luces.cli discover

# Consultar el estado en tiempo real de un foco específico:
python -m gestor_luces.cli status 192.168.100.6

# Encender el foco con un 80% de brillo:
python -m gestor_luces.cli on 192.168.100.6 --brightness 80

# Establecer un color RGB:
python -m gestor_luces.cli color 192.168.100.6 255 120 0 --brightness 100

# Ajustar la temperatura de color (CCT en Kelvin):
python -m gestor_luces.cli temp 192.168.100.6 2700

# Activar una escena de fábrica por su número de ID:
python -m gestor_luces.cli scene 192.168.100.6 5 --speed 120

# Apagar el foco:
python -m gestor_luces.cli off 192.168.100.6
```

---

## Verificación y Pruebas Automatizadas

La suite de pruebas valida exhaustivamente las reglas de negocio, la persistencia en formato JSON, los límites de frecuencia, el puente asíncrono de PyWebView, la sincronización de la bandeja del sistema, los algoritmos de captura de pantalla y el procesamiento de señales de audio.

Las pruebas se ejecutan de forma 100% independiente de la red real gracias a un servidor simulador UDP en memoria (`FakeWizBulbServer`) que responde a las peticiones JSON-RPC (`getPilot`, `setPilot`, `getSystemConfig`).

Para correr las pruebas:

```bash
pytest
```

Resultado esperado:
```
73 passed in ~2.0s
```

Para ejecutar el análisis estático de seguridad y la auditoría de vulnerabilidades en dependencias (usando `requirements-dev.txt`):

```bash
python -m bandit -r src -q
python -m pip_audit -r requirements.txt
```

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

Requisitos para compilar: el entorno virtual del proyecto con `requirements.txt` (o `requirements-dev.txt`), e [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) para el instalador. Si falta Inno Setup, el script omite el instalador con una advertencia. Si `signtool.exe` está en el `PATH` y se define la variable de entorno `SIGN_CERT_SHA1` con el thumbprint del certificado, `build.ps1` firma automáticamente el ejecutable y el instalador con SHA-256 y sello de tiempo RFC 3161.

Notas para las PCs de destino:
- Windows 10/11 de 64 bits con el Runtime de Microsoft Edge WebView2 (viene en Windows 11 y en la mayoría de los Windows 10 actualizados). El instalador avisa si falta, pero no lo instala.
- Salvo que se compile con `SIGN_CERT_SHA1`, los ejecutables no están firmados, así que SmartScreen muestra "Windows protegió tu PC": elegí **Más información** y luego **Ejecutar de todas formas**. Verificá la descarga contra `SHA256SUMS.txt`.
- La instalación por defecto es por usuario en `%LOCALAPPDATA%\Programs\GestorDeLuces` (no pide permisos de administrador); si se requiere proteger los binarios bajo `C:\Program Files`, ejecutá el instalador como administrador o con `/ALLUSERS`.
- Los datos del usuario viven en `%LOCALAPPDATA%\GestorDeLuces`, nunca junto al ejecutable.
- Si se mueve la carpeta portable con "Iniciar con Windows" activado, la entrada del registro se corrige en el siguiente arranque.
- A veces `Compress-Archive` falla por un archivo bloqueado justo después de PyInstaller (el antivirus lo está escaneando); volvé a correr el script.

---

## Documentación Técnica Detallada

- [Arquitectura y Concurrencia](docs/architecture.es.md): Análisis detallado del diseño hexagonal, ciclo de vida de los hilos y prevención de condiciones de carrera.
- [Protocolo WiZ UDP y Modos de Streaming](docs/wiz_protocol.es.md): Especificación técnica de los paquetes JSON-RPC, regulación a 10 Hz y catálogo de escenas.
- [English Documentation](README.md): Full documentation in English.

