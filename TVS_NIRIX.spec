# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('EFI_Flashing_And_Static', 'EFI_Flashing_And_Static'), ('EFI_RVS', 'EFI_RVS'), ('fail picture.png', '.'), ('Pass picture.png', '.'), ('TVS logo white.png', '.'), ('Nirix Logo.png', '.')]
binaries = [('log_cleanup.cp313-win_amd64.pyd', '.'), ('security_manager.cp313-win_amd64.pyd', '.')]
hiddenimports = ['log_cleanup', 'security_manager', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.sip', 'serial.tools.list_ports', 'can', 'can.message', 'can.interfaces.pcan', 'Crypto.Cipher.AES', 'usb.core', 'usb.util', 'udsoncan', 'isotp', 'openpyxl']
hiddenimports += collect_submodules('udsoncan')
hiddenimports += collect_submodules('isotp')
tmp_ret = collect_all('intelhex')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('bincopy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['TVS_NirixX_Plant_2.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'sklearn', 'nltk', 'torch', 'torchvision'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TVS_NIRIX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TVS_NIRIX',
)
