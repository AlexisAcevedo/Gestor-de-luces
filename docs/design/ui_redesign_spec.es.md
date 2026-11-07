# Especificación de Rediseño de UI — Exploración en Dos Worktrees

## 1. Contexto y Diagnóstico del Problema

La interfaz de escritorio actual (`ui/index.html`, `ui/styles.css`, `ui/app.js`) utiliza una estética densa de "Consola Fotométrica" que presenta varios problemas estructurales y visuales detectados en la revisión de diseño:

1. **Jerarquía Visual Competitiva ("Too much + Flat"):** Cinco bloques pesados (barra lateral de lámparas, encabezado de telemetría, caja de brillo con 5 botones de porcentaje, barra de 6 pestañas y panel de trabajo RGB con 4 campos numéricos) compiten con el mismo peso visual y bordes estructurales duros (`#5A657A` / `#353E4F`).
2. **Prioridad de Uso Invertida:** El flujo diario real del usuario consiste en **encender y apagar rápido el foco (ON/OFF)**, **ajustar el porcentaje de brillo (dimming)** y **elegir la calidez del tono blanco (temperatura Kelvin)** para un foco principal. Sin embargo, la interfaz actual dedica ~30% del ancho a una barra lateral fija de red multi-foco y abre por defecto en la rueda cromática RGB.
3. **Tamaño de Ventana Desproporcionado:** `src/gestor_luces/main.py` fuerza actualmente la ventana al 90% del monitor principal (`WINDOW_SCREEN_RATIO = 0.9`, hasta `1440x920`), lo cual resulta excesivo para un controlador de escritorio de acceso rápido.
4. **Clichés de Dashboard Generado por IA:** Abuso de etiquetas técnicas en fuente monoespaciada (`UDP 38899`, `STANDBY`), textos en mayúsculas con espaciado ancho y tarjetas encajonadas idénticas.

---

## 2. Skill de Diseño de Referencia (`benjitaylor/skills` — `stageshow`)

La skill `stageshow` (`https://github.com/benjitaylor/skills`) ya se encuentra instalada localmente en `.agents/skills/stageshow/` (la skill anterior `frontend-design` fue eliminada para evitar conflictos). Leer `.agents/skills/stageshow/SKILL.md`, `.agents/skills/stageshow/references/craft.md`, `.agents/skills/stageshow/references/looks.md`, `.agents/skills/stageshow/examples/dark-hero` y `.agents/skills/stageshow/examples/looks/skeuomorphic.tsx` antes de planificar o escribir código.

> **Nota para Worktrees:** Dado que `.agents/` está en `.gitignore`, el comando `git worktree add` no copiará `.agents/skills/stageshow/` automáticamente a los nuevos worktrees. Copiar la carpeta `.agents/` dentro de cada worktree creado (o leerla desde la raíz del repositorio principal) para que la skill esté disponible en ambos entornos.

> **Nota Arquitectónica:** **No** migrar la aplicación a React ni reemplazar los controles reales de PyWebView por el kit de animaciones simuladas de `stageshow`. Se debe mantener intacto el stack actual en Vanilla HTML/CSS/JS y la Arquitectura Hexagonal. El objetivo es extraer y aplicar las **reglas de oficio visual, disciplina de tokens, jerarquía de superficies y tipografía** de `stageshow` a la UI real de la aplicación, ejecutando `modern-web-guidance` primero para todos los patrones HTML/CSS/DOM.

### Reglas Centrales de Oficio de `stageshow` a Aplicar
- **Un Único Punto Focal Claro:** La vista debe dirigirse de inmediato al control principal (Encendido Maestro + Brillo + Calidez/Kelvin).
- **Jerarquía mediante Pasos de Superficie, No Bordes de Cajas:** Reemplazar los bordes de alto contraste tipo wireframe por diferencias sutiles de superficie, brillos superiores coherentes (`inset 0 1px 0`) y espacio en blanco intencional.
- **Restricción Tipográfica:**
  - Una sola familia sans-serif (`--font-sans`), usando mayúscula inicial normal (*sentence case*) en lugar de etiquetas en `MAYÚSCULAS`.
  - Reservar `--font-mono` (`font-variant-numeric: tabular-nums`) estrictamente para valores numéricos en vivo (`2700 K`, `85%`, direcciones IP), nunca para etiquetas decorativas.
  - Eliminar el ruido de telemetría decorativa (`UDP 38899` fijo, subtítulos redundantes).
