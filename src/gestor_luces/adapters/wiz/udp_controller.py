"""Adaptador de infraestructura UDP para focos inteligentes Philips WiZ.

Implementa el puerto LightController comunicandose directamente mediante datagramas
JSON sobre UDP (puerto 38899 por defecto). Permite inyectar puertos personalizados
y candidatos de sondeo para ejecutar pruebas de integracion deterministas contra
simuladores locales en 127.0.0.1 sin requerir hardware fisico ni permisos de administrador.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any

from pywizlight import discovery
from pywizlight.scenes import SCENES as PYWIZLIGHT_SCENES

from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import get_builtin_scene
from gestor_luces.domain.value_objects import Color, LightMode

DEFAULT_WIZ_UDP_PORT = 38899
_MAX_NETWORK_TEXT_LEN = 64


def _safe_int(value: Any, default: int) -> int:
    """Convierte datos no confiables de red a int sin lanzar excepciones."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_text(value: Any, default: str) -> str:
    """Normaliza texto recibido por red acotando su longitud."""
    return str(value)[:_MAX_NETWORK_TEXT_LEN] if value is not None else default


def detect_local_ipv4() -> str | None:
    """Detecta la IPv4 de la placa de red local activa (Ethernet/WiFi) hacia el router."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def compute_subnet_broadcast(local_ip: str | None) -> str:
    """Calcula la direccion de broadcast dirigida (/24) de la interfaz activa."""
    if not local_ip:
        return "255.255.255.255"
    try:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(network.broadcast_address)
    except ValueError:
        return "255.255.255.255"


class _UdpResponseProtocol(asyncio.DatagramProtocol):
    """Protocolo interno de asyncio para recibir una respuesta JSON unica por UDP."""

    def __init__(self, future: asyncio.Future[dict[str, Any]]) -> None:
        self._future = future

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        if self._future.done():
            return
        try:
            decoded = json.loads(data.decode("utf-8", errors="ignore"))
            if isinstance(decoded, dict):
                self._future.set_result(decoded)
        except json.JSONDecodeError:
            pass

    def error_received(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)


class WizUdpController:
    """Adaptador UDP asincrono que implementa el contrato LightController para focos WiZ."""

    def __init__(
        self,
        port: int = DEFAULT_WIZ_UDP_PORT,
        default_timeout: float = 0.8,
        probe_candidates: list[str] | None = None,
    ) -> None:
        self._port = port
        self._default_timeout = default_timeout
        self._probe_candidates = list(probe_candidates) if probe_candidates is not None else None
        self._stream_sock: socket.socket | None = None

    def _get_stream_socket(self) -> socket.socket:
        """Devuelve un socket UDP no bloqueante reutilizable para el flujo continuo."""
        if self._stream_sock is None or self._stream_sock.fileno() < 0:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._stream_sock = sock
        return self._stream_sock

    def close(self) -> None:
        """Cierra el socket UDP reutilizado por `stream_pilot` si fue inicializado."""
        if self._stream_sock is not None:
            try:
                self._stream_sock.close()
            except OSError:
                pass
            self._stream_sock = None

    def _resolve_endpoint(self, ip_or_endpoint: str) -> tuple[str, int]:
        """Permite direcciones IP estandar o endpoints 'ip:puerto' para pruebas locales."""
        cleaned = ip_or_endpoint.strip()
        if ":" in cleaned:
            host, raw_port = cleaned.rsplit(":", 1)
            return host, int(raw_port)
        return cleaned, self._port

    async def _send_request(
        self,
        ip: str,
        method: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Envia un comando JSON UDP al foco y espera su respuesta de forma no bloqueante."""
        host, port = self._resolve_endpoint(ip)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        payload = json.dumps({"method": method, "params": params}).encode("utf-8")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()

        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpResponseProtocol(future),
            remote_addr=(host, port),
        )
        try:
            transport.sendto(payload)
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except (TimeoutError, OSError):
            return None
        finally:
            transport.close()

    async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
        """Descubre focos WiZ combinando broadcast UDP y barrido unicast de respaldo."""
        found_by_ip: dict[str, Bulb] = {}

        # Si se inyectaron candidatos explicitos (ej. en pruebas de integracion locales),
        # los sondeamos directamente sin depender del broadcast del sistema operativo.
        if self._probe_candidates is not None:
            probed_results = await asyncio.gather(
                *(self.probe_bulb(candidate, timeout=0.5) for candidate in self._probe_candidates),
                return_exceptions=True,
            )
            for bulb in probed_results:
                if isinstance(bulb, Bulb):
                    found_by_ip[bulb.ip] = bulb
            return list(found_by_ip.values())

        local_ip = detect_local_ipv4()
        target_broadcast = compute_subnet_broadcast(local_ip)

        if self._port == DEFAULT_WIZ_UDP_PORT:
            try:
                discovered = await discovery.discover_lights(
                    broadcast_space=target_broadcast,
                    wait_time=wait_time,
                )
                for item in discovered:
                    probed = await self.probe_bulb(item.ip, timeout=0.6)
                    if probed is not None:
                        found_by_ip[item.ip] = probed
            except OSError:
                pass

        # Respaldo unicast /24 cuando el Firewall de Windows filtra las respuestas broadcast
        if not found_by_ip and local_ip:
            network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            tasks = [
                self.probe_bulb(str(host_ip), timeout=0.35)
                for host_ip in network.hosts()
                if str(host_ip) != local_ip
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for bulb in results:
                if isinstance(bulb, Bulb):
                    found_by_ip[bulb.ip] = bulb

        return list(found_by_ip.values())

    async def probe_bulb(self, ip: str, timeout: float = 1.0) -> Bulb | None:
        """Consulta getSystemConfig y getPilot para construir una entidad Bulb completa."""
        sys_resp = await self._send_request(ip, "getSystemConfig", {}, timeout=timeout)
        if not sys_resp or not isinstance(sys_resp.get("result"), dict):
            return None

        sys_result = sys_resp["result"]
        mac = _safe_text(sys_result.get("mac"), "unknown")
        module_name = _safe_text(sys_result.get("moduleName"), "ESP01_SHRGB1C_31")

        state = await self.get_state(ip, timeout=timeout)
        return Bulb(
            ip=ip,
            mac=mac,
            module_name=module_name,
            is_online=True,
            state=state if state is not None else LightState(is_on=False),
        )

    async def get_state(self, ip: str, timeout: float = 1.0) -> LightState | None:
        """Obtiene el estado en vivo del foco mediante el metodo UDP getPilot."""
        response = await self._send_request(ip, "getPilot", {}, timeout=timeout)
        if not response or not isinstance(response.get("result"), dict):
            return None

        pilot = response["result"]
        is_on = bool(pilot.get("state", False))
        raw_dimming = _safe_int(pilot.get("dimming", 100), 100)
        brightness = max(10, min(100, raw_dimming))
        speed = _safe_int(pilot.get("speed", 100), 100)

        scene_id = pilot.get("sceneId")
        if isinstance(scene_id, int) and scene_id > 0:
            builtin = get_builtin_scene(scene_id)
            scene_name = (
                builtin.name
                if builtin is not None
                else PYWIZLIGHT_SCENES.get(scene_id, f"Scene {scene_id}")
            )
            return LightState(
                is_on=is_on,
                brightness=brightness,
                mode=LightMode.SCENE,
                color=None,
                temperature=None,
                scene_id=scene_id,
                scene_name=scene_name,
                speed=speed,
            )

        if all(channel in pilot for channel in ("r", "g", "b")):
            color = Color(
                r=max(0, min(255, _safe_int(pilot["r"], 0))),
                g=max(0, min(255, _safe_int(pilot["g"], 0))),
                b=max(0, min(255, _safe_int(pilot["b"], 0))),
            )
            return LightState(
                is_on=is_on,
                brightness=brightness,
                mode=LightMode.RGB,
                color=color,
                temperature=None,
                scene_id=None,
                scene_name=None,
                speed=speed,
            )

        raw_temp = _safe_int(pilot.get("temp", 4200), 4200)
        clamped_temp = max(2200, min(6500, raw_temp))
        return LightState(
            is_on=is_on,
            brightness=brightness,
            mode=LightMode.TEMPERATURE,
            color=None,
            temperature=clamped_temp,
            scene_id=None,
            scene_name=None,
            speed=speed,
        )

    async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
        """Envia setPilot para encender o apagar el foco."""
        params: dict[str, Any] = {"state": bool(is_on)}
        if brightness is not None:
            params["dimming"] = int(brightness)
        return await self._send_set_pilot(ip, params)

    async def set_brightness(self, ip: str, brightness: int) -> bool:
        """Envia setPilot modificando unicamente el porcentaje de dimming."""
        params: dict[str, Any] = {"state": True, "dimming": int(brightness)}
        return await self._send_set_pilot(ip, params)

    async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
        """Envia setPilot con los canales r, g, b y brillo opcional."""
        params: dict[str, Any] = {
            "state": True,
            "r": color.r,
            "g": color.g,
            "b": color.b,
        }
        if brightness is not None:
            params["dimming"] = int(brightness)
        return await self._send_set_pilot(ip, params)

    async def set_temperature(self, ip: str, kelvin: int, brightness: int | None = None) -> bool:
        """Envia setPilot con temperatura de blanco en grados Kelvin."""
        params: dict[str, Any] = {
            "state": True,
            "temp": int(kelvin),
        }
        if brightness is not None:
            params["dimming"] = int(brightness)
        return await self._send_set_pilot(ip, params)

    async def set_scene(
        self,
        ip: str,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
    ) -> bool:
        """Envia setPilot con el identificador de escena nativa y velocidad opcional."""
        params: dict[str, Any] = {
            "state": True,
            "sceneId": int(scene_id),
        }
        if speed is not None:
            params["speed"] = int(speed)
        if brightness is not None:
            params["dimming"] = int(brightness)
        return await self._send_set_pilot(ip, params)

    async def stream_pilot(self, ip: str, color: Color, brightness: int) -> None:
        """Envia un datagrama UDP setPilot sin esperar confirmacion para baja latencia."""
        host, port = self._resolve_endpoint(ip)
        payload = json.dumps(
            {
                "method": "setPilot",
                "params": {
                    "state": True,
                    "r": color.r,
                    "g": color.g,
                    "b": color.b,
                    "dimming": int(brightness),
                },
            }
        ).encode("utf-8")

        try:
            self._get_stream_socket().sendto(payload, (host, port))
        except OSError:
            self.close()

    async def _send_set_pilot(self, ip: str, params: dict[str, Any]) -> bool:
        """Ejecuta setPilot y verifica que el foco confirme con success=True."""
        response = await self._send_request(ip, "setPilot", params)
        if not response or not isinstance(response.get("result"), dict):
            return False
        return bool(response["result"].get("success", False))
