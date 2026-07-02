# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all
block_cipher = None

LITE_BUILD = os.environ.get('LITE_BUILD', '') in ('1', 'true', 'yes')

# Collect all vosk and sounddevice package files (including native DLLs)
vosk_datas, vosk_binaries, vosk_hiddenimports = collect_all('vosk')
sd_datas, sd_binaries, sd_hiddenimports = collect_all('sounddevice')

# In lite builds we do not bundle the Vosk model to keep the installer small.
# The app will default to Web Speech API and can download the model later if desired.
model_datas = []
if not LITE_BUILD:
    model_datas = [('models/vosk-model-en-us-0.22-lgraph', 'models/vosk-model-en-us-0.22-lgraph')]

a = Analysis(
    ['serve.py'],
    pathex=['.'],
    binaries=vosk_binaries + sd_binaries,
    datas=[
        ('web-ui', 'web-ui'),
        ('data/rhema.db', 'data'),
    ] + model_datas + vosk_datas + sd_datas,
    hiddenimports=['websockets', 'websockets.legacy', 'websockets.legacy.server', 'websockets.legacy.client',
                   'vosk', 'sounddevice', 'cffi'] + vosk_hiddenimports + sd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