- **Espaciado y Alineación:**
  - Margen interno mínimo de `12px` para textos respecto a los bordes de su contenedor; separación mínima de `8px` entre controles interactivos.
  - Agrupar por espacio en blanco (*whitespace groups*) en lugar de líneas divisorias.

---

## 3. Arquitectura Espacial Compartida (Aplica a Ambas Ramas)

Ambas ramas experimentales deben implementar la misma reorganización estructural antes de aplicar su identidad estética particular:

### 3.1. Controlador Compacto de Una Columna + Cajón Deslizable (Drawer) de Focos
- **Eliminar la barra lateral izquierda fija del 30% de ancho (`aside.fixture-rail`) de la grilla principal.**
- Reemplazarla en la barra superior por un **Botón / Píldora de Foco Activo** (ícono de menú / drawer + nombre del foco activo + punto de estado en línea) y el **Selector Rápido de Idioma (`EN` / `ES`)**.
- Mover `aside.fixture-rail` (que contiene `#fixture-list`, `#scan-network-btn`, `#open-add-dialog-btn`, `#select-all-fixtures`, `#fixture-count-badge`, `#sync-now-btn`, `#auto-sync-toggle`, `#shortcuts-help-btn` y `#status-banner`) dentro de un **Drawer / panel lateral deslizable** que permanece oculto durante el uso diario y se despliega suavemente al hacer clic en el botón de foco/menú.

### 3.2. Escenario Principal (Hero): Encendido Rápido + Brillo + Calidez (Kelvin)
- **Interruptor Maestro Protagonista (`#master-power-btn`):** Control central/superior táctil y prominente para encender y apagar al instante (también vinculado a la barra espaciadora `Space`), acompañado por `#photometric-aperture` y `#live-state-pill`.
- **Control Primario de Brillo (`#brightness-slider` + `#brightness-output`):** Pista deslizante ancha y táctil integrada directamente en el escenario principal. Mantener los botones `.brightness-preset` discretos o compactos para que no compitan con el deslizador.
- **Modo por Defecto (`Blanco / Kelvin` primero):**
  - Establecer **Blanco / Calidez (Kelvin)** (`#tab-btn-temperature` / `#panel-temperature`) como la vista activa inicial —o integrar la calidez (`#kelvin-slider`, `#kelvin-output`, tarjetas `.kelvin-card` de `2200 K` a `6500 K`) en la vista principal— para que el usuario pueda prender/apagar, regular el brillo y elegir la calidez apenas abre la app.
  - Mantener `#quick-save-preset-btn` accesible de forma discreta sin recargar el botón de encendido.

### 3.3. Dock Inferior Silencioso de Modos y Revelación Progresiva
- Rediseñar `.mode-tabs` como un control segmentado o dock compacto y silencioso para alternar entre:
  1. **Blanco / Calidez (`temperature`)** — Pestaña activa por defecto
  2. **Color (`rgb`)** — Con `#color-wheel-canvas` como protagonista y los campos numéricos (`#input-r`, `#input-g`, `#input-b`, `#input-hex`, `#apply-rgb-btn`) guardados en una sección colapsable/popover secundaria junto a `#swatch-grid`
  3. **Escenas (`scene`)** — Las 36 escenas nativas de WiZ con filtros de categoría y velocidad
  4. **Presets (`custom`)** — Escenas personalizadas guardadas por el usuario
  5. **Ambilight (`ambilight`)** — Sincronización de pantalla en tiempo real
  6. **Música (`music`)** — Sincronización de audio WASAPI
- **Indicador Vivo de Procesos en Segundo Plano:** Mantener `#tab-ambilight-dot`, `#tab-music-dot` y la barra colapsable `#sleep-timer-details` limpios y discretos al pie del escenario, mostrando una píldora de estado clara cuando Ambilight, Music Sync o el Sleep Timer estén activos.

### 3.4. Geometría Compacta de Ventana en Escritorio (`src/gestor_luces/main.py`)
- Actualizar las dimensiones iniciales de la ventana en `src/gestor_luces/main.py` para que la aplicación abra como un controlador de escritorio compacto y proporcionado (por ejemplo, ancho inicial `~520–620px`, alto `~720–800px`, tamaño mínimo `~460x600`) en lugar de `WINDOW_SCREEN_RATIO = 0.9` (`1440x920`), manteniendo el diseño responsivo si el usuario decide agrandar la ventana.

