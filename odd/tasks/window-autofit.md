# window-autofit — La ventana se ajusta de verdad al contenido de cada sección

Feature de UI sobre la rama `chore/repo-hardening` (worktree `.worktrees/repo-hardening`).
Cambia la política de auto-fit de la ventana nativa: hoy nunca baja del tamaño de la
pestaña White y mide con las grillas topeadas, así que Escenas queda chica y Presets no
cambia de tamaño.

## Specs

- S1: «busca la sesion de repo hardening, estabamos con algunos bugs de anoche. Quiero agregar algo del comportamiento de la ventana que no es tan responsive como me gustaria, en la seccion escenas la ventana queda chica y no alcanza a mostrar casi el menu de escenas y hay que agrandar la ventana, cuando vas a presets queda con el tamaño de main y no cambia» (usuario, textual).
- S2: decisiones del usuario (2026-11-12): (a) «Fit real al contenido, sin scroll interno» — la ventana muestra el contenido completo de la sección y no hay scroll interno dentro de las grillas; (b) «Sí, que pueda achicarse» — la ventana puede quedar por debajo del alto de la pestaña White, con piso `WINDOW_MIN_SIZE`; (c) el trabajo va en la rama `chore/repo-hardening`.
- S3: el techo del fit sigue siendo el área de trabajo del monitor (`_fit_native_window_height`), no un tope de CSS; cuando el contenido exceda esa área, scrollea el escenario (`.photometric-stage`), nunca una grilla interna.
- S4: los cambios de sección, de idioma y los renders asíncronos (catálogo de escenas, presets) deben terminar en un pedido de fit; una sección que cambia contenido sin pedir fit es un defecto.

## Tasks

| ID | Spec | Route | Commit |
| --- | --- | --- | --- |
| T1 quitar los topes de `40dvh`/`320px` de `.scenes-grid` y `.custom-scenes-grid` | S1, S2, S3 | inline | `6efe4e4` |
| T2 fit real: medir solo la pestaña activa, eliminar el piso del baseline y el clamp de medición | S2, S3 | inline | `6efe4e4` |
| T3 refit después de renders asíncronos y cambio de idioma | S4 | inline | `6efe4e4` |
| T4 tests: guardrail de CSS y del contrato del fit | S1, S3 | inline | `6efe4e4` |
| T5 checklist manual en Windows real (escenas crece, presets achica, sin scroll interno) | S1, S2 | usuario + inline | — |

## Log

- L1 (2026-11-12, usuario): «busca la sesion de repo hardening, estabamos con algunos bugs de anoche. Quiero agregar algo del comportamiento de la ventana que no es tan responsive como me gustaria, en la seccion escenas la ventana queda chica y no alcanza a mostrar casi el menu de escenas y hay que agrandar la ventana, cuando vas a presets queda con el tamaño de main y no cambia».
- L2 (2026-11-12): diagnóstico (explorer `gentle-ai-explore`, tarea `mweae4ui-1-hu13`). El fit calcula `max(baseline(White al ancho actual), altura natural de la pestaña activa)` (`ui/js/shortcuts.js:193-218`): de ahí el «queda con el tamaño de main y no cambia» de Presets. Además las dos grillas están topeadas con `max-height: min(40dvh, 320px); overflow-y: auto` (`ui/styles.css:1344-1354`, `:1667-1677`) y durante la medición se fuerzan a `max-height: 48px` (`ui/styles.css:2365-2369`), así que 36 escenas en 3 columnas se miden como ~48-320 px y scrollean adentro: de ahí el «queda chica» de Escenas. El clamp del backend es `[640, alto del área de trabajo]` (`window_geometry.py:213-218`), o sea el límite es de CSS/JS, no del SO.
- L3 (2026-11-12, usuario): decisiones S2 (a) y (b) confirmadas en el cuestionario de esta sesión; se ejecuta después de T-3.6 (bugs de bandeja) por pedido del usuario.
- L4 (2026-11-12): **T1-T4 completas** (inline, commit `6efe4e4`). CSS: `.scenes-grid` y `.custom-scenes-grid` quedan sin `max-height` ni `overflow`, y la regla `.is-measuring` de las grillas conserva solo `flex: 0 0 auto` (sin el tope de 48 px). Eliminado todo el mecanismo de baseline (`measureBaseline`, `fitBaseline`, `invalidateFitBaseline`, CSS `.is-measuring-baseline` y el listener de `resize` que invalidaba la caché): el target del fit es ahora `measureNaturalHeight(stage)`, o sea el contenido real de la sección activa, y la ventana puede achicarse hasta el mínimo configurado (`WINDOW_MIN_SIZE[1]` = 640) o crecer hasta el área de trabajo. `syncLanguageUi` pide `requestFit(true)` cuando cambia el idioma (antes solo invalidaba el baseline). Tests nuevos en `tests/test_window_fit.py`: guardrail de que las grillas no tienen tope ni scroll interno ni clamp de medición, de que el target es `measureNaturalHeight` y de que el cambio de idioma reajusta. RED verificado (los dos tests fallan con el UI previo, `git stash` de `ui/`) → GREEN. Suite 129 passed, `node --check` OK en `shortcuts.js`/`app.js`, `ruff check`/`format --check` limpios. Docs actualizados: `README.md`/`README.es.md` (§interfaz) y `docs/design/ui_redesign_spec{,.es}.md` (§2 geometría). PENDIENTE: T5, checklist manual en Windows real (Escenas debe crecer hasta mostrar todas las tarjetas sin scroll interno; Presets debe achicar la ventana).
