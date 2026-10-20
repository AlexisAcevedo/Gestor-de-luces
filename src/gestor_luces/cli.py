"""Herramienta de linea de comandos (Fase 1) para verificar la comunicacion UDP con focos WiZ.

Este modulo permite comprobar de punta a punta que la PC (conectada por Ethernet)
puede descubrir y controlar el foco WiZ (conectado por WiFi 2.4 GHz) en la misma LAN
usando el puerto UDP 38899, antes de construir el resto de las capas.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import socket
import sys
from typing import Any

from pywizlight import PilotBuilder, discovery, wizlight
from pywizlight.utils import percent_to_hex

WIZ_UDP_PORT = 38899


def detect_local_ipv4() -> str | None:
    """Detecta la direccion IPv4 local activa de la interfaz conectada al router.

    Se abre un socket UDP hacia una IP externa sin enviar trafico real para que
    el sistema operativo elija la placa de red con salida a la red local (Ethernet),
    evitando adaptadores virtuales como WSL o Docker.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def compute_subnet_broadcast(local_ip: str | None) -> str:
    """Calcula la direccion de broadcast dirigida (/24) a partir de la IP local.

    En Windows con multiples placas de red, enviar a 255.255.255.255 suele salir
    por la interfaz equivocada. Enviar a 192.168.X.255 fuerza el enrutamiento
    por la subred de la placa Ethernet activa.
    """
    if not local_ip:
        return "255.255.255.255"
    try:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(network.broadcast_address)
    except ValueError:
        return "255.255.255.255"


async def probe_single_ip(ip: str, timeout: float = 0.35) -> dict[str, Any] | None:
    """Sondea una IP especifica por UDP unicast directo usando getSystemConfig.

    Sirve como alternativa cuando el Firewall de Windows bloquea las respuestas
    entrantes de un broadcast UDP, ya que el trafico unicast saliente abre
    automaticamente el paso para la respuesta de la misma IP.
    """
    loop = asyncio.get_running_loop()
    payload = json.dumps({"method": "getSystemConfig", "params": {}}).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await loop.sock_sendto(sock, payload, (ip, WIZ_UDP_PORT))
        data = await asyncio.wait_for(loop.sock_recv(sock, 1024), timeout=timeout)
        response = json.loads(data.decode("utf-8", errors="ignore"))
        result = response.get("result")
        if isinstance(result, dict) and "mac" in result:
            return {
                "ip": ip,
                "mac": result.get("mac", "unknown"),
                "module_name": result.get("moduleName", "unknown"),
            }
    except (TimeoutError, OSError, json.JSONDecodeError):
        return None
    finally:
        sock.close()
    return None


async def sweep_subnet_for_bulbs(local_ip: str) -> list[dict[str, Any]]:
    """Realiza un barrido unicast asincrono en la subred /24 local.

    Gracias a asyncio, podemos consultar las 254 direcciones de la red local en
    paralelo en menos de medio segundo sin bloquear el hilo ni ser filtrados
    por la regla de broadcast del Firewall de Windows.
    """
    network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    tasks = [
        probe_single_ip(str(host_ip))
        for host_ip in network.hosts()
        if str(host_ip) != local_ip
    ]
    results = await asyncio.gather(*tasks)
    return [item for item in results if item is not None]


