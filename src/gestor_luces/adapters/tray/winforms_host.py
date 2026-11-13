"""Host de `System.Windows.Forms`: apartamento STA, ventana oculta y ciclo de mensajes.

La vista de bandeja necesita un hilo propio inicializado como STA y un bombeo de mensajes
para que `NotifyIcon` y `ContextMenuStrip` existan: `run` bloquea ese hilo dentro de
`Application.Run(form)`. Este modulo concentra todo ese ciclo de vida —resolucion perezosa
de pythonnet, inicializacion COM, la ventana invisible 0x0 que sirve de ancla, el arranque
del bucle y el marshalling con `Control.Invoke`— de modo que `winforms_tray` solo compone
piezas y `winforms_icon`/`winforms_menu`/`winforms_paint` no tocan hilos.

`pythonnet` se importa dentro de `_load_winforms()` (nunca al importar el modulo) para que
el paquete se pueda usar en Linux/CI sin CLR y para que la vista degradada a `pystray` sea
siempre posible.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import NATIVE_CALL_ERRORS
from gestor_luces.adapters.tray.tray_view import ICON_NAME, Dispatch, TrayView

_LOGGER = logging.getLogger(__name__)

_COINIT_APARTMENTTHREADED = 0x2

#: Fallos de *binding* de pythonnet, antes de llegar al CLR: el miembro no existe
#: (`AttributeError`), la firma o el overload no aceptan los argumentos (`TypeError`) o un
#: primitivo no se puede convertir al tipo pedido (`ValueError`, `OverflowError`).
_CLR_BINDING_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    TypeError,
    ValueError,
    OverflowError,
)


def clr_errors(api: Any) -> tuple[type[BaseException], ...]:
    """Excepciones reales de una llamada a WinForms a traves de pythonnet.

    Una llamada al CLR solo puede fallar de dos maneras: una excepcion propia de .NET
    —pythonnet la expone como subclase Python de `System.Exception`, la raiz de todas
    ellas— o un fallo de *binding* de pythonnet antes de llegar al CLR (miembro ausente,
    firma que no coincide, conversion de un primitivo). Cualquier otra excepcion es un
    defecto del programa y debe propagarse a quien pueda arreglarlo.

    La raiz del CLR viaja en el `api` resuelto porque `System` solo se importa dentro de
    `_load_winforms`; con un doble de prueba sin `system_exception` quedan los fallos de
    binding, que son los unicos que un doble puede producir.
    """
    root = getattr(api, "system_exception", None)
    if isinstance(root, type):
        return (root, *_CLR_BINDING_ERRORS)
    return _CLR_BINDING_ERRORS


def release_native(teardown: Callable[[], None], api: Any, *, what: str) -> None:
    """Libera un recurso nativo de la bandeja (ventana, menu, icono o `HICON`).

    Es el unico guardia de la liberacion de recursos nativos de la vista: un recurso que no
    se puede liberar durante el cierre no puede tumbar el hilo de la vista ni el de refresco
    (el icono desaparece pero la app sigue viva), y la traza deja en el log el recurso que
    se filtro. La liberacion de objetos nativos solo falla con `clr_errors`.
    """
    try:
        teardown()
    except clr_errors(api):
        _LOGGER.debug("%s failed.", what, exc_info=True)


class _WinFormsApi:
    """Modulos de .NET resueltos una sola vez (import perezoso y guardado)."""

    def __init__(
        self,
        forms: Any,
        drawing: Any,
        action: Any,
        memory_stream: Any,
        system_exception: Any,
    ) -> None:
        self.forms = forms
        self.drawing = drawing
        self.action = action
        self.memory_stream = memory_stream
        #: `System.Exception` de pythonnet: raiz de toda excepcion del CLR (ver `clr_errors`).
        self.system_exception = system_exception


_API: _WinFormsApi | None = None
_API_RESOLVED = False


def _load_winforms() -> _WinFormsApi | None:
    """Resuelve pythonnet y WinForms una sola vez; devuelve None si no estan disponibles.

    Es el unico punto de import de .NET en el paquete de la vista, y nunca lanza: cualquier
    fallo se traduce en `None` para que la bandeja caiga a la vista de `pystray`.
    """
    global _API, _API_RESOLVED
    if _API_RESOLVED:
        return _API
    _API_RESOLVED = True
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Drawing as drawing
        import System.Windows.Forms as forms
        from System import Action
        from System import Exception as SystemException
        from System.IO import MemoryStream
    # FRONTERA (disponibilidad de WinForms): este es el unico import de .NET del paquete y
    # el punto donde la bandeja decide usar `pystray`. `clr.AddReference` y los `import`
    # pueden fallar con cualquier excepcion del CLR o de importacion de Python, y la vista
    # degradada tiene que ser siempre posible, asi que se atrapa todo y se devuelve `None`.
    except Exception:
        _LOGGER.debug("WinForms is unavailable; the tray falls back to pystray.", exc_info=True)
        return None
    _API = _WinFormsApi(
        forms=forms,
        drawing=drawing,
        action=Action,
        memory_stream=MemoryStream,
        system_exception=SystemException,
    )
    return _API


def _co_initialize_apartment() -> None:
    """Inicializa el hilo de la vista como STA, requisito de COM/WinForms."""
    try:
        ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # Una llamada `ctypes` a ole32 solo falla con `NATIVE_CALL_ERRORS`; sin STA el bombeo
    # arranca igual (WinForms lo exige para COM, no para existir).
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("STA initialization failed; continuing.", exc_info=True)


def create_host_form(api: _WinFormsApi) -> Any:
    """Ventana invisible (0x0, sin borde) que solo existe para hospedar el bombeo."""
    form = api.forms.Form()
    form.ShowInTaskbar = False
    form.FormBorderStyle = getattr(api.forms.FormBorderStyle, "None")
    form.Opacity = 0
    form.WindowState = api.forms.FormWindowState.Minimized
    form.Size = api.drawing.Size(0, 0)
    form.Text = ICON_NAME
    return form


def run_message_loop(api: _WinFormsApi, form: Any) -> None:
    """Bloquea el hilo de la vista en el bombeo de mensajes de WinForms."""
    api.forms.Application.Run(form)


def invoke_on_ui_thread(api: _WinFormsApi, form: Any, action: Callable[[], None]) -> None:
    """Ejecuta `action` en el hilo del bucle de mensajes de la vista.

    Un fallo de marshalling o una excepcion del CLR dentro de `action` se registra y se
    descarta, porque la vista se refresca de nuevo en el proximo cambio de estado; un
    defecto de Python fuera de `clr_errors` sube a quien invoco (el guardia de la vista o
    el bucle de la bandeja) en vez de perderse.
    """
    try:
        if form.IsHandleCreated and form.InvokeRequired:
            form.Invoke(api.action(action))
            return
        action()
    # Un update marshalado cruza a .NET (o re-lanza lo que `action` provoco alli): se
    # registra y se descarta, porque la vista se refresca de nuevo en el proximo cambio.
    except clr_errors(api):
        _LOGGER.exception("WinForms tray update failed.")


def dispose_host(api: _WinFormsApi, form: Any) -> None:
    """Descarta la ventana oculta del bombeo (en el hilo de la vista)."""
    if form is None:
        return
    release_native(form.Dispose, api, what="Tray form disposal")


def create_view(
    view_class: Callable[..., TrayView],
    dispatch: Dispatch,
    *,
    loader: Callable[[], _WinFormsApi | None] = _load_winforms,
    destroy_icon: Callable[[int], None] | None = None,
    api: _WinFormsApi | None = None,
    dwmapi: Any = None,
    platform: str | None = None,
) -> TrayView | None:
    """Construye la vista WinForms, o `None` si pythonnet/WinForms no estan disponibles.

    Nunca lanza: la bandeja debe seguir existiendo aunque el CLR no cargue, y con ella el
    respaldo de `pystray`. El `loader` es el de `winforms_tray`, que es el modulo del que
    las pruebas parchean la resolucion de .NET.
    """
    resolved = api or loader()
    if resolved is None:
        return None
    try:
        return view_class(
            dispatch,
            api=resolved,
            destroy_icon=destroy_icon,
            dwmapi=dwmapi,
            platform=platform,
        )
    # FRONTERA (disponibilidad de WinForms): si el CLR cargo pero la vista no se puede
    # construir, la bandeja tiene que existir igual con el respaldo `pystray`; es la misma
    # garantia de `_load_winforms`, aplicada al constructor de la vista.
    except Exception:
        _LOGGER.exception("WinForms tray view could not be created; falling back to pystray.")
        return None
