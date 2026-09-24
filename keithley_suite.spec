# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Calorimetric Thermal Wave Analysis Program.

Cross-platform: produces a .app bundle on macOS and a folder-based EXE
distribution on Windows / Linux. The BUNDLE step is skipped on non-darwin
platforms (it raises NotImplementedError on Windows otherwise).
"""

import sys

block_cipher = None

# Pick the right app icon for the host platform.
# Files are optional — drop them in assets/ to enable, or leave icon_path=None.
import os as _os
if sys.platform == 'darwin' and _os.path.exists('assets/app_icon.icns'):
    icon_path = 'assets/app_icon.icns'
elif sys.platform == 'win32' and _os.path.exists('assets/app_icon.ico'):
    icon_path = 'assets/app_icon.ico'
else:
    icon_path = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('calorimeter_profiles', 'calorimeter_profiles'),
           ('ctwa/assets', 'ctwa/assets')],
    hiddenimports=[
        'ctwa',
        'ctwa.app',
        'ctwa.theme',
        'ctwa.connect_panel',
        'ctwa.instruments',
        'ctwa.instruments.capabilities',
        'ctwa.instruments.registry',
        'ctwa.instruments.smu',
        'ctwa.instruments.discovery',
        # Drivers are imported by name at connect time (smu._DRIVERS), which
        # PyInstaller's static analysis cannot see — so they are listed here.
        'keithley2450_driver',
        'keithley6430_driver',
        'keithley2602b_driver',
        'keithley2611a_driver',
        'network_setup',
        '_version',
        'calorimeter_reader',
        'calorimeter_setups',
        'calorimeter_discovery',
        'calorimeter_wizard',
        'signal_units',
        'realtime_tab',
        'updater',
        'sniffer',
        'sniffer.capture',
        'sniffer.reassembly',
        'sniffer.framer',
        'sniffer.fields',
        'sniffer.profile',
        'sniffer.modbus',
        'scapy',
        'scapy.all',
        'scapy.layers.inet',
        'scapy.sendrecv',
        'scapy.interfaces',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtSvg',
        'shiboken6',
        'pyqtgraph',
        'numpy',
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'pyvisa',
        'pyvisa.resources',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Other Qt bindings installed alongside must not be bundled: pyqtgraph
    # probes for them, and PyInstaller refuses a build with two.
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Calorimetric Thermal Wave Analysis Program',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Calorimetric Thermal Wave Analysis Program',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Calorimetric Thermal Wave Analysis Program.app',
        icon=icon_path,
        bundle_identifier='com.omervered.ctwa',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '1.0.0',  # bump per release
        },
    )
