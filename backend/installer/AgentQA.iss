; AgentQA Studio installer (Inno Setup 6.3 or newer). Built by installer\build_installer.ps1.
; Installs for the current user only, so no administrator rights are needed on government laptops.
; Projects live in %USERPROFILE%\AgentQA\projects and survive upgrades and uninstalls.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7D3F0C52-4B8E-4A57-9E7C-2B1A6F0D9A41}
AppName=AgentQA Studio
AppVersion={#AppVersion}
AppPublisher=AgentQA Studio
AppComments=Autonomous web portal testing on local AI, no API keys
DefaultDirName={localappdata}\Programs\AgentQA Studio
DefaultGroupName=AgentQA Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AgentQA-Studio-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=AgentQA Studio {#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\AgentQA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
Name: "{%USERPROFILE}\AgentQA\projects"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\AgentQA Studio"; Filename: "{app}\AgentQA Studio.cmd"; WorkingDir: "{app}"; Comment: "Open the AgentQA dashboard"
Name: "{group}\AgentQA Demo"; Filename: "{app}\AgentQA Demo.cmd"; WorkingDir: "{app}"; Comment: "Run every agent on the bundled demo portal"
Name: "{group}\AgentQA command line"; Filename: "{cmd}"; Parameters: "/k cd /d ""{app}"" && agentqa.cmd --help"; WorkingDir: "{app}"
Name: "{group}\Uninstall AgentQA Studio"; Filename: "{uninstallexe}"
Name: "{userdesktop}\AgentQA Studio"; Filename: "{app}\AgentQA Studio.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AgentQA Studio.cmd"; Description: "Open AgentQA Studio now"; Flags: postinstall nowait shellexec skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"
