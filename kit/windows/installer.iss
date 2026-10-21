; TOTK IPA Builder for Windows: installs a private Python 3.14, the TOTK-ipa kit (app shell, MacNativeGames' build
; scripts, Windows builds of hactool / SPIRV-Cross / the shader translator, the Python packages as wheels) and a Start
; menu entry for the builder window (kit\gui.py), which asks for the game files and builds the IPA.
; Built by .github/workflows/build-kit.yml:  iscc /DSourceDir=<dist> /DAppVersion=<version> installer.iss
; No game file is in it. Per-user install: no administrator rights needed.

#ifndef SourceDir
  #define SourceDir "dist"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C4D1A52-2E0B-4E43-9E7B-9C2A1D5F3B71}
AppName=TOTK IPA Builder
AppVersion={#AppVersion}
AppPublisher=TOTK-ipa
AppPublisherURL=https://github.com/NawafLc/TOTK-ipa
DefaultDirName={localappdata}\Programs\TOTK IPA Builder
DefaultGroupName=TOTK IPA Builder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=TOTK-ipa-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourceDir}\kit\NOTICE.txt
UninstallDisplayName=TOTK IPA Builder
UninstallDisplayIcon={app}\python\pythonw.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TOTK IPA Builder"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\kit\gui.py"""; WorkingDir: "{app}\kit"
Name: "{group}\Uninstall TOTK IPA Builder"; Filename: "{uninstallexe}"
Name: "{userdesktop}\TOTK IPA Builder"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\kit\gui.py"""; WorkingDir: "{app}\kit"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\kit\gui.py"""; WorkingDir: "{app}\kit"; Description: "Start TOTK IPA Builder (choose your game files and build the IPA)"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\kit\__pycache__"
Type: filesandordirs; Name: "{app}\kit\tools\__pycache__"
Type: filesandordirs; Name: "{app}\python"
