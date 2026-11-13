"""Estado compartido y colaboradores de los servicios de aplicacion.

`LightControlService` se apoya en este contexto para que las capacidades
(control de focos, inventario, escenas, temporizador, Ambilight, musica y
ajustes) compartan un unico inventario de focos, la seleccion activa, las
preferencias globales y los manejadores de flujo continuo.

El contexto concentra ademas lo que no pertenece a una sola capacidad: la
traduccion de fotogramas a comandos UDP y la liberacion de los recursos
compartidos entre flujos.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable

from gestor_luces.application.ambilight_stream import AmbilightStreamManager
from gestor_luces.application.music_stream import MusicSyncStreamManager
from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.sleep_timer import SleepTimerManager
from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import CustomScene
from gestor_luces.domain.value_objects import (
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    Color,
    LightMode,
    normalize_language,
    normalize_theme,
)
from gestor_luces.ports.repositories import (
    AudioSampler,
    BulbRepository,
    LightController,
    SceneRepository,
    ScreenSampler,
    SettingsRepository,
)

MAX_EXPLICIT_TARGETS = 64
MAX_DISPLAY_NAME_LEN = 80


def validate_display_name(raw_name: str, kind: str) -> str:
    """Valida que un nombre de foco o escena no este vacio ni exceda el largo maximo."""
    cleaned = raw_name.strip()
    if not cleaned:
        raise ValueError(f"{kind} name cannot be empty.")
    if len(cleaned) > MAX_DISPLAY_NAME_LEN:
        raise ValueError(f"{kind} name is too long (max {MAX_DISPLAY_NAME_LEN} chars).")
    return cleaned


def validate_local_endpoint(value: str) -> str:
    """Valida que el destino sea una IPv4 local (privada, loopback o link-local).

    Acepta 'a.b.c.d' o 'a.b.c.d:puerto'. Evita que el puente de la UI dirija
    trafico UDP hacia hosts publicos o nombres DNS arbitrarios.
    """
    host, sep, raw_port = value.strip().partition(":")
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError as exc:
        raise ValueError(f"Invalid bulb IPv4 address: {value!r}") from exc
    if not (address.is_private or address.is_loopback or address.is_link_local):
        raise ValueError(f"Bulb address must be on the local network: {value!r}")
    if sep and not (raw_port.isdigit() and 1 <= int(raw_port) <= 65535):
        raise ValueError(f"Invalid bulb port: {value!r}")
    return value.strip()


class ServiceContext:
    """Colaboradores y estado mutable compartidos por los servicios de aplicacion."""

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
        self.controller = controller
        self.bulb_repo = bulb_repository
        self.scene_repo = scene_repository
        self.settings_repo = settings_repository
        self.rate_limiter = rate_limiter or StreamRateLimiter()
        self.sleep_timer = sleep_timer or SleepTimerManager()
        self.screen_sampler = screen_sampler
        self.screen_sampler_factory = screen_sampler_factory
        self.ambilight = ambilight_manager or AmbilightStreamManager(sampler=screen_sampler)
        self.audio_sampler = audio_sampler
        self.audio_sampler_factory = audio_sampler_factory
        self.music_sync = music_manager or MusicSyncStreamManager(sampler=audio_sampler)
        self.bulbs: dict[str, Bulb] = {}
        self.selected_ips: list[str] = []
        self.custom_scenes: dict[str, CustomScene] = {}
        self.language: str = DEFAULT_LANGUAGE
        self.theme: str = DEFAULT_THEME

        if self.bulb_repo is not None:
            for saved_bulb in self.bulb_repo.load_bulbs():
                self.bulbs[saved_bulb.ip] = saved_bulb
            self.selected_ips = list(self.bulbs.keys())

        if self.scene_repo is not None:
            for saved_scene in self.scene_repo.load_scenes():
                self.custom_scenes[saved_scene.id] = saved_scene

        if self.settings_repo is not None:
            loaded_settings = self.settings_repo.load_settings()
            self.language = normalize_language(loaded_settings.get("language", DEFAULT_LANGUAGE))
            self.theme = normalize_theme(loaded_settings.get("theme", DEFAULT_THEME))

    def list_bulbs(self) -> list[Bulb]:
        """Devuelve la lista de todos los focos registrados actualmente."""
        return list(self.bulbs.values())

    def get_bulb(self, ip: str) -> Bulb | None:
        """Obtiene un foco registrado por su direccion IP."""
        return self.bulbs.get(ip)

    def select_targets(self, ips: list[str]) -> list[str]:
        """Define que subconjunto de focos recibira los comandos cuando no se indiquen IPs
        explicitas."""
        valid_ips = [ip for ip in ips if ip in self.bulbs]
        self.selected_ips = valid_ips
        resolved_targets = self.get_target_ips()
        self.ambilight.update_targets(resolved_targets)
        self.music_sync.update_targets(resolved_targets)
        return list(self.selected_ips)

    def get_target_ips(self, explicit_ips: list[str] | None = None) -> list[str]:
        """Resuelve la lista de IPs destino para una operacion de control.

        Si el llamador pasa explicit_ips, se utilizan esas direcciones. De lo contrario,
        se usan los focos seleccionados actualmente (o todos los registrados si la
        seleccion esta vacia).
        """
        if explicit_ips is not None:
            if len(explicit_ips) > MAX_EXPLICIT_TARGETS:
                raise ValueError(f"Too many target IPs (max {MAX_EXPLICIT_TARGETS}).")
            for explicit_ip in explicit_ips:
                validate_local_endpoint(explicit_ip)
            return list(explicit_ips)
        if self.selected_ips:
            return list(self.selected_ips)
        return list(self.bulbs.keys())

    def ensure_bulb_entry(self, ip: str) -> Bulb:
        """Obtiene la instancia Bulb registrada o crea una temporal si la IP es nueva."""
        bulb = self.bulbs.get(ip)
        if bulb is None:
            bulb = Bulb(ip=ip)
            self.bulbs[ip] = bulb
        return bulb

    def resolve_reference_state(self, source_ip: str | None = None) -> LightState:
        """Determina el estado luminico de referencia a partir de una IP o la seleccion actual."""
        if source_ip and source_ip in self.bulbs:
            return self.bulbs[source_ip].state
        for ip in self.get_target_ips():
            if ip in self.bulbs:
                return self.bulbs[ip].state
        if self.bulbs:
            return next(iter(self.bulbs.values())).state
        return LightState()

    def persist_bulbs(self) -> None:
        """Delega el guardado del inventario si hay un repositorio configurado."""
        if self.bulb_repo is not None:
            self.bulb_repo.save_bulbs(self.list_bulbs())

    def persist_scenes(self) -> None:
        """Delega el guardado de escenas personalizadas si hay un repositorio configurado."""
        if self.scene_repo is not None:
            self.scene_repo.save_scenes(self.list_custom_scenes())

    def list_custom_scenes(self) -> list[CustomScene]:
        """Devuelve la coleccion de escenas personalizadas creadas por el usuario."""
        return list(self.custom_scenes.values())

    def persist_settings(self) -> None:
        """Delega el guardado de preferencias globales si hay un repositorio configurado."""
        if self.settings_repo is not None:
            self.settings_repo.save_settings({"language": self.language, "theme": self.theme})

    def ensure_screen_sampler(self) -> ScreenSampler | None:
        """Obtiene el adaptador de pantalla inyectado o lo instancia mediante la fabrica
        provista."""
        if self.screen_sampler is None and self.screen_sampler_factory is not None:
            self.screen_sampler = self.screen_sampler_factory()
            self.ambilight.set_sampler(self.screen_sampler)
        return self.screen_sampler

    def ensure_audio_sampler(self) -> AudioSampler | None:
        """Obtiene el adaptador de audio inyectado o lo instancia mediante la fabrica provista."""
        if self.audio_sampler is None and self.audio_sampler_factory is not None:
            self.audio_sampler = self.audio_sampler_factory()
            self.music_sync.set_sampler(self.audio_sampler)
        return self.audio_sampler

    async def stream_color_frame(
        self,
        color: Color,
        brightness: int = 100,
        ips: list[str] | None = None,
    ) -> bool:
        """Envia un fotograma continuo (Ambilight/Musica) filtrado por el RateLimiter.

        Devuelve True si al menos un foco recibio un paquete nuevo, o False si
        todos los envios fueron suprimidos por limite de frecuencia o deduplicacion.
        """
        target_ips = self.get_target_ips(ips)
        if not target_ips:
            return False

        tasks = []
        for ip in target_ips:
            prepared = self.rate_limiter.prepare_frame(ip, color, brightness)
            if prepared is not None:
                smoothed_color, smoothed_brightness = prepared
                bulb = self.ensure_bulb_entry(ip)
                bulb.state = LightState(
                    is_on=True,
                    brightness=smoothed_brightness,
                    mode=LightMode.RGB,
                    color=smoothed_color,
                    temperature=None,
                )
                tasks.append(
                    self.controller.stream_pilot(
                        ip,
                        color=smoothed_color,
                        brightness=smoothed_brightness,
                    )
                )

        if not tasks:
            return False

        await asyncio.gather(*tasks)
        return True

    def close_audio_sampler(self) -> None:
        """Libera de forma segura los recursos de los muestreadores y del controlador UDP."""
        if self.audio_sampler is not None:
            close_fn = getattr(self.audio_sampler, "close", None)
            if callable(close_fn):
                close_fn()
        if self.screen_sampler is not None:
            screen_close = getattr(self.screen_sampler, "close", None)
            if callable(screen_close):
                screen_close()
        ctrl_close = getattr(self.controller, "close", None)
        if callable(ctrl_close):
            ctrl_close()
