"""Issue #14011 — items created by another process get selected.

    https://github.com/files-community/Files/issues/14011

Open since 2023, reported by a maintainer and labelled `help wanted`. A file
appearing in the current folder from outside Files is selected automatically,
which the reporter hit as a Minecraft server failing to save its world because
`level.dat` was in use.

**This does not propose a second test framework.** Files already has
Appium-based interaction tests in `tests/Files.InteractionTests`. This is a
standalone reproduction that happens to be written with `wintegrate`; the
measurement is the point and porting it to the existing harness is
straightforward.

Run it with::

    pip install wintegrate pytest
    pytest tests/ui-repro -v -rxX -s

Measured on **4.2.9.0**, Windows 11 26100 ARM64:

    step                                   existing_a  existing_b  external_new
    navigated to the folder                     False       False   -
    clicked existing_a.txt                      True        False   -
    another process created external_new.txt    False       False   True

Two things happen at once, and the first is the one a user notices: **the
selection they were holding is taken away**, and the new file is selected in its
place.

The reporter's steps involve downloading and running a Minecraft server. They
are not needed — any second process creating a file in the folder does it, and
this test is that second process.

`yair100` (maintainer) diagnosed the cause on the issue:

> This can be done by moving `HandleChangesOccurredAsync` out of the file
> watcher and only calling it when using an internal action (eg rename, paste,
> delete etc).

which is why the assertions below are about *externally* created items only.
Selecting an item the user just created **from inside Files** is wanted
behaviour and is not asserted against here.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("wintegrate", reason="pip install wintegrate")

from wintegrate import Window, interop  # noqa: E402
from wintegrate.apps import (  # noqa: E402
    find_packaged_app,
    launch_packaged_app,
    sweep_processes_verified,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="drives the packaged app through UI Automation"
)

PACKAGE = "Files"
PROCESS = "Files.exe"
WINDOW_CLASS = "WinUIDesktopWin32WindowClass"
ADDRESS_BAR_ID = "PART_TextBox"
CONTROL_TYPE_LIST_ITEM = 50007
CONTROL_TYPE_BUTTON = 50000
# WinUI's ContentDialog names its buttons this way, and only these two.
# `CloseButton` was in this list once: it is also the id of the *tab* close
# button on Files' own title bar, so the dismissal closed the tab, the address
# bar went with it, and the failure read as "PART_TextBox does not exist" three
# runs in a row. An id that is not scoped to a dialog is not a dialog id.
DIALOG_DISMISS_IDS = ("SecondaryButton", "PrimaryButton")

EXISTING_A = "existing_a.txt"
EXISTING_B = "existing_b.txt"
EXTERNAL = "external_new.txt"

# Files takes a while to come up cold, and the file watcher is asynchronous.
SETTLE_AFTER_LAUNCH = float(os.environ.get("FILES_SETTLE", "8"))
WATCHER_TIMEOUT = float(os.environ.get("FILES_WATCHER_TIMEOUT", "10"))

# Constants.LocalSettings.SettingsFolderName / UserSettingsFileName. An earlier
# version of this wrote LocalState/settings.json, which Files never reads — so
# none of these applied and the "Files is running as administrator" dialog sat
# over the file list for the whole recording.
SETTINGS_RELATIVE_PATH = ("settings", "user_settings.json")

DETERMINISTIC_STARTUP = {
    "ContinueLastSessionOnStartUp": False,
    "RestoreTabsOnStartup": False,
    "OpenSpecificPageOnStartup": False,
    # A hosted runner's session is elevated, so Files shows this every launch.
    "ShowRunningAsAdminPrompt": False,
}


def settled_selection(window: Window, wanted: set[str], timeout: float = 20.0) -> dict[str, bool]:
    """Reads the selection until every expected row has been seen once."""
    deadline = time.monotonic() + timeout
    state: dict[str, bool] = {}
    while time.monotonic() < deadline:
        state = _selection(window)
        if wanted <= set(state):
            return state
        time.sleep(1.0)
    return state


def _dismiss_any_content_dialog(window: Window, timeout: float = 8.0) -> None:
    """Closes a startup ContentDialog if one is up, and says which.

    `invoke()`, not `click()`: a physical click aims at the middle of the
    element's bounding rectangle and silently does nothing when there isn't one.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            root = window.re_resolve_element()
            buttons = root.find_all(control_type_id=CONTROL_TYPE_BUTTON)
        except Exception:  # noqa: BLE001 - the tree is still settling
            time.sleep(0.5)
            continue
        for button in buttons:
            if (button.automation_id or "") not in DIALOG_DISMISS_IDS:
                continue
            print(f"dismissing a startup dialog via {button.automation_id!r} ({button.name!r})")
            try:
                button.invoke()
            except Exception as exc:  # noqa: BLE001
                print(f"  invoke failed: {type(exc).__name__}: {exc}")
            time.sleep(1.5)
            return
        time.sleep(0.5)
    print("no startup dialog to dismiss")


