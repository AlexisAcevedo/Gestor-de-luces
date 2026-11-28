"""Regression tests for Win32 64-bit ctypes handles, UI marshalling, Region disposal,
SingleInstanceGuard handle lifecycle, and Windows autostart hardening."""

from __future__ import annotations

import ctypes
import sys
import types
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from gestor_luces.adapters.platform.windows import window_chrome
from gestor_luces.adapters.system import single_instance as single_instance_module
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.system.windows_autostart import (
    DEFAULT_VALUE_NAME,
    RUN_KEY_PATH,
    WindowsRegistryAutostart,
    build_autostart_command,
)
from gestor_luces.adapters.tray import winforms_host, winforms_paint
from gestor_luces.adapters.tray import winforms_icon as winforms_icon_module
from gestor_luces.adapters.tray.winforms_icon import IconCache, _build_icon_image


class _FakeHandle:
    def __init__(self, value: int) -> None:
        self._value = value

    def ToInt64(self) -> int:
        return self._value


class _FakeNativeForm:
    def __init__(self, hwnd: int) -> None:
        self.Handle = _FakeHandle(hwnd)


class _CallableWithSig:
    def __init__(self, impl: Any) -> None:
        self._impl = impl
        self.argtypes: list[Any] | None = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self._impl(*args)


def test_apply_window_icon_unwraps_native_configures_64bit_and_caches_handles(
    tmp_path: Path,
) -> None:
    """apply_window_icon unwraps .native, sets 64-bit signatures, and caches/destroys HICONs."""
    icon1 = tmp_path / "one.ico"
    icon2 = tmp_path / "two.ico"
    icon1.write_bytes(b"\x00\x00\x01\x00")
    icon2.write_bytes(b"\x00\x00\x01\x00")

    loaded: list[tuple[str, int, int]] = []
    messages: list[tuple[int, int, int, int]] = []
    destroyed: list[int] = []
    next_handle = {"v": 0x1_0000_0400}

    def _load(_inst: Any, path: str, _kind: int, cx: int, cy: int, _flags: int) -> int:
        loaded.append((path, cx, cy))
        next_handle["v"] += 1
        return next_handle["v"]

    def _send(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        messages.append((int(hwnd), int(msg), int(wparam), int(lparam)))
        return 0

    def _destroy(handle: int) -> int:
        destroyed.append(int(handle))
        return 1

    user32 = types.SimpleNamespace(
        GetSystemMetrics=_CallableWithSig(lambda idx: 32 if idx in (11, 12) else 16),
        LoadImageW=_CallableWithSig(_load),
        SendMessageW=_CallableWithSig(_send),
        DestroyIcon=_CallableWithSig(_destroy),
    )

    hwnd_64 = 0x1_0000_1234
    wrapped = types.SimpleNamespace(native=_FakeNativeForm(hwnd_64))

    assert window_chrome.apply_window_icon(wrapped, icon1, platform="win32", user32=user32) is True
    assert len(loaded) == 2
    assert messages == [
        (hwnd_64, window_chrome.WM_SETICON, window_chrome.WIN_ICON_BIG, 0x1_0000_0401),
        (hwnd_64, window_chrome.WM_SETICON, window_chrome.WIN_ICON_SMALL, 0x1_0000_0402),
    ]
    assert destroyed == []
    assert user32.LoadImageW.restype is wintypes.HANDLE
    assert user32.SendMessageW.restype is ctypes.c_ssize_t
    assert user32.DestroyIcon.argtypes == [wintypes.HICON]
    assert user32.DestroyIcon.restype is wintypes.BOOL

    # Same icon reuses cached handles without calling LoadImageW again.
    assert window_chrome.apply_window_icon(wrapped, icon1, platform="win32", user32=user32) is True
    assert len(loaded) == 2
    assert destroyed == []

    # Switching icon loads new handles and destroys the prior two.
    assert window_chrome.apply_window_icon(wrapped, icon2, platform="win32", user32=user32) is True
    assert len(loaded) == 4
    assert destroyed == [0x1_0000_0401, 0x1_0000_0402]

    window_chrome.release_window_icons(wrapped, platform="win32", user32=user32)
    assert destroyed == [0x1_0000_0401, 0x1_0000_0402, 0x1_0000_0403, 0x1_0000_0404]


def test_apply_app_user_model_id_configures_ctypes_signature() -> None:
    """SetCurrentProcessExplicitAppUserModelID receives explicit LPCWSTR/c_long signature."""
    seen: list[str] = []
    setter = _CallableWithSig(lambda app_id: seen.append(app_id) or 0)
    shell32 = types.SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=setter)

    assert (
        window_chrome.apply_app_user_model_id(
            "AlexisAcevedo.WizConsole",
            platform="win32",
            shell32=shell32,
        )
        is True
    )
    assert setter.argtypes == [wintypes.LPCWSTR]
    assert setter.restype is ctypes.c_long
    assert seen == ["AlexisAcevedo.WizConsole"]


