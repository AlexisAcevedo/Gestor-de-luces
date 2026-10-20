"""Puente IPC entre la ventana de PyWebView (JavaScript) y LightControlService.

PyWebView invoca los metodos expuestos en `js_api` desde hilos de trabajo sincronos,
mientras que el nucleo de comunicacion UDP (`WizUdpController` y `LightControlService`)
es completamente asincrono sobre `asyncio`. Para evitar bloquear la interfaz grafica
o crear bucles de eventos efimeros que rompan el transporte UDP en Windows, este
adaptador mantiene un event loop dedicado en un hilo demonio en segundo plano y
despacha cada operacion mediante `asyncio.run_coroutine_threadsafe`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import threading
from typing import Any

from gestor_luces.application.service import LightControlService
from gestor_luces.domain.scenes import list_builtin_scenes


class WebviewBridge:
    """Adaptador primario que expone los casos de uso de iluminacion a la UI HTML/JS."""

    def __init__(
        self,
        service: LightControlService,
        default_timeout: float = 12.0,
    ) -> None:
        self._service = service
        self._default_timeout = default_timeout
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name="GestorLucesAsyncLoop",
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

    def _build_response(
        self,
        ok: bool = True,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Construye un sobre JSON uniforme para sincronizar el estado de la vista JS."""
        bulbs = [bulb.to_dict() for bulb in self._service.list_bulbs()]
        selected_ips = self._service.get_target_ips()
        scenes = [scene.to_dict() for scene in list_builtin_scenes()]
        return {
            "ok": ok,
            "bulbs": bulbs,
            "selected_ips": selected_ips,
            "scenes": scenes,
            "error": error,
        }

    def shutdown(self) -> None:
        """Detiene limpiamente el bucle de eventos en segundo plano al cerrar la aplicacion."""
        if self._closed:
            return
        self._closed = True
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def get_initial_state(self) -> dict[str, Any]:
        """Obtiene el inventario inicial de focos y el catalogo de 36 escenas nativas.

        Si aun no hay focos registrados en memoria o persistencia, lanza una busqueda
        rapida inicial para poblar la consola automaticamente al abrir la ventana.
        """
        try:
            if not self._service.list_bulbs():
                self._run_async(self._service.discover_bulbs(wait_time=1.8), timeout=15.0)
            else:
                self._run_async(self._service.refresh_states(), timeout=6.0)
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def discover_bulbs(self) -> dict[str, Any]:
        """Escanea la red local en busca de focos Philips WiZ y sincroniza su estado."""
        try:
            self._run_async(self._service.discover_bulbs(wait_time=2.0), timeout=15.0)
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def add_manual_bulb(self, ip: str, name: str = "") -> dict[str, Any]:
        """Agrega un foco por direccion IP explicita y verifica su disponibilidad UDP."""
        try:
            self._run_async(self._service.add_manual_bulb(ip=str(ip), name=str(name)))
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def rename_bulb(self, ip: str, new_name: str) -> dict[str, Any]:
        """Actualiza el nombre descriptivo de un foco registrado."""
        try:
            self._service.rename_bulb(ip=str(ip), new_name=str(new_name))
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def select_targets(self, ips: list[str]) -> dict[str, Any]:
        """Actualiza la seleccion de focos activos para control individual o grupal."""
        try:
            normalized = [str(ip) for ip in ips] if isinstance(ips, list) else []
            self._service.select_targets(normalized)
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def refresh_states(self) -> dict[str, Any]:
        """Consulta el estado real (getPilot) de todos los focos registrados."""
        try:
            all_ips = [b.ip for b in self._service.list_bulbs()]
            if all_ips:
                self._run_async(self._service.refresh_states(ips=all_ips), timeout=6.0)
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Conmuta el encendido/apagado de los focos seleccionados o indicados."""
        try:
            parsed_brightness = int(brightness) if brightness is not None else None
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.set_power(
                    is_on=bool(is_on),
                    brightness=parsed_brightness,
                    ips=target_ips,
                )
            )
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_brightness(
        self,
        brightness: int,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ajusta el nivel de brillo (10-100%) de los focos objetivo."""
        try:
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.set_brightness(
                    brightness=int(brightness),
                    ips=target_ips,
                )
            )
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_color(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aplica un color RGB (0-255 por canal) a los focos objetivo."""
        try:
            parsed_brightness = int(brightness) if brightness is not None else None
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.set_color(
                    r=int(r),
                    g=int(g),
                    b=int(b),
                    brightness=parsed_brightness,
                    ips=target_ips,
                )
            )
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_temperature(
        self,
        kelvin: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aplica una temperatura de blanco (2200K-6500K) a los focos objetivo."""
        try:
            parsed_brightness = int(brightness) if brightness is not None else None
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.set_temperature(
                    kelvin=int(kelvin),
                    brightness=parsed_brightness,
                    ips=target_ips,
                )
            )
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_builtin_scene(
        self,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Activa una escena nativa de WiZ (ID 1-36) con velocidad y brillo opcionales."""
        try:
            parsed_speed = int(speed) if speed is not None else None
            parsed_brightness = int(brightness) if brightness is not None else None
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.set_builtin_scene(
                    scene_id=int(scene_id),
                    speed=parsed_speed,
                    brightness=parsed_brightness,
                    ips=target_ips,
                )
            )
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))
