; Inno Setup script for Meno.
;
; Compile with build.ps1, or directly:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\meno.iss
;
; Inno Setup: https://jrsoftware.org/isdl.php
;
; Requires PyInstaller to have run first: this script packages dist\Meno\, it
; does not build it.

#define AppName        "Meno"
#define AppVersion     "0.1.0"
#define AppPublisher   "Klay Garcia"
#define AppExeName     "Meno.exe"

[Setup]
; AppId is the identity Windows uses to recognise an existing installation and
; upgrade it in place. It must not change between versions; a new GUID would
; make 0.2 install alongside 0.1 rather than replace it.
AppId={{160DCD50-39B6-44F7-82C0-969C49352086}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=Meno-{#AppVersion}-Setup
SetupIconFile=..\meno\assets\meno.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 64-bit only, matching the bundled Python and Qt.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; "lowest" allows installation into the user's own profile without an
; administrator password; a per-machine install into Program Files remains
; selectable on the first page. The application writes nothing outside its own
; directory and %APPDATA%\Meno.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The complete PyInstaller output directory. recursesubdirs includes
; _internal, which holds Qt and OpenCV; the executable alone will not run.
Source: "..\dist\Meno\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

; Uninstall does not remove %APPDATA%\Meno, so settings and the HUD layout
; survive a reinstall. The HUD > Open config folder menu item opens that
; directory for manual removal.
