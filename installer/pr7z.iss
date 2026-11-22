; Paragon PR7-Z installer (Inno Setup 6).
;   iscc /DAppVersion=0.3.0 installer\pr7z.iss      (after pyinstaller pr7z.spec has made dist\PR7-Z)
;
; Installs for the current user only (no admin rights) into %LOCALAPPDATA%\Programs\PR7-Z, adds a Start
; menu entry, and turns on the Explorer right-click menu and "Open with" (both optional, ticked).
; Registration is done by PR7-Z itself (pr7z/shell.py), so the installer, Tools > Options and
; `PR7-Z.exe --register` all do exactly the same thing. The uninstaller removes it again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{9914C6C8-01EC-476F-845D-98F814A0426E}
AppName=Paragon PR7-Z
AppVersion={#AppVersion}
AppVerName=Paragon PR7-Z {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-Z
DefaultGroupName=Paragon PR7-Z
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-Z-Setup-{#AppVersion}
SetupIconFile=..\pr7z\icons\app.ico
UninstallDisplayIcon={app}\PR7-Z.exe
UninstallDisplayName=Paragon PR7-Z
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
; Close a running PR7-Z before replacing its files. Explorer never holds files from here: the menu
; DLL it loads is a per-user copy (see pr7z/shell.py deploy_dll), so Explorer isn't restarted.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "contextmenu"; Description: "Add PR7-Z to Explorer's right-click menu (like 7-Zip)"
Name: "openwith"; Description: "List PR7-Z under ""Open with"" for archive files (.7z, .zip, .rar, .iso ...)"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-Z\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files from an older version that this one no longer has (keeps _internal exactly this build's).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-Z"; Filename: "{app}\PR7-Z.exe"; Comment: "Archive manager"
Name: "{autodesktop}\Paragon PR7-Z"; Filename: "{app}\PR7-Z.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-Z.exe"; Parameters: "--register-menu"; Tasks: contextmenu; Flags: runhidden waituntilterminated; StatusMsg: "Adding PR7-Z to Explorer's right-click menu..."
Filename: "{app}\PR7-Z.exe"; Parameters: "--unregister-menu"; Tasks: not contextmenu; Flags: runhidden waituntilterminated
Filename: "{app}\PR7-Z.exe"; Parameters: "--register-open-with"; Tasks: openwith; Flags: runhidden waituntilterminated; StatusMsg: "Adding PR7-Z to ""Open with""..."
Filename: "{app}\PR7-Z.exe"; Parameters: "--unregister-open-with"; Tasks: not openwith; Flags: runhidden waituntilterminated
Filename: "{app}\PR7-Z.exe"; Description: "{cm:LaunchProgram,Paragon PR7-Z}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\PR7-Z.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "PR7ZUnregister"
