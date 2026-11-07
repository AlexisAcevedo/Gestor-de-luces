# Plan de trabajo — Endurecimiento de `gestor-luces`

> Documento derivado del roast técnico del repo. Objetivo: convertir 19 hallazgos dispersos
> en una secuencia ejecutable, con criterios de aceptación verificables por comando y sin
> romper lo que ya funciona.
>
> Estado del repo al crear este plan: rama `main`, árbol limpio, versión `0.3.1`,
> 74 archivos versionados, 26 commits, autor único.

---

## 1. Cómo usar este documento

- Cada tarea tiene **ID estable** (`T-0.1`, `T-3.2`, …). Usá esos IDs en commits y en el
  seguimiento; el prefijo indica la fase.
- Cada tarea declara **Aceptación**: un comando o verificación concreta. Si no se puede
  verificar, la tarea no está terminada.
- Los **Gates** son puertas duras: no se abre la fase siguiente hasta que el gate de la
  anterior esté cerrado. Existen porque la mayor parte del trabajo pendiente *toca* código
  que hoy nadie vigila; refactorizar sin red de seguridad es empeorar el problema.
- **Esfuerzo**: `S` ≤ 2 h, `M` = 2–6 h, `L` = 1–2 días.
- **Riesgo**: referencia a los ítems de riesgo alto del arnés. `none` = cambio contenido.
  Todo ítem marcado exige verificación independiente antes de cerrar la tarea.
