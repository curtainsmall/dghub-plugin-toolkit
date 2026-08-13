; DGHub SDK Packer — Inno Setup 安装脚本（每用户安装）
; 由 build.py 调用：ISCC installer.iss /DMyVersion=<x.y.z>
; 打包 onedir（bin\dghub-sdk-packer\）为安装器，装到 LocalAppData 并将安装目录加入用户 PATH。
; GUI = dgpacker-gui.exe（开始菜单）；CI CLI = dgpacker-cli.exe（PATH 命令 `dgpacker-cli build`）。

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

#define MyAppName "DGHub SDK Packer"
#define MyGuiExe "dgpacker-gui.exe"
#define MyCliExe "dgpacker-cli.exe"

[Setup]
AppId={{A7C3E1F2-5B9D-4E8A-9C2F-1D3B6E4A8F70}
AppName={#MyAppName}
AppVersion={#MyVersion}
AppPublisher=DGHub
DefaultDirName={localappdata}\dghub-sdk-packer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ChangesEnvironment=yes
OutputDir=installer
OutputBaseFilename=dghub-sdk-packer-setup
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
Source: "bin\dghub-sdk-packer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 开始菜单只放 GUI；CLI(dgpacker-cli.exe) 通过 PATH 使用，无需快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyGuiExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyGuiExe}"; Tasks: desktopicon

[Run]
; 「启动 Packer」复选框（默认勾选——安装完成即启动）；静默安装跳过
Filename: "{app}\{#MyGuiExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; 将安装目录加入用户 PATH（使 dgpacker-cli 全局可用）；ChangesEnvironment=yes 会广播 WM_SETTINGCHANGE
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;
