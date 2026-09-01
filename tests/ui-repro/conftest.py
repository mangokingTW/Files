"""Recording support for the reproductions.

A reproduction a maintainer has to take on trust is worth much less than one
they can watch. The video is not the evidence — the assertions are — but it
answers a different question: *does this look like the bug I was told about?*

**The recorder is started by the test, not at session start.** An autouse
session fixture begins recording before anything exists, so the first two thirds
of the file are the runner's own console and an application still launching.
Here the app fixture calls `recording.begin()` once its window is up and
maximised, which is the first frame worth keeping.

Off unless `WINTEGRATE_RECORD=1`, because it costs a capture thread. Needs the
video extra::

    pip install "wintegrate[video]"
"""

from __future__ import annotations

import ctypes
import os
import platform
from ctypes import wintypes
from pathlib import Path

import pytest

RECORDING_FPS = 10
OUTPUT_DIR = Path("recording-artifacts")
SW_MAXIMIZE = 3


def maximize(hwnd: int) -> None:
    """Fills the screen before recording starts, so the video is legible.

    A default-sized window on a 1024x768 runner leaves the interesting columns
    off screen or too small to read, which is most of what makes a recording
    useless to the person it was made for.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow(hwnd, SW_MAXIMIZE)


class _Recording:
    """Starts on request; stops once, at the end of the session."""

    def __init__(self) -> None:
        self._recorder = None

    def begin(self) -> None:
        if self._recorder is not None:
            return
        if os.environ.get("WINTEGRATE_RECORD") != "1" or os.name != "nt":
            return
        try:
            from wintegrate import ContinuousRecorder
        except ImportError:
            # Missing the video extra must not fail a run that is about
            # something else entirely.
            print("recording requested but wintegrate[video] is not installed")
            return

        arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = OUTPUT_DIR / f"reproduction-{arch}.mp4"
        recorder = ContinuousRecorder(output, fps=RECORDING_FPS)
        try:
            if not recorder.start():
                return
        except Exception as exc:  # noqa: BLE001 - a recorder must not break the run
            print(f"recording failed to start ({type(exc).__name__}: {exc})")
            return
        self._recorder = recorder
        self._output = output
        print(f"recording -> {output}")

    def stop(self) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder.stop()
            size = self._output.stat().st_size if self._output.exists() else 0
            print(f"recording saved: {self._output} ({size / 1024:.0f} KB)")
        except Exception as exc:  # noqa: BLE001
            print(f"recording failed to stop cleanly ({type(exc).__name__}: {exc})")
        finally:
            self._recorder = None


@pytest.fixture(scope="session")
def recording():
    controller = _Recording()
    yield controller
    controller.stop()