def test_winforms_icon_destroy_handle_64bit_signature_and_error_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DestroyIcon uses 64-bit HICON signature, cleans up on Icon.FromHandle error, and
    survives Dispose() failures."""
    destroyed_calls: list[int] = []
    destroy_fn = _CallableWithSig(lambda h: destroyed_calls.append(int(h)) or 1)
    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(user32=types.SimpleNamespace(DestroyIcon=destroy_fn)),
        ArgumentError=ctypes.ArgumentError,
    )
    monkeypatch.setattr(winforms_icon_module, "ctypes", fake_ctypes)

    winforms_icon_module._destroy_icon_handle(0)
    assert destroyed_calls == []

    winforms_icon_module._destroy_icon_handle(0x1_0000_5678)
    assert destroy_fn.argtypes == [wintypes.HICON]
    assert destroy_fn.restype is wintypes.BOOL
    assert destroyed_calls == [0x1_0000_5678]

    # _build_icon_image destroys the HICON if Icon.FromHandle fails.
    class _FakeBitmap:
        def __init__(self, _src: Any) -> None:
            self.disposed = False

        def GetHicon(self) -> _FakeHandle:
            return _FakeHandle(0x1_0000_9999)

        def Dispose(self) -> None:
            self.disposed = True

    class _FakeDisposable:
        def Dispose(self) -> None:
            return None

    class _FailingIcon:
        @staticmethod
        def FromHandle(_h: Any) -> Any:
            raise ValueError("FromHandle failed")

    fake_api = types.SimpleNamespace(
        memory_stream=lambda _b: _FakeDisposable(),
        drawing=types.SimpleNamespace(
            Image=types.SimpleNamespace(FromStream=lambda _s: _FakeDisposable()),
            Bitmap=_FakeBitmap,
            Icon=_FailingIcon,
        ),
    )
    leaked_cleanup: list[int] = []
    with pytest.raises(ValueError, match="FromHandle failed"):
        _build_icon_image((10, 20, 30), fake_api, destroy_icon=leaked_cleanup.append)
    assert leaked_cleanup == [0x1_0000_9999]

    # IconCache.icon_for still calls destroy_icon when previous.Dispose() raises a CLR error.
    class _ExplodingPreviousIcon:
        def Dispose(self) -> None:
            raise AttributeError("already disposed")

    cache_destroyed: list[int] = []
    cache = IconCache(fake_api, destroy_icon=cache_destroyed.append)
    cache._icon = _ExplodingPreviousIcon()
    cache._handle = 0x1_0000_7777
    cache._rgb = (1, 2, 3)

    monkeypatch.setattr(
        winforms_icon_module,
        "_build_icon_image",
        lambda _rgb, _api, **_kw: ("new-icon", 0x1_0000_8888),
    )
    assert cache.icon_for((4, 5, 6)) == "new-icon"
    assert cache_destroyed == [0x1_0000_7777]


def test_invoke_on_ui_thread_skips_when_handle_missing_or_disposed() -> None:
    """invoke_on_ui_thread never calls action or Invoke without a created non-disposed handle."""
    called: list[str] = []
    invoked: list[Any] = []
    fake_api = types.SimpleNamespace(action=lambda fn: fn)

    no_handle = types.SimpleNamespace(
        IsHandleCreated=False,
        InvokeRequired=True,
        IsDisposed=False,
        Invoke=lambda fn: invoked.append(fn),
    )
    winforms_host.invoke_on_ui_thread(fake_api, no_handle, lambda: called.append("ran"))
    assert called == []
    assert invoked == []

    disposed = types.SimpleNamespace(
        IsHandleCreated=True,
        InvokeRequired=False,
        IsDisposed=True,
        Invoke=lambda fn: invoked.append(fn),
    )
    winforms_host.invoke_on_ui_thread(fake_api, disposed, lambda: called.append("ran"))
    assert called == []
    assert invoked == []

    ready_inline = types.SimpleNamespace(
        IsHandleCreated=True,
        InvokeRequired=False,
        IsDisposed=False,
        Invoke=lambda fn: invoked.append(fn),
    )
    winforms_host.invoke_on_ui_thread(fake_api, ready_inline, lambda: called.append("inline"))
    assert called == ["inline"]

    ready_marshal = types.SimpleNamespace(
        IsHandleCreated=True,
        InvokeRequired=True,
        IsDisposed=False,
        Invoke=lambda fn: invoked.append(fn),
    )
    winforms_host.invoke_on_ui_thread(fake_api, ready_marshal, lambda: called.append("marshalled"))
    assert len(invoked) == 1


def test_apply_menu_region_disposes_prior_region_and_cleans_up_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_menu_region disposes replaced Region objects and cleans up new Region on error."""
    paths_created: list[Any] = []

    class _FakeGraphicsPath:
        def __init__(self) -> None:
            self.disposed = False
            paths_created.append(self)

        def AddArc(self, *_args: Any) -> None:
            return None

        def CloseFigure(self) -> None:
            return None

        def Dispose(self) -> None:
            self.disposed = True

    class _FakeRegion:
        def __init__(self, _path: Any = None) -> None:
            self.disposed = False

        def Dispose(self) -> None:
            self.disposed = True

    drawing2d_mod = types.ModuleType("System.Drawing.Drawing2D")
    drawing2d_mod.GraphicsPath = _FakeGraphicsPath  # type: ignore[attr-defined]
    drawing_mod = types.ModuleType("System.Drawing")
    drawing_mod.Drawing2D = drawing2d_mod  # type: ignore[attr-defined]
    sys_mod = types.ModuleType("System")
    sys_mod.Drawing = drawing_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "System", sys_mod)
    monkeypatch.setitem(sys.modules, "System.Drawing", drawing_mod)
    monkeypatch.setitem(sys.modules, "System.Drawing.Drawing2D", drawing2d_mod)

    fake_api = types.SimpleNamespace(drawing=types.SimpleNamespace(Region=_FakeRegion))

    prior = _FakeRegion()
    control = types.SimpleNamespace(
        Size=types.SimpleNamespace(Width=160, Height=120),
        DeviceDpi=96,
        Region=prior,
    )
    assert winforms_paint.apply_menu_region(control, fake_api) is True
    assert isinstance(control.Region, _FakeRegion)
    assert control.Region is not prior
    assert prior.disposed is True
    assert control.Region.disposed is False
    assert paths_created[-1].disposed is True

    # Failure when assigning Region disposes the newly created Region and preserves prior.
    kept_prior = _FakeRegion()
    created_on_fail: list[_FakeRegion] = []

    def _failing_region_ctor(path: Any) -> _FakeRegion:
        reg = _FakeRegion(path)
        created_on_fail.append(reg)
        return reg

    fail_api = types.SimpleNamespace(drawing=types.SimpleNamespace(Region=_failing_region_ctor))

    class _ReadOnlyRegionControl:
        Size = types.SimpleNamespace(Width=160, Height=120)
        DeviceDpi = 96

        @property
        def Region(self) -> _FakeRegion:  # noqa: N802
            return kept_prior

        @Region.setter
        def Region(self, _value: Any) -> None:  # noqa: N802
            raise AttributeError("cannot assign Region")

    assert winforms_paint.apply_menu_region(_ReadOnlyRegionControl(), fail_api) is False
    assert kept_prior.disposed is False
    assert len(created_on_fail) == 1
    assert created_on_fail[0].disposed is True


