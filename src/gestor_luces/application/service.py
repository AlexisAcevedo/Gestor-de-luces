"""Fachada de casos de uso para la gestion y el control de focos inteligentes.

`LightControlService` conserva el contrato publico historico —el que consume el
puente de la UI— y delega cada capacidad en un servicio especializado:

- `BulbInventoryService`: descubrimiento, alta manual, renombrado y refresco de estado.
- `BulbControlService`: encendido, brillo, color, temperatura y escenas nativas.
- `SceneService`: catalogo de presets, CRUD y favoritos.
- `TimerService`: temporizador de apagado.
- `AmbilightService`: sincronizacion continua con la pantalla.
- `MusicService`: sincronizacion acustica y dispositivos de audio.
- `SettingsService`: idioma y tema.

El estado compartido vive en `ServiceContext`, de modo que el puente de la UI no
necesita conocer la descomposicion y no cambia cuando una capacidad se parte.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gestor_luces.application.ambilight_service import AmbilightService
from gestor_luces.application.ambilight_stream import AmbilightStreamManager
from gestor_luces.application.bulb_control_service import BulbControlService
from gestor_luces.application.bulb_inventory_service import BulbInventoryService
from gestor_luces.application.music_service import MusicService
from gestor_luces.application.music_stream import MusicSyncStreamManager
from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.scene_service import SceneService
from gestor_luces.application.service_context import (
    MAX_DISPLAY_NAME_LEN,
    MAX_EXPLICIT_TARGETS,
    ServiceContext,
    validate_local_endpoint,
)
from gestor_luces.application.settings_service import SettingsService
from gestor_luces.application.sleep_timer import AwaitableStatusDict, SleepTimerManager
from gestor_luces.application.timer_service import TimerService
from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import CustomScene
from gestor_luces.domain.value_objects import Color, LightMode
from gestor_luces.ports.repositories import (
    AudioSampler,
    BulbRepository,
    LightController,
    SceneRepository,
    ScreenSampler,
    SettingsRepository,
)

__all__ = [
    "MAX_DISPLAY_NAME_LEN",
    "MAX_EXPLICIT_TARGETS",
    "LightControlService",
    "validate_local_endpoint",
]


class LightControlService:
    """Fachada de aplicacion que coordina el inventario de focos, escenas y temporizadores."""

    def __init__(
        self,
        controller: LightController,
        bulb_repository: BulbRepository | None = None,
        scene_repository: SceneRepository | None = None,
        rate_limiter: StreamRateLimiter | None = None,
        sleep_timer: SleepTimerManager | None = None,
        screen_sampler: ScreenSampler | None = None,
        ambilight_manager: AmbilightStreamManager | None = None,
        audio_sampler: AudioSampler | None = None,
        music_manager: MusicSyncStreamManager | None = None,
        settings_repository: SettingsRepository | None = None,
        screen_sampler_factory: Callable[[], ScreenSampler] | None = None,
        audio_sampler_factory: Callable[[], AudioSampler] | None = None,
    ) -> None:
        context = ServiceContext(
            controller=controller,
            bulb_repository=bulb_repository,
            scene_repository=scene_repository,
            rate_limiter=rate_limiter,
            sleep_timer=sleep_timer,
            screen_sampler=screen_sampler,
            ambilight_manager=ambilight_manager,
            audio_sampler=audio_sampler,
            music_manager=music_manager,
            settings_repository=settings_repository,
            screen_sampler_factory=screen_sampler_factory,
            audio_sampler_factory=audio_sampler_factory,
        )
        self._ctx = context
        self._settings = SettingsService(context)
        self._inventory = BulbInventoryService(context)
        self._bulb_control = BulbControlService(
            context,
            stop_ambilight=self.stop_ambilight,
            stop_music_sync=self.stop_music_sync,
        )
        self._scenes = SceneService(context, bulb_control=self._bulb_control)
        self._timer = TimerService(context, bulb_control=self._bulb_control)
        self._ambilight = AmbilightService(context, stop_music_sync=self.stop_music_sync)
        self._music = MusicService(context, stop_ambilight=self.stop_ambilight)

    def get_language(self) -> str:
        """Devuelve el codigo de idioma activo (`en` o `es`) de la consola."""
        return self._settings.get_language()

    def set_language(self, language: str) -> str:
        """Valida, actualiza y persiste el idioma activo de la interfaz y la bandeja."""
        return self._settings.set_language(language)

    def get_theme(self) -> str:
        """Devuelve el identificador del tema visual activo (`architectural-stone` o
        `atmospheric-dark`)."""
        return self._settings.get_theme()

    def set_theme(self, theme: str) -> str:
        """Normaliza, actualiza y persiste el tema visual activo de la consola."""
        return self._settings.set_theme(theme)

    def list_bulbs(self) -> list[Bulb]:
        """Devuelve la lista de todos los focos registrados actualmente."""
        return self._inventory.list_bulbs()

    def get_bulb(self, ip: str) -> Bulb | None:
        """Obtiene un foco registrado por su direccion IP."""
        return self._inventory.get_bulb(ip)

    def select_targets(self, ips: list[str]) -> list[str]:
        """Define que subconjunto de focos recibira los comandos cuando no se indiquen IPs
        explicitas."""
        return self._ctx.select_targets(ips)

    def get_target_ips(self, explicit_ips: list[str] | None = None) -> list[str]:
        """Resuelve la lista de IPs destino para una operacion de control."""
        return self._ctx.get_target_ips(explicit_ips)

    async def discover_bulbs(self, wait_time: float = 2.5) -> list[Bulb]:
        """Ejecuta el descubrimiento en la red local y sincroniza el estado real de cada foco."""
        return await self._inventory.discover_bulbs(wait_time=wait_time)

    async def add_manual_bulb(self, ip: str, name: str | None = None) -> Bulb:
        """Registra un foco manualmente por su IP y verifica su estado en la red."""
        return await self._inventory.add_manual_bulb(ip, name=name)

    def rename_bulb(self, ip: str, new_name: str) -> Bulb:
        """Cambia el nombre amigable de un foco registrado y guarda el cambio."""
        return self._inventory.rename_bulb(ip, new_name)

    async def refresh_states(self, ips: list[str] | None = None) -> list[Bulb]:
        """Consulta en paralelo el estado real (getPilot) de los focos indicados."""
        return await self._inventory.refresh_states(ips)

    async def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Enciende o apaga uno o varios focos en paralelo."""
        return await self._bulb_control.set_power(is_on, brightness=brightness, ips=ips)

    async def set_brightness(
        self,
        brightness: int,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Ajusta el brillo (10-100%) en todos los focos objetivo."""
        return await self._bulb_control.set_brightness(brightness, ips=ips)

    async def set_color(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica un color RGB validado a uno o multiples focos."""
        return await self._bulb_control.set_color(r, g, b, brightness=brightness, ips=ips)

    async def set_temperature(
        self,
        kelvin: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica una temperatura de color blanco (2200K-6500K) a los focos objetivo."""
        return await self._bulb_control.set_temperature(kelvin, brightness=brightness, ips=ips)

    async def set_builtin_scene(
        self,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Activa una de las 36 escenas nativas de WiZ en los focos objetivo."""
        return await self._bulb_control.set_builtin_scene(
            scene_id, speed=speed, brightness=brightness, ips=ips
        )

    async def stream_color_frame(
        self,
        color: Color,
        brightness: int = 100,
        ips: list[str] | None = None,
    ) -> bool:
        """Envia un fotograma continuo (Ambilight/Musica) filtrado por el RateLimiter."""
        return await self._ctx.stream_color_frame(color, brightness=brightness, ips=ips)

    def list_custom_scenes(self) -> list[CustomScene]:
        """Devuelve la coleccion de escenas personalizadas creadas por el usuario."""
        return self._scenes.list_custom_scenes()

    def get_custom_scene(self, scene_id: str) -> CustomScene | None:
        """Busca una escena personalizada por su identificador unico."""
        return self._scenes.get_custom_scene(scene_id)

    def save_custom_scene_from_current(
        self,
        name: str,
        source_ip: str | None = None,
        scene_id: str | None = None,
    ) -> CustomScene:
        """Captura la fotografia luminica actual del foco de referencia y la guarda como preset."""
        return self._scenes.save_custom_scene_from_current(
            name, source_ip=source_ip, scene_id=scene_id
        )

    def create_or_update_custom_scene(
        self,
        name: str,
        mode: LightMode | str,
        brightness: int = 100,
        color: Color | None = None,
        temperature: int | None = None,
        built_in_scene_id: int | None = None,
        speed: int = 100,
        scene_id: str | None = None,
    ) -> CustomScene:
        """Crea un nuevo preset personalizado o actualiza uno existente validando el dominio."""
        return self._scenes.create_or_update_custom_scene(
            name=name,
            mode=mode,
            brightness=brightness,
            color=color,
            temperature=temperature,
            built_in_scene_id=built_in_scene_id,
            speed=speed,
            scene_id=scene_id,
        )

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> CustomScene:
        """Marca o desmarca un preset como favorito de la bandeja y persiste el cambio."""
        return self._scenes.set_custom_scene_favorite(scene_id, is_favorite)

    def list_favorite_scenes(self) -> list[CustomScene]:
        """Devuelve los presets marcados como favoritos respetando el orden de creacion."""
        return self._scenes.list_favorite_scenes()

    def rename_custom_scene(self, scene_id: str, new_name: str) -> CustomScene:
        """Actualiza el nombre de una escena personalizada existente y la persiste."""
        return self._scenes.rename_custom_scene(scene_id, new_name)

    def delete_custom_scene(self, scene_id: str) -> None:
        """Elimina una escena personalizada del inventario y actualiza el archivo JSON."""
        self._scenes.delete_custom_scene(scene_id)

    async def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica los parametros guardados en una escena personalizada a los focos objetivo."""
        return await self._scenes.apply_custom_scene(scene_id, ips=ips)

    def start_sleep_timer(
        self,
        minutes: float,
        ips: list[str] | None = None,
    ) -> AwaitableStatusDict:
        """Programa el apagado automatico con atenuacion progresiva tras `minutes` minutos."""
        return self._timer.start_sleep_timer(minutes, ips=ips)

    def cancel_sleep_timer(self) -> AwaitableStatusDict:
        """Cancela el temporizador de apagado activo."""
        return self._timer.cancel_sleep_timer()

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Consulta el estado actual del temporizador de apagado."""
        return self._timer.get_sleep_timer_status()

    def list_monitors(self) -> list[dict[str, Any]]:
        """Devuelve la lista de monitores disponibles para el modo Ambilight."""
        return self._ambilight.list_monitors()

    def start_ambilight(
        self,
        monitor_index: int = 1,
        color_mode: str = "vibrant",
        auto_brightness: bool = True,
        brightness: int = 85,
        smoothing_alpha: float = 0.38,
        ips: list[str] | None = None,
        min_brightness: int = 10,
    ) -> AwaitableStatusDict:
        """Inicia la sincronizacion continua del color de la pantalla con los focos objetivo."""
        return self._ambilight.start_ambilight(
            monitor_index=monitor_index,
            color_mode=color_mode,
            auto_brightness=auto_brightness,
            brightness=brightness,
            smoothing_alpha=smoothing_alpha,
            ips=ips,
            min_brightness=min_brightness,
        )

    def stop_ambilight(self) -> AwaitableStatusDict:
        """Detiene el flujo continuo de Ambilight."""
        return self._ambilight.stop_ambilight()

    def get_ambilight_status(self) -> dict[str, Any]:
        """Devuelve el estado actual de la sincronizacion Ambilight."""
        return self._ambilight.get_ambilight_status()

    def list_audio_devices(self) -> list[dict[str, Any]]:
        """Devuelve la lista de dispositivos WASAPI Loopback disponibles para el modo Musica."""
        return self._music.list_audio_devices()

    def start_music_sync(
        self,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
        smoothing_alpha: float = 0.50,
        audio_brightness: bool = True,
        brightness: int = 85,
        device_index: int | None = None,
        ips: list[str] | None = None,
    ) -> AwaitableStatusDict:
        """Inicia la sincronizacion acustica WASAPI Loopback hacia los focos objetivo."""
        return self._music.start_music_sync(
            palette_mode=palette_mode,
            sensitivity=sensitivity,
            smoothing_alpha=smoothing_alpha,
            audio_brightness=audio_brightness,
            brightness=brightness,
            device_index=device_index,
            ips=ips,
        )

    def stop_music_sync(self, close_sampler: bool = False) -> AwaitableStatusDict:
        """Detiene el flujo continuo de sincronizacion musical y opcionalmente cierra el stream
        WASAPI."""
        return self._music.stop_music_sync(close_sampler=close_sampler)

    def get_music_sync_status(self) -> dict[str, Any]:
        """Devuelve el estado actual y telemetria espectral de la sincronizacion musical."""
        return self._music.get_music_sync_status()

    def close_audio_sampler(self) -> None:
        """Libera de forma segura los recursos de los muestreadores y del controlador UDP."""
        self._ctx.close_audio_sampler()
