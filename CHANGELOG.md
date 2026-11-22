# Changelog

## 0.2.0

- Explorer right-click menu like 7-Zip's, as a shell extension (`PR7ZShell.dll`, `shellext/`): Open
  archive, Open archive > (*, #, #:e, 7z, zip, cab, rar, iso, tar, wim), Extract files..., Extract Here,
  Extract to "name\", Test archive, Add to archive..., Compress and email..., Add to "name.7z" /
  "name.zip", Compress to "name.7z" / "name.zip" and email, CRC SHA > (CRC-32 ... SHA-512, BLAKE2sp, *).
  Real file names in the items, 7-Zip's "_2" when a name is taken, extract/test items only on
  archives, every selected file in one launch (a list file for very large selections).
- Tools > Options: "Integrate PR7-Z to shell context menu", "Cascaded context menu" and a checkbox per
  menu item, as on 7-Zip's 7-Zip tab. The basic fixed-text menu remains when the DLL isn't present.
- Compress and email (Simple MAPI: the default email program opens with the archive attached).
- Open a file as a chosen archive type (`--open-as`, 7-Zip's -t); extract and test keep the type.
- New command-line actions: --add-to, --add-to-email, --add-email, --extract-into, --open-as,
  --hash:METHOD, --files-from.

## 0.1.0

First version.

- 7-Zip File Manager's window: menus, toolbar (Add, Extract, Test, Copy, Move, Delete, Info),
  address bar, list with 7-Zip's columns (folders first), status bar, keyboard shortcuts.
- Browse folders, drives, and archives as folders (nested archives, flat view, typed paths into
  archives); open files with their app; edit files inside archives and update the archive.
- Add to Archive with all of 7-Zip's options (format, level, method, dictionary, word size, solid
  block, threads, volumes, parameters, update and path modes, SFX, shared files, delete after,
  AES-256 with encrypted names); Extract (path and overwrite modes, password, eliminate root
  folder); Test; delete and rename inside archives; new folders in archives; drag and drop both
  ways.
- Progress window (elapsed / remaining, speed, sizes, current file; Background, Pause, Cancel);
  7-Zip's Confirm File Replace and password questions, answered back to the engine.
- Copy / Move / Delete (Recycle Bin) / Rename / New folder / New file on disk; CRC / SHA checksums;
  split and combine files; favorites; folders history; benchmark; properties.
- Explorer right-click submenu and "Open with" (per user), with several selected files collected
  into one dialog.
- Paragon OBSIDIAN look (family palette and gradient, Inter, piano-black keys, PR7-Z mark and icon).
- Engine: bundled official 7-Zip 26.01 (7z.exe, 7z.dll, 7z.sfx).
