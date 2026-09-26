Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!ifndef PAYLOAD
  !define PAYLOAD "..\dist\CodexModelSwitch.exe"
!endif
!ifndef README_PATH
  !define README_PATH "..\使用说明.md"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "..\dist\CodexModelSwitch-Setup-1.6.exe"
!endif

Name "Codex Model Switch 1.6"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\CodexModelSwitch"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "1.6.0.0"
VIAddVersionKey "ProductName" "Codex Model Switch"
VIAddVersionKey "FileDescription" "Codex Model Switch Installer"
VIAddVersionKey "FileVersion" "1.6.0.0"
VIAddVersionKey "LegalCopyright" "Codex Model Switch contributors"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "安装 Codex Model Switch 1.6"
!define MUI_WELCOMEPAGE_TEXT "安装多平台模型切换器。$\r$\n$\r$\n程序将安装到当前 Windows 用户目录，无需管理员权限。$\r$\n$\r$\n升级前请关闭旧版切换器。安装不会更改 Codex 的模型配置。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "本程序需要 64 位 Windows。"
    Abort
  ${EndIf}
  SetShellVarContext current
FunctionEnd

Section "程序文件（必选）" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /oname=CodexModelSwitch.exe "${PAYLOAD}"
  File /oname=使用说明.md "${README_PATH}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  !ifndef TEST_BUILD
    CreateDirectory "$SMPROGRAMS\Codex Model Switch"
    CreateShortcut "$SMPROGRAMS\Codex Model Switch\Codex Model Switch.lnk" "$INSTDIR\CodexModelSwitch.exe"
    CreateShortcut "$SMPROGRAMS\Codex Model Switch\卸载.lnk" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "DisplayName" "Codex Model Switch"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "DisplayVersion" "1.6.0"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "DisplayIcon" "$INSTDIR\CodexModelSwitch.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "NoRepair" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch" "EstimatedSize" 23000
  !endif
SectionEnd

Section "桌面快捷方式" SEC_DESKTOP
  !ifndef TEST_BUILD
    CreateShortcut "$DESKTOP\Codex Model Switch.lnk" "$INSTDIR\CodexModelSwitch.exe"
  !endif
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  !ifndef TEST_BUILD
    Delete "$DESKTOP\Codex Model Switch.lnk"
    Delete "$SMPROGRAMS\Codex Model Switch\Codex Model Switch.lnk"
    Delete "$SMPROGRAMS\Codex Model Switch\卸载.lnk"
    RMDir "$SMPROGRAMS\Codex Model Switch"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexModelSwitch"
  !endif
  Delete "$INSTDIR\CodexModelSwitch.exe"
  Delete "$INSTDIR\使用说明.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; Intentionally preserve LOCALAPPDATA\CodexModelSwitch and Codex configuration.
SectionEnd
