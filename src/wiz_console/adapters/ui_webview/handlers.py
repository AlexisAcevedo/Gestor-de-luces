"""Casos de uso de iluminacion que el puente expone a la vista, agrupados por capacidad.

Cada metodo publico de `BridgeHandlers` es una entrada de `JS_API_DISPATCH` (ver
`dispatch`), salvo los de la ventana hospedada, que viven en `dispatch` junto a `JsApi`.
Todos comparten la misma frontera de errores: la operacion se ejecuta dentro del bucle
del puente y solo los errores declarados en `SERVICE_CALL_ERRORS` vuelven a JavaScript
como `{ok: False, error}`; cualquier otro propaga, para que un fallo inesperado no se
disfrace de error de validacion.
"""

from __future__ import annotations

import logging
import math
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _req_int(value: Any, *, field: str) -> int:
    """Validate and convert a required integer argument from JavaScript."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{field} must be a finite integer.")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be an integer.")
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer.") from exc
    raise ValueError(f"{field} must be an integer.")


def _opt_int(value: Any, *, field: str) -> int | None:
    """Validate and convert an optional integer argument from JavaScript."""
    return _req_int(value, field=field) if value is not None else None


def _req_float(value: Any, *, field: str) -> float:
    """Validate and convert a required finite float argument from JavaScript."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number.")
    if isinstance(value, (int, float)):
        try:
            parsed = float(value)
        except OverflowError as exc:
            raise ValueError(f"{field} must be a finite number.") from exc
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be a finite number.")
        try:
            parsed = float(text)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"{field} must be a finite number.") from exc
    else:
        raise ValueError(f"{field} must be a finite number.")
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be a finite number.")
    return parsed


def _req_bool(value: Any, *, field: str) -> bool:
    """Validate a required boolean argument from JavaScript."""
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean.")
    return value


