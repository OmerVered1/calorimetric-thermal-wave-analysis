; Inno Setup script for Calorimetric Thermal Wave Analysis Program (Windows installer)
; Build prerequisites:
;   1. PyInstaller has produced  dist\Calorimetric Thermal Wave Analysis Program\  (folder
;      containing the .exe and all its dependencies).
;   2. Inno Setup 6+ is installed (or ISCC.exe is on PATH).
; Usage:
;   iscc /DAppVersion=2.0.3 windows_installer.iss
; The CI workflow (.github/workflows/build-windows.yml) passes AppVersion
; from the pushed git tag.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{E6842112-0CFB-49C8-AFF4-66B21CC5A2A2}
AppName=Calorimetric Thermal Wave Analysis Program
AppVersion={#AppVersion}
AppVerName=Calorimetric Thermal Wave Analysis Program {#AppVersion}
AppPublisher=Omer Vered
AppPublisherURL=https://github.com/OmerVered1/calorimetric-thermal-wave-analysis
AppSupportURL=https://github.com/OmerVered1/calorimetric-thermal-wave-analysis/issues
AppUpdatesURL=https://github.com/OmerVered1/calorimetric-thermal-wave-analysis/releases
DefaultDirName={autopf}\Calorimetric Thermal Wave Analysis Program
DefaultGroupName=Calorimetric Thermal Wave Analysis Program
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=CTWA-Setup-{#AppVersion}
#if FileExists("assets\app_icon.ico")
SetupIconFile=assets\app_icon.ico
#endif
UninstallDisplayIcon={app}\Calorimetric Thermal Wave Analysis Program.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Bundle the entire PyInstaller output folder.
Source: "dist\Calorimetric Thermal Wave Analysis Program\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Calorimetric Thermal Wave Analysis Program"; Filename: "{app}\Calorimetric Thermal Wave Analysis Program.exe"
Name: "{group}\Uninstall Calorimetric Thermal Wave Analysis Program"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Calorimetric Thermal Wave Analysis Program"; Filename: "{app}\Calorimetric Thermal Wave Analysis Program.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Calorimetric Thermal Wave Analysis Program.exe"; Description: "Launch Calorimetric Thermal Wave Analysis Program"; Flags: nowait postinstall skipifsilent
