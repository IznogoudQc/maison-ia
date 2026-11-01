; Installateur Windows de Maison IA (Inno Setup 6). Construit par .github/workflows/release.yml :
;   iscc /DAppVersion=0.2.0 packaging\installateur.iss
; Fichiers ASCII seulement (pas d'accents) pour eviter les soucis d'encodage.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E2B4C1A-5D3F-4A8B-9C6E-2F1D0A4B7C55}
AppName=Maison IA
AppVersion={#AppVersion}
AppPublisher=IznogoudQc
AppPublisherURL=https://github.com/IznogoudQc/maison-ia
DefaultDirName={autopf}\MaisonIA
DefaultGroupName=Maison IA
OutputDir=..\dist
OutputBaseFilename=MaisonIA-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\MaisonIA.exe

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\dist\MaisonIA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Maison IA"; Filename: "{app}\MaisonIA.exe"
Name: "{group}\Entrer ma cle Claude"; Filename: "{app}\MaisonIA.exe"; Parameters: "--cle"
Name: "{group}\Mes sauvegardes et reglages"; Filename: "{userappdata}\MaisonIA"
Name: "{group}\Desinstaller Maison IA"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Maison IA"; Filename: "{app}\MaisonIA.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MaisonIA.exe"; Description: "Lancer Maison IA"; Flags: nowait postinstall skipifsilent
