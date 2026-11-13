"""Puerto entrante para los casos de uso de iluminacion que consume la UI.

El adaptador primario (el puente de PyWebView) declara aqui que necesita de la
aplicacion y nunca importa la clase concreta que lo implementa. La composicion
inyecta la fachada real (`LightControlService`), que satisface este contrato de
forma estructural (`typing.Protocol`): no hay herencia explicita, asi que los
dobles de prueba y cualquier fachada futura cumplen solo por tener los mismos
metodos con la misma firma.

Solo se declaran las operaciones que el puente consume de verdad: las que expone
a JavaScript la tabla `JS_API_DISPATCH` mas las que usa internamente para armar
la instantanea de estado y cerrar los flujos continuos.
"""

from __future__ import annotations

from typing import Any, Protocol

from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import CustomScene


class LightControlServicePort(Protocol):
    """Superficie del servicio de iluminacion que el puente de la UI necesita."""

    # --- Preferencias: idioma y tema ---
    def get_language(self) -> str:
        """Devuelve el codigo de idioma activo (`en` o `es`)."""
        ...

    def set_language(self, language: str) -> str:
        """Valida, actualiza y persiste el idioma activo de la interfaz y la bandeja."""
        ...

    def get_theme(self) -> str:
        """Devuelve el identificador del tema visual activo."""
        ...

    def set_theme(self, theme: str) -> str:
        """Normaliza, actualiza y persiste el tema visual activo de la consola."""
        ...

    # --- Inventario de focos ---
    def list_bulbs(self) -> list[Bulb]:
        """Devuelve la lista de todos los focos registrados actualmente."""
        ...

    def get_bulb(self, ip: str) -> Bulb | None:
        """Obtiene un foco registrado por su direccion IP."""
        ...

    async def discover_bulbs(self, wait_time: float = 2.5) -> list[Bulb]:
        """Ejecuta el descubrimiento en la red local y sincroniza el estado real de cada foco."""
        ...

    async def add_manual_bulb(self, ip: str, name: str | None = None) -> Bulb:
        """Registra un foco manualmente por su IP y verifica su estado en la red."""
        ...

    def rename_bulb(self, ip: str, new_name: str) -> Bulb:
        """Cambia el nombre amigable de un foco registrado y guarda el cambio."""
        ...

    async def refresh_states(self, ips: list[str] | None = None) -> list[Bulb]:
        """Consulta en paralelo el estado real (getPilot) de los focos indicados."""
        ...

    def select_targets(self, ips: list[str]) -> list[str]:
        """Define que subconjunto de focos recibira los comandos."""
        ...

    def get_target_ips(self, explicit_ips: list[str] | None = None) -> list[str]:
        """Resuelve la lista de IPs destino para una operacion de control."""
        ...

    # --- Control de focos ---
    async def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Enciende o apaga uno o varios focos en paralelo."""
        ...

    async def set_brightness(
        self,
        brightness: int,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Ajusta el brillo (10-100%) en todos los focos objetivo."""
        ...

    async def set_color(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica un color RGB validado a uno o multiples focos."""
        ...

    async def set_temperature(
        self,
        kelvin: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica una temperatura de color blanco (2200K-6500K) a los focos objetivo."""
        ...

    async def set_builtin_scene(
        self,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Activa una de las 36 escenas nativas de WiZ en los focos objetivo."""
        ...

    # --- Escenas personalizadas ---
    def list_custom_scenes(self) -> list[CustomScene]:
        """Devuelve la coleccion de escenas personalizadas creadas por el usuario."""
        ...

    def save_custom_scene_from_current(
        self,
        name: str,
        source_ip: str | None = None,
        scene_id: str | None = None,
    ) -> CustomScene:
        """Captura la fotografia luminica actual del foco de referencia y la guarda como preset."""
        ...

    def rename_custom_scene(self, scene_id: str, new_name: str) -> CustomScene:
        """Actualiza el nombre de una escena personalizada existente y la persiste."""
        ...

    def delete_custom_scene(self, scene_id: str) -> None:
        """Elimina una escena personalizada del inventario y actualiza el archivo JSON."""
        ...

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> CustomScene:
        """Marca o desmarca un preset como favorito de la bandeja y persiste el cambio."""
        ...

    async def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica los parametros guardados en una escena personalizada a los focos objetivo."""
        ...

    # --- Temporizador de apagado ---
    def start_sleep_timer(
        self,
        minutes: float,
        ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Programa el apagado automatico con atenuacion progresiva tras `minutes` minutos."""
        ...

    def cancel_sleep_timer(self) -> dict[str, Any]:
        """Cancela el temporizador de apagado activo."""
        ...

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Consulta el estado actual del temporizador de apagado."""
        ...

    # --- Ambilight ---
    def list_monitors(self) -> list[dict[str, Any]]:
        """Devuelve la lista de monitores disponibles para el modo Ambilight."""
        ...

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
        """Inicia la sincronizacion continua del color de la pantalla con los focos objetivo."""
        ...

    def stop_ambilight(self) -> dict[str, Any]:
        """Detiene el flujo continuo de Ambilight."""
        ...

    def get_ambilight_status(self) -> dict[str, Any]:
        """Devuelve el estado actual de la sincronizacion Ambilight."""
        ...

    # --- Sincronizacion musical ---
    def list_audio_devices(self) -> list[dict[str, Any]]:
        """Devuelve la lista de dispositivos WASAPI Loopback disponibles para el modo Musica."""
        ...

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
        """Inicia la sincronizacion acustica WASAPI Loopback hacia los focos objetivo."""
        ...

    def stop_music_sync(self, close_sampler: bool = False) -> dict[str, Any]:
        """Detiene la sincronizacion musical y opcionalmente cierra el flujo WASAPI."""
        ...

    def get_music_sync_status(self) -> dict[str, Any]:
        """Devuelve el estado actual y telemetria espectral de la sincronizacion musical."""
        ...

    def close_audio_sampler(self) -> None:
        """Libera de forma segura los recursos de los muestreadores de audio."""
        ...