async def run_discover(broadcast_space: str | None, wait_time: float) -> int:
    """Descubre focos WiZ en la LAN combinando broadcast y barrido unicast de respaldo."""
    local_ip = detect_local_ipv4()
    target_broadcast = broadcast_space or compute_subnet_broadcast(local_ip)

    print(f"Local IPv4 detected : {local_ip or 'unknown'}")
    print(f"Broadcast address   : {target_broadcast}:{WIZ_UDP_PORT}")
    print("Searching for WiZ bulbs on the local network...")

    found_by_ip: dict[str, dict[str, str]] = {}

    try:
        bulbs = await discovery.discover_lights(
            broadcast_space=target_broadcast,
            wait_time=wait_time,
        )
        for bulb in bulbs:
            found_by_ip[bulb.ip] = {
                "ip": bulb.ip,
                "mac": bulb.mac or "unknown",
                "method": "broadcast",
            }
    except OSError as exc:
        print(f"Broadcast socket warning: {exc}")

    # Si el broadcast no encontro focos y conocemos nuestra IP local, ejecutamos
    # el barrido unicast para sortear posibles bloqueos del Firewall de Windows.
    if not found_by_ip and local_ip:
        print("No broadcast replies received. Running fast unicast subnet probe...")
        probed = await sweep_subnet_for_bulbs(local_ip)
        for item in probed:
            found_by_ip[item["ip"]] = {
                "ip": item["ip"],
                "mac": item["mac"],
                "method": f"unicast-probe ({item['module_name']})",
            }

    if not found_by_ip:
        print("\nNo WiZ bulbs found.")
        print("Checklist:")
        print("  1. Ensure the bulb is powered on and connected to 2.4 GHz Wi-Fi.")
        print("  2. Verify the PC and bulb are on the same LAN subnet.")
        print("  3. If you know the bulb IP from the WiZ mobile app, test it directly:")
        print("     python -m gestor_luces.cli status --ip <BULB_IP>")
        return 1

    print(f"\nFound {len(found_by_ip)} bulb(s):")
    for info in found_by_ip.values():
        print(f"  - IP: {info['ip']:15s} | MAC: {info['mac']} | Via: {info['method']}")
    return 0


async def resolve_target_ip(explicit_ip: str | None) -> str | None:
    """Resuelve la IP del foco a partir del argumento --ip o descubre el primero en la red."""
    if explicit_ip:
        return explicit_ip

    local_ip = detect_local_ipv4()
    target_broadcast = compute_subnet_broadcast(local_ip)
    try:
        bulbs = await discovery.discover_lights(broadcast_space=target_broadcast, wait_time=2.0)
        if bulbs:
            return bulbs[0].ip
    except OSError:
        pass

    if local_ip:
        probed = await sweep_subnet_for_bulbs(local_ip)
        if probed:
            return str(probed[0]["ip"])
    return None


async def print_bulb_status(bulb: wizlight) -> None:
    """Consulta el estado en vivo del foco mediante getPilot y lo muestra en consola."""
    states = await bulb.updateState()
    state = states[0] if states else None
    if state is None:
        print(f"No response received from bulb at {bulb.ip}.")
        return

    is_on = state.get_state()
    raw_dimming = state.pilotResult.get("dimming")
    rgb = state.get_rgb()
    colortemp = state.get_colortemp()
    scene = state.get_scene()

    print(f"Bulb IP      : {bulb.ip}")
    print(f"Power state  : {'ON' if is_on else 'OFF'}")
    print(f"Brightness   : {f'{raw_dimming}%' if raw_dimming is not None else 'N/A'}")
    print(f"RGB color    : {rgb if rgb != (None, None, None) else 'N/A'}")
    print(f"Color temp   : {f'{colortemp} K' if colortemp is not None else 'N/A'}")
    print(f"Active scene : {scene if scene is not None else 'None'}")


