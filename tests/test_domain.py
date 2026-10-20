"""Pruebas unitarias de la capa de Dominio (Value Objects, Entidades y Escenas)."""

from __future__ import annotations

import pytest
from pywizlight.scenes import SCENES as PYWIZLIGHT_SCENES

from gestor_luces.domain import (
    Brightness,
    BuiltInScene,
    Bulb,
    Color,
    ColorTemperature,
    CustomScene,
    Group,
    LightMode,
    LightState,
    SceneSpeed,
    get_builtin_scene,
    list_builtin_scenes,
)


def test_color_validation_and_hex_conversion() -> None:
    """Verifica que Color valide el rango 0-255 y convierta ida y vuelta a hexadecimal."""
    coral = Color(255, 80, 32)
    assert coral.to_hex() == "#ff5020"
    assert Color.from_hex("#FF5020") == coral
    assert Color.from_hex("ff5020") == coral

    with pytest.raises(ValueError, match="between 0 and 255"):
        Color(-1, 0, 0)

    with pytest.raises(ValueError, match="between 0 and 255"):
        Color(0, 256, 0)

    with pytest.raises(ValueError, match="between 0 and 255"):
        Color(True, 0, 0)  # type: ignore[arg-type]


def test_color_lerp_interpolation() -> None:
    """Verifica que la interpolacion lineal (lerp) calcule puntos intermedios exactos."""
    black = Color(0, 0, 0)
    white = Color(200, 100, 50)

    assert black.lerp(white, 0.0) == black
    assert black.lerp(white, 1.0) == white
    assert black.lerp(white, 0.5) == Color(100, 50, 25)


def test_value_objects_boundaries() -> None:
    """Comprueba los limites fisicos de brillo (10-100), Kelvin (2200-6500) y velocidad (10-200)."""
    assert Brightness(10).percent == 10
    assert Brightness(100).percent == 100
    with pytest.raises(ValueError, match="between 10 and 100"):
        Brightness(9)
    with pytest.raises(ValueError, match="between 10 and 100"):
        Brightness(101)

    assert ColorTemperature(2200).kelvin == 2200
    assert ColorTemperature(6500).kelvin == 6500
    with pytest.raises(ValueError, match="between 2200 and 6500"):
        ColorTemperature(2100)
    with pytest.raises(ValueError, match="between 2200 and 6500"):
        ColorTemperature(6600)

    assert SceneSpeed(10).value == 10
    assert SceneSpeed(200).value == 200
    with pytest.raises(ValueError, match="between 10 and 200"):
        SceneSpeed(5)


def test_builtin_scenes_catalog_matches_pywizlight() -> None:
    """Garantiza que las 36 escenas nativas coincidan con los IDs y nombres de pywizlight."""
    scenes = list_builtin_scenes()
    assert len(scenes) == 36

    for scene in scenes:
        assert isinstance(scene, BuiltInScene)
        assert 1 <= scene.scene_id <= 36
        assert PYWIZLIGHT_SCENES[scene.scene_id] == scene.name
        assert get_builtin_scene(scene.scene_id) == scene

    # Escena dinamica (Party = 4) vs escena fija (Warm white = 11)
    party = get_builtin_scene(4)
    warm_white = get_builtin_scene(11)
    assert party is not None and party.supports_speed is True
    assert warm_white is not None and warm_white.supports_speed is False


def test_custom_scene_and_bulb_serialization() -> None:
    """Verifica la serializacion a diccionario de Bulb, LightState, Group y CustomScene."""
    bulb = Bulb(ip="192.168.1.38", mac="a8bb50df9029")
    assert bulb.name == "WiZ Bulb (192.168.1.38)"

    bulb.state = LightState(
        is_on=True,
        brightness=75,
        mode=LightMode.SCENE,
        scene_id=1,
    )
    assert bulb.state.scene_name == "Ocean"
    serialized = bulb.to_dict()
    assert serialized["ip"] == "192.168.1.38"
    assert serialized["state"]["scene_name"] == "Ocean"

    custom = CustomScene(
        id="cyberpunk",
        name="Cyberpunk",
        mode=LightMode.RGB,
        brightness=85,
        color=Color(255, 0, 128),
    )
    restored = CustomScene.from_dict(custom.to_dict())
    assert restored == custom

    group = Group(id="desk", name="Escritorio", bulb_ips=["192.168.1.38", "192.168.1.39"])
    assert group.to_dict()["bulb_ips"] == ["192.168.1.38", "192.168.1.39"]
