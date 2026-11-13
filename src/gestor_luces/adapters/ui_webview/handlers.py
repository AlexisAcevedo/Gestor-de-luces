"""Casos de uso de iluminacion que el puente expone a la vista, agrupados por capacidad.

Cada metodo publico de `BridgeHandlers` es una entrada de `JS_API_DISPATCH` (ver
`dispatch`), salvo los de la ventana hospedada, que viven en `dispatch` junto a `JsApi`.
Todos comparten la misma frontera de errores: la operacion se ejecuta dentro del bucle
del puente y solo los errores declarados en `SERVICE_CALL_ERRORS` vuelven a JavaScript
como `{ok: False, error}`; cualquier otro propaga, para que un fallo inesperado no se
disfrace de error de validacion.
"""

from __future__ import annotations

from typing import Any


def _opt_int(value: Any) -> int | None:
    """Convierte un argumento opcional de JavaScript a entero."""
    return int(value) if value is not None else None


def _opt_ips(ips: Any) -> list[str] | None:
    """Normaliza la lista opcional de IPs objetivo que envia la vista."""
    return [str(ip) for ip in ips] if isinstance(ips, list) else None


def _opt_stripped(value: Any) -> str | None:
    """Recorta un argumento de texto opcional, o devuelve `None` si viene vacio."""
    return str(value).strip() if value else None


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
        return self._call(lambda: self._service.add_manual_bulb(ip=str(ip), name=str(name)))

    def rename_bulb(self, ip: str, new_name: str) -> dict[str, Any]:
        """Actualiza el nombre descriptivo de un foco registrado."""
        return self._call(lambda: self._service.rename_bulb(ip=str(ip), new_name=str(new_name)))

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
                is_on=bool(is_on), brightness=_opt_int(brightness), ips=_opt_ips(ips)
            )
        )

    def set_brightness(self, brightness: int, ips: list[str] | None = None) -> dict[str, Any]:
        """Ajusta el nivel de brillo (10-100%) de los focos objetivo."""
        return self._call(
            lambda: self._service.set_brightness(brightness=int(brightness), ips=_opt_ips(ips))
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
                r=int(r), g=int(g), b=int(b), brightness=_opt_int(brightness), ips=_opt_ips(ips)
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
                kelvin=int(kelvin), brightness=_opt_int(brightness), ips=_opt_ips(ips)
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
                scene_id=int(scene_id),
                speed=_opt_int(speed),
                brightness=_opt_int(brightness),
                ips=_opt_ips(ips),
            )
        )

    # --- Presets personalizados -----------------------------------------------------

    def save_custom_scene(self, name: str, source_ip: str | None = None) -> dict[str, Any]:
        """Guarda el estado luminico actual como un nuevo preset personalizado en JSON."""
        return self._call(
            lambda: self._service.save_custom_scene_from_current(
                name=str(name), source_ip=_opt_stripped(source_ip)
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
            cleaned_id = str(scene_id).strip()
            cleaned_name = str(name).strip()
            if capture_current:
                return self._service.save_custom_scene_from_current(
                    name=cleaned_name, scene_id=cleaned_id
                )
            return self._service.rename_custom_scene(scene_id=cleaned_id, new_name=cleaned_name)

        return self._call(_apply)

    def delete_custom_scene(self, scene_id: str) -> dict[str, Any]:
        """Elimina una escena personalizada guardada."""
        return self._call(lambda: self._service.delete_custom_scene(scene_id=str(scene_id).strip()))

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> dict[str, Any]:
        """Agrega o quita un preset personalizado del submenu de favoritos de la bandeja."""
        return self._call(
            lambda: self._service.set_custom_scene_favorite(
                scene_id=str(scene_id).strip(), is_favorite=bool(is_favorite)
            )
        )

    def apply_custom_scene(self, scene_id: str, ips: list[str] | None = None) -> dict[str, Any]:
        """Aplica una escena personalizada a los focos seleccionados o indicados."""
        return self._call(
            lambda: self._service.apply_custom_scene(
                scene_id=str(scene_id).strip(), ips=_opt_ips(ips)
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
                monitor_index=int(monitor_index),
                color_mode=str(color_mode),
                auto_brightness=bool(auto_brightness),
                brightness=int(brightness),
                smoothing_alpha=float(smoothing_alpha),
                ips=_opt_ips(ips),
                min_brightness=int(min_brightness),
            )
        )

    def stop_ambilight(self) -> dict[str, Any]:
        """Detiene el flujo continuo de Ambilight en ejecucion."""
        return self._call(lambda: self._service.stop_ambilight())

    def get_ambilight_status(self) -> dict[str, Any]:
        """Obtiene el estado en vivo del muestreo Ambilight para la vista previa."""
        # Sondeo frecuente de previsualizacion: evita reconstruir el menu Win32 cada 400ms.
        return self._poll()

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
                palette_mode=str(palette_mode),
                sensitivity=float(sensitivity),
                smoothing_alpha=float(smoothing_alpha),
                audio_brightness=bool(audio_brightness),
                brightness=int(brightness),
                device_index=_opt_int(device_index),
                ips=_opt_ips(ips),
            )
        )

    def stop_music_sync(self) -> dict[str, Any]:
        """Detiene el flujo continuo de sincronizacion musical."""
        return self._call(lambda: self._service.stop_music_sync())

    def get_music_sync_status(self) -> dict[str, Any]:
        """Obtiene la telemetria espectral (Graves, Medios, Agudos y RMS) en tiempo real."""
        # Sondeo de 250ms de barras espectrales: no reconstruye el menu de la bandeja.
        return self._poll()

    # --- Arranque con el sistema ----------------------------------------------------

    def get_autostart(self) -> dict[str, Any]:
        """Report whether the app is registered to start with the operating system."""
        if self._autostart is None:
            return {"ok": False, "error": "Autostart is not available.", "enabled": False}
        try:
            return {"ok": True, "enabled": bool(self._autostart.is_enabled())}
        except OSError as exc:
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
        except OSError as exc:
            return {"ok": False, "error": str(exc), "enabled": False}
