; -*- mode: ini ; coding: utf-8 -*-
; Inno Setup script for ai-translator.
; Builds packaging\windows\installer\ai-translator-setup-<version>.exe
; from the PyInstaller output in packaging\windows\dist\ai-translator.
;
; Version can be overridden:  ISCC /DAppVersion=1.2.3 ai-translator.iss

#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#define MyAppName "AI Translator"
#define MyAppExeName "ai-translator.exe"

[Setup]
AppId={{8A6E4F2C-1B3D-4E5A-9C7B-2D0F6A8E5C41}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\ai-translator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=ai-translator-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\ai-translator\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
