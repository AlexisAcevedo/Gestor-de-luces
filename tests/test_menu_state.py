"""Pruebas del sondeo de modo menu de Win32 usado por la bandeja (Fase 3, T-3.6).

`_is_menu_open` consulta `GetGUIThreadInfo(0, ...)`: sus banderas de modo menu son la
unica forma de saber, desde el hilo de refresco, que el HMENU no se puede reconstruir
porque el usuario tiene el menu desplegado.
"""

from __future__ import annotations

import ctypes
from typing import Any

import pytest

from gestor_luces.adapters.platform.windows.menu_state import (
    GUI_INMENUMODE,
    GUI_POPUPMENUMODE,
    GUI_SYSTEMMENUMODE,
    _GuiThreadInfo,
    _is_menu_open,
)


class FakeUser32:
    """Doble de `user32` que solo implementa `GetGUIThreadInfo`."""

    def __init__(self, flags: int, result: int = 1) -> None:
        self.flags = flags
        self.result = result
        self.calls: list[int] = []

    def GetGUIThreadInfo(self, thread_id: int, info_ptr: Any) -> int:
        self.calls.append(thread_id)
        info = ctypes.cast(info_ptr, ctypes.POINTER(_GuiThreadInfo)).contents
        info.flags = self.flags if self.result else 0
        return self.result


@pytest.mark.parametrize("flags", [GUI_INMENUMODE, GUI_SYSTEMMENUMODE, GUI_POPUPMENUMODE])
def test_is_menu_open_reports_every_menu_mode_flag(flags: int) -> None:
    """Cualquiera de las banderas de modo menu significa que hay un menu desplegado."""
    user32 = FakeUser32(flags)

    assert _is_menu_open(platform="win32", user32=user32) is True
    assert user32.calls == [0]


def test_is_menu_open_is_false_without_menu_flags() -> None:
    """Sin banderas de menu el HMENU se puede reconstruir con seguridad."""
    assert _is_menu_open(platform="win32", user32=FakeUser32(0x20)) is False


def test_is_menu_open_is_false_when_the_probe_fails() -> None:
    """Un fallo de la API nunca debe bloquear el refresco para siempre."""
    assert _is_menu_open(platform="win32", user32=FakeUser32(GUI_POPUPMENUMODE, result=0)) is False


def test_is_menu_open_is_false_off_windows() -> None:
    """Fuera de Windows el concepto no aplica y no se toca ninguna DLL."""
    user32 = FakeUser32(GUI_POPUPMENUMODE)

    assert _is_menu_open(platform="linux", user32=user32) is False
    assert user32.calls == []
