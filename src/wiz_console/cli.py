"""Command-line tool to discover and control WiZ bulbs over local UDP."""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

from wiz_console.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    JsonZoneRepository,
    resolve_default_data_dir,
)
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.models import LightState
from wiz_console.domain.value_objects import Color, validate_local_endpoint


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
        print("     python -m wiz_console.cli status --ip <BULB_IP>")
        return 1

    print(f"\nFound {len(bulbs)} bulb(s):")
    for bulb in bulbs:
        print(f"  - IP: {bulb.ip:15s} | MAC: {bulb.mac} | Module: {bulb.module_name}")
    return 0


def _resolve_bulb_ip_by_name(name: str, data_dir: Path | None) -> str:
    """Look up a persisted fixture IP by case-insensitive display name."""
    storage_dir = data_dir if data_dir is not None else resolve_default_data_dir()
    bulbs = JsonBulbRepository(data_dir=storage_dir).load_bulbs()
    needle = name.strip().lower()
    for bulb in bulbs:
        if bulb.name.strip().lower() == needle:
            return validate_local_endpoint(bulb.ip)
    raise ValueError(f"No saved bulb named {name!r} found in {storage_dir}.")


async def _resolve_target_ip(
    controller: WizUdpController,
    explicit_ip: str | None,
    explicit_name: str | None = None,
    data_dir: Path | None = None,
) -> str | None:
    """Resolve target bulb IP from `--ip`, `--name`, or LAN auto-discovery."""
    if explicit_ip is not None:
        return validate_local_endpoint(explicit_ip)
    if explicit_name is not None:
        return _resolve_bulb_ip_by_name(explicit_name, data_dir)

    bulbs = await controller.discover(wait_time=2.0)
    if bulbs:
        return bulbs[0].ip
    return None


def _build_cli_service(controller: WizUdpController, data_dir: Path | None) -> LightControlService:
    storage_dir = data_dir if data_dir is not None else resolve_default_data_dir()
    return LightControlService(
        controller=controller,
        bulb_repository=JsonBulbRepository(data_dir=storage_dir),
        scene_repository=JsonSceneRepository(data_dir=storage_dir),
        settings_repository=JsonSettingsRepository(data_dir=storage_dir),
        zone_repository=JsonZoneRepository(data_dir=storage_dir),
    )