---

## 4. Estrategia de Ramas, Worktrees y Subagentes en Paralelo

Crear dos ramas de Git y dos worktrees aislados a partir de `main` para poder ejecutar, probar y comparar ambos diseños lado a lado:

1. **Rama A:** `ui/atmospheric-dark` (Ruta sugerida de worktree: `../gestor-luces-atmospheric-dark` o `.worktrees/atmospheric-dark`)
2. **Rama B:** `ui/architectural-stone` (Ruta sugerida de worktree: `../gestor-luces-architectural-stone` o `.worktrees/architectural-stone`)

### Subagentes Especializados Disponibles en `.agents/agents/`
- **`ui-craft-specialist`** (`.agents/agents/ui-craft-specialist.md`): Especialista de implementación de UI con permisos de escritura, preconfigurado con las reglas de `stageshow`, `modern-web-guidance`, restricciones CSP y contratos de DOM/i18n. Invocar una instancia por cada worktree para construir ambas variantes en paralelo.
- **`hexagonal-auditor`** (`.agents/agents/hexagonal-auditor.md`): Auditor de solo lectura de arquitectura y pruebas. Invocar al finalizar la implementación para validar los límites hexagonales y ejecutar `.venv\Scripts\pytest.exe -q`.

---

## 5. Especificaciones Estéticas por Rama

### 5.1. Rama A: `ui/atmospheric-dark` (Opción 2 — *Atmospheric Glass & Light*)
*Dirección visual inspirada en `stageshow/examples/dark-hero`, Apple Home y proyección lumínica ambiental.*

- **Paleta y Superficies:**
  - Lienzo negro carbón mate profundo (`#08090C`) cuando el foco está apagado (`data-power="off"`).
  - Superficies elevadas de cristal esmerilado translúcido (`rgba(22, 25, 32, 0.72)` con `backdrop-filter: blur(24px)`) y borde especular superior sutil (`1px solid rgba(255, 255, 255, 0.08)`).
- **Halo Fotométrico Atmosférico:**
  - Cuando `data-power="on"`, proyectar un resplandor radial amplio y difuso detrás del encabezado/escenario usando `color-mix(in oklab, var(--beam-color) 35%, transparent)` para que la calidez real en Kelvin (`2200 K` ámbar hasta `6500 K` luz día) o el color RGB bañe orgánicamente el ambiente de la app sin usar bordes de colores duros.
- **Controles:**
  - Pistas deslizantes táctiles tipo píldora (`height: 36px–44px`, `border-radius: 14px`) rellenas con un gradiente suave de luminosidad guiado por `--beam-color`.
  - Botón/orbe de encendido escultórico que responde suavemente a la emisión de luz activa.

### 5.2. Rama B: `ui/architectural-stone` (Opción 3 — *Minimal Precision / Braun & Lutron*)
*Dirección visual inspirada en `stageshow/examples/looks/skeuomorphic.tsx`, Dieter Rams (Braun) y botoneras arquitectónicas Lutron Palladiom.*

- **Paleta y Superficies:**
  - Chasis en tonos de piedra caliza cálida y papel mineral (`#F4F1EA` / `#EFECE6`), cavidades de control empotradas (`#E5E0D8` con sombra interior sutil) y teclas/tarjetas físicas en blanco mate nítido (`#FFFFFF` con `0 1px 2px rgba(20, 18, 15, 0.08), 0 0 0 1px rgba(20, 18, 15, 0.06)`).
  - Tipografía color tinta de alto contraste (`#181715` primario, `#6E6A63` secundario).
  - Conmutador sutil opcional de tema (Piedra Día vs. Grafito Noche), abriendo por defecto en Piedra Cálida Arquitectónica.
- **Representación Física de la Luz sobre Superficie Clara:**
  - En lugar de teñir todo el fondo, representar `--beam-color` mediante un **anillo/apertura óptica empotrada** con sombra interna y pistas deslizantes retroiluminadas que brillen con profundidad física contra la piedra mate.
