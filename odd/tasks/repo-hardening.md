# repo-hardening — Endurecimiento del repo según PLAN.md

Ejecuta el plan de endurecimiento `PLAN.md` (fases 0–6, más las enmiendas de su sección 11)
en la rama `feature/repo-hardening` (worktree `.worktrees/repo-hardening`, creado desde
`main` en `075825b`). El merge a `main` está gateado por la verificación al 100 % del
usuario.

## Specs

- S1: «Analiza el plan de implementacion creado ayer, verifica si falta algo, luego crea una rama/worktree nuevo para aplicar los cambios propuestos en el plan, cuando verifiquemos que funciona al 100% mergeamos a main completo» (usuario, textual).
- S2: Decisiones del usuario (2026-11-08): D1 = A (`ui/scenes.json` generado por `scripts/export_scenes.py` + test de sync), D2 = A (mover `docs/ui_redesign_spec{,.es}.md` a `docs/design/` y des-ignorarlas), D3 = A (reescribir `cli.py` sobre `LightControlService`), D4 = A (`http_server=True` + ESM, con verificación previa T-2.0; cae a B si el spike falla).
- S3: `PLAN.md` es la especificación ejecutable: cada tarea T-x.y con su criterio de Aceptación, más las enmiendas de la sección 11 (G1–G9 y tareas nuevas T-1.8, T-2.0, T-3.5, T-4.4). Ante conflicto, manda §11.
- S4: «cuando verifiquemos que funciona al 100% mergeamos a main completo»: el merge a `main` y cualquier push/publicación requieren verificación y decisión explícita del usuario; no se ejecutan por continuidad.

## Tasks

| ID | Spec | Route | Commit |
| --- | --- | --- | --- |
| T-0.1 CI mínimo | S3 | inline | `4355052` |
| T-0.2 Ruff + baseline de formato | S3 | inline (backstop) | `8c69a34` + `72054d8` |
| T-0.3 pyproject fuente de deps | S3 | inline | `5774335` |
| T-0.4 requirements-dev limpio | S3 | inline (absorbido por T-0.3) | `5774335` |
| T-0.5 bandit/pip-audit en CI | S3 | inline | `d7842ab` |
| T-1.1 docs ignoradas + `.atl/` | S2, S3 | worker | `4863fe8` |
| T-1.2 un solo número de tests | S3 | worker | `b5e5d3a` |
| T-1.3 símbolos fantasma en docs | S3 | worker | `1b84e86` |
| T-1.4 terminar traducción ES | S3 | worker | `87aaa46` |
| T-1.5 promesa del README | S3 | worker | `a933ffd` |
| T-1.6 índice de docs | S3 | worker | `8a53275` |
| T-1.7 código muerto (`Group`) | S3 | worker | `f8d0501` |
| T-1.8 README sin `requirements.txt` | S3 (§11/G9) | worker | `3dda857` |
| T-2.0 spike D4-A (loopback + ESM) | S2, S3 (§11/G7) | inline (spike) | `fb6ee21` |
| T-2.1 fuente única de escenas | S2, S3 | inline | `bd9ccdc` |
| T-2.2 partir `app.js` | S2, S3 (§11/G1,G5) | worker | `b5e0295` |
| T-2.3 dueño único de i18n | S3 | worker | `8f64d2d` |
| T-2.4 `cli.py` sobre el servicio | S2, S3 | worker | — |
| T-3.1 tests de caracterización | S3 | worker | — |
| T-3.2 capa de plataforma Windows | S3 (§11/G6) | worker | — |
| T-3.3 ciclo de vida testeable | S3 | worker | — |
| T-3.4 `print` → `logging` | S3 | inline | — |
| T-3.5 descomponer `tray_icon.py` | S3 (§11/G2) | worker | — |
| T-4.1 partir `LightControlService` | S3 | worker | — |
| T-4.2 dispatch explícito en bridge | S3 | worker | — |
| T-4.3 bridge contra ports | S3 | inline | — |
| T-4.4 partir `bridge.py`/`wasapi_sampler.py` | S3 (§11/G3) | worker | — |
| T-5.1 triage de `except Exception` | S3 | worker | — |
| T-5.2 modelo de concurrencia | S3 | worker | — |
| T-5.3 `pass` mudos | S3 | inline | — |
| T-6.1 tests `SingleInstanceGuard` | S3 | worker | — |
| T-6.2 tests de JS | S3 | worker | — |
| T-6.3 des-flakear la suite | S3 | worker | — |
| T-6.4 desacoplar tests de internals | S3 | inline | — |
| T-6.5 expandir el dominio | S3 | worker | — |
| T-6.6 cobertura por paquete | S3 | inline | — |
| Verificación final + merge a main | S1, S4 | usuario + inline | — |

