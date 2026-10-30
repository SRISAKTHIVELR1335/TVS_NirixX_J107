;---------------------------------------
; Installer Name / Output / Settings
;---------------------------------------
OutFile "TVS_NIRIX_Setup.exe"
InstallDir "C:\Nirix\ApplicationFiles"
RequestExecutionLevel user
Icon "NIRIX App Logo.ico"

;---------------------------------------
; Pages
;---------------------------------------
Page directory
Page instfiles

;---------------------------------------
; INSTALL SECTION
;---------------------------------------
Section "Install TVS_NIRIX"

    SetOutPath "$INSTDIR"

    ; Copy main EXE
    File /r "dist\TVS_NIRIX\TVS_NIRIX.exe"
    File /r "dist\TVS_NIRIX\NirixX_ConfigManager.exe"

    ; Copy folders
    File /r "dist\TVS_NIRIX\sku_files"
    File /r "dist\TVS_NIRIX\_internal"
    File /r "dist\TVS_NIRIX\EFI_Flashing_And_Static"
    File /r "dist\TVS_NIRIX\EFI_RVS"
    File /r "dist\TVS_NIRIX\dtc error code"

    ; Config files
    File "dist\TVS_NIRIX\station.ini.enc"
    File "dist\TVS_NIRIX\api.ini.enc"
    File "dist\TVS_NIRIX\log_cleanup.cp313-win_amd64.pyd"
    File "dist\TVS_NIRIX\security_manager.cp313-win_amd64.pyd"
    File "dist\TVS_NIRIX\scanner.ini.enc"
    File "dist\TVS_NIRIX\SKU_File_Mapping.xlsx.enc"

    ; UI Assets
    File "dist\TVS_NIRIX\fail picture.png"
    File "dist\TVS_NIRIX\Pass picture.png"
    File "dist\TVS_NIRIX\NIRIX Logo.png"
    File "dist\TVS_NIRIX\NIRIX_Logo.png"
    File "dist\TVS_NIRIX\TVS logo white.png"
    File "dist\TVS_NIRIX\NIRIX App Logo.ico"

    ; Create Uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ;---------------------------------------
    ; Shortcuts (Direct EXE launch)
    ;---------------------------------------
    CreateShortcut "$DESKTOP\TVS_NIRIX.lnk" "$INSTDIR\TVS_NIRIX.exe" "" "$INSTDIR\NIRIX App Logo.ico"
    CreateShortcut "$SMPROGRAMS\TVS_NIRIX.lnk" "$INSTDIR\TVS_NIRIX.exe" "" "$INSTDIR\NIRIX App Logo.ico"

SectionEnd

;---------------------------------------
; UNINSTALL
;---------------------------------------
Section "Uninstall"
    Delete "$DESKTOP\TVS_NIRIX.lnk"
    Delete "$SMPROGRAMS\TVS_NIRIX.lnk"
    RMDir /r "$INSTDIR"
SectionEnd