- **Controles:**
  - Proporciones de hardware de precisión (`border-radius: 8px`), respuesta mecánica al presionar (`transform: translateY(1px)`) y marcas de escala grabadas con limpieza en las pistas de Kelvin y Brillo.

---

## 6. Contratos Técnicos y de Tests Innegociables (Checklist Cero Pérdida)

Para garantizar cero regresiones en `ui/app.js`, `ui/i18n.js`, `WebviewBridge` y la suite de `pytest` (`tests/test_i18n.py`, `tests/test_app_shell.py`, `tests/test_security_hardening.py`, `tests/test_ui_bridge.py`), ambas ramas **DEBEN** preservar:

1. **Content Security Policy (CSP):**
   Mantener intacta la etiqueta `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' file:; style-src 'self' file:; img-src 'self' file: data:; font-src 'self' file:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">` en `ui/index.html`. No usar fuentes de CDNs externos ni scripts inline.
2. **IDs y Selectores del DOM Requeridos por `ui/app.js` y `tests/test_i18n.py`:**
   - Contenedor y Notificaciones: `#toast-region`, `#console-shell` (con atributo `data-power`)
   - Idioma y Drawer de Focos: `#lang-btn-en`, `#lang-btn-es`, `#scan-network-btn`, `#scan-btn-label`, `#open-add-dialog-btn`, `#select-all-fixtures`, `#fixture-count-badge`, `#fixture-list`, `#sync-now-btn`, `#auto-sync-toggle`, `#shortcuts-help-btn`, `#status-banner`
   - Encabezado y Encendido Maestro: `#photometric-aperture`, `#target-summary`, `#live-state-pill`, `#telemetry-meta`, `#quick-save-preset-btn`, `#master-power-btn`, `#master-power-label`
   - Brillo (Dimming): `#brightness-slider`, `#brightness-output`, `.brightness-preset[data-brightness]`
   - Pestañas y Paneles de Modo: `#tab-btn-rgb` (`#panel-rgb`), `#tab-btn-temperature` (`#panel-temperature`), `#tab-btn-scene` (`#panel-scene`), `#tab-btn-custom` (`#panel-custom`, `#custom-tab-label`), `#tab-btn-ambilight` (`#panel-ambilight`, `#tab-ambilight-dot`), `#tab-music` (`#panel-music`, `#tab-music-dot`), `.mode-tab[data-mode]`
   - Controles RGB: `#color-wheel-canvas`, `#wheel-reticle`, `#input-r`, `#input-g`, `#input-b`, `#input-hex`, `#apply-rgb-btn`, `#swatch-grid`, `.color-swatch`
   - Controles Kelvin: `#kelvin-slider`, `#kelvin-output`, `.kelvin-card[data-kelvin]`
   - Escenas y Presets: `#scene-category-bar`, `#scene-filter-favorites`, `#scene-cat-favorites-label`, `.scene-filter[data-category]`, `#scene-speed-container`, `#scene-speed-slider`, `#scene-speed-output`, `#scenes-grid`, `#open-save-scene-dialog-btn`, `#custom-scenes-grid`
   - Controles Ambilight: `#ambilight-status-badge`, `#ambilight-frames-readout`, `#ambilight-preview-swatch`, `#ambilight-color-readout`, `#toggle-ambilight-btn`, `#toggle-ambilight-label`, `#ambilight-monitor-select`, `.ambilight-mode-btn[data-color-mode]`, `#ambilight-smoothing-slider`, `#ambilight-smoothing-output`, `#ambilight-auto-brightness`, `#ambilight-min-brightness-row`, `#ambilight-min-brightness-slider`, `#ambilight-min-brightness-output`
   - Controles Music Sync: `#music-status-badge`, `#music-frames-readout`, `#music-preview-swatch`, `#music-color-readout`, `#music-meter-bass-val`, `#music-meter-bass-fill`, `#music-meter-mid-val`, `#music-meter-mid-fill`, `#music-meter-treble-val`, `#music-meter-treble-fill`, `#music-meter-rms-val`, `#music-meter-rms-fill`, `#toggle-music-btn`, `#toggle-music-label`, `#music-device-select`, `.music-palette-btn[data-palette-mode]`, `#music-sensitivity-slider`, `#music-sensitivity-output`, `#music-smoothing-slider`, `#music-smoothing-output`, `#music-audio-brightness`
   - Temporizador (Sleep Timer): `#sleep-timer-details`, `#sleep-timer-badge`, `.sleep-preset-btn[data-minutes]`, `#sleep-minutes-input`, `#start-sleep-timer-btn`, `#cancel-sleep-timer-btn`
   - Modales (`<dialog>`): `#add-bulb-dialog` (`#add-bulb-form`, `#manual-ip-input`, `#manual-name-input`, `#submit-add-bulb-btn`), `#rename-bulb-dialog` (`#rename-bulb-form`, `#rename-bulb-ip-display`, `#rename-bulb-ip-input`, `#rename-bulb-name-input`), `#shortcuts-dialog`, `#custom-scene-dialog` (`#custom-scene-form`, `#custom-scene-dialog-title`, `#custom-scene-dialog-subtitle`, `#custom-scene-id-input`, `#custom-scene-name-input`, `#custom-scene-overwrite-row`, `#custom-scene-overwrite-checkbox`, `#custom-scene-submit-btn`)
