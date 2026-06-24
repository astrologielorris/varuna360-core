# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=[('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/apps/widgets/chart_view.cpython-312-x86_64-linux-gnu.so', 'apps/widgets'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/apps/widgets/wheel_view.cpython-312-x86_64-linux-gnu.so', 'apps/widgets'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/apps/widgets/wheel_items.cpython-312-x86_64-linux-gnu.so', 'apps/widgets'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/apps/widgets/north_indian_view.cpython-312-x86_64-linux-gnu.so', 'apps/widgets'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/apps/widgets/zodiac_renderer.cpython-312-x86_64-linux-gnu.so', 'apps/widgets'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/visualizations/wheel_geometry.cpython-312-x86_64-linux-gnu.so', 'visualizations'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/visualizations/wheel_constants.cpython-312-x86_64-linux-gnu.so', 'visualizations'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/core/planets_calculator.cpython-312-x86_64-linux-gnu.so', 'core'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/core/planets_data_compat.cpython-312-x86_64-linux-gnu.so', 'core'), ('/home/lorris/application/Varuna360_libaditya/build/lite_compiled/AI_tools/AI_main_function/retinue.cpython-312-x86_64-linux-gnu.so', 'AI_tools/AI_main_function')],
    datas=[('img', 'img'), ('icon', 'icon'), ('app_settings.json', '.'), ('settings.json', '.'), ('ephe', 'ephe'), ('libaditya/ephe', 'libaditya/ephe'), ('chtk_files', 'chtk_files'), ('data', 'data'), ('docs', 'docs')],
    hiddenimports=['timezonefinder', 'h3', 'geopy', 'geopy.geocoders', 'geocoder', 'requests', 'jwt', 'cryptography'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'matplotlib', 'IPython', 'notebook'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Varuna360Core-3.1.0-linux-x86_64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='Varuna360Core-3.1.0-linux-x86_64',
)
