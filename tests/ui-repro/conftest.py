"""Records the whole run to one video when `WINTEGRATE_RECORD=1`.

A reproduction that a maintainer has to take on trust is worth much less than
one they can watch. The video is not the evidence — the assertions are — but it
answers the question a table of booleans cannot: *does this look like the bug I
was told about?*

Off by default, because it costs a capture thread for the entire run. Needs the
video extra::

    pip install "wintegrate[video]"

The frame rate is deliberately low. This is evidence to scrub through, not
something anyone watches at full speed, and 10 fps keeps a short run inside a
couple of megabytes.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

RECORDING_FPS = 10
OUTPUT_DIR = Path("recording-artifacts")


@pytest.fixture(scope="session", autouse=True)
def recording():
    if os.environ.get("WINTEGRATE_RECORD") != "1" or os.name != "nt":
        yield
        return

    try:
        from wintegrate import ContinuousRecorder
    except ImportError:
        # Missing the video extra must not fail a run that is about something
        # else entirely.
        print("recording requested but wintegrate[video] is not installed; continuing")
        yield
        return

    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"reproduction-{arch}.mp4"
    recorder = ContinuousRecorder(output, fps=RECORDING_FPS)

    started = False
    try:
        started = recorder.start()
    except Exception as exc:  # noqa: BLE001 - a recorder must not break the run
        print(f"recording failed to start ({type(exc).__name__}: {exc}); continuing")

    if not started:
        yield
        return

    print(f"recording -> {output}")
    try:
        yield
    finally:
        try:
            recorder.stop()
            size = output.stat().st_size if output.exists() else 0
            print(f"recording saved: {output} ({size / 1024:.0f} KB)")
        except Exception as exc:  # noqa: BLE001
            print(f"recording failed to stop cleanly ({type(exc).__name__}: {exc})")
