"""Herramienta de linea de comandos para descubrir y controlar focos WiZ por UDP.

Reutiliza `WizUdpController` (el mismo adaptador que usa `LightControlService`) para
descubrir, sondear y controlar los focos, de modo que el CLI no abre sockets propios
ni depende de `pywizlight` directamente.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.domain.models import LightState
from gestor_luces.domain.value_objects import Color


def _format_state(state: LightState) -> str:
    """Formatea un `LightState` para mostrarlo en consola (misma salida que el CLI previo)."""
    color = state.color
    rgb = f"({color.r}, {color.g}, {color.b})" if color is not None else "N/A"
    temperature = f"{state.temperature} K" if state.temperature is not None else "N/A"
    scene = state.scene_name if state.scene_name is not None else "None"
    return "\n".join(
        [
            f"Power state  : {'ON' if state.is_on else 'OFF'}",
            f"Brightness   : {state.brightness}%",
            f"RGB color    : {rgb}",
            f"Color temp   : {temperature}",
            f"Active scene : {scene}",
        ]
    )


async def _print_bulb_state(controller: WizUdpController, ip: str) -> bool:
    """Consulta el estado en vivo del foco y lo imprime; devuelve si hubo respuesta."""
    state = await controller.get_state(ip)
    if state is None:
        print(f"No response received from bulb at {ip}.")
        return False
    print(f"Bulb IP      : {ip}")
    print(_format_state(state))
    return True


async def run_discover(
    controller: WizUdpController,
    wait_time: float,
) -> int:
    """Descubre focos WiZ en la LAN usando el adaptador UDP compartido."""
    print("Searching for WiZ bulbs on the local network...")

    bulbs = await controller.discover(wait_time=wait_time)

    if not bulbs:
        print("\nNo WiZ bulbs found.")
        print("Checklist:")
        print("  1. Ensure the bulb is powered on and connected to 2.4 GHz Wi-Fi.")
        print("  2. Verify the PC and bulb are on the same LAN subnet.")
        print("  3. If you know the bulb IP from the WiZ mobile app, test it directly:")
        print("     python -m gestor_luces.cli status --ip <BULB_IP>")
        return 1

    print(f"\nFound {len(bulbs)} bulb(s):")
    for bulb in bulbs:
        print(f"  - IP: {bulb.ip:15s} | MAC: {bulb.mac} | Module: {bulb.module_name}")
    return 0


async def _resolve_target_ip(
    controller: WizUdpController,
    explicit_ip: str | None,
) -> str | None:
    """Resuelve la IP del foco a partir de --ip o descubre el primero en la red."""
    if explicit_ip:
        return explicit_ip

    bulbs = await controller.discover(wait_time=2.0)
    if bulbs:
        return bulbs[0].ip
    return None


async def run_command(controller: WizUdpController, args: argparse.Namespace) -> int:
    """Ejecuta el subcomando CLI seleccionado contra el adaptador UDP compartido."""
    if args.command == "discover":
        return await run_discover(controller, args.wait)

    target_ip = await _resolve_target_ip(controller, args.ip)
    if not target_ip:
        print("Error: Could not find a WiZ bulb automatically. Pass --ip <BULB_IP>.")
        return 1

    if args.command == "status":
        return 0 if await _print_bulb_state(controller, target_ip) else 1

    if args.command == "on":
        ok = await controller.set_power(target_ip, True, args.brightness)
        if not ok:
            print(f"Failed to turn ON bulb at {target_ip}.")
            return 1
        print(f"Turned ON bulb at {target_ip}.")
        await _print_bulb_state(controller, target_ip)
        return 0

    if args.command == "off":
        ok = await controller.set_power(target_ip, False)
        if not ok:
            print(f"Failed to turn OFF bulb at {target_ip}.")
            return 1
        print(f"Turned OFF bulb at {target_ip}.")
        await _print_bulb_state(controller, target_ip)
        return 0

    if args.command == "color":
        color = Color(r=args.r, g=args.g, b=args.b)
        ok = await controller.set_color(target_ip, color, args.brightness)
        if not ok:
            print(f"Failed to apply RGB color to {target_ip}.")
            return 1
        print(
            f"Applied RGB ({args.r}, {args.g}, {args.b}) "
            f"at {args.brightness}% brightness to {target_ip}."
        )
        await _print_bulb_state(controller, target_ip)
        return 0

    if args.command == "kelvin":
        ok = await controller.set_temperature(target_ip, args.temp, args.brightness)
        if not ok:
            print(f"Failed to apply color temperature to {target_ip}.")
            return 1
        print(
            f"Applied color temperature {args.temp} K "
            f"at {args.brightness}% brightness to {target_ip}."
        )
        await _print_bulb_state(controller, target_ip)
        return 0

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
        description="Discover and control WiZ bulbs over local UDP 38899.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: discover
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover WiZ bulbs on the local network via broadcast and unicast fallback.",
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
    controller = WizUdpController()
    try:
        return asyncio.run(run_command(controller, args))
    finally:
        controller.close()


if __name__ == "__main__":
    sys.exit(main())
