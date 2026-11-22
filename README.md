# Paragon PR7-Z

The Paragon family's archive manager: it works the way **7-Zip File Manager** works, in the family's
OBSIDIAN look (the PR7 plugins, Paragon Photo). Personal use.

Compression is done by the **official 7-Zip engine** (7z.exe + 7z.dll, 7-Zip 26.01, bundled in
`engine/`), so every archive is exactly what 7-Zip itself would make or read: 7z, zip, tar, wim, gzip,
bzip2 and xz to create; ~50 formats to open (rar, iso, cab, dmg, vhd(x), zstd, msi, squashfs ...).

## Install (Windows 10/11, x64)

1. Download **`PR7-Z-Setup-<version>.exe`** from the repo's **Releases** (or the latest build's
   *PR7-Z-Setup* artifact under **Actions**) and run it. No admin rights: it installs for your user
   into `%LOCALAPPDATA%\Programs\PR7-Z` and adds PR7-Z to the Start menu.
2. Leave **"Add PR7-Z to Explorer's right-click menu"** ticked (and "Open with" if you like). Right-click
   any file: the PR7-Z menu is there (Windows 11: under "Show more options", like 7-Zip's).
3. To update, run the newer setup over it. To remove: Settings > Apps > Installed apps > Paragon PR7-Z,
   which also removes the menu.

Change the menu any time in **Tools > Options** (cascaded or not, which items), as in 7-Zip's Options.
There's also a portable zip (`PR7-Z-<version>-windows-x64.zip`): keep `PR7-Z.exe` and its `_internal`
folder together, outside OneDrive, and turn the menu on in Tools > Options.

## Use

Everything 7-Zip File Manager does, with its shortcuts: browse folders and open archives like
folders (archives inside archives too); Add / Extract / Test / Copy / Move / Delete / Info on the
toolbar; F2 rename, F4 edit, F5 copy, F6 move, F7 new folder, Alt+Enter properties, Backspace up,
Ctrl+PgDown open inside, Alt+1..9 favorites, Alt+F12 folders history; CRC/SHA checksums, split and
combine files, flat view, benchmark. Drop files on an open archive to add them to the folder you're
in; drag items out to extract them; edit a file inside an archive and PR7-Z offers to update the
archive when you save. Help > Contents (F1) lists it all.

Explorer menu (like 7-Zip's): Open archive, Open archive >, Extract files..., Extract Here,
Extract to "name\", Test archive, Add to archive..., Compress and email..., Add to "name.7z" /
"name.zip", Compress to ... and email, CRC SHA >. The names are the real ones; all selected files go
to one dialog.

## Run from source

```bash
pip install -r requirements.txt
python -m pr7z            # or: python -m pr7z D:\Music\ELSEWORLD_Stems.7z
```

Tests: `pip install -r requirements-dev.txt` then `python -m pytest` (on Linux set `PR7Z_7Z` to a
`7zz` binary). Build: the menu DLL with CMake (`shellext/`), the exe with `pyinstaller pr7z.spec`, the
installer with Inno Setup (`iscc /DAppVersion=x.y.z installer\pr7z.iss`). CI does all three on every push
(`.github/workflows/build.yml`) and tests the installer.
