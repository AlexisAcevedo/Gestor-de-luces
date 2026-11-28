"""Tests for delta status polling endpoints on WebviewBridge / BridgeHandlers."""

from __future__ import annotations

import threading

from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.ui_webview.lifecycle import ASYNC_LOOP_THREAD_NAME
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService


def test_delta_status_polls_return_only_target_section_on_async_loop() -> None:
    """`get_ambilight_status` and `get_music_sync_status` return delta envelopes on loop thread."""
    observed_threads: list[str] = []

    class TrackingService(LightControlService):
        def get_ambilight_status(self) -> dict[str, object]:
            observed_threads.append(threading.current_thread().name)
            return super().get_ambilight_status()

        def get_music_sync_status(self) -> dict[str, object]:
            observed_threads.append(threading.current_thread().name)
            return super().get_music_sync_status()

    service = TrackingService(controller=WizUdpController(probe_candidates=[]))
    bridge = WebviewBridge(service=service)
    try:
        ambi = bridge.get_ambilight_status()
        assert ambi["ok"] is True
        assert ambi["error"] is None
        assert "ambilight" in ambi
        assert set(ambi.keys()) == {"ok", "ambilight", "error"}

        music = bridge.get_music_sync_status()
        assert music["ok"] is True
        assert music["error"] is None
        assert "music_sync" in music
        assert set(music.keys()) == {"ok", "music_sync", "error"}

        assert observed_threads == [ASYNC_LOOP_THREAD_NAME, ASYNC_LOOP_THREAD_NAME]
    finally:
        bridge.shutdown()


def test_poll_section_catches_expected_service_errors() -> None:
    """`_poll_section` converts service boundary errors into `{ok: False, error}`."""

    class FailingService(LightControlService):
        def get_ambilight_status(self) -> dict[str, object]:
            raise RuntimeError("sampler unavailable")

        def get_music_sync_status(self) -> dict[str, object]:
            raise ValueError("invalid audio device")

    service = FailingService(controller=WizUdpController(probe_candidates=[]))
    bridge = WebviewBridge(service=service)
    try:
        ambi = bridge.get_ambilight_status()
        assert ambi == {"ok": False, "error": "sampler unavailable"}

        music = bridge.get_music_sync_status()
        assert music == {"ok": False, "error": "invalid audio device"}
    finally:
        bridge.shutdown()
