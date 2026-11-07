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
| T-0.2 Ruff + baseline de formato | S3 | worker | — |
| T-0.3 pyproject fuente de deps | S3 | inline | `5774335` |
| T-0.4 requirements-dev limpio | S3 | inline (absorbido por T-0.3) | `5774335` |
| T-0.5 bandit/pip-audit en CI | S3 | inline | — |
| T-1.1 docs ignoradas + `.atl/` | S2, S3 | inline | — |
| T-1.2 un solo número de tests | S3 | inline | — |
| T-1.3 símbolos fantasma en docs | S3 | inline | — |
| T-1.4 terminar traducción ES | S3 | inline | — |
| T-1.5 promesa del README | S3 | inline | — |
| T-1.6 índice de docs | S3 | inline | — |
| T-1.7 código muerto (`Group`) | S3 | inline | — |
| T-1.8 README sin `requirements.txt` | S3 (§11/G9) | inline | — |
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
- L7 (2026-11-08): T-0.3/T-0.4 implementados inline (launcher de writers rechazó el launch sin `Spec:`/`workspace_root`; próximo worker se lanza con ambos). Aceptación verificada: (a) `pip install -e ".[dev]"` en venv nuevo del worktree OK; (b) 100 passed; (c) `gestor-luces --help` exit 0; (d) venv sin extras instala las 7 deps runtime (importables) y `pip show pytest` falla; (e) `pip check` limpio en ambos. (f) build congelado + `--smoke-test` corriendo en background. VERIFICADO (f): `scripts/build.ps1` completo (instalador + SHA256SUMS) y `dist/GestorDeLuces/GestorDeLuces.exe --smoke-test` exit 0; T-0.3/T-0.4 commiteados en `5774335`. `requirements.txt`/`requirements-dev.txt` eliminados (fuente única: `pyproject.toml`); README EN/ES actualizado en las 4 líneas que instruían instalar por requirements. PENDIENTE: campo `license` de `[project]` no definido — no existe archivo LICENSE en el repo y elegir una licencia es decisión del usuario. GOTCHA: el paquete `pywebview==6.2.1` se importa como `webview` (no `pywebview`); verificar imports con el nombre real (`webview, pywizlight, pystray, mss, numpy, PIL, pyaudiowpatch`).
