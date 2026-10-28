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
from collections.abc import Callable, Coroutine
import logging
import threading
from typing import Any

from gestor_luces.application.service import LightControlService
from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import list_builtin_scenes
from gestor_luces.ports.autostart import AutostartManager

_LOGGER = logging.getLogger(__name__)


class WebviewBridge:
    """Adaptador primario que expone los casos de uso de iluminacion a la UI HTML/JS."""

    def __init__(
        self,
        service: LightControlService,
        default_timeout: float = 12.0,
        on_state_changed: Callable[[], None] | None = None,
        autostart: AutostartManager | None = None,
    ) -> None:
        self._service = service
        # Private on purpose (see `_on_state_changed`): never exposed to JavaScript.
        self._autostart = autostart
        self._default_timeout = default_timeout
        # Atributo privado a proposito: PyWebView expone a JavaScript todo atributo publico
        # del objeto `js_api`, y un callback interno no debe ser invocable desde la vista.
        self._on_state_changed = on_state_changed
        self._shutdown_lock = threading.Lock()
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
        custom_scenes = [scene.to_dict() for scene in self._service.list_custom_scenes()]
        sleep_timer = self._service.get_sleep_timer_status()
        ambilight = self._service.get_ambilight_status()
        monitors = self._service.list_monitors()
        music_sync = self._service.get_music_sync_status()
        audio_devices = self._service.list_audio_devices()
        language = self._service.get_language()
        return {
            "ok": ok,
            "language": language,
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
                pass
            self._closed = True
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread.is_alive():
                self._thread.join(timeout=2.0)

    def get_tray_snapshot(self) -> dict[str, Any]:
        """Devuelve una vista resumida y serializable del estado para la bandeja del sistema.

        Se construye dentro del bucle asincrono porque los diccionarios del servicio se
        mutan en ese hilo; leerlos desde el hilo de la bandeja podria observar estados
        intermedios o fallar por modificacion concurrente durante la iteracion.
        """

        async def _collect() -> dict[str, Any]:
            return self._collect_tray_snapshot()

        return self._run_async(_collect(), timeout=3.0)

    def _collect_tray_snapshot(self) -> dict[str, Any]:
        """Resume el estado de los focos objetivo, los presets y el temporizador."""
        targets: list[Bulb] = [
            bulb
            for ip in self._service.get_target_ips()
            if (bulb := self._service.get_bulb(ip)) is not None
        ]
        lit = [bulb for bulb in targets if bulb.is_online and bulb.state.is_on]
        reference = lit[0] if lit else (targets[0] if targets else None)
        state = reference.state if reference is not None else None
        color = state.color if state is not None else None
        return {
            "is_on": bool(lit),
            "brightness": state.brightness if state is not None else 100,
            "mode": state.mode.value if state is not None else None,
            "color": [color.r, color.g, color.b] if color is not None else None,
            "temperature": state.temperature if state is not None else None,
            "presets": [
                {"id": scene.id, "name": scene.name, "is_favorite": scene.is_favorite}
                for scene in self._service.list_custom_scenes()
            ],
            "sleep_timer_active": bool(self._service.get_sleep_timer_status().get("active")),
            "language": self._service.get_language(),
        }

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
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_language(self, language: str) -> dict[str, Any]:
        """Cambia y persiste el idioma activo (`en` o `es`), refrescando tambien la bandeja."""
        try:
            self._service.set_language(str(language))
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def get_autostart(self) -> dict[str, Any]:
        """Report whether the app is registered to start with the operating system."""
        if self._autostart is None:
            return {"ok": False, "error": "Autostart is not available.", "enabled": False}
        try:
            return {"ok": True, "enabled": bool(self._autostart.is_enabled())}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "enabled": False}

    def set_autostart(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable starting with the operating system (always minimized to the tray)."""
        if self._autostart is None:
            return {"ok": False, "error": "Autostart is not available.", "enabled": False}
        try:
            if bool(enabled):
                self._autostart.enable()
            else:
                self._autostart.disable()
            self._notify_state_changed()
            return {"ok": True, "enabled": bool(self._autostart.is_enabled())}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "enabled": False}

    def discover_bulbs(self) -> dict[str, Any]:
        """Escanea la red local en busca de focos Philips WiZ y sincroniza su estado."""
        try:
            self._run_async(self._service.discover_bulbs(wait_time=2.0), timeout=15.0)
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def add_manual_bulb(self, ip: str, name: str = "") -> dict[str, Any]:
        """Agrega un foco por direccion IP explicita y verifica su disponibilidad UDP."""
        try:
            self._run_async(self._service.add_manual_bulb(ip=str(ip), name=str(name)))
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def rename_bulb(self, ip: str, new_name: str) -> dict[str, Any]:
        """Actualiza el nombre descriptivo de un foco registrado."""
        try:
            self._service.rename_bulb(ip=str(ip), new_name=str(new_name))
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def select_targets(self, ips: list[str]) -> dict[str, Any]:
        """Actualiza la seleccion de focos activos para control individual o grupal."""
        try:
            normalized = [str(ip) for ip in ips] if isinstance(ips, list) else []
            self._service.select_targets(normalized)
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def refresh_states(self) -> dict[str, Any]:
        """Consulta el estado real (getPilot) de todos los focos registrados."""
        try:
            all_ips = [b.ip for b in self._service.list_bulbs()]
            if all_ips:
                self._run_async(self._service.refresh_states(ips=all_ips), timeout=6.0)
            return self._success_response()
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
            return self._success_response()
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
            return self._success_response()
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
            return self._success_response()
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
            return self._success_response()
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
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def save_custom_scene(
        self,
        name: str,
        source_ip: str | None = None,
    ) -> dict[str, Any]:
        """Guarda el estado luminico actual como un nuevo preset personalizado en JSON."""
        try:
            cleaned_ip = str(source_ip).strip() if source_ip else None
            self._service.save_custom_scene_from_current(
                name=str(name),
                source_ip=cleaned_ip,
            )
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def update_custom_scene(
        self,
        scene_id: str,
        name: str,
        capture_current: bool = False,
    ) -> dict[str, Any]:
        """Renombra un preset personalizado y opcionalmente sobreescribe su estado luminico."""
        try:
            cleaned_id = str(scene_id).strip()
            cleaned_name = str(name).strip()
            if capture_current:
                self._service.save_custom_scene_from_current(
                    name=cleaned_name,
                    scene_id=cleaned_id,
                )
            else:
                self._service.rename_custom_scene(
                    scene_id=cleaned_id,
                    new_name=cleaned_name,
                )
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def delete_custom_scene(self, scene_id: str) -> dict[str, Any]:
        """Elimina una escena personalizada guardada."""
        try:
            self._service.delete_custom_scene(scene_id=str(scene_id).strip())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> dict[str, Any]:
        """Agrega o quita un preset personalizado del submenu de favoritos de la bandeja."""
        try:
            self._service.set_custom_scene_favorite(
                scene_id=str(scene_id).strip(),
                is_favorite=bool(is_favorite),
            )
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aplica una escena personalizada a los focos seleccionados o indicados."""
        try:
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            self._run_async(
                self._service.apply_custom_scene(
                    scene_id=str(scene_id).strip(),
                    ips=target_ips,
                )
            )
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def start_sleep_timer(
        self,
        minutes: float,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Inicia el temporizador de apagado con atenuacion progresiva en el bucle asincrono."""
        try:
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None

            async def _start() -> dict[str, Any]:
                return self._service.start_sleep_timer(
                    minutes=float(minutes),
                    ips=target_ips,
                )

            self._run_async(_start())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def cancel_sleep_timer(self) -> dict[str, Any]:
        """Cancela el temporizador de apagado activo."""
        try:
            async def _cancel() -> dict[str, Any]:
                return self._service.cancel_sleep_timer()

            self._run_async(_cancel())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Obtiene el sobre actualizado incluyendo la cuenta regresiva del temporizador."""
        try:
            # Consulta de solo lectura sondeada cada segundo: no notifica a la bandeja.
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def start_ambilight(
        self,
        monitor_index: int = 1,
        color_mode: str = "vibrant",
        auto_brightness: bool = True,
        brightness: int = 85,
        smoothing_alpha: float = 0.38,
        ips: list[str] | None = None,
        min_brightness: int = 10,
    ) -> dict[str, Any]:
        """Inicia la sincronizacion Ambilight de pantalla en el bucle de eventos asincrono."""
        try:
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None

            async def _start() -> dict[str, Any]:
                return self._service.start_ambilight(
                    monitor_index=int(monitor_index),
                    color_mode=str(color_mode),
                    auto_brightness=bool(auto_brightness),
                    brightness=int(brightness),
                    smoothing_alpha=float(smoothing_alpha),
                    ips=target_ips,
                    min_brightness=int(min_brightness),
                )

            self._run_async(_start())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def stop_ambilight(self) -> dict[str, Any]:
        """Detiene el flujo continuo de Ambilight en ejecucion."""
        try:
            async def _stop() -> dict[str, Any]:
                return self._service.stop_ambilight()

            self._run_async(_stop())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def get_ambilight_status(self) -> dict[str, Any]:
        """Obtiene el estado en vivo del muestreo Ambilight para la vista previa."""
        try:
            # Sondeo frecuente de previsualizacion: evita reconstruir el menu Win32 cada 400ms.
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def start_music_sync(
        self,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
        smoothing_alpha: float = 0.50,
        audio_brightness: bool = True,
        brightness: int = 85,
        device_index: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Inicia la sincronizacion musical WASAPI Loopback en el bucle asincrono."""
        try:
            target_ips = [str(ip) for ip in ips] if isinstance(ips, list) else None
            parsed_device = int(device_index) if device_index is not None else None

            async def _start() -> dict[str, Any]:
                return self._service.start_music_sync(
                    palette_mode=str(palette_mode),
                    sensitivity=float(sensitivity),
                    smoothing_alpha=float(smoothing_alpha),
                    audio_brightness=bool(audio_brightness),
                    brightness=int(brightness),
                    device_index=parsed_device,
                    ips=target_ips,
                )

            self._run_async(_start())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def stop_music_sync(self) -> dict[str, Any]:
        """Detiene el flujo continuo de sincronizacion musical."""
        try:
            async def _stop() -> dict[str, Any]:
                return self._service.stop_music_sync()

            self._run_async(_stop())
            return self._success_response()
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))

    def get_music_sync_status(self) -> dict[str, Any]:
        """Obtiene la telemetria espectral (Graves, Medios, Agudos y RMS) en tiempo real."""
        try:
            # Sondeo de 250ms de barras espectrales: no reconstruye el menu de la bandeja.
            return self._build_response(ok=True)
        except Exception as exc:
            return self._build_response(ok=False, error=str(exc))
