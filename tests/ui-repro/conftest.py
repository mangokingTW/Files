"""Recording support for the reproductions.

A reproduction a maintainer has to take on trust is worth much less than one
they can watch. The video is not the evidence — the assertions are — but it
answers a different question: *does this look like the bug I was told about?*

Maximising lives in the library now (`Window.maximize()`, which verifies with
`IsZoomed` and reports back), so this file only owns the recorder.

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

import os
import platform
from pathlib import Path

import pytest

RECORDING_FPS = 10
OUTPUT_DIR = Path("recording-artifacts")

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