3. **Integridad Bilingüe (`tests/test_i18n.py`):**
   - Preservar `<script src="i18n.js"></script>` y `<script src="app.js"></script>`.
   - Mantener todas las claves existentes en `ui/i18n.js` verificadas por `test_ui_i18n_assets_and_builtin_scene_names_preserved` (cualquier texto nuevo debe agregarse tanto en `en` como en `es` sin borrar claves existentes).
4. **Compuerta de Verificación:**
   - Ejecutar `pytest` en cada worktree y verificar que el 100% de la suite pase en verde antes de finalizar.

---

## 7. Estado de Implementación y Unificación Multitema en `main`

La exploración del rediseño de interfaz en múltiples worktrees fue completada y **unificada en la rama `main`** bajo una arquitectura multitema en tiempo de ejecución:

1. **Arquitectura Unificada de Tokens Multitema (`ui/themes.css` + `ui/styles.css`):**
   - Consolida la disposición de controlador compacto de una sola columna, el cajón lateral deslizable de focos (`aside#fixture-drawer`), la pestaña de Blanco/Kelvin como vista activa por defecto (`#tab-btn-temperature` / `#panel-temperature`) y el cumplimiento estricto de Content Security Policy (CSP) sin atributos `style=""` en línea.
   - Implementa un sistema de tokens de diseño CSS de 3 niveles en `ui/themes.css` con conmutación instantánea en tiempo de ejecución entre **Architectural Stone** (`architectural-stone`, tema claro predeterminado) y **Atmospheric Dark** (`atmospheric-dark`, tema oscuro seleccionable).
   - La selección de tema se valida en la capa de dominio (`SUPPORTED_THEMES`, `DEFAULT_THEME = "architectural-stone"`), se persiste en `settings.json` (`SettingsRepository.get_theme` / `set_theme`), se expone en la barra superior (`#theme-btn-stone` / `#theme-btn-dark`) y se sincroniza con la barra de título de Windows DWM (`DwmSetWindowAttribute` 20) y el color de fondo de WebView2 (`THEME_WINDOW_CHROME`).
2. **Geometría de Ventana y Autoajuste Dinámico de Altura:**
   - Dimensiones configuradas en `WINDOW_DEFAULT_SIZE = (620, 760)` y `WINDOW_MIN_SIZE = (480, 640)`, calibradas para operar con cero desplazamiento vertical (*zero vertical scroll*) en las 6 pestañas de modo.
   - Incluye ajuste dinámico de altura guiado por contenido (`fit_window_height` en `WebviewBridge` y `_fit_native_window_height` en `main.py`), tomando la pestaña Blanco (Kelvin) con las secciones colapsables cerradas como altura base de referencia.
3. **Punto de Entrada del Paquete, Diagnóstico Multi-Instancia y Suite de Pruebas Automatizadas:**
   - Se incorporó el punto de entrada de paquete `src/gestor_luces/__main__.py` (`python -m gestor_luces`) además de `python -m gestor_luces.main`.
   - Se añadió el parámetro de línea de comandos `--multi-instance` para omitir el cerrojo de instancia única durante comparaciones de diagnóstico lado a lado.
   - Verificado mediante **99 pruebas automatizadas** que cubren invariantes de dominio, persistencia, contratos de tema/idioma en el puente de UI, geometría de ventana, autoajuste dinámico de altura y endurecimiento de seguridad.