- Las **Decisiones abiertas (D#)** son las únicas cosas que necesitan tu criterio, no mi
  ejecución. Están todas en la sección 4.

Regla de envío: una tarea = un commit revisable (≈400 líneas máx. de cambio real). Si una
tarea no entra en un commit, se parte en subtareas; no se mezcla con otra fase.

---

## 2. Estado de partida (medido, no estimado)

| Métrica | Valor real | Nota |
| --- | --- | --- |
| Líneas Python (`src/`) | 6.801 | 38 archivos `.py` (25 módulos + `__init__`) |
| Líneas frontend (`ui/`) | 8.265 | `app.js` = 3.375 en un IIFE, sin módulos |
| Archivos versionados | 74 | `.venv/`, `build/`, `dist/`, `.atl/` presentes y *untracked* |
| Tests | 78 funciones / 100 nodos por parametrización | `README.md:15` dice 100, `:171` dice 99, `:307` dice "100 passed" |
| `except Exception` en `src/` | **75** | `main.py`: 20 · `bridge.py`: 34 · `wasapi_sampler.py`: 9 · `tray_icon.py`: 6 |
| `def` en `application/service.py` | 60 | 42 públicos de 48 métodos (10 closures anidadas), 841 líneas |
| Closures anidadas en `main()` | 19 | `main.py:682-883` |
| Líneas Win32/ctypes en `main.py` | 436 de 927 + `MessageBoxW` (`:844-847`) | DWM, HWND, `MonitorFromWindow`, `MenuStrip` |
| CI | **no existe** | sin `.github/`, ni GitLab, ni pre-commit |
| Linter / type checker | **no configurado ni instalado** | `.venv/Scripts` solo tiene `bandit`, `pip-audit`, `pytest` |
| `dependencies` en `pyproject.toml` | **ausente** | `[project]` parcial ya existe (`pyproject.toml:5-9`); las deps viven en `requirements.txt` |
| Dependencias de test en runtime | 3 | `pytest`, `pytest-asyncio`, `pyinstaller` en `requirements.txt:19-23` |
| Cobertura de `ui/app.js` | 0 tests | 3.375 líneas |
| Cobertura de `SingleInstanceGuard` | 0 tests | 0 referencias en `tests/` |
| Docs en disco pero *ignored* | 2 | `docs/ui_redesign_spec{,.es}.md` |

---

## 3. Principios de secuenciación

1. **Red de seguridad antes que bisturí.** El código que hay que partir (`main.py`,
   `service.py`, `bridge.py`) es justamente el que está peor cubierto. Primero CI + linter +
   medición; después se mueve una línea.
2. **Lo barato y visible primero.** Docs, README, dependencias, `.gitignore`: alto valor,
   riesgo casi nulo, y deja de contaminar la lectura del repo mientras se trabaja lo caro.
3. **Respetar el hexágono que ya está bien.** `domain/` y `application/` son puros y lo
   prueban en `tests/test_security_hardening.py:130-147`. **No se toca esa frontera.** La
   deuda está en los bordes: `main.py`, `bridge.py`, `cli.py`, `ui/`.
4. **Sin reescrituras.** Nada de "pasemos la UI a React", ni build step, ni cambiar de
   framework de escritorio. Cada tarea debe dejar el producto corriendo igual.
5. **Caracterización antes de extracción.** Cualquier movimiento de código en `main.py`
   exige un test que congele el comportamiento actual primero.
6. **Un cambio, un commit, un motivo.** Los commits del repo ya son buenos; el plan debe
   preservar ese estándar.

---

## 4. Decisiones abiertas

Estas cuatro definen *cómo* se resuelve una tarea, no *si* se hace. Se pueden resolver al
llegar a la fase correspondiente; no bloquean la Fase 0.

### D1 — Fuente única del catálogo de escenas (bloquea `T-2.1`) · **resuelta: A (2026-11-08)**
Hoy las 36 escenas están duplicadas: `domain/scenes.py:45-80` y `ui/app.js:14-51`
(`FALLBACK_SCENES`).

- **Opción A (recomendada):** un script `scripts/export_scenes.py` genera `ui/scenes.json`
  desde `domain/scenes.py`, y un test asserta que el JSON commiteado coincide con el dominio.
  Sin build step, sin red, `FALLBACK_SCENES` desaparece.
- **Opción B:** el bridge expone el catálogo en el handshake de arranque y se borra el
  fallback. Más simple, pero la UI queda sin nada que pintar hasta que el bridge responda
  (parpadeo en el primer paint).
- **Opción C:** se acepta la duplicación y solo se agrega un test de igualdad. Barato, pero
  no resuelve nada.

Recomiendo **A**: es la única que elimina la duplicación sin empeorar el arranque.

### D2 — Qué hacer con `docs/ui_redesign_spec{,.es}.md` (bloquea `T-1.1`) · **resuelta: A (2026-11-08)**
Están en disco, gitignoreados por `.gitignore:36`, y no figuran en el índice de docs.

- **A (recomendada):** moverlos a `docs/design/` y dejar de ignorarlos. Son documentación
  real y describen decisiones de UI que alguien va a necesitar.
- **B:** borrarlos. Si son spec de un rediseño ya implementado en v0.3.0, ya cumplieron.
- **C:** dejarlos ignorados y sacarlos del árbol de trabajo (`docs/` local).

### D3 — `cli.py`: refactorizar o eliminar (bloquea `T-2.4`) · **resuelta: A (2026-11-08)**
`cli.py` (384 líneas) reimplementa UDP con sockets propios (`cli.py:66-98`) e importa
`pywizlight` directo, duplicando `WizUdpController`. Su docstring todavía dice "Fase 1".

- **A (recomendada):** reescribirlo sobre `LightControlService` con el mismo wiring que
  `main.py:543-566`. Mantiene la CLI y mata la duplicación.
- **B:** eliminarlo. Si nadie lo usa, es 384 líneas de mantenimiento gratis de baja.

### D4 — Módulos ES en el frontend (bloquea `T-2.2`) · **resuelta: A (2026-11-08)**
`ui/app.js` no se puede partir en `type="module"` sobre `file://` (Chromium bloquea ESM por
CORS). Requiere una de estas dos:

- **A (recomendada):** `pywebview.start(http_server=True)` para servir la UI por loopback y
  habilitar ESM real. **Requiere verificación previa:** confirmar que el serving local no
  amplía la superficie de ataque (hoy el bridge es IPC directo) y que no rompe
  `resolve_ui_directory()` ni el empaquetado PyInstaller.
- **B:** partir `app.js` en varios archivos unidos por nombres globales (`window.GLState`,
  `window.GLScenes`, …) cargados por `<script src>` en orden. Feo, pero cero cambios de
  plataforma y cero riesgo de empaquetado.

Si la verificación de A falla, el plan cae a B sin cambiar el resto.

---

## 5. Fases y tareas

### Fase 0 — Red de seguridad · *bloqueante de todo lo demás*

**Objetivo:** que cualquier regresión futura duela en un rojo automático, no en la mano del
usuario.

**T-0.1 — CI mínimo (build + tests)**
- Crear `.github/workflows/ci.yml`: `windows-latest`, matriz Python `3.12` y `3.14`
  (amendado §11/L12: `numpy==2.5.4` exige `>=3.12`; el piso 3.11 original era imposible),
  `pip install -e ".[dev]"`, `pytest`.
- Cachear `~/.cache/pip`.
- **Aceptación:** el workflow corre verde en un PR de prueba y el merge queda bloqueado si
  falla (branch protection).
- **Esfuerzo:** S · **Riesgo:** ítem 5 (infraestructura de entrega) · **Depende de:** —

**T-0.2 — Ruff configurado y baseline congelado**
- Agregar `[tool.ruff]` a `pyproject.toml`: `target-version = "py311"`, `line-length = 100`,
  `select = ["E","F","W","I","UP","B","SIM","S"]`, `ignore = ["S101"]` para `tests/`,
  `exclude = [".venv","build","dist"]`.
- Generar el baseline con `ruff check --fix` y `ruff format` en **un commit aislado**
  (solo formato, cero lógica) para que el ruido no se mezcle con las tareas siguientes.
- Sumar `ruff check` y `ruff format --check` al CI.
- **Aceptación:** `ruff check .` y `ruff format --check .` en exit 0, y el CI los corre.
- **Esfuerzo:** M · **Riesgo:** none · **Depende de:** T-0.1

**T-0.3 — `pyproject.toml` como fuente de verdad de dependencias**
- Mover las 7 dependencias de runtime (`requirements.txt:2-16`) a `[project.dependencies]` con
  los pins actuales.
- **Sacar** `pytest`, `pytest-asyncio` y `pyinstaller` de `requirements.txt` (son de dev).
- Agregar `[project.optional-dependencies] dev = [...]`, `license`, `authors`,
  `[project.urls]` y `[project.scripts] gestor-luces = "gestor_luces.main:main"`.
- Reducir `requirements.txt`/`requirements-dev.txt` a comentarios que remitan a
  `pip install -e ".[dev]"` (o eliminarlos, ver `T-0.4`).
- **Aceptación:** `pip install -e ".[dev]"` en un venv limpio instala todo; `pytest` pasa;
  `gestor-luces --help` funciona como entry point; `pip show pytest` en ese venv no existe
  tras `pip install -e .` sin extras. Tras `scripts/build.ps1`, el exe congelado pasa
  `--smoke-test` (G8/§11).
- **Esfuerzo:** M · **Riesgo:** ítem 5 (dependencias) · **Depende de:** T-0.1

**T-0.4 — Limpiar `requirements-dev.txt`**
- Quitar los tres re-pins que ya trae `-r requirements.txt:1`.
- Dejar solo `bandit` y `pip-audit` (o moverlos a `[project.optional-dependencies] dev` si
  T-0.3 absorbió el archivo).
- **Aceptación:** ningún paquete aparece dos veces en la resolución; `pipdeptree` limpio.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-0.3

**T-0.5 — `bandit` y `pip-audit` al CI**
- Agregar los dos al workflow. Primera pasada **no bloqueante** (informativa) mientras se
  triagea el backlog que reporten; bloqueante cuando el reporte quede en cero o con
  excepciones documentadas en un `bandit.yaml`.
- **Aceptación:** el job corre y publica el reporte como artifact; el README deja de
  instruir "corré esto a mano".
- **Esfuerzo:** S · **Riesgo:** ítem 5 · **Depende de:** T-0.1, T-0.2

> **Gate 0** — `main` protegido: CI verde con `ruff` + `pytest` + `bandit` + `pip-audit`, y
> `pip install -e ".[dev]"` reproduce el entorno sin `requirements.txt`.

---

### Fase 1 — Higiene del repositorio y documentación · *riesgo casi nulo*

**Objetivo:** que lo que el repo *dice* sea verdad, y que el árbol de trabajo no mienta.

**T-1.1 — Resolver docs ignoradas y `.atl/`**
- Ejecutar la decisión **D2** sobre `docs/ui_redesign_spec{,.es}.md`.
- Agregar `.atl/` a `.gitignore` (hoy existe vacío y no está ignorado).
- **Aceptación:** `git status --porcelain --ignored` no muestra directorios vacíos sin
  propósito; `docs/` versionado coincide con lo que hay en disco.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** D2

**T-1.2 — Un solo número de tests en el README**
- Reemplazar los tres valores (`README.md:15`, `:171`, `:307`; espejados en `README.es.md`)
  por una afirmación sin número absoluto, o por un badge de CI. Los números en un README
  envejecen mal por definición.
- **Aceptación:** `grep -nE "\b(99|100)\b.*test" README*.md` devuelve vacío.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-0.1 (para el badge)

**T-1.3 — Corregir símbolos fantasma en `docs/architecture.*.md`**
- `JsApiFacade` (`architecture.md:83`, `architecture.es.md:83`) → `JsApi` (`bridge.py:717`).
- `resize_window_to_content` y `BeginInvoke` (`architecture.md:252`) → los símbolos reales
  (`fit_window_height`, `native_form.Invoke`).
- **Aceptación:** todo nombre de símbolo citado en los docs existe: un script de 20 líneas
  que extraiga backticks con pinta de identificador y haga `grep` en `src/` corre en CI como
  *warning*.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** —

**T-1.4 — Terminar la traducción ES**
- `README.es.md:171` "(99 tests)", `:307` "100 passed in ~2.5s", `:116` `| Testing |`.
  Auditar que no queden restos en inglés en prosa.
- **Aceptación:** `grep -nE "\b(Tests?|Testing|passed|Coverage)\b" README.es.md` devuelve
  solo nombres propios de herramientas.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-1.2

**T-1.5 — Ajustar la promesa del README a la realidad**
- `README.md:12` "Complete decoupling" es falso mientras `main.py` importe 12 adapters y
  `bridge.py:19` importe la clase concreta. Reformular a algo verificable: "domain y
  application no dependen de adapters (verificado por test)".
- **Aceptación:** la afirmación tiene un test o un comando que la respalda.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** —

**T-1.6 — Índice de docs completo**
- `README.md:130-140` lista 4 documentos. Listar todos los de `docs/` tras T-1.1.
- **Aceptación:** el set de `ls docs/*.md` es igual al set listado en el README.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-1.1

**T-1.7 — Borrar código muerto chico**
- Eliminar la entidad `Group` (`domain/models.py:117`) y sus exports (`domain/__init__.py:6,30`).
- Alinear el docstring `"Fase 1"` de `cli.py:1` con el estado real (o resolverlo en T-2.4).
- **Aceptación:** `grep -rn "\bGroup\b" src/ ui/ tests/` devuelve vacío; suite verde.
- **Esfuerzo:** S · **Riesgo:** ítem 3 (símbolo exportado del paquete `domain`) · **Depende de:** —

> **Gate 1** — Ningún documento del repo afirma algo que el código contradice. `docs/` y
> `.gitignore` coinciden con lo que hay en disco.

---

### Fase 2 — Fuente única y frontera del frontend

**T-2.1 — Fuente única del catálogo de escenas**
- Ejecutar **D1**.
- Si es A: crear `scripts/export_scenes.py`, generar `ui/scenes.json`, borrar
  `FALLBACK_SCENES` de `ui/app.js:14-51` y leer el JSON al arrancar.
- Test nuevo: `tests/test_scene_catalog_sync.py` que compare `ui/scenes.json` contra
  `domain.scenes` y falle con un mensaje que diga "corré `python scripts/export_scenes.py`".
- **Aceptación:** `grep -c "FALLBACK_SCENES" ui/app.js` = 0; el test falla si se cambia el
  dominio sin regenerar, y pasa tras regenerar. El `--smoke-test` verifica `ui/scenes.json`
  (actualizar la enumeración de `main.py:602-606` y `:632-644`, G1/§11).
- **Esfuerzo:** M · **Riesgo:** ítem 3 (contrato consumido por la UI) · **Depende de:** D1, Gate 0

**T-2.2 — Partir `ui/app.js` en módulos**
- Ejecutar **D4**.
- Partir en unidades por responsabilidad, cada archivo ≤ 400 líneas: `store.js` (estado),
  `bridge-client.js` (llamadas a `JsApi`), `scenes.js`, `ambilight.js`, `music.js`,
  `shortcuts.js`, `toasts.js`, `app.js` (bootstrap). Agrupar los ~20 closures sueltos del
  IIFE en estas unidades sin cambiar comportamiento.
- Sin tests de JS todavía (eso es T-6.2): la red acá es la suite de integración existente
  (`tests/test_ui_bridge.py`, `tests/test_window_fit.py`) y la prueba manual del checklist de
  `T-2.3`.
- Red más ancha de lo que el plan original decía (G5/§11): `tests/test_i18n.py:197-229`
  hardcodea `app.js`/`i18n.js`/`index.html` (`:222` asserta el `<script src>`, `:229` un
  string de `app.js`) y el orden de scripts de `index.html:1154-1155` es load-bearing: esa
  suite también debe terminar verde. `app.js` tiene un segundo IIFE en `:3370`
  (`setupResizeThrottle`).
- **Aceptación:** ningún archivo de `ui/js/` supera 400 líneas; la app arranca, cambia de
  tema, aplica escenas y abre ambilight y music sync igual que antes.
- **Esfuerzo:** L · **Riesgo:** ítem 6 (no hay test que atrape una regresión en el frontend)
  · **Depende de:** D4, T-2.1

**T-2.3 — Dueño único de las traducciones**
- Hoy las traducciones viven en dos lugares: `adapters/tray/menu_model.py:78-96` (tabla
  de cadenas de la bandeja; `service.py:127-149` son solo getters/setters de idioma/tema)
  y `ui/i18n.js` (689 líneas). (Premisa corregida en §11.) Definir quién manda: recomiendo que el backend solo
  resuelva las cadenas de bandeja y errores de dominio, y que la UI sea dueña de todo el
  texto de pantalla. Documentar la regla en `docs/architecture.md`.
- **Aceptación:** no existe la misma clave en los dos lugares; checklist manual de la UI en
  ambos idiomas pasa.
- **Esfuerzo:** M · **Riesgo:** ítem 3 (contrato de claves i18n) · **Depende de:** T-2.2

**T-2.4 — `cli.py` sobre el servicio**
- Ejecutar **D3**.
- Si es A: construir el servicio con el mismo wiring de `main.py:543-566`, borrar los sockets
  propios (`cli.py:32,65`) y dejar `pywizlight` solo para descubrimiento si hace falta.
- **Aceptación:** `cli.py` queda sin sockets propios: ni el descubrimiento UDP (`cli.py:65`)
  ni el probe de IP local (`:32`), y el `import socket` (`:14`) desaparece o se muda a un
  helper compartido; `gestor-luces-cli --list` (o el subcomando equivalente) devuelve lo
  mismo que antes contra `tests/simulators/fake_wiz_bulb.py`. (Scope corregido en §11.)
- **Esfuerzo:** M · **Riesgo:** ítem 3 (CLI consumida por el usuario) · **Depende de:** D3, T-0.3

> **Gate 2** — Existe una sola definición de las escenas y una sola definición de cada
> cadena de UI; `app.js` está partido y la app se comporta igual.

---

### Fase 3 — Descomponer `main.py` · *la tarea de mayor riesgo*

**Objetivo:** `main.py` vuelve a ser un composition root de ~250 líneas y el código Win32
tiene un lugar donde se puede testear.

**T-3.1 — Congelar comportamiento con tests de caracterización**
- Antes de mover una línea: ampliar `tests/test_window_geometry.py` y
  `tests/test_window_fit.py` para cubrir los caminos de `_compute_initial_window_geometry`
  (`main.py:140`), `_compute_fit_height` (`:171`) y `_fit_native_window_height` (`:186`),
  incluidos los bordes: monitor más chico que `WINDOW_MIN_SIZE`, DPI raro, altura 0.
- **Aceptación:** cobertura medida de `main.py:65-500` > 60 %, y mover el código después no
  cambia ningún resultado de test.
- **Esfuerzo:** M · **Riesgo:** ítem 6 · **Depende de:** Gate 0

**T-3.2 — Extraer la capa de plataforma Windows**
- Mover a `adapters/platform/windows/`: `window_chrome.py` (DWM/dark titlebar,
  `main.py:100-137`), `window_geometry.py` (`main.py:140-382`), `foreground.py`
  (`main.py:384-428`), `menu_sync.py` (`main.py:430-500`) y `message.py` (`main.py:844-847`, `MessageBoxW`; G6/§11).
- Cada módulo recibe las funciones `ctypes` como dependencia inyectable (ya existe el patrón
  `_configure_fn_signature`), para poder testear sin una ventana real.
- **Aceptación:** `main.py` no contiene `ctypes` ni `windll`; los tests de T-3.1 pasan contra
  los nuevos módulos sin cambios.
- **Esfuerzo:** L · **Riesgo:** ítem 6 · **Depende de:** T-3.1

**T-3.3 — Convertir las 14 closures de `main()` en un ciclo de vida testeable**
- Extraer a una clase `DesktopApplication` (o `AppLifecycle`) con métodos nombrados:
  `show/hide/toggle_window`, `sync_menu`, `notify_ui`, `quit`, `on_closing/minimized/closed`,
  `set_theme_titlebar`, `toggle_autostart`.
- `main()` queda en: parsear args, construir dependencias, instanciar, `webview.start()`,
  devolver exit code.
- **Aceptación:** `wc -l src/gestor_luces/main.py` ≤ 300; `python -m gestor_luces --smoke-test`
  devuelve 0; bandeja, menú, atajos y autostart se prueban a mano desde el checklist.
- **Esfuerzo:** L · **Riesgo:** ítem 6 · **Depende de:** T-3.2

**T-3.4 — `print` → `logging`**
- Reemplazar los 5 `print` de `main.py:614,654,658,660,905` por `_LOGGER` con el nivel
  correcto. Configurar un handler que escriba a archivo en `resolve_default_data_dir()`.
- **Aceptación:** `grep -rn "print(" src/` vacío (excepto `cli.py` si sigue siendo CLI de
  salida al usuario, documentado).
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-3.3

> **Gate 3** — `main.py` ≤ 300 líneas, cero `ctypes` fuera de `adapters/platform/`, suite
> verde, app funcionando en Windows con bandeja y autostart.

---

### Fase 4 — Descomponer `service.py` y `bridge.py`

**T-4.1 — Partir `LightControlService` por capacidad**
- Dividir las 841 líneas / 48 métodos en servicios de 100–200 líneas:
  `BulbControlService` (encendido, color, temperatura, targeting), `SceneService` (catálogo,
  CRUD, favoritos), `TimerService` (sleep timer), `AmbilightService`, `MusicService`
  (audio + dispositivos), `SettingsService` (tema, idioma, persistencia).
- `LightControlService` sobrevive como **fachada** que delega: así `bridge.py` no cambia en
  esta tarea y se puede partir después.
- **Aceptación:** ningún servicio nuevo supera 250 líneas; `tests/test_persistence_and_scenes.py`,
  `test_ambilight.py`, `test_music_sync.py` y `test_ui_bridge.py` pasan **sin modificarse**
  (esa es la prueba de que el contrato se preservó).
- **Esfuerzo:** L · **Riesgo:** ítem 6 · **Depende de:** Gate 3

**T-4.2 — Dispatch explícito en `bridge.py`**
- Reemplazar la copia reflexiva de atributos (`bridge.py:732-736`) por una tabla de
  despacho explícita `{nombre_js: callable}` construida a mano. Ganancia: el contrato con la
  UI queda legible y auditable, y los 34 `except Exception` dejan de ser la única defensa.
- Mantener el set de 30 métodos expuestos exactamente igual (hay un test que lo mira:
  `tests/test_security_hardening.py:61`).
- **Aceptación:** `grep -c "except Exception" bridge.py` ≤ 10; el test de `JS_API_EXCLUDED`
  pasa adaptado a la tabla; la UI sigue llamando los mismos 30 métodos.
- **Esfuerzo:** M · **Riesgo:** ítem 2 (superficie de IPC del frontend) · **Depende de:** T-4.1

**T-4.3 — `bridge.py` contra ports, no contra clases concretas**
- `bridge.py:19` importa `LightControlService` (concreta). Definir el protocolo en
  `ports/` y tipar contra él.
- **Aceptación:** el AST scan de `tests/test_security_hardening.py:130-147` se extiende a
  `adapters/ui_webview/bridge.py` y pasa.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-4.1

> **Gate 4** — Ningún módulo de `src/` supera 300 líneas (exige T-4.4: `bridge.py` = 758 y
> `wasapi_sampler.py` = 485); la frontera hexagonal está verificada por test también del
> lado del bridge.

---

### Fase 5 — Concurrencia y manejo de errores

**T-5.1 — Inventario y triage de los 75 `except Exception`**
- Clasificar cada uno en tres cajas: **frontera** (se captura para no tumbar la app, pero se
  loguea con `exc_info=True`), **esperado** (reemplazar por la excepción concreta) y
  **bug** (borrar el `except`).
- Regla de destino: un único punto de frontera por proceso (el bucle del bridge, el del
  tray, el del webview) y todo lo demás específico.
- Empezar por `bridge.py` (34) y `main.py` (20), que son el 72 % del total.
- **Aceptación:** `grep -rn "except Exception" src/ | wc -l` ≤ 10 y **cada uno** tiene un
  comentario que justifica por qué es frontera; `grep -rn "except:\|except BaseException"`
  = 0.
- **Esfuerzo:** L · **Riesgo:** ítem 6 (cambiar el manejo de errores puede convertir un
  fallo silencioso en un crash visible — para bien o para mal) · **Depende de:** Gate 4

**T-5.2 — Decidir el modelo de concurrencia**
- Hoy hay tres: 8 `threading.Thread` crudos (`main.py:773,780,895`, `tray_icon.py:79,181,182`,
  `single_instance.py:125`, `bridge.py:55`), un event loop dedicado (`bridge.py:52-60`) y
  `asyncio.run` en `cli.py:379`.
- Documentar en `docs/architecture.md` qué corre dónde y quién es dueño de cada hilo; luego
  colapsar los `Thread(...)` del tray y los del ciclo de vida en **un** ejecutor con nombre.
- **Aceptación:** el documento describe los hilos y su dueño; no queda ningún
  `threading.Thread(` sin nombre ni dueño declarado; cerrar la app no deja hilos vivos
  (verificable con `threading.enumerate()` en un test de cierre).
- **Esfuerzo:** M · **Riesgo:** ítem 4 (concurrencia) · **Depende de:** T-5.1

**T-5.3 — `pass` mudos**
- Los 5 `pass` de `cli.py:166`, `json_repositories.py:73`, `udp_controller.py:76,111,179`:
  cada uno necesita un `_LOGGER.debug` con el contexto, o dejar de existir.
- **Aceptación:** ningún `pass` como único cuerpo de un `except`.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-5.1

> **Gate 5** — ≤ 10 `except Exception`, todos de frontera y logueados; modelo de hilos
> documentado y sin hilos huérfanos al cerrar.

---

### Fase 6 — Cerrar los agujeros de test

**T-6.1 — `SingleInstanceGuard`**
- Tests de `adapters/system/single_instance.py`: segunda instancia detectada, lock liberado al
  salir, lock sobrevive a un proceso matado (comportamiento documentado, no idealizado).
- **Aceptación:** 0 → ≥ 4 tests; `grep -c "SingleInstanceGuard" tests/*.py` > 0.
- **Esfuerzo:** S · **Riesgo:** ítem 4 (concurrencia entre procesos) · **Depende de:** Gate 1

**T-6.2 — Tests de JS**
- Con `T-2.2` hecho, los módulos puros (`store.js`, `scenes.js`, `toasts.js`) son testeables.
  Requiere decidir runner: `node --test` (cero dependencias) o `vitest`.
- **Aceptación:** `npm test` (o el equivalente) corre en CI sobre Windows y cubre el reducer
  de estado y el mapeo escena→comando; umbral mínimo 60 % en esos dos archivos.
- **Esfuerzo:** M · **Riesgo:** ítem 5 (agrega una toolchain nueva) · **Depende de:** T-2.2

**T-6.3 — Des-*flakear* la suite**
- Reemplazar los `time.sleep` / `asyncio.sleep` fijos (`test_music_sync.py:276`,
  `test_persistence_and_scenes.py:209` + 8 sitios) por esperas sobre condición
  (`asyncio.Event`, `threading.Event`, polling con timeout).
- Agregar `pytest-timeout` y `pytest-repeat` (o `-x --count=5`) en un job de CI nocturno.
- **Aceptación:** 5 corridas consecutivas en verde; ningún `sleep(` con constante fija en
  `tests/`.
- **Esfuerzo:** M · **Riesgo:** none · **Depende de:** Gate 0

**T-6.4 — Desacoplar los tests de internals**
- `test_security_hardening.py:149-167` verifica el **nombre** del thread
  (`"GestorLucesAsyncLoop"`) y `:115-127` accede a `controller._stream_sock`. Reescribir
  ambos para observar comportamiento (¿el socket quedó cerrado? ¿el loop está vivo?) en vez
  de strings y atributos privados.
- **Aceptación:** `grep -rn '"[A-Z][a-zA-Z]*Loop"' tests/` vacío; ningún test toca un
  atributo con prefijo `_` de `src/`.
- **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-5.2

**T-6.5 — Expandir el dominio**
- 5 tests para 163 líneas de `domain/` es poco. Cubrir `scenes.py` (36 escenas bien formadas,
  rangos de color/temperatura válidos), `value_objects.py` (límites de brillo, parseo de IP) y
  `models.py`.
- **Aceptación:** `domain/` con ≥ 90 % de cobertura de líneas, sin fakes ni mocks (no los
  necesita).
- **Esfuerzo:** M · **Riesgo:** none · **Depende de:** Gate 0

**T-6.6 — Cobertura medida y por paquete**
- `pytest --cov=gestor_luces --cov-report=term-missing` en CI, con umbrales **por paquete**
  (`domain` 90, `application` 75, `adapters` 55) en lugar de un % global que se puede
  maquillar.
- **Aceptación:** el job falla si un paquete baja del umbral; el número aparece en el README
  vía badge y **no escrito a mano** (cierra T-1.2 del todo).
- **Esfuerzo:** S · **Riesgo:** ítem 5 · **Depende de:** T-0.1

> **Gate 6** — Ningún módulo de `src/` sin tests; suites estables en 5 corridas; cobertura
> vigilada por paquete.

---

## 6. Secuencia sugerida y esfuerzo

| # | Fase | Tareas | Esfuerzo | Riesgo dominante | Puede paralelizarse |
| --- | --- | --- | --- | --- | --- |
| 1 | Red de seguridad | T-0.1 → T-0.5 | 1 día | ítem 5 | T-0.2 ∥ T-0.3 |
| 2 | Higiene y docs | T-1.1 → T-1.7 | medio día | none / ítem 3 | sí, todas independientes |
| 3 | Tests baratos | T-6.1, T-6.3, T-6.4, T-6.5 | 1 día | ítem 4 | sí, tras Gate 1 |
| 4 | Frontend | T-2.1 → T-2.4 | 2–3 días | ítem 6 | T-2.4 ∥ T-2.1 |
| 5 | `main.py` | T-3.1 → T-3.4 | 2–3 días | ítem 6 | no (secuencial) |
| 6 | `service` / `bridge` | T-4.1 → T-4.3 | 2 días | ítems 2/6 | no |
| 7 | Errores y concurrencia | T-5.1 → T-5.3 | 2 días | ítems 4/6 | T-5.3 ∥ T-5.1 |
| 8 | Cobertura y JS | T-6.2, T-6.6 | 1 día | ítem 5 | sí |

**Total aproximado: 12–14 días de trabajo efectivo.** Si tuvieras que hacer solo **una**
cosa: Fase 0 completa. Es la que convierte todo lo demás de "fe" en "verificable".

---

## 7. Trazabilidad: hallazgo del roast → tarea que lo cierra

| Hallazgo | Evidencia | Tarea |
| --- | --- | --- |
| Cero CI | sin `.github/` | T-0.1 |
| Cero linter aunque `.gitignore:10-11` ignore sus cachés | `.venv/Scripts` sin ruff/mypy | T-0.2 |
| `pyproject.toml` sin `dependencies` ni metadata | `pyproject.toml:1-19` | T-0.3 |
| `pytest`/`pyinstaller` en runtime | `requirements.txt:20-25` | T-0.3 |
| `requirements-dev.txt` se duplica a sí mismo | `requirements-dev.txt:1-8` | T-0.4 |
| Seguridad "a mano" | `README.md:311-313` | T-0.5 |
| Docs ignoradas por el propio repo | `.gitignore:37` | T-1.1 |
| Tres números distintos de tests | `README.md:15,171,307` | T-1.2 |
| Símbolos fantasma en docs | `architecture.md:83,252` | T-1.3 |
| ES sin traducir del todo | `README.es.md:116,171,307` | T-1.4 |
| "Complete decoupling" falso | `README.md:12` vs `main.py:19-38` | T-1.5 |
| Índice de docs incompleto | `README.md:130-140` | T-1.6 |
| Entidad `Group` muerta | `domain/models.py:117` | T-1.7 |
| Escenas duplicadas ×2 | `app.js:14-49` vs `scenes.py:45-80` | T-2.1 |
| `app.js` 3.375 líneas, sin módulos | `index.html:1154-1155` | T-2.2 |
| i18n en dos lugares | `service.py:127-149` + `i18n.js` | T-2.3 |
| UDP duplicado en `cli.py` | `cli.py:20-21,66-98` | T-2.4 |
| ~455 líneas Win32 en `main.py` | `main.py:65-500` | T-3.2 |
| 14 closures en `main()` | `main.py:682-851+` | T-3.3 |
| `print()` en librería | `main.py:614,654,658,660,905` | T-3.4 |
| `service.py` 841 líneas / 48 métodos | `service.py:80-840` | T-4.1 |
| Dispatch reflejivo en el bridge | `bridge.py:736-741` | T-4.2 |
| Bridge acoplado a clase concreta | `bridge.py:19` | T-4.3 |
| 75 `except Exception` | conteo verificado | T-5.1 |
| Tres modelos de concurrencia | 8 `Thread(` + loop + `asyncio.run` | T-5.2 |
| 5 `pass` mudos | `cli.py:166`, `json_repositories.py:73`, `udp_controller.py:76,111,179` | T-5.3 |
| `SingleInstanceGuard` sin tests | 0 referencias | T-6.1 |
| `app.js` sin tests | 0 tests JS | T-6.2 |
| Tests por reloj | 10 `sleep` fijos | T-6.3 |
| Tests de strings y atributos privados | `test_security_hardening.py:61,115-127,149-167` | T-6.4 |
| Dominio con 5 tests | `test_domain.py` | T-6.5 |
| Cobertura no medida | — | T-6.6 |

---

## 8. No-objetivos (explícitos)

Para que el alcance no se estire solo:

- **No** se migra la UI a un framework ni se agrega un build step.
- **No** se cambia `pywebview`, `pystray` ni el stack de captura.
- **No** se reescribe la arquitectura hexagonal: `domain/` y `application/` ya cumplen y hay
  un test que lo prueba. Se corrige el borde, no el centro.
- **No** se persigue un % de cobertura global como meta.
- **No** se agrega soporte multiplataforma. La app es Windows-only y el plan asume eso; lo
  único que se pide es que el código de Windows viva en un directorio que se pueda testear.
- **No** se toca el formato de datos en disco (`data/*.json`); si alguna tarea lo necesita,
  se detiene y se abre una decisión.

---

## 9. Definición de terminado (global)

El plan está cerrado cuando todo esto se puede verificar con un comando o un clic:

1. Un PR a `main` no mergea sin CI verde (`ruff`, `pytest`, `coverage`, `bandit`,
   `pip-audit`).
2. `pip install -e ".[dev]"` en un venv limpio reproduce el entorno y la app arranca con
   `gestor-luces`.
3. Ningún archivo de `src/` supera 300 líneas (incluye `bridge.py`/`wasapi_sampler.py`,
   T-4.4); ningún archivo **JS** de `ui/` supera 400 (`styles.css`, `index.html`,
   `themes.css` e `i18n.js` quedan como deuda declarada, §11/G4).
4. `grep -rn "except Exception" src/ | wc -l` ≤ 10, todos de frontera y logueados.
5. `main.py` no contiene `ctypes`, `print`, ni closures de negocio.
6. Un solo origen para el catálogo de escenas y para cada cadena de UI.
7. Todo documento del repo afirma solo lo que el código hace, y el índice de docs está
   completo.
8. `SingleInstanceGuard`, `domain/` y los módulos puros de JS tienen tests propios; la suite
   pasa 5 veces seguidas sin `sleep` fijos.
9. `README`/`README.es` no contienen ningún número escrito a mano sobre tests o cobertura.

---

## 10. Primer movimiento concreto

Nada de este plan necesita una decisión tuya para arrancar por acá:

```
T-0.1  .github/workflows/ci.yml  +  branch protection en main
T-0.2  [tool.ruff] en pyproject.toml  +  commit aislado de formato
```

Con eso el repo deja de ser "confío en que anda" y pasa a ser "el CI dice si anda". Todo lo
demás de este documento se vuelve medible desde ese momento.

---

## 11. Enmiendas tras verificación de evidencia (2026-11-08)

La evidencia del plan se verificó línea por línea contra el repo antes de ejecutarlo. Las
correcciones de cifras ya están aplicadas inline arriba; esta sección registra los huecos
que el plan original no cubría y las tareas nuevas que los cierran. Ante conflicto entre
esta sección y el cuerpo del plan, manda esta sección.

**Correcciones verificadas:** `service.py` tiene 42 métodos públicos de 48 totales (no "48
públicos") y 10 closures anidadas; `main()` contiene **19** closures (`main.py:682-883`);
`src/` son 38 archivos `.py`; son **7** dependencias de runtime; `[project]` ya existe
parcialmente; el dispatch reflexivo está en `bridge.py:732-736`; `FALLBACK_SCENES` ocupa
`app.js:14-51` y hay un segundo IIFE en `app.js:3370` (`setupResizeThrottle`); las deps de
test están en `requirements.txt:19-23`; los ignores citados son `.gitignore:36` (docs) y
`:9-10` (cachés de linter).

**Huecos y su cierre:**

- **G1 — el smoke test hardcodea los assets de UI.** `main.py:602-606` y `:632-644`
  enumeran `index.html, themes.css, styles.css, i18n.js, app.js`; `ui/scenes.json` (T-2.1)
  y `ui/js/*` (T-2.2) nunca se verificarían. El empaquetado sí es genérico
  (`packaging/gestor_luces.spec:17-20` copia `ui/` entero; `installer.iss:41` es
  recursivo). → Cierre: la aceptación de T-2.1/T-2.2 incluye actualizar esa enumeración.
- **G5 — tests existentes hardcodean el layout de `ui/`.** Ver bullet nuevo en T-2.2.
- **G7 — la verificación previa de D4-A no tenía dueño.** → Nueva tarea **T-2.0** (abajo).
- **G2 — `tray_icon.py` (353 líneas, 6 `except Exception` en `:198,209,257,271,293,314`,
  3 threads crudos en `:79,181,182`) no estaba en ninguna fase de descomposición.** →
  Nueva tarea **T-3.5** (abajo).
- **G3 — Gate 4 inalcanzable:** `bridge.py` = 758 líneas y `wasapi_sampler.py` = 485; nada
  los partía. → Nueva tarea **T-4.4** (abajo).
- **G4 — DoD #3 inalcanzable en el frontend:** `styles.css` 2.435, `index.html` 1.158,
  `themes.css` 611, `i18n.js` 689. Partirlos ahora es reescritura de bajo valor. → DoD #3
  re-escrito para medir solo archivos JS; CSS/HTML queda como deuda declarada (coherente
  con "sin reescrituras").
- **G6 — `ctypes` fuera del mapa de T-3.2:** `main.py:844-847` (`MessageBoxW`). → T-3.2
  extrae también `message.py`.
- **G8 — nada re-verifica el artefacto congelado tras T-0.3.** `scripts/build.ps1` no
  corre `--smoke-test`. → Aceptación de T-0.3 ampliada.
- **G9 — el README instruye `pip install -r requirements.txt`** y T-0.3/T-0.4 lo dejan
  mentiroso. → Nueva tarea **T-1.8** (abajo).

**Tareas nuevas:**

**T-1.8 — README: instalación sin `requirements.txt`**
- Actualizar la sección de instalación de `README.md`/`README.es.md` a
  `pip install -e ".[dev]"` para desarrollo (y documentar la instalación desde fuente para
  uso).
- **Aceptación:** `grep -n "requirements.txt" README*.md` devuelve vacío (salvo historial
  de cambios). **Esfuerzo:** S · **Riesgo:** none · **Depende de:** T-0.3.

**T-2.0 — Spike de verificación de D4-A (loopback + ESM)**
- Verificar ANTES de T-2.2: (1) `pywebview.start(http_server=True)` no amplía superficie
  de ataque (solo loopback; el bridge sigue siendo IPC directo); (2)
  `resolve_ui_directory()` (`main.py:521`) sirve la UI igual desde fuente y desde
  `_internal/ui/` congelado; (3) `scripts/build.ps1` + `--smoke-test` siguen verdes con la
  UI servida.
- Si algo falla: se ejecuta D4-B sin cambiar el resto del plan. El veredicto se documenta en
  `docs/architecture.md`.
- **Aceptación:** spike documentado con veredicto A/B y evidencia (comando + salida); si A,
  la app arranca servida por loopback tanto en dev como en el exe congelado.
  **Esfuerzo:** M · **Riesgo:** ítem 5 · **Depende de:** Gate 0.

**T-3.5 — Descomponer `tray_icon.py`**
- 353 líneas con 6 `except Exception` (`:198,209,257,271,293,314`) y 3 threads crudos
  (`:79,181,182`); solo aparecía en los conteos de T-5.1/T-5.2. Mover la construcción del
  menú y el ciclo de vida de la bandeja a unidades testeables, dejando `pystray` solo en el
  borde.
- **Aceptación:** ningún archivo nuevo supera 250 líneas; suite verde; bandeja probada a
  mano (checklist). **Esfuerzo:** M · **Riesgo:** ítem 6 · **Depende de:** T-3.3.

**T-4.4 — Partir `bridge.py` y `wasapi_sampler.py` por debajo de 300**
- `bridge.py` (758 líneas) → paquete `adapters/ui_webview/` con `dispatch` (tabla de
  T-4.2), `handlers` por capacidad y `lifecycle` (event loop propio). `wasapi_sampler.py`
  (485) → sesión/dispositivos/captura.
- **Aceptación:** `wc -l` < 300 por archivo; el set de 30 métodos JS expuestos sigue igual
  (`tests/test_security_hardening.py:61`); `test_ambilight.py` y `test_music_sync.py`
  pasan sin modificarse. **Esfuerzo:** L · **Riesgo:** ítem 2 · **Depende de:** T-4.2, T-4.3.

**Decisiones resueltas (2026-11-08, usuario):** D1 = A · D2 = A · D3 = A · D4 = A.