async def run_command(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando CLI seleccionado."""
    if args.command == "discover":
        return await run_discover(args.broadcast, args.wait)

    target_ip = await resolve_target_ip(args.ip)
    if not target_ip:
        print("Error: Could not find a WiZ bulb automatically. Pass --ip <BULB_IP>.")
        return 1

    bulb = wizlight(target_ip)
    try:
        if args.command == "status":
            await print_bulb_status(bulb)
            return 0

        if args.command == "on":
            pilot = (
                PilotBuilder(brightness=percent_to_hex(args.brightness))
                if args.brightness is not None
                else PilotBuilder()
            )
            await bulb.turn_on(pilot)
            print(f"Turned ON bulb at {target_ip}.")
            await print_bulb_status(bulb)
            return 0

        if args.command == "off":
            await bulb.turn_off()
            print(f"Turned OFF bulb at {target_ip}.")
            await print_bulb_status(bulb)
            return 0

        if args.command == "color":
            pilot = PilotBuilder(
                rgb=(args.r, args.g, args.b),
                brightness=percent_to_hex(args.brightness),
            )
            await bulb.turn_on(pilot)
            print(
                f"Applied RGB ({args.r}, {args.g}, {args.b}) "
                f"at {args.brightness}% brightness to {target_ip}."
            )
            await print_bulb_status(bulb)
            return 0

        if args.command == "kelvin":
            pilot = PilotBuilder(
                colortemp=args.temp,
                brightness=percent_to_hex(args.brightness),
            )
            await bulb.turn_on(pilot)
            print(
                f"Applied color temperature {args.temp} K "
                f"at {args.brightness}% brightness to {target_ip}."
            )
            await print_bulb_status(bulb)
            return 0
    finally:
        await bulb.async_close()

    return 1


def restricted_int(min_val: int, max_val: int):
    """Genera un validador de enteros acotado para argparse."""

    def validator(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Expected integer, got '{raw}'.") from exc
        if not (min_val <= value <= max_val):
            raise argparse.ArgumentTypeError(
                f"Value must be between {min_val} and {max_val}, got {value}."
            )
        return value

    return validator


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="gestor-luces-cli",
        description="Phase 1 CLI tool to discover and control WiZ bulbs over local UDP 38899.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: discover
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover WiZ bulbs on the local network via broadcast and unicast fallback.",
    )
    discover_parser.add_argument(
        "--broadcast",
        default=None,
        help="Explicit broadcast IP (defaults to active /24 subnet broadcast).",
    )
    discover_parser.add_argument(
        "--wait",
        type=float,
        default=3.0,
        help="Seconds to wait for broadcast replies (default: 3.0).",
    )

    # Argumento comun --ip para los comandos de control
    ip_parent = argparse.ArgumentParser(add_help=False)
    ip_parent.add_argument(
        "--ip",
        default=None,
        help="Target bulb IPv4 address (auto-discovers first bulb if omitted).",
    )

    # Subcomando: status
    subparsers.add_parser(
        "status",
        parents=[ip_parent],
        help="Read current state (getPilot) from the bulb.",
    )

    # Subcomando: on
    on_parser = subparsers.add_parser(
        "on",
        parents=[ip_parent],
        help="Turn the bulb on (optionally setting brightness).",
    )
    on_parser.add_argument(
        "--brightness",
        type=restricted_int(10, 100),
        default=None,
        help="Brightness percentage (10-100).",
    )

    # Subcomando: off
    subparsers.add_parser(
        "off",
        parents=[ip_parent],
        help="Turn the bulb off.",
    )

    # Subcomando: color
    color_parser = subparsers.add_parser(
        "color",
        parents=[ip_parent],
        help="Set RGB color (0-255 each) and optional brightness.",
    )
    color_parser.add_argument("r", type=restricted_int(0, 255), help="Red channel (0-255).")
    color_parser.add_argument("g", type=restricted_int(0, 255), help="Green channel (0-255).")
    color_parser.add_argument("b", type=restricted_int(0, 255), help="Blue channel (0-255).")
    color_parser.add_argument(
        "--brightness",
        type=restricted_int(10, 100),
        default=100,
        help="Brightness percentage (10-100, default: 100).",
    )

    # Subcomando: kelvin
    kelvin_parser = subparsers.add_parser(
        "kelvin",
        parents=[ip_parent],
        help="Set white color temperature in Kelvin (2200-6500).",
    )
    kelvin_parser.add_argument(
        "temp",
        type=restricted_int(2200, 6500),
        help="Color temperature in Kelvin (2200-6500).",
    )
    kelvin_parser.add_argument(
        "--brightness",
        type=restricted_int(10, 100),
        default=100,
        help="Brightness percentage (10-100, default: 100).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada sincrono que inicia el event loop de asyncio."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run_command(args))


if __name__ == "__main__":
    sys.exit(main())