def _selection(window: Window) -> dict[str, bool]:
    """Which of our files the list reports as selected, right now.

    Keyed on the leading file name because the item's accessible name carries
    trailing metadata — `'existing_a.txt, 資料夾'` on this machine — which is
    localised and not worth matching on.
    """
    state: dict[str, bool] = {}
    for element in window.re_resolve_element().find_all(control_type_id=CONTROL_TYPE_LIST_ITEM):
        # Both reads are guarded, not just the second one. The list re-renders
        # while this walks it, and a stale element raises on *any* property —
        # `.name` included, which is where it actually blew up on a runner
        # (COMError: an event was unable to invoke any of the subscribers).
        try:
            name = element.name or ""
            if not name:
                continue
            for wanted in (EXISTING_A, EXISTING_B, EXTERNAL):
                if name.startswith(wanted):
                    state[wanted] = bool(element.is_selected)
        except Exception:  # noqa: BLE001 - a stale item is not a selection
            continue
    return state


@pytest.fixture(scope="module")
def observed(recording) -> dict[str, dict[str, bool]]:
    """Selection state before and after another process creates a file."""
    folder = Path.home() / f"issue14011-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    (folder / EXISTING_A).write_text("a", encoding="utf-8")
    (folder / EXISTING_B).write_text("b", encoding="utf-8")

    aumid = find_packaged_app(PACKAGE)
    if aumid is None:
        pytest.skip(f"{PACKAGE} is not installed")
    settings = Path(os.environ["LOCALAPPDATA"]).joinpath(
        "Packages", aumid.split("!")[0], "LocalState", *SETTINGS_RELATIVE_PATH
    )
    original = settings.read_text(encoding="utf-8") if settings.exists() else None
    config = json.loads(original) if original else {}
    config.update(DETERMINISTIC_STARTUP)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(config, indent=2), encoding="utf-8")

    sweep_processes_verified((PROCESS,), ("Files",))
    process, window = Window.launch_and_discover(
        launch_packaged_app(aumid),
        timeout=180.0,
        process_names=(PROCESS,),
        window_classes=(WINDOW_CLASS,),
        require_all=True,
    )
    try:
        # Maximised before recording starts, so the file list fills the frame
        # and the selection highlight is legible.
        with window.foreground(verify=False):
            assert window.focus_content_island(timeout=20.0), (
                "keyboard focus never reached the XAML island, so nothing typed below "
                "would have gone to the address bar"
            )
            time.sleep(SETTLE_AFTER_LAUNCH)

            # Belt and braces on the admin dialog. The setting written above
            # should stop it appearing, but a dialog covering the file list
            # makes the recording worthless, so one is dismissed if present.
            _dismiss_any_content_dialog(window)

            # Window.maximize() verifies with IsZoomed and reports back: a
            # window can decline, and one whose default rectangle already
            # exceeds the screen looks maximised without being maximised.
            if not window.maximize():
                print("the window declined to maximise; the recording will be small")

            # Wait for the address bar to resolve *after* the resize, rather
            # than sleeping a fixed amount and hoping. A WinUI 3 content island
            # does re-lay-out to follow its window, but not instantly; a fixed
            # pause ends mid-layout on a slow machine, with the frame already
            # full-screen and part of the visual tree not yet realised. That
            # reads as "PART_TextBox does not exist" when it means "ask again in
            # a moment" — and it cost two runs and a wrong conclusion about
            # content islands before it was waited on properly.
            address = window.re_resolve_element().find_descendant(
                automation_id=ADDRESS_BAR_ID, timeout=45.0
            )

            # Only now is there something worth filming.
            recording.begin()
            address.set_focus()
            time.sleep(0.5)
            interop.send_keys("^a")
            interop.send_keys(str(folder))
            time.sleep(0.8)
            interop.send_keys("{ENTER}")
            time.sleep(5.0)

            # Retried rather than read once: the listing is still settling and
            # a single pass can catch every item mid-refresh.
            after_navigation = settled_selection(window, {EXISTING_A, EXISTING_B})
            assert set(after_navigation) >= {EXISTING_A, EXISTING_B}, (
                f"the folder listing never showed the starting files; saw "
                f"{after_navigation!r}"
            )

            # `select_verified()` rather than `click()`. A physical click aims
            # at the middle of the element's bounding rectangle and silently
            # does nothing when there isn't one — which is what happened on the
            # hosted runners, where the smaller desktop leaves list items
            # unlaid-out: the control below caught it as "clicking did not
            # select", which is exactly what it is for.
            selected = False
            for element in window.re_resolve_element().find_all(
                control_type_id=CONTROL_TYPE_LIST_ITEM
            ):
                if (element.name or "").startswith(EXISTING_A):
                    selected = element.select_verified(timeout=5.0)
                    break
            assert selected, (
                f"could not select {EXISTING_A} through the SelectionItem pattern; "
                "the assertions below would be measuring an empty selection"
            )
            time.sleep(1.5)
            after_click = _selection(window)

            # This process is the "other process". Nothing about the reporter's
            # Minecraft server is needed — only that the writer is not Files.
            (folder / EXTERNAL).write_text("x", encoding="utf-8")

            deadline = time.monotonic() + WATCHER_TIMEOUT
            after_external = after_click
            while time.monotonic() < deadline:
                time.sleep(1.0)
                after_external = _selection(window)
                if EXTERNAL in after_external:
                    break

        results = {
            "after_navigation": after_navigation,
            "after_click": after_click,
            "after_external_create": after_external,
        }
        print("\n  step                      " + "  ".join(f"{n:<16}" for n in
              (EXISTING_A, EXISTING_B, EXTERNAL)))
        for label, state in results.items():
            cells = "  ".join(f"{str(state.get(n, '-')):<16}" for n in
                              (EXISTING_A, EXISTING_B, EXTERNAL))
            print(f"  {label:<24}  {cells}")
        return results
    finally:
        process.terminate()
        sweep_processes_verified((PROCESS,), ("Files",))
        if original is not None:
            settings.write_text(original, encoding="utf-8")
        else:
            settings.unlink(missing_ok=True)
        shutil.rmtree(folder, ignore_errors=True)


