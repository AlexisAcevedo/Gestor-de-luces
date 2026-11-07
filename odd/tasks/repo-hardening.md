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
| T-2.0 spike D4-A (loopback + ESM) | S2, S3 (§11/G7) | worker | — |
| T-2.1 fuente única de escenas | S2, S3 | worker | — |
| T-2.2 partir `app.js` | S2, S3 (§11/G1,G5) | worker | — |
| T-2.3 dueño único de i18n | S3 | worker | — |
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
