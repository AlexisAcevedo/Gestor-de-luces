"""Ciclo de vida asincrono del puente IPC: bucle de eventos dedicado y sobres de respuesta.

PyWebView invoca los metodos expuestos en `js_api` desde hilos de trabajo sincronos,
mientras que el nucleo de comunicacion UDP (`WizUdpController`) y el servicio de control
(`LightControlServicePort`) son completamente asincronos sobre `asyncio`. Para evitar
bloquear la interfaz grafica o crear bucles de eventos efimeros que rompan el transporte
UDP en Windows, el puente mantiene un event loop dedicado en un hilo demonio en segundo
plano y despacha cada operacion mediante `asyncio.run_coroutine_threadsafe`.

Este modulo concentra esa maquinaria: el arranque y el cierre del bucle, el despacho
`_run_async`, la serializacion atomica del estado para JavaScript, el aviso a la bandeja y
las operaciones programadas de apagado.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from gestor_luces.domain.scenes import list_builtin_scenes

_LOGGER = logging.getLogger(__name__)

ASYNC_LOOP_THREAD_NAME = "GestorLucesAsyncLoop"

# Errores que un caso de uso puede lanzar al invocarse desde JavaScript y que la vista ya
# sabe presentar como `{ok: False, error}`. Cualquier otra excepcion propaga: un fallo
# inesperado no debe disfrazarse de error de validacion del puente.
_SERVICE_CALL_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,  # validacion del servicio y conversiones int()/float() de argumentos JS
    KeyError,  # preset o foco inexistente
    TypeError,  # argumentos JS con la forma equivocada
    OSError,  # E/S de persistencia y de red
    RuntimeError,  # bucle asincrono detenido o fallo de plataforma
    TimeoutError,  # el servicio no respondio dentro del timeout del puente
)


async def _await_action(action: Callable[[], Any]) -> None:
    """Resuelve la accion (corrutina o valor sincrono) dentro del bucle del puente."""
    result = action()
    if inspect.isawaitable(result):
        await result


class BridgeLifecycle:
    """Bucle de eventos privado del puente, sobres JSON y aviso de cambios de estado."""

    def _call(
        self,
        action: Callable[[], Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Ejecuta la accion en el bucle del puente y sella el sobre JSON resultante."""
        try:
            self._run_async(_await_action(action), timeout=timeout)
        except _SERVICE_CALL_ERRORS as exc:
            return self._build_response(ok=False, error=str(exc))
        return self._success_response()

    def _poll(self) -> dict[str, Any]:
        """Devuelve el sobre de solo lectura sin notificar a la bandeja."""
        try:
            return self._build_response(ok=True)
        except _SERVICE_CALL_ERRORS as exc:
            return self._build_response(ok=False, error=str(exc))

    def _start_async_loop(self) -> None:
        """Arranca el hilo demonio que ejecuta el bucle de eventos del puente."""
        self._shutdown_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name=ASYNC_LOOP_THREAD_NAME,
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        """Ejecuta de forma continua el bucle de eventos asincrono en su propio hilo."""
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    def _run_async(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        """Ejecuta una corrutina de forma segura desde cualquier hilo sincrono de PyWebView."""
        if self._closed or not self._loop.is_running():
            coro.close()
            raise RuntimeError("Background asyncio event loop is not running.")
        effective_timeout = timeout if timeout is not None else self._default_timeout
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=effective_timeout)

    def _collect_response_snapshot(
        self,
        ok: bool = True,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Lee y serializa de forma atomica el estado del servicio para la vista JS."""
        if self._monitors_cache is None:
            self._monitors_cache = list(self._service.list_monitors())
        if self._audio_devices_cache is None:
            self._audio_devices_cache = list(self._service.list_audio_devices())

        bulbs = [bulb.to_dict() for bulb in self._service.list_bulbs()]
        selected_ips = self._service.get_target_ips()
        scenes = [scene.to_dict() for scene in list_builtin_scenes()]
        custom_scenes = [scene.to_dict() for scene in self._service.list_custom_scenes()]
        sleep_timer = self._service.get_sleep_timer_status()
        ambilight = self._service.get_ambilight_status()
        monitors = list(self._monitors_cache)
        music_sync = self._service.get_music_sync_status()
        audio_devices = list(self._audio_devices_cache)
        language = self._service.get_language()
        theme = self._service.get_theme()
        return {
            "ok": ok,
            "language": language,
            "theme": theme,
            "bulbs": bulbs,
            "selected_ips": selected_ips,
            "scenes": scenes,
            "custom_scenes": custom_scenes,
            "sleep_timer": sleep_timer,
            "ambilight": ambilight,
            "monitors": monitors,
            "music_sync": music_sync,
            "audio_devices": audio_devices,
            "error": error,
        }

    def _build_response(
        self,
        ok: bool = True,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Construye un sobre JSON uniforme sincronizado con el bucle de eventos asincrono."""
        if (
            threading.current_thread() is self._thread
            or self._closed
            or not self._loop.is_running()
        ):
            return self._collect_response_snapshot(ok=ok, error=error)

        async def _snapshot() -> dict[str, Any]:
            return self._collect_response_snapshot(ok=ok, error=error)

        try:
            return self._run_async(_snapshot(), timeout=3.0)
        except Exception:
            # Frontera: si el bucle asincrono falla al serializar el estado, degradamos a
            # la lectura directa en lugar de romper la respuesta que espera JavaScript.
            return self._collect_response_snapshot(ok=ok, error=error)

    def _success_response(self) -> dict[str, Any]:
        """Notifica el cambio de estado a observadores externos y devuelve el sobre exitoso."""
        self._notify_state_changed()
        return self._build_response(ok=True)

    def set_state_change_listener(self, listener: Callable[[], None] | None) -> None:
        """Registra o reemplaza el observador invocado tras cada mutacion desde la UI."""
        self._on_state_changed = listener

    def _notify_state_changed(self) -> None:
        """Avisa a la bandeja del sistema sin permitir que un fallo suyo rompa la respuesta JS."""
        if self._on_state_changed is None:
            return
        try:
            self._on_state_changed()
        except Exception:
            # Frontera: el observador es codigo de la bandeja, no del puente; su fallo
            # no debe impedir que la operacion pedida desde la vista se confirme.
            _LOGGER.exception("State change listener failed.")

    def shutdown(self) -> None:
        """Detiene limpiamente el bucle de eventos en segundo plano al cerrar la aplicacion.

        Es idempotente y segura entre hilos porque puede invocarse a la vez desde el
        evento `closed` de la ventana, la opcion Quit de la bandeja y el final de `main`.
        """
        with self._shutdown_lock:
            if self._closed:
                return
            try:
                if self._loop.is_running():

                    async def _cancel() -> None:
                        self._service.stop_ambilight()
                        self._service.stop_music_sync(close_sampler=True)
                        self._service.cancel_sleep_timer()

                    self._run_async(_cancel(), timeout=1.5)
                else:
                    self._service.close_audio_sampler()
            except Exception:
                # Frontera: `shutdown` corre en el cierre de la app y es idempotente; una
                # excepcion aqui dejaria el bucle o el hilo sin liberar.
                _LOGGER.debug(
                    "Ignoring error while cancelling streams during shutdown.", exc_info=True
                )
            self._closed = True
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread.is_alive():
                self._thread.join(timeout=2.0)

    # --- Temporizador de apagado programado -----------------------------------------

    def start_sleep_timer(self, minutes: float, ips: list[str] | None = None) -> dict[str, Any]:
        """Inicia el temporizador de apagado con atenuacion progresiva en el bucle asincrono."""
        return self._call(
            lambda: self._service.start_sleep_timer(
                minutes=float(minutes),
                ips=[str(ip) for ip in ips] if isinstance(ips, list) else None,
            )
        )

    def cancel_sleep_timer(self) -> dict[str, Any]:
        """Cancela el temporizador de apagado activo."""
        return self._call(lambda: self._service.cancel_sleep_timer())

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Obtiene el sobre actualizado incluyendo la cuenta regresiva del temporizador."""
        # Consulta de solo lectura sondeada cada segundo: no notifica a la bandeja.
        return self._poll()

    # --- Ajustes persistentes del host ----------------------------------------------

    def set_language(self, language: str) -> dict[str, Any]:
        """Cambia y persiste el idioma activo (`en` o `es`), refrescando tambien la bandeja."""
        return self._call(lambda: self._service.set_language(str(language)))

    def set_theme(self, theme: str) -> dict[str, Any]:
        """Cambia y persiste el tema visual activo (`architectural-stone` o `atmospheric-dark`)."""
        if not isinstance(theme, str):
            return self._build_response(ok=False, error="Theme must be a string.")
        return self._call(lambda: self._service.set_theme(theme))
