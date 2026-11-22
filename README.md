# Paragon PR7-Z

The Paragon family's archive manager: it works the way **7-Zip File Manager** works, in the family's
OBSIDIAN look (the PR7 plugins, Paragon Photo). Personal use.

Compression is done by the **official 7-Zip engine** (7z.exe + 7z.dll, 7-Zip 26.01, bundled in
`engine/`), so every archive is exactly what 7-Zip itself would make or read: 7z, zip, tar, wim, gzip,
bzip2 and xz to create; ~50 formats to open (rar, iso, cab, dmg, vhd(x), zstd, msi, squashfs ...).

## Install (Windows 10/11, x64)

1. Download `PR7-Z-<version>-windows-x64.zip` from the repo's **Releases** (or the latest build's
   artifact under **Actions**), unzip it anywhere (e.g. `C:\Tools\PR7-Z`), and run `PR7-Z.exe`.
2. **Tools > Options**: *Add to Explorer* puts a PR7-Z submenu on Explorer's right-click menu; *File
   types: Add* lists PR7-Z under "Open with" for archives. Both are per-user (no admin rights) and
   *Remove* takes them out again. Same from a terminal: `PR7-Z.exe --register` / `--unregister`.
   (Windows 11 shows the submenu under "Show more options".)

## Use

Everything 7-Zip File Manager does, with its shortcuts: browse folders and open archives like
folders (archives inside archives too); Add / Extract / Test / Copy / Move / Delete / Info on the
toolbar; F2 rename, F4 edit, F5 copy, F6 move, F7 new folder, Alt+Enter properties, Backspace up,
Ctrl+PgDown open inside, Alt+1..9 favorites, Alt+F12 folders history; CRC/SHA checksums, split and
combine files, flat view, benchmark. Drop files on an open archive to add them to the folder you're
in; drag items out to extract them; edit a file inside an archive and PR7-Z offers to update the
archive when you save. Help > Contents (F1) lists it all.

Explorer menu: Open archive, Extract files..., Extract Here, Extract to "<name>\", Test archive,
Add to archive..., Add to "<name>.7z" / "<name>.zip", CRC SHA. Several selected files go to one
dialog.

## Run from source

```bash
pip install -r requirements.txt
python -m pr7z            # or: python -m pr7z D:\Music\ELSEWORLD_Stems.7z
```

Tests: `pip install -r requirements-dev.txt` then `python -m pytest` (on Linux set `PR7Z_7Z` to a
`7zz` binary). Build the exe: `pyinstaller pr7z.spec` (CI does this on every push: `.github/workflows/build.yml`).
