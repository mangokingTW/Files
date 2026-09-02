# UI reproductions

Standalone reproductions of reported UI issues, driven against an **installed**
Files package through Windows UI Automation.

## This is not a proposal to add a second test framework

Files already has Appium-based interaction tests in
`tests/Files.InteractionTests`. These are written with
[`wintegrate`](https://github.com/mangokingTW/wintegrate) because that is what
they were developed in; **the measurement is the point**, and porting one to the
existing MSTest/Appium harness is a small job. They live outside
`tests/Files.InteractionTests` so nothing in the solution picks them up.

## Running

```bash
pip install "wintegrate>=0.5.1" pytest
pytest tests/ui-repro -v -rxX -s
```

The tests skip on non-Windows and skip if the `Files` package is not installed.

## Green means the issue still reproduces

Each file targets one **open** issue, so the reproduction is marked
`xfail(strict=True)`:

| result | means |
|---|---|
| **xfail** | the issue still reproduces on this build |
| **XPASS** (a failure, because `strict`) | the behaviour changed — fixed, or the build is different |
| **a control fails** | the harness did not measure what it claims to; ignore the rest |

Expected on 4.2.9.0:

```
test_clicking_an_item_selects_it                             PASSED  <- control
test_the_external_file_appears_in_the_listing                PASSED  <- control
test_the_users_selection_survives_an_external_file_creation  XFAIL   <- the issue
test_an_externally_created_item_is_not_selected              XFAIL   <- the issue
```

The observation prints on every run, because an xfail swallows the assertion
output:

```
  step                      existing_a.txt  existing_b.txt  external_new.txt
  after_navigation          False           False           -
  after_click               True            False           -
  after_external_create     False           False           True
```

## Current reproductions

| file | issue |
|---|---|
| `test_issue_14011_external_selection.py` | [#14011](https://github.com/files-community/Files/issues/14011) — items created by another process get selected |

## Three mistakes this harness made, and how they were found

Kept here because each one failed in a way that pointed somewhere else.

**Settings written to a file the app never reads.** The deterministic-startup
settings went to `LocalState/settings.json`; Files reads
`LocalState/settings/user_settings.json`
(`Constants.LocalSettings.SettingsFolderName` + `UserSettingsFileName`). Nothing
errored — the settings simply had no effect, and the only visible symptom was
the "Files is running as administrator" dialog sitting over the file list for
the whole recording.

**A dismissal that closed the tab.** The startup-dialog helper matched
`CloseButton`, which is also the id of the *tab* close button on Files' own
title bar. It closed the tab, the address bar went with it, and three runs
failed with `PART_TextBox does not exist`. **An id that is not scoped to a
dialog is not a dialog id.**

**Two changes at once, then guessing.** The settings path and a new maximise
call landed together, so when the address bar went missing there were two
suspects and I blamed a third — first WinUI content islands "not following a
resize", then `ShowWindow` versus `WM_SYSCOMMAND`, then a slow machine. A probe
that launched three ways — old settings, new settings, new settings plus
maximise — found `PART_TextBox` present in **all three**, which cleared both
changes in one run and left only the dismissal.

The run went from 132 seconds of timeouts to 29.6 seconds.
