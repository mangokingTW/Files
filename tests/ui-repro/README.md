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
pip install wintegrate pytest
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
