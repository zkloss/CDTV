; CDTV Windows installer (Inno Setup 6)
; 先执行：python -m PyInstaller CDTV.spec --noconfirm --clean
; 再执行：ISCC.exe installer\CDTV.iss
; 安装包只包含程序与运行环境，不包含任何本机项目、账号、Cookie 或数据库。

#define MyAppName "CDTV"
#define MyAppVersion "2026.11.19"
#define MyAppPublisher "zkloss"
#define MyAppURL "https://github.com/zkloss/CDTV"
#define MyAppExeName "CDTV.exe"

[Setup]
AppId={{8E2A7C1B-3F5D-4B8A-9C1E-7D2F4A6B8C0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\CDTV
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=CDTV_Setup_{#MyAppVersion}_x64
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
UsePreviousAppDir=no
DirExistsWarning=auto
LicenseFile=..\LICENSE
VersionInfoVersion=2026.11.19.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=CDTV AI 漫剧与短剧自动化创作客户端安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "创建快速启动栏快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked; OnlyBelowVersion: 6.3

[Files]
; 程序、_internal 运行库与外部 runtime（含 Chrome for Testing）
Source: "..\dist\CDTV\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*,output\*,unins*,*.log"
; 空的本地数据目录由安装器创建，首次启动即可写项目
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\BUILD_VERSION.json"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\storage"; Flags: uninsneveruninstall
Name: "{app}\data\storage\files"; Flags: uninsneveruninstall
Name: "{app}\data\accounts"; Flags: uninsneveruninstall
Name: "{app}\output"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
