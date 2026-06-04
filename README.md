# Video Converter Pro

A fast, fully offline Windows desktop app for batch-converting video and audio files. Built with Python, pywebview, React, and FFmpeg.

---

## Features

- **Batch conversion** — add multiple files or an entire folder at once
- **7 output formats** — MP4 (H.264), MKV, AVI, MOV, WebM (VP9), MP4 (H.265/HEVC), MP3
- **Quality presets** — Ultra · High · Balanced · Fast (CRF-based)
- **GPU acceleration** — NVIDIA NVENC, Intel QSV, AMD AMF, with automatic CPU fallback
- **Parallel workers** — convert up to 4 files simultaneously
- **Per-file pause & resume** — lossless, backed by MKV temp segments + FFmpeg concat
- **Video trimming** — set start/end time per file before conversion
- **Session history** — log of every conversion with status and output size
- **Fully offline** — no internet required at runtime; all assets are bundled

---

## Supported Input Formats

`mp4` `mkv` `avi` `mov` `flv` `wmv` `webm` `m4v` `3gp` `f4v` `hevc` `m2v` `mjpeg`
`mpeg` `mpg` `mts` `mxf` `ogv` `rm` `ts` `vob` `wtv` `y4m`
`mp3` `wav` `m4a` `ogg` `flac` `aac` `wma`

---

## Requirements

| Item | Details |
|---|---|
| OS | Windows 10 / 11 (64-bit) |
| Python | 3.10 or newer |
| FFmpeg | `ffmpeg.exe` + `ffprobe.exe` placed in the `bin/` folder |
| Internet | Required **once** (first-time setup downloads React & Babel) |

---

## Getting Started (Run from Source)

### 1 — Clone the repository

```bash
git clone https://github.com/your-username/video-converter-pro.git
cd video-converter-pro
```

### 2 — Add FFmpeg binaries

Download a Windows FFmpeg build from **[ffmpeg.org/download.html](https://ffmpeg.org/download.html)** (recommend the gpl-shared or essentials build from gyan.dev or BtbN).

Copy `ffmpeg.exe` and `ffprobe.exe` into the `bin/` folder:

```
bin/
├── ffmpeg.exe
├── ffprobe.exe
└── .gitkeep
```

### 3 — Create a virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4 — Download the frontend libraries (one-time)

```bash
python setup_deps.py
```

This downloads React 18, ReactDOM, and Babel into `frontend/lib/`. No Node.js required.

### 5 — Launch the app

**Option A — double-click launcher (recommended for non-developers):**

```
run_converter.bat
```

This script auto-creates the venv, installs deps, downloads frontend libs, and launches the app — all in one step.

**Option B — manual:**

```bash
venv\Scripts\pythonw.exe main.py
```

---

## Building a Standalone .exe

The included `build_app.py` uses PyInstaller to package everything — Python runtime, pywebview, React frontend, FFmpeg binaries — into a single `VideoConverterPro.exe`.

```bash
# Make sure you are inside the venv with all deps installed
venv\Scripts\activate

# Run the build script
python build_app.py
```

The output is placed in `dist/VideoConverterPro.exe`. No installation required — the `.exe` is fully self-contained.

> **Note:** The build may take 1–3 minutes. Antivirus software sometimes flags PyInstaller-built executables as suspicious because they self-extract into a temp folder at startup. This is a known false-positive. You can whitelist the file or sign it with a code-signing certificate.

---

## Project Structure

```
video-converter-pro/
│
├── main.py               # Entry point — creates the pywebview window
├── converter.py          # FFmpeg engine (ConversionManager)
├── utils.py              # Helpers: logging, history, file utilities
├── build_app.py          # PyInstaller build script
├── setup_deps.py         # Downloads React/Babel into frontend/lib/
├── run_converter.bat     # One-click launcher for Windows
├── requirements.txt
│
├── backend/
│   └── api.py            # Python ↔ JS bridge (pywebview JS API)
│
├── frontend/
│   ├── index.html        # App shell
│   ├── lib/              # React + Babel (downloaded by setup_deps.py)
│   └── app/
│       ├── app.jsx       # Root React component, state management
│       ├── components.jsx # Reusable UI components (sidebar, dropdowns)
│       ├── rows.jsx      # File row, empty state, bottom bar
│       ├── modals.jsx    # About and History modals
│       ├── trim.jsx      # Video trim panel
│       ├── data.jsx      # Static data: formats, presets, GPU options
│       ├── icons.jsx     # SVG icon components
│       └── styles.css    # All styling (plain CSS, no framework)
│
├── assets/
│   ├── fonts/            # Plus Jakarta Sans, JetBrains Mono (bundled TTFs)
│   └── images/           # App icon (VCP.ico)
│
├── bin/                  # Place ffmpeg.exe + ffprobe.exe here (not in git)
├── logs/                 # Runtime log files (one per session, not in git)
└── tests/                # Integration and security tests
```

---

## Architecture Overview

```
JS (React)  ──── window.pywebview.api.method() ────▶  Python (Api class)
Python      ──── window.dispatchEvent('vc-update') ──▶  JS event handler
```

- **Frontend** — React 18 (production build), Babel in-browser transpiler, plain CSS. No Node.js or build step needed.
- **Backend** — Python class exposed to JS via pywebview. Runs on a background thread.
- **Engine** — FFmpeg subprocess managed by `ConversionManager`. Progress parsed from stderr (`time=` lines).
- **Pause/Resume** — FFmpeg encodes to a temp `.mkv` segment. On resume, a second segment is encoded and both are concatenated with `ffconcat` and remuxed (stream copy) to the final container — no re-encoding on resume.
- **File dialogs** — tkinter (stdlib). pywebview's own dialog silently fails on Windows when called from a background API thread.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | pywebview (WebView2 / Edge on Windows), frameless window |
| Backend | Python 3 (stdlib + pywebview) |
| Conversion engine | FFmpeg (bundled in `bin/`) |
| Frontend | React 18 (UMD production build) |
| JSX transpiler | Babel Standalone (in-browser) |
| Fonts | Plus Jakarta Sans · JetBrains Mono (bundled TTFs) |
| Packaging | PyInstaller (single-file .exe) |

---

## Running Tests

```bash
venv\Scripts\activate
python -m pytest tests/ -v
```

---

## Contributing

Pull requests are welcome. For significant changes, please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request

---

## License

MIT — see [LICENSE](LICENSE) for details.
