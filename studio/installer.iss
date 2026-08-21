; DGHub SDK Studio — Inno Setup 安装脚本（每用户安装）
; 由 build.py 调用：ISCC installer.iss /DMyVersion=<x.y.z>
; 打包 onedir（bin\dghub-sdk-studio\）为安装器，装到 LocalAppData 并将安装目录加入用户 PATH。
; GUI = dgstudio-gui.exe（开始菜单）；CI CLI = dgstudio-cli.exe（PATH 命令 `dgstudio-cli build`）。
; 旧版（DGHub SDK Packer）存在时：自动迁移 state.json 到新配置目录、静默卸载
; 旧版安装并清理旧配置（安装后只保留 Studio）。

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

#define MyAppName "DGHub SDK Studio"
#define MyGuiExe "dgstudio-gui.exe"
#define MyCliExe "dgstudio-cli.exe"

[Setup]
AppId={{B9E5C2A1-4D6F-4E8B-9A3C-7F1D2E5B8A04}
AppName={#MyAppName}
AppVersion={#MyVersion}
AppPublisher=DGHub
DefaultDirName={localappdata}\dghub-sdk-studio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ChangesEnvironment=yes
OutputDir=installer
OutputBaseFilename=dghub-sdk-studio-setup
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyGuiExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; onedir 全部内容（两个 exe + 共享 _internal/）
Source: "bin\dghub-sdk-studio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 开始菜单只放 GUI；CLI(dgstudio-cli.exe) 通过 PATH 使用，无需快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyGuiExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyGuiExe}"; Tasks: desktopicon

[Run]
; 「启动 Studio」复选框（默认勾选——安装完成即启动）；静默安装跳过
Filename: "{app}\{#MyGuiExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; 将安装目录加入用户 PATH（使 dgstudio-cli 全局可用）；ChangesEnvironment=yes 会广播 WM_SETTINGCHANGE
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
// 旧版 AppId（DGHub SDK Packer，v0.16.0 之前）——用于注册表定位
// 旧版真实安装位置（用户可能自定义过安装目录，不能只查默认路径）
#define OLD_APP_ID "{A7C3E1F2-5B9D-4E8A-9C2F-1D3B6E4A8F70}"

function GetOldInstallDir(): string;
var
  InstallDir: string;
begin
  Result := '';
  if RegQueryStringValue(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OLD_APP_ID}_is1',
      'InstallLocation', InstallDir) then
    Result := InstallDir;
end;

function GetOldUninstallPath(): string;
var
  Uninst: string;
begin
  Result := '';
  if RegQueryStringValue(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OLD_APP_ID}_is1',
      'UninstallString', Uninst) then
  begin
    // UninstallString 形如 "C:\...\unins000.exe"（可能带引号）
    Uninst := Trim(Uninst);
    if (Length(Uninst) >= 2) and (Uninst[1] = '"') and (Uninst[Length(Uninst)] = '"') then
      Uninst := Copy(Uninst, 2, Length(Uninst) - 2);
    Result := Uninst;
  end;
end;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  // 已含则不重复追加
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure RemovePath(Param: string);
var
  OrigPath: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
    exit;
  P := Pos(';' + Uppercase(Param), ';' + Uppercase(OrigPath));
  if P = 0 then
    P := Pos(Uppercase(Param), Uppercase(OrigPath));
  if P > 0 then
  begin
    // 删除 PATH 中的安装目录段（带或不带前导分号）
    if (P > 1) and (Copy(OrigPath, P - 1, 1) = ';') then
      Delete(OrigPath, P - 1, Length(Param) + 1)
    else
      Delete(OrigPath, P, Length(Param));
    RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Profile: string;
  OldConfigDir: string;
  NewConfigDir: string;
  OldInstallDir: string;
  UninstPath: string;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    Profile := GetEnv('USERPROFILE');
    OldConfigDir := Profile + '\.dghub-sdk-packer';       // 旧版配置目录
    NewConfigDir := Profile + '\.dghub-sdk-studio';       // 新版配置目录
    // 旧版安装目录：优先注册表（覆盖自定义安装路径），回退默认路径
    OldInstallDir := GetOldInstallDir();
    if OldInstallDir = '' then
      OldInstallDir := GetEnv('LOCALAPPDATA') + '\dghub-sdk-packer';
    // 1) 旧版配置迁移：仅当旧 state.json 存在且新配置尚未生成时复制（不覆盖）
    if FileExists(OldConfigDir + '\state.json') and not FileExists(NewConfigDir + '\state.json') then
    begin
      CreateDir(NewConfigDir);
      FileCopy(OldConfigDir + '\state.json', NewConfigDir + '\state.json', False);
    end;
    // 2) 自动卸载旧版 Packer（静默）：先终止残留进程，再运行其卸载器；
    //    卸载器缺失（目录残留）时直接删除安装目录——安装后只保留 Studio
    if DirExists(OldInstallDir) then
    begin
      Exec('taskkill.exe', '/IM dgpacker-gui.exe /F /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Exec('taskkill.exe', '/IM dgpacker-cli.exe /F /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      UninstPath := GetOldUninstallPath();
      if UninstPath = '' then
        UninstPath := OldInstallDir + '\unins000.exe';
      if FileExists(UninstPath) then
        Exec(UninstPath, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
      else
        DelTree(OldInstallDir, True, True, False);
    end;
    // 3) 清理旧配置目录：迁移已完成（步骤 1），旧配置不再需要
    if DirExists(OldConfigDir) then
      DelTree(OldConfigDir, True, True, False);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;