def _req_str(value: Any, *, field: str) -> str:
    """Validate a required string argument from JavaScript."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    return value


def _opt_str(value: Any, *, field: str) -> str:
    """Validate an optional string argument, defaulting `None` to an empty string."""
    return "" if value is None else _req_str(value, field=field)


def _opt_ips(ips: Any) -> list[str] | None:
    """Normaliza la lista opcional de IPs objetivo que envia la vista."""
    if ips is None:
        return None
    if not isinstance(ips, list) or any(not isinstance(ip, str) for ip in ips):
        raise ValueError("ips must be a list of strings.")
    return list(ips)


def _opt_stripped(value: Any, *, field: str) -> str | None:
    """Recorta un argumento de texto opcional, o devuelve `None` si viene vacio."""
    if value is None:
        return None
    return _req_str(value, field=field).strip() or None


class BridgeHandlers:
    """Operaciones de iluminacion invocables desde la vista, agrupadas por capacidad."""

    # --- Inventario y focos ---------------------------------------------------------

    def get_initial_state(self) -> dict[str, Any]:
        """Obtiene el inventario inicial de focos y el catalogo de 36 escenas nativas.

        Si aun no hay focos registrados en memoria o persistencia, lanza una busqueda
        rapida inicial para poblar la consola automaticamente al abrir la ventana.
        """

        async def _init() -> None:
            if not self._service.list_bulbs():
                await self._service.discover_bulbs(wait_time=1.8)
            else:
                await self._service.refresh_states()

        return self._call(_init, timeout=15.0)

    def discover_bulbs(self) -> dict[str, Any]:
        """Escanea la red local en busca de focos Philips WiZ y sincroniza su estado."""
        return self._call(lambda: self._service.discover_bulbs(wait_time=2.0), timeout=15.0)

    def add_manual_bulb(self, ip: str, name: str = "") -> dict[str, Any]:
        """Agrega un foco por direccion IP explicita y verifica su disponibilidad UDP."""
        return self._call(
            lambda: self._service.add_manual_bulb(
                ip=_req_str(ip, field="ip"),
                name=_opt_str(name, field="name"),
            )
        )

    def rename_bulb(self, ip: str, new_name: str) -> dict[str, Any]:
        """Actualiza el nombre descriptivo de un foco registrado."""
        return self._call(
            lambda: self._service.rename_bulb(
                ip=_req_str(ip, field="ip"),
                new_name=_req_str(new_name, field="new_name"),
            )
        )

    def remove_bulb(self, ip: str) -> dict[str, Any]:
        """Remove a registered bulb from the local inventory."""
        return self._call(lambda: self._service.remove_bulb(ip=_req_str(ip, field="ip")))

    def select_targets(self, ips: list[str]) -> dict[str, Any]:
        """Actualiza la seleccion de focos activos para control individual o grupal."""
        return self._call(lambda: self._service.select_targets(_opt_ips(ips) or []))

    def refresh_states(self) -> dict[str, Any]:
        """Consulta el estado real (getPilot) de todos los focos registrados."""

        async def _refresh() -> None:
            all_ips = [b.ip for b in self._service.list_bulbs()]
            if all_ips:
                await self._service.refresh_states(ips=all_ips)

        return self._call(_refresh, timeout=6.0)

    # --- Control luminico -----------------------------------------------------------

    def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Conmuta el encendido/apagado de los focos seleccionados o indicados."""
        return self._call(
            lambda: self._service.set_power(
                is_on=_req_bool(is_on, field="is_on"),
                brightness=_opt_int(brightness, field="brightness"),
                ips=_opt_ips(ips),
            )
        )

    def toggle_power(self) -> dict[str, Any]:
        """Invierte el encendido real de los focos objetivo (uso exclusivo de la bandeja).

        No usa la direccion con la que el menu de la bandeja fue construido: mientras la app
        vive en la bandeja el estado cacheado puede estar desactualizado, y el item
        "Encender/Apagar" ofreceria el sentido contrario. Primero se lee el estado real
        (getPilot) de los focos objetivo y recien despues se aplica el inverso. Un foco que
        no responde no cuenta como encendido: si ninguno consta como encendido se enciende,
        que es la accion que no apaga nada por error.
        """

        async def _toggle() -> None:
            target_ips = self._service.get_target_ips()
            if not target_ips:
                return
            await self._service.refresh_states(ips=target_ips)
            lit = any(
                bulb is not None and bulb.is_online and bulb.state.is_on
                for bulb in (self._service.get_bulb(ip) for ip in target_ips)
            )
            await self._service.set_power(is_on=not lit)

        return self._call(_toggle)

    def set_brightness(self, brightness: int, ips: list[str] | None = None) -> dict[str, Any]:
        """Ajusta el nivel de brillo (10-100%) de los focos objetivo."""
        return self._call(
            lambda: self._service.set_brightness(
                brightness=_req_int(brightness, field="brightness"),
                ips=_opt_ips(ips),
            )
        )

    def set_color(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aplica un color RGB (0-255 por canal) a los focos objetivo."""
        return self._call(
            lambda: self._service.set_color(
                r=_req_int(r, field="r"),
                g=_req_int(g, field="g"),
                b=_req_int(b, field="b"),
                brightness=_opt_int(brightness, field="brightness"),
                ips=_opt_ips(ips),
            )
        )

    def set_temperature(
        self,
        kelvin: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aplica una temperatura de blanco (2200K-6500K) a los focos objetivo."""
        return self._call(
            lambda: self._service.set_temperature(
                kelvin=_req_int(kelvin, field="kelvin"),
                brightness=_opt_int(brightness, field="brightness"),
                ips=_opt_ips(ips),
            )
        )

    def set_builtin_scene(
        self,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Activa una escena nativa de WiZ (ID 1-36) con velocidad y brillo opcionales."""
        return self._call(
            lambda: self._service.set_builtin_scene(
                scene_id=_req_int(scene_id, field="scene_id"),
                speed=_opt_int(speed, field="speed"),
                brightness=_opt_int(brightness, field="brightness"),
                ips=_opt_ips(ips),
            )
        )

    def set_auto_sync(self, enabled: bool) -> dict[str, Any]:
        """Persist periodic auto-sync polling preference."""
        return self._call(lambda: self._service.set_auto_sync(_req_bool(enabled, field="enabled")))

    def set_favorite_builtin_scenes(self, scene_ids: list[int]) -> dict[str, Any]:
        """Persist the ordered list of favorite built-in WiZ scene IDs."""

        def _update() -> None:
            if not isinstance(scene_ids, list):
                raise ValueError("scene_ids must be a list of integers.")
            parsed = [_req_int(item, field="scene_id") for item in scene_ids]
            self._service.set_favorite_builtin_scenes(parsed)

        return self._call(_update)

    def set_global_hotkeys(
        self,
        enabled: bool,
        bindings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Validate and persist opt-in global Windows hotkeys configuration."""

        def _update() -> None:
            checked_enabled = _req_bool(enabled, field="enabled")
            checked_bindings: dict[str, str] | None = None
            if bindings is not None:
                if not isinstance(bindings, dict):
                    raise ValueError("bindings must be a mapping of action names to shortcuts.")
                checked_bindings = {
                    _req_str(k, field="action").strip(): _req_str(v, field="combo").strip()
                    for k, v in bindings.items()
                }
            self._service.set_global_hotkeys(checked_enabled, bindings=checked_bindings)

        return self._call(_update)

    # --- Presets personalizados -----------------------------------------------------

    def save_custom_scene(self, name: str, source_ip: str | None = None) -> dict[str, Any]:
        """Guarda el estado luminico actual como un nuevo preset personalizado en JSON."""
        return self._call(
            lambda: self._service.save_custom_scene_from_current(
                name=_req_str(name, field="name"),
                source_ip=_opt_stripped(source_ip, field="source_ip"),
            )
        )

    def update_custom_scene(
        self,
        scene_id: str,
        name: str,
        capture_current: bool = False,
    ) -> dict[str, Any]:
        """Renombra un preset personalizado y opcionalmente sobreescribe su estado luminico."""

        def _apply() -> Any:
            cleaned_id = _req_str(scene_id, field="scene_id").strip()
            cleaned_name = _req_str(name, field="name").strip()
            if _req_bool(capture_current, field="capture_current"):
                return self._service.save_custom_scene_from_current(
                    name=cleaned_name, scene_id=cleaned_id
                )
            return self._service.rename_custom_scene(scene_id=cleaned_id, new_name=cleaned_name)

        return self._call(_apply)

    def delete_custom_scene(self, scene_id: str) -> dict[str, Any]:
        """Elimina una escena personalizada guardada."""
        return self._call(
            lambda: self._service.delete_custom_scene(
                scene_id=_req_str(scene_id, field="scene_id").strip()
            )
        )

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> dict[str, Any]:
        """Agrega o quita un preset personalizado del submenu de favoritos de la bandeja."""
        return self._call(
            lambda: self._service.set_custom_scene_favorite(
                scene_id=_req_str(scene_id, field="scene_id").strip(),
                is_favorite=_req_bool(is_favorite, field="is_favorite"),
            )
        )

    def apply_custom_scene(self, scene_id: str, ips: list[str] | None = None) -> dict[str, Any]:
        """Aplica una escena personalizada a los focos seleccionados o indicados."""
        return self._call(
            lambda: self._service.apply_custom_scene(
                scene_id=_req_str(scene_id, field="scene_id").strip(),
                ips=_opt_ips(ips),
            )
        )

    # --- Flujos continuos (Ambilight y Musica) --------------------------------------

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
        return self._call(
            lambda: self._service.start_ambilight(
                monitor_index=_req_int(monitor_index, field="monitor_index"),
                color_mode=_req_str(color_mode, field="color_mode"),
                auto_brightness=_req_bool(auto_brightness, field="auto_brightness"),
                brightness=_req_int(brightness, field="brightness"),
                smoothing_alpha=_req_float(smoothing_alpha, field="smoothing_alpha"),
                ips=_opt_ips(ips),
                min_brightness=_req_int(min_brightness, field="min_brightness"),
            )
        )

    def stop_ambilight(self) -> dict[str, Any]:
        """Detiene el flujo continuo de Ambilight en ejecucion."""
        return self._call(lambda: self._service.stop_ambilight())

    def get_ambilight_status(self) -> dict[str, Any]:
        """Obtiene el estado en vivo del muestreo Ambilight para la vista previa."""
        # Sondeo frecuente de previsualizacion: evita reconstruir el menu Win32 cada 400ms.
        return self._poll_section("ambilight", self._service.get_ambilight_status)

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
        return self._call(
            lambda: self._service.start_music_sync(
                palette_mode=_req_str(palette_mode, field="palette_mode"),
                sensitivity=_req_float(sensitivity, field="sensitivity"),
                smoothing_alpha=_req_float(smoothing_alpha, field="smoothing_alpha"),
                audio_brightness=_req_bool(audio_brightness, field="audio_brightness"),
                brightness=_req_int(brightness, field="brightness"),
                device_index=_opt_int(device_index, field="device_index"),
                ips=_opt_ips(ips),
            )
        )

    def stop_music_sync(self) -> dict[str, Any]:
        """Detiene el flujo continuo de sincronizacion musical."""
        return self._call(lambda: self._service.stop_music_sync())

    def get_music_sync_status(self) -> dict[str, Any]:
        """Obtiene la telemetria espectral (Graves, Medios, Agudos y RMS) en tiempo real."""
        # Sondeo de 250ms de barras espectrales: no reconstruye el menu de la bandeja.
        return self._poll_section("music_sync", self._service.get_music_sync_status)

    def _poll_section(self, key: str, reader: Any) -> dict[str, Any]:
        """Read a single live-stream status section on the bridge loop for delta polling."""
        import threading

        async def _read() -> Any:
            return reader()

        try:
            if (
                threading.current_thread() is self._thread
                or self._closed
                or not self._loop.is_running()
            ):
                data = reader()
            else:
                data = self._run_async(_read(), timeout=3.0)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, key: data, "error": None}

    # --- Arranque con el sistema ----------------------------------------------------

    def get_autostart(self) -> dict[str, Any]:
        """Report whether the app is registered to start with the operating system."""
        if self._autostart is None:
            return {"ok": False, "error": "Autostart is not available.", "enabled": False}
        try:
            return {"ok": True, "enabled": bool(self._autostart.is_enabled())}
        except OSError:
            _LOGGER.warning("Unable to read autostart setting.", exc_info=True)
            return {"ok": False, "error": "Unable to read autostart setting.", "enabled": False}

    def set_autostart(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable starting with the operating system (always minimized to the tray)."""
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "enabled must be a boolean.", "enabled": False}
        if self._autostart is None:
            return {"ok": False, "error": "Autostart is not available.", "enabled": False}
        try:
            if enabled:
                self._autostart.enable()
            else:
                self._autostart.disable()
            self._notify_state_changed()
            return {"ok": True, "enabled": bool(self._autostart.is_enabled())}
        except OSError:
            _LOGGER.warning("Unable to update autostart setting.", exc_info=True)
            return {
                "ok": False,
                "error": "Unable to update autostart setting.",
                "enabled": False,
            }
