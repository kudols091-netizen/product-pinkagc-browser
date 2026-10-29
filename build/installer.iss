; Inno Setup — tao bo cai PinkAgc Browser. Compile: iscc build\installer.iss
; Yeu cau da build dist\PinkAgcBrowser.exe truoc (build\build-exe.ps1).
; LUU Y vendor\ ~4.6GB -> bo cai se rat nang. Phuong an nhe: KHONG dong goi vendor,
;   tai ovobrowser lan dau chay (xem build\README.md).

#define MyAppVersion "0.1.0"

[Setup]
AppName=PinkAgc Browser
AppVersion={#MyAppVersion}
AppPublisher=PinkAgc
DefaultDirName={autopf}\PinkAgc Browser
DefaultGroupName=PinkAgc Browser
OutputDir=..\dist
OutputBaseFilename=PinkAgcBrowser-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\PinkAgcBrowser.exe"; DestDir: "{app}"; Flags: ignoreversion
; Bo dong duoi neu chon phuong an "tai vendor lan dau" (xem README):
Source: "..\vendor\*"; DestDir: "{app}\vendor"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\PinkAgc Browser"; Filename: "{app}\PinkAgcBrowser.exe"
Name: "{autodesktop}\PinkAgc Browser"; Filename: "{app}\PinkAgcBrowser.exe"

[Run]
Filename: "{app}\PinkAgcBrowser.exe"; Description: "Chay PinkAgc Browser"; Flags: nowait postinstall skipifsilent