def test_single_instance_guard_access_denied_close_handle_and_wait_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SingleInstanceGuard handles ERROR_ACCESS_DENIED, closes handles, and stops on WAIT_FAILED."""
    monkeypatch.setattr(sys, "platform", "win32")

    closed_handles: list[int] = []
    set_events: list[int] = []
    wait_calls: list[int] = []
    state = {"mutex_ret": 0x1001, "event_ret": 0x2002, "last_error": 0, "wait_ret": 0xFFFFFFFF}

    create_mutex_fn = _CallableWithSig(lambda *_a: state["mutex_ret"])
    create_event_fn = _CallableWithSig(lambda *_a: state["event_ret"])
    local_free_fn = _CallableWithSig(lambda *_a: 0)
    set_event_fn = _CallableWithSig(lambda h: set_events.append(int(h.value or 0)) or 1)
    close_handle_fn = _CallableWithSig(lambda h: closed_handles.append(int(h.value or 0)) or 1)
    wait_fn = _CallableWithSig(
        lambda h, _ms: wait_calls.append(int(h.value or 0)) or state["wait_ret"]
    )

    kernel32 = types.SimpleNamespace(
        CreateMutexW=create_mutex_fn,
        CreateEventW=create_event_fn,
        LocalFree=local_free_fn,
        SetEvent=set_event_fn,
        CloseHandle=close_handle_fn,
        WaitForSingleObject=wait_fn,
    )
    advapi32 = types.SimpleNamespace(
        ConvertStringSecurityDescriptorToSecurityDescriptorW=_CallableWithSig(lambda *_a: 0)
    )

    fake_ctypes = types.SimpleNamespace(
        Structure=ctypes.Structure,
        c_uint32=ctypes.c_uint32,
        c_int=ctypes.c_int,
        c_void_p=ctypes.c_void_p,
        c_wchar_p=ctypes.c_wchar_p,
        POINTER=ctypes.POINTER,
        byref=ctypes.byref,
        sizeof=ctypes.sizeof,
        WinDLL=lambda name, **_kw: kernel32 if name == "kernel32" else advapi32,
        windll=types.SimpleNamespace(kernel32=kernel32),
        get_last_error=lambda: state["last_error"],
    )
    monkeypatch.setattr(single_instance_module, "ctypes", fake_ctypes)

    # 1. ERROR_ACCESS_DENIED marks instance non-primary and closes nothing if handle is 0.
    state["mutex_ret"] = None
    state["event_ret"] = None
    state["last_error"] = 5
    denied = SingleInstanceGuard(mutex_name="M1", event_name="E1")
    assert denied.acquire() is False
    assert denied.is_primary is False

    # 2. Primary acquires handles, signals event, WaitForSingleObject exits on WAIT_FAILED,
    #    and release() closes both handles once.
    state["mutex_ret"] = 0x1001
    state["event_ret"] = 0x2002
    state["last_error"] = 0
    state["wait_ret"] = 0xFFFFFFFF

    primary = SingleInstanceGuard(mutex_name="M2", event_name="E2")
    assert primary.acquire() is True
    primary.signal_existing_instance()
    assert set_events == [0x2002]
    assert set_event_fn.argtypes == [ctypes.c_void_p]
    assert set_event_fn.restype is ctypes.c_int

    callbacks: list[str] = []
    primary.listen(lambda: callbacks.append("show"))
    # Wait for listener thread to exit on WAIT_FAILED.
    thread = getattr(primary, "_listener_thread", None)
    assert thread is not None
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert wait_fn.restype is ctypes.c_uint32
    assert len(wait_calls) == 1
    assert callbacks == []

    primary.release()
    assert closed_handles == [0x2002, 0x1001]
    assert close_handle_fn.argtypes == [ctypes.c_void_p]
    assert close_handle_fn.restype is ctypes.c_int

    # Idempotent second release does not double-close handles.
    primary.release()
    assert closed_handles == [0x2002, 0x1001]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex test")
def test_single_instance_guard_real_release_frees_os_mutex() -> None:
    """Releasing a SingleInstanceGuard closes its OS handle so a new guard acquires primary."""
    suffix = uuid.uuid4().hex
    mutex = f"Local\\WizConsole.Test.{suffix}"
    event = f"Local\\WizConsole.Test.Show.{suffix}"
    first = SingleInstanceGuard(mutex_name=mutex, event_name=event)
    second = SingleInstanceGuard(mutex_name=mutex, event_name=event)
    try:
        assert first.acquire() is True
        first.release()
        assert second.acquire() is True
    finally:
        first.release()
        second.release()


def test_windows_autostart_hardening() -> None:
    """Autostart validates paths, value names, REG_SZ types, commands, and OSError on read."""

    class _TypedFakeRegistry:
        HKEY_CURRENT_USER = "HKCU"
        KEY_READ = 1
        KEY_SET_VALUE = 2
        REG_SZ = 1
        REG_DWORD = 4

        def __init__(self) -> None:
            self.values: dict[tuple[str, str], tuple[Any, int]] = {}
            self.fail_open_on_read = False

        class _Key:
            def __init__(self, path: str) -> None:
                self.path = path

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_a: Any) -> None:
                return None

        def OpenKey(self, _root: str, path: str, _res: int, access: int) -> Any:  # noqa: N802
            if self.fail_open_on_read and access == self.KEY_READ:
                raise PermissionError("access denied")
            return self._Key(path)

        CreateKeyEx = OpenKey  # noqa: N815

        def QueryValueEx(self, key: Any, name: str) -> tuple[Any, int]:  # noqa: N802
            if (key.path, name) not in self.values:
                raise FileNotFoundError(name)
            return self.values[(key.path, name)]

        def SetValueEx(  # noqa: N802
            self, key: Any, name: str, _res: int, kind: int, value: str
        ) -> None:
            self.values[(key.path, name)] = (value, kind)

        def DeleteValue(self, key: Any, name: str) -> None:  # noqa: N802
            if (key.path, name) not in self.values:
                raise FileNotFoundError(name)
            del self.values[(key.path, name)]

    for bad_exe in ("", "   ", 'C:\\bad"app.exe', "C:\\bad\napp.exe", "C:\\bad\x00app.exe"):
        with pytest.raises(ValueError):
            build_autostart_command(frozen=True, executable=bad_exe)

    reg = _TypedFakeRegistry()
    for bad_name in ("", "   ", "bad\\name", "bad\nname", "bad\x00name"):
        with pytest.raises(ValueError):
            WindowsRegistryAutostart(registry=reg, value_name=bad_name)

    # Non-REG_SZ value is ignored safely.
    reg.values[(RUN_KEY_PATH, DEFAULT_VALUE_NAME)] = (123, reg.REG_DWORD)
    autostart = WindowsRegistryAutostart(
        registry=reg, command_factory=lambda: '"app.exe" --minimized'
    )
    assert autostart.registered_command() is None
    assert autostart.is_enabled() is False

    # Control characters in command_factory are rejected without writing to registry.
    bad_autostart = WindowsRegistryAutostart(
        registry=reg, command_factory=lambda: "cmd\n--minimized"
    )
    with pytest.raises(ValueError):
        bad_autostart.enable()
    assert reg.values[(RUN_KEY_PATH, DEFAULT_VALUE_NAME)] == (123, reg.REG_DWORD)

    # OSError during refresh_if_stale read returns False gracefully.
    reg.fail_open_on_read = True
    assert autostart.refresh_if_stale() is False