async def run_command(controller: WizUdpController, args: argparse.Namespace) -> int:
    """Ejecuta el subcomando CLI seleccionado contra el adaptador UDP compartido."""
    data_dir_raw = getattr(args, "data_dir", None)
    data_dir = Path(data_dir_raw) if data_dir_raw else None

    if args.command == "discover":
        return await run_discover(controller, args.wait)

    if args.command == "zones":
        service = _build_cli_service(controller, data_dir)
        select_query = getattr(args, "select", None)
        zones = service.list_zones()
        if select_query:
            needle = select_query.strip().lower()
            match = next(
                (z for z in zones if z.id == select_query or z.name.strip().lower() == needle),
                None,
            )
            if match is None:
                print(f"Error: Unknown zone {select_query!r}.")
                return 1
            selected = service.select_zone(match.id)
            print(f"Selected zone '{match.name}' ({len(selected)} bulb target(s)).")
            return 0
        if not zones:
            print("No zones defined.")
            return 0
        for zone in zones:
            print(f"  - {zone.name} ({zone.id}): {', '.join(zone.bulb_ips)}")
        return 0

    try:
        target_ip = await _resolve_target_ip(
            controller,
            getattr(args, "ip", None),
            getattr(args, "name", None),
            data_dir,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if not target_ip:
        print("Error: Could not find a WiZ bulb automatically. Pass --ip <BULB_IP> or --name.")
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

    if args.command == "brightness":
        ok = await controller.set_brightness(target_ip, args.brightness)
        if not ok:
            print(f"Failed to set brightness on {target_ip}.")
            return 1
        print(f"Set brightness to {args.brightness}% on {target_ip}.")
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

    if args.command == "scene":
        ok = await controller.set_scene(
            target_ip,
            args.scene_id,
            speed=getattr(args, "speed", None),
            brightness=getattr(args, "brightness", None),
        )
        if not ok:
            print(f"Failed to apply scene #{args.scene_id} to {target_ip}.")
            return 1
        print(f"Applied scene #{args.scene_id} to {target_ip}.")
        await _print_bulb_state(controller, target_ip)
        return 0

    if args.command == "preset":
        service = _build_cli_service(controller, data_dir)
        query = args.name_or_id.strip()
        preset = next(
            (
                s
                for s in service.list_custom_scenes()
                if s.id == query or s.name.strip().lower() == query.lower()
            ),
            None,
        )
        if preset is None:
            print(f"Error: Unknown custom preset {args.name_or_id!r}.")
            return 1
        await service.apply_custom_scene(preset.id, ips=[target_ip])
        print(f"Applied preset '{preset.name}' to {target_ip}.")
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


def _local_endpoint_arg(raw: str) -> str:
    """Validate `--ip` CLI argument as a local IPv4 bulb endpoint."""
    try:
        return validate_local_endpoint(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_wait_seconds(raw: str) -> float:
    """Validate `discover --wait` as a finite duration in [0.1, 30.0] seconds."""
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError(f"Expected number, got '{raw}'.") from exc
    if not math.isfinite(value) or not (0.1 <= value <= 30.0):
        raise argparse.ArgumentTypeError(
            f"Wait time must be between 0.1 and 30.0 seconds, got {raw}."
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="wiz-console-cli",
        description="Discover and control WiZ bulbs over local UDP 38899.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Optional WizConsole data directory (bulbs/scenes/zones JSON).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover WiZ bulbs on the local network via broadcast and unicast fallback.",
    )
    discover_parser.add_argument(
        "--wait",
        type=_positive_wait_seconds,
        default=3.0,
        help="Seconds to wait for broadcast replies (default: 3.0).",
    )

    ip_parent = argparse.ArgumentParser(add_help=False)
    ip_parent.add_argument(
        "--ip",
        type=_local_endpoint_arg,
        default=None,
        help="Target bulb IPv4 address (auto-discovers first bulb if omitted).",
    )
    ip_parent.add_argument(
        "--name",
        default=None,
        help="Target saved bulb display name from bulbs.json.",
    )

    subparsers.add_parser(
        "status",
        parents=[ip_parent],
        help="Read current state (getPilot) from the bulb.",
    )

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

    subparsers.add_parser(
        "off",
        parents=[ip_parent],
        help="Turn the bulb off.",
    )

    bri_parser = subparsers.add_parser(
        "brightness",
        parents=[ip_parent],
        help="Set brightness percentage (10-100).",
    )
    bri_parser.add_argument(
        "brightness",
        type=restricted_int(10, 100),
        help="Brightness percentage (10-100).",
    )

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

    scene_parser = subparsers.add_parser(
        "scene",
        parents=[ip_parent],
        help="Activate a built-in WiZ scene by ID (1-36).",
    )
    scene_parser.add_argument("scene_id", type=restricted_int(1, 36), help="Built-in scene ID.")
    scene_parser.add_argument("--brightness", type=restricted_int(10, 100), default=None)
    scene_parser.add_argument("--speed", type=restricted_int(10, 200), default=None)

    preset_parser = subparsers.add_parser(
        "preset",
        parents=[ip_parent],
        help="Apply a saved custom preset by name or ID.",
    )
    preset_parser.add_argument("name_or_id", help="Custom preset name or ID.")

    zones_parser = subparsers.add_parser(
        "zones",
        help="List saved zones or select a zone as default targets.",
    )
    zones_parser.add_argument("--select", default=None, help="Zone name or ID to select.")

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
