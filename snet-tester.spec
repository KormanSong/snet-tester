# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('snet_tester/ui/main_window.ui', 'snet_tester/ui'), ('snet_tester/presets.json', 'snet_tester')],
    hiddenimports=['snet_tester', 'snet_tester.main', 'snet_tester.config', 'snet_tester.comm', 'snet_tester.comm.worker', 'snet_tester.protocol', 'snet_tester.protocol.codec', 'snet_tester.protocol.constants', 'snet_tester.protocol.convert', 'snet_tester.protocol.parser', 'snet_tester.protocol.types', 'snet_tester.views', 'snet_tester.views.helpers', 'snet_tester.views.main_window', 'snet_tester.views.plot_view', 'snet_tester.views.response_tracker', 'snet_tester.views.rx_panel', 'snet_tester.views.tx_panel'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='snet-tester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
