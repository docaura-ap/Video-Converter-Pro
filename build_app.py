"""
Build script — packages Video Converter Pro into a single .exe using PyInstaller.

Prerequisites (run once):
    pip install pyinstaller pywebview
    python setup_deps.py       # downloads React/Babel into frontend/lib/

Then build:
    python build_app.py
"""
import PyInstaller.__main__
import os
import sys
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Pre-flight checks ────────────────────────────────────────────────────────

bin_dir = os.path.join(ROOT, 'bin')
if not os.path.exists(os.path.join(bin_dir, 'ffmpeg.exe')):
    print("ERROR: bin/ffmpeg.exe not found. Add ffmpeg.exe and ffprobe.exe to the bin/ folder.")
    sys.exit(1)

lib_dir = os.path.join(ROOT, 'frontend', 'lib')
if not os.path.exists(os.path.join(lib_dir, 'react.production.min.js')):
    print("Frontend libraries missing. Running setup_deps.py first...")
    import subprocess
    subprocess.check_call([sys.executable, os.path.join(ROOT, 'setup_deps.py')])

# ── Clean previous builds ────────────────────────────────────────────────────

for d in ('dist', 'build'):
    p = os.path.join(ROOT, d)
    if os.path.exists(p):
        shutil.rmtree(p)

# ── Icon (optional) ──────────────────────────────────────────────────────────

icon_path = os.path.join(ROOT, 'assets', 'images', 'VCP.ico')
icon_args = [f'--icon={icon_path}'] if os.path.exists(icon_path) else []

# ── PyInstaller arguments ────────────────────────────────────────────────────

args = [
    'main.py',
    '--name=VideoConverterPro',
    '--noconsole',
    '--onefile',

    # Data bundles  (src;dest_inside_bundle)
    '--add-data=frontend;frontend',          # HTML / CSS / JSX / lib
    '--add-data=assets/fonts;assets/fonts',  # bundled fonts
    '--add-data=bin;bin',                    # FFmpeg + FFprobe
    '--add-data=backend;backend',            # Python API bridge

    # pywebview hidden imports
    '--hidden-import=webview',
    '--hidden-import=webview.platforms.winforms',
    '--hidden-import=clr',
    '--hidden-import=pythonnet',

    '--clean',
    '--noconfirm',
] + icon_args

print("Building Video Converter Pro...")
PyInstaller.__main__.run(args)
print("\nDone — check the dist/ folder.")