def test_clicking_an_item_selects_it(observed):
    """Control: selection is readable, and is not simply True for everything."""
    after_click = observed["after_click"]
    assert after_click.get(EXISTING_A) is True, (
        f"clicking {EXISTING_A} did not select it ({after_click!r}); the assertions "
        "below would be measuring nothing"
    )
    assert after_click.get(EXISTING_B) is False, (
        f"{EXISTING_B} reports as selected without being clicked ({after_click!r})"
    )


def test_the_external_file_appears_in_the_listing(observed):
    """Control: the watcher noticed the file at all.

    Without this, "the new item is not selected" would also pass on a build that
    simply never showed it.
    """
    assert EXTERNAL in observed["after_external_create"], (
        f"{EXTERNAL} never appeared in the listing within {WATCHER_TIMEOUT}s"
    )


@pytest.mark.xfail(
    strict=True,
    reason="issue #14011 is open: an externally created item takes the selection",
)
def test_the_users_selection_survives_an_external_file_creation(observed):
    """Reproduces #14011, from the side a user notices."""
    after = observed["after_external_create"]
    assert after.get(EXISTING_A) is True, (
        f"{EXISTING_A} was selected before another process created {EXTERNAL}, and is "
        f"not selected afterwards ({after!r}). A file operation by an unrelated program "
        "moved the user's selection."
    )


@pytest.mark.xfail(
    strict=True,
    reason="issue #14011 is open: an externally created item takes the selection",
)
def test_an_externally_created_item_is_not_selected(observed):
    """Reproduces #14011, from the side the issue describes."""
    after = observed["after_external_create"]
    assert after.get(EXTERNAL) is False, (
        f"{EXTERNAL} was created by another process and Files selected it ({after!r}). "
        "Selecting an item the user created from inside Files is wanted; selecting one "
        "that appeared from outside is what this issue is about."
    )