## Log

- L1 (2026-11-08, usuario): «Analiza el plan de implementacion creado ayer, verifica si falta algo, luego crea una rama/worktree nuevo para aplicar los cambios propuestos en el plan, cuando verifiquemos que funciona al 100% mergeamos a main completo».
- L2 (2026-11-08): evidencia del plan verificada con `gentle-ai-explore` (tarea `mw6hg6it-1-0kki`): métricas mayormente confirmadas; correcciones (`service.py` 42/48 públicos, 19 closures en `main()` `682-883`, 38 archivos `.py`, 7 deps de runtime, `[project]` parcial existente, dispatch en `bridge.py:732-736`, `FALLBACK_SCENES` `app.js:14-51`, segundo IIFE `app.js:3370`, deps de test en `requirements.txt:19-23`, `.gitignore:36/9-10`, T-2.3: la tabla real es `menu_model.py:78-96`) y huecos G1–G9 aplicados como enmiendas en `PLAN.md` §11 (tareas nuevas T-1.8, T-2.0, T-3.5, T-4.4; DoD #3 y Gate 4 re-escritos).
- L3 (2026-11-08, usuario): decisiones resueltas D1 = A, D2 = A, D3 = A, D4 = A.
- L4 (2026-11-08): rama `feature/repo-hardening` creada desde `main` (`075825b`) con worktree `.worktrees/repo-hardening`; `PLAN.md` (antes untracked) se versiona en la rama con las enmiendas.
- L5 (2026-11-08): T-0.1 implementado inline (`.github/workflows/ci.yml`); su aceptación completa (PR de prueba verde + branch protection) requiere push, que es decisión del usuario (S4).
- L6 (2026-11-08): límite de slice registrado — el commit `4dc0840` (752 líneas) es el documento del plan + enmiendas §11, no código; los slices de ~400 líneas se aplican desde acá hacia adelante a las unidades de implementación (T-0.2 en adelante). Suite verificada verde desde el worktree (100 passed) con `PYTHONPATH=<worktree>/src` y el venv del repo principal.
- L7 (2026-11-08): T-0.3/T-0.4 implementados inline (launcher de writers rechazó el launch sin `Spec:`/`workspace_root`; próximo worker se lanza con ambos). Aceptación verificada: (a) `pip install -e ".[dev]"` en venv nuevo del worktree OK; (b) 100 passed; (c) `gestor-luces --help` exit 0; (d) venv sin extras instala las 7 deps runtime (importables) y `pip show pytest` falla; (e) `pip check` limpio en ambos. VERIFICADO (f): `scripts/build.ps1` completo (instalador + SHA256SUMS) y `dist/GestorDeLuces/GestorDeLuces.exe --smoke-test` exit 0; T-0.3/T-0.4 commiteados en `5774335`. `requirements.txt`/`requirements-dev.txt` eliminados (fuente única: `pyproject.toml`); README EN/ES actualizado en las 4 líneas que instruían instalar por requirements. GOTCHA: el paquete `pywebview==6.2.1` se importa como `webview` (no `pywebview`); verificar imports con el nombre real (`webview, pywizlight, pystray, mss, numpy, PIL, pyaudiowpatch`).
- L8 (2026-11-08): T-0.2 inline (context backstop activo a los 150k tokens). ruff 0.17.4; 68 violaciones → 0 (`ruff check .` y `ruff format --check .` exit 0). Baseline aislado `8c69a34` (33 archivos): safe fixes (orden de imports, 4 imports sin uso) + format + 6 correcciones manuales preservando comportamiento (`contextlib.suppress` ×2 SIM105, `StrEnum` UP042 — serialización por `.value` verificada en `models.py:41`, `zip(strict=True)` B905, re-export `AutostartManager` en `ports/__init__.__all__` F401, splits de líneas E501). pytest 100 passed antes y después. GOTCHA: `ruff format` colapsa a una línea los docstrings multilínea cuyo contenido entra solo; al envolver, dejar margen para `"""` de cierre (wrap con límite 96). `ruff==0.17.4` agregado al extra `dev`; CI corre `ruff check` + `ruff format --check` (`72054d8`). T-5.3 pierde 2 sitios (`json_repositories.py`, `udp_controller.py`) convertidos a `contextlib.suppress`.
- L9 (2026-11-08, usuario): «1 licencia mit 2 hace el push» — licencia MIT y push autorizados. Agregado `LICENSE` + `license = "MIT"` SPDX + `license-files` + `setuptools>=77` en `pyproject.toml` (`2f77f6e`); reinstall editable verificado, 100 passed.
- L10 (2026-11-08): T-0.5 inline (`d7842ab`): bandit + pip-audit en CI como pasos informativos (`continue-on-error`) con reporte JSON de bandit como artifact; README EN/ES dejan de instruir ejecución manual. Local: bandit 0 hallazgos, pip-audit sin vulnerabilidades conocidas.
- L11 (2026-11-08): Fase 0 completa salvo Gate 0 pendiente de verificación en GitHub (ver L12). Documento ODD expuesto en la raíz del proyecto vía junction `odd` → `.worktrees/repo-hardening/odd` para que el launcher de workers encuentre `Spec: odd/tasks/repo-hardening.md, T<n>`.
- L12 (2026-11-08): push autorizado por el usuario; rama renombrada `feature/repo-hardening` → `chore/repo-hardening` (naming del skill branch-pr) y PR draft #1 creado (https://github.com/AlexisAcevedo/Gestor-de-luces/pull/1). Primera corrida de CI: 3.14 ✅, **3.11 ❌** — `numpy==2.5.4` exige `Requires-Python >=3.12`, así que el piso 3.11 era imposible con los pins actuales. Corregido: `requires-python = ">=3.12"`, ruff `target-version = py312`, matriz CI `3.12/3.14`, `PLAN.md` T-0.1 amendado. Gate 0 queda pendiente de la corrida verde del CI en el PR.
- L13 (2026-11-08): CI verde en ambas patas (3.12: 59s, 3.14: 55s, run 42398704688) → **Gate 0 cerrado** salvo branch protection de `main` (cambio de settings del repo, decisión pendiente del usuario). Fase 1 completa vía worker `gentle-ai-worker` (tarea `mw6pftn4-2-gbxg`), commits `4863fe8`..`3dda857`, un commit por tarea; spot-check del parent: suite 100 passed, árbol limpio. Notas del worker: T-1.3 guardrail warning-only (`scripts/check_doc_symbols.py` reporta 9 tokens no-src, todos conceptos externos); T-1.7: `tests/test_domain.py` SÍ referenciaba `Group` (import + 2 asserts) — removidos dentro de la superficie permitida, conteo se mantiene en 100; T-1.6: índice lista los 6 docs (4 top-level + `docs/design/`).
- L14 (2026-11-08, usuario): «al terminar esta fase pongamos en pausa el proyecto que me quedo sin tokens» — **PROYECTO EN PAUSA** tras el cierre de Fase 1. Retomar por: Fase 2, empezando por T-2.0 (spike D4-A: `http_server=True` + ESM, ver `PLAN.md` §11/G7), luego T-2.1 (scenes.json), T-2.2 (partir app.js), T-2.3, T-2.4. Estado del repo: rama `chore/repo-hardening` pusheada (CI verde), PR draft #1 abierto, worktree `.worktrees/repo-hardening` con venv dev funcional, junction `odd/` en la raíz del proyecto. Resto pendiente: branch protection (usuario), Fases 2–6, verificación final + merge gateado (S4).
- L15 (2026-11-08): **T-2.0 (spike D4-A) — veredicto A** (verificado inline, sin GUI, con evidencia). (1) El servidor HTTP de pywebview enlaza **solo `127.0.0.1`** (observado `http://127.0.0.1:42001/`, puerto fijo `DEFAULT_HTTP_PORT=42001` porque `private_mode=False`). (2) El bridge sigue siendo IPC directo (`window.pywebview.api` host object nativo de WebView2); el endpoint HTTP `/js_api/<uuid>` solo transporta callbacks de promesas, gateado por `uuid` aleatorio. (3) Servido estático con MIME correcto (`index.html`→`text/html`, `app.js`/`i18n.js`→`text/javascript` compatible con ESM, CSS→`text/css`); traversal `../../` → `403`. (4) **Arranque en dev verificado**: `python -m gestor_luces --minimized --multi-instance` sirvió `index.html` HTTP 200 en `127.0.0.1:42001`, log sin errores. (5) `resolve_ui_directory()` sin cambios: `ui/` desde fuente y `_MEIPASS/ui` congelado, ambas rutas planas → misma raíz de servidor. GOTCHAS para T-2.2: la URL debe ser ruta plana `str(index_path)` (no `.as_uri()`, porque `file://` no se reescribe a HTTP); la CSP `'self'` se adapta al origen http (los `file:` explícitos quedan vestigiales); `localStorage` migra de origen `file://` → `http://127.0.0.1:42001` (persiste por puerto fijo, pero lo previo de `file://` no se transfiere — nota de migración única); puerto fijo puede colisionar bajo `--multi-instance`; la ruta raíz `/` de pywebview es una ruta muerta rota (500, nunca se usa). El patch de 2 líneas (`url=str(index_path)` + `http_server=True`) se probó y **se revirtió**: su aplicación definitiva pertenece a T-2.2 (D4). Verificación del exe congelado diferida a T-2.2 (mecanismo idéntico por ruta; build completo costoso). Docs actualizados en `docs/architecture{,.es}.md` §6. Suite 100 passed + ruff limpio.
- L16 (2026-11-08): **T-2.1 completa** (inline). `scripts/export_scenes.py` genera `ui/scenes.json` (36 escenas) desde `domain.scenes.BUILTIN_SCENES`; `FALLBACK_SCENES` eliminado de `ui/app.js` (grep = 0) y reemplazado por `SCENE_CATALOG` + `loadSceneCatalog()` que hace `fetch("scenes.json")`; CSP `connect-src 'none'`→`'self'`; `--smoke-test` ahora verifica `ui/scenes.json` (enumeración de `main.py` ampliada); test nuevo `tests/test_scene_catalog_sync.py` (RED/GREEN verificado: mutar el JSON falla con "corré `python scripts/export_scenes.py`", regenerar pasa). `test_i18n.py::test_ui_i18n_assets_and_builtin_scene_names_preserved` corregido (G5): los nombres de escena ahora se verifican contra `scenes.json` (ya no `app.js`). NOTA: el `fetch` solo funcionará cuando T-2.2 active `http_server` (sobre `file://` falla silenciosamente y el handshake del backend provee las escenas — flicker transitorio solo en dev entre este commit y T-2.2, irrelevante para el merge gateado). Suite 102 passed + ruff limpio + `node --check ui/app.js` OK.
- L17 (2026-11-11): **T-2.2 completa** (retomado desde PAUSA; commit `b5e0295`). `ui/app.js` (3354 líneas) partido en 10 módulos ES bajo `ui/js/`: `ambilight`, `bridge-client`, `fixtures`, `music`, `scenes`, `shortcuts`, `stage-controls`, `store`, `toasts` + `app.js` (entry que coordina ciclo de vida/ARIA/tema/i18n). `index.html` carga `<script type="module" src="js/app.js">`; `main.py` sirve `js/app.js`; `test_i18n.py` escanea `ui/js/*.js` (glob ordenado). Stub legacy `ui/app.js` conservado (check de existencia de assets). Verificación: 10/10 módulos `node --check` OK; suite 102 passed (2.02s); comparación de símbolos vs `HEAD:ui/app.js` confirma que ninguna función se perdió (nuevas: `createEl`, `createStarIcon`, `createSvgIcon`, `renderAllPanels`, `mutateTargetBulbs`, `updateApertureGlow`, `getBackendApi`, `setEnvelopeHandler`, `invalidateFitBaseline`). Ruff no disponible local (tool global uv de la sesión anterior, no quedó en venv) — lo verifica el CI en el PR. Pendiente para cerrar del todo T-2.2: re-verificar exe congelado con serve-HTTP (build completo, diferido). Resto: T-2.3, T-2.4, Fases 3–6, merge gateado (S4).
- L18 (2026-11-11): **T-2.3 completa** (commit `8f64d2d`). Regla de dueño único de i18n establecida y documentada: el backend es dueño solo de cadenas de bandeja + errores de dominio (`menu_model._TRAY_STRINGS`, snake_case sin namespace: `hide_window`, `turn_off`, `brightness`, …); la UI es dueña de todo el texto de pantalla (`ui/i18n.js` DICTIONARIES, `namespace.camelCase`: `rail.scanBtn`, `stage.turnOff`, `shortcuts.brightness`, …). Las convenciones son deliberadamente incompatibles, por lo que una clave literal jamás colisiona (verificado: `tray_keys & ui_keys == set()`). Guardrail nuevo `tests/test_i18n.py::test_i18n_single_owner_backend_tray_vs_ui_screen` (importa `_TRAY_STRINGS` desde `menu_model`, extrae claves UI con regex `namespace.camelCase`). Documentación agregada en `docs/architecture{,.es}.md` §6 (subsección "Internationalization (i18n) Ownership"). Suite 103 passed (1 test nuevo). Solapamientos conceptuales legítimos detectados y NO tocados (contextos distintos, no "la misma clave"): `turn_off`↔`stage.turnOff`, `turn_on`↔`stage.turnOn`, `brightness`↔`shortcuts.brightness`. Ruff no disponible local (CI lo verifica). Próximo: T-2.4 (`cli.py` sobre el servicio, D3).
