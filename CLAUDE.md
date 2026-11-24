# Paragon PR7-Z: notes for Claude

**Paragon PR7-Z** is the owner's personal archive manager: a Python (PySide6) app that **works the way
7-Zip File Manager works** and looks like the Paragon family (the PR7 plugins `ARYEZ/Paragon-PR7-*`,
Paragon Photo `ARYEZ/Paragon-Photo`). Windows 10/11 x64 is the target; it also runs on Linux for tests.
The owner writes Python; explain the why of changes.

## How it's built

- **No compression code of our own.** Every archive operation runs the official 7-Zip console engine:
  `engine/7z.exe` + `7z.dll` + `7z.sfx` (unmodified 7-Zip **26.01** x64, extracted from
  `7z2601-x64.exe` of https://github.com/ip7z/7zip/releases). `engine.find_7z()` uses the bundled one,
  then an installed 7-Zip, then PATH; `PR7Z_7Z` overrides (tests on Linux: a `7zz` binary).
  To update 7-Zip: download the new `7zNNNN-x64.exe` and the Linux tarball from that releases page,
  `7zz x 7zNNNN-x64.exe 7z.exe 7z.dll 7z.sfx License.txt readme.txt`, replace the files in `engine/`
  (License -> `7-Zip-License.txt`, readme -> `7-Zip-readme.txt`), run the tests, note it in NOTICE and CHANGELOG.
- `pr7z/engine.py` (no Qt): listing (`7z l -slt`, parsed by `parse_slt`), the command lines for every
  7-Zip GUI option (`add_args`, `extract_args`, ...), and `ProgressParser`, which reads 7z's stdout
  (progress redrawn with backspaces, `ERROR:` lines, and the **overwrite** and **password** prompts,
  recognised as soon as their question text arrives).
- `pr7z/jobs.py`: runs 7z in a `QProcess`; prompts go to callbacks (the UI's dialogs) and the answer is
  written to 7z's stdin, exactly as 7-Zip's own GUI does. Extract / test pass no `-p` when no password
  is known, so 7z asks. Listing (synchronous) passes a placeholder password so it fails instead of waiting.
- `pr7z/operations.py`: 7-Zip FM's actions as job steps. Extracting from inside an archive folder keeps
  paths relative to it (staging folder in the destination, then a move: same drive, instant); adding
  into an archive folder uses a hard-linked staging tree. Both settle clashes with the same question.
- `pr7z/models.py` (locations: drives, folder, inside an archive; `ArchiveTree` fills implied folders and
  totals folder sizes), `main_window.py` (the window; `EntryModel` is a plain Python list model: **don't
  go back to QStandardItemModel**, its item ownership crashed PySide on `clear()`), `dialogs.py`,
  `add_dialog.py`, `options.py`, `shell.py` (Explorer menu and Open with, HKCU only), `app.py` (CLI and
  the collector that merges the basic menu's one-process-per-file launches), `mail.py` (Compress and email).
- **The Explorer menu is `shellext/PR7ZShell.cpp`** (the one C++ part; a shell extension like 7-Zip's
  7-zip.dll, CLSID {ED2155D5-4754-4F17-A401-780852864C71}: never change it). Explorer loads it into its own
  process, so it stays small and does no file work: it builds the menu (names by the same rules as
  `default_extract_dir` / `default_archive_name`, keep them in step) and starts PR7-Z with an action
  (`--add-to`, `--extract-into` ...; `--files-from` for huge selections). Settings in
  `HKCU\Software\Paragon\PR7-Z\Shell` (Command, Icon, Cascaded, Items bit mask in `enum Item` order =
  `shell.MENU_ITEMS`). Build: `cmake -S shellext -B shellext/build -A x64 && cmake --build shellext/build
  --config Release` (CI does it); a syntax check here: `x86_64-w64-mingw32-g++ -std=c++17 -Wall -Wextra
  -shared ...`. Tests drive the real COM path through its `PR7Z_SelfTest` export (tests/test_shell_menu.py,
  Windows only) and split each command line with `CommandLineToArgvW`.
- **Installer: `installer/pr7z.iss`** (Inno Setup 6), per-user (`PrivilegesRequired=lowest`, into
  %LOCALAPPDATA%\Programs\PR7-Z); AppId {9914C6C8-01EC-476F-845D-98F814A0426E} is permanent (upgrades find
  the install by it). It registers through PR7-Z itself (`--register-menu`, `--register-open-with`;
  `--unregister` on uninstall), so installer, Options and CLI share `shell.py`. Wizard images:
  `tools/make_installer_art.py`. CI installs it silently and runs `tools/verify_install.py installed`, then
  uninstalls and runs `... uninstalled`.
- **The registered menu DLL is a copy** (`shell.deploy_dll`): %LOCALAPPDATA%\Paragon\PR7-Z\shellext\
  PR7ZShell-<sha256[:12]>.dll. Explorer locks the DLL it has loaded; registering a content-named copy
  means installs never overwrite a locked file or restart Explorer. Don't register the file in `_internal`.

- Updates: `pr7z/updates.py` (no Qt; GitHub's public releases/latest, User-Agent names only the app, installer asset `PR7-Z-Setup-*.exe`, run with /SILENT /relaunch=1) and `update_ui.py` (once-a-day check from app.py, the menu's Check for Updates, UpdateDialog; settings updates/auto|last|skip; `notify` for tests). The installer's [Code] Relaunch starts PR7-Z again only for /relaunch=1. Same files in every family app (PR7-W's update_ui imports PyQt6): keep them in step. `family.py`: the other family apps by their permanent AppIds (uninstall InstallLocation).

## The look (family rules)

- From Paragon Photo's `docs/paragon-finish-spec.md` (extracted from the PR7 plugins). OBSIDIAN is the
  only finish so far; AURORA (the light one) is the next to add (`theme.py` is where its values go).
- **Colours: the family's only**: hues ~318 deg -> 0 -> 42 deg (pink, red, orange), pearl white and onyx
  greys. No green, blue, purple, yellow or cyan anywhere, Qt's defaults included (`theme.palette()`
  sets every role). Accent fills are the family gradient (DE0639 -> CD6619 x 1.18); text never carries it.
- Inter only (`pr7z/fonts`), labels/headings/keys UPPER CASE, body sentence case.
- The PR7-Z mark uses the PR7 `Logo.cpp` letter geometry (widgets.py); the icon is drawn by
  `tools/make_icon.py` (don't edit `pr7z/icons/` by hand).
- Check visual changes with `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` and look at the PNGs.

## Rules

- Behaviour questions: do what 7-Zip File Manager does (its menus, shortcuts, dialogs, defaults).
- Tests: `python -m pytest` (offscreen Qt, the real engine). New features get tests that check what the
  feature really does to the files/archives, not just that it runs. Tests must never write the real
  settings (conftest points QSettings at a temp folder).
- CI (`.github/workflows/build.yml`, windows-latest): tests against the bundled 7z.exe, then the
  PyInstaller build (`pr7z.spec`, folder build so Explorer actions start fast) and a zip artifact;
  a `v*` tag publishes a release.
- Releases: bump `__version__` in `pr7z/__init__.py`, add a `## x.y.z` section to CHANGELOG.md.
