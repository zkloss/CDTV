# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('frontend/dist', 'frontend/dist'), ('skill_loader.py', '.'), ('model_seeds.py', '.'), ('film_filter.py', '.'), ('external_toolbox.py', '.'), ('breeze_bridge.py', '.'), ('huashu_bridge.py', '.'), ('dubbing_alignment.py', '.'), ('assets', 'assets'), ('runtime/ffmpeg.exe', 'runtime'), ('runtime/audio-review', 'runtime/audio-review')],
    hiddenimports=['skill_loader', 'shotcraft_bridge', 'whole_film_renderer', 'local_storage', 'audio_contract', 'model_seeds', 'film_filter', 'external_toolbox', 'huashu_bridge', 'webview.platforms.edgechromium'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt6', 'matplotlib', 'scipy', 'pandas', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CDTV',
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
    icon='assets/app-icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CDTV',
)
